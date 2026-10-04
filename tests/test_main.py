"""Pruebas de punta a punta: del config.yaml al mensaje de Discord.

Toda la red esta simulada, asi que no se toca la API de Blizzard ni se envia
nada a Discord de verdad.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

import main as cli

WEBHOOK = "https://discord.com/api/webhooks/1/abc"
VENTAS_WEBHOOK = "https://discord.com/api/webhooks/3/ventas"
TOKEN_URL = "https://oauth.battle.net/token"
BASE = "https://eu.api.blizzard.com/data/wow"
ICON_URL = "https://render.worldofwarcraft.com/eu/icons/56/7705643.jpg"

CONFIG = """
region: eu
items:
  - name: "Greaves of the Noxious Depths"
    item_id: 5000
    max_price_by_ilvl: { 298: 9000, 311: 90000 }
bonus_ilvl_map:
  12843: 311
settings:
  max_workers: 2
"""


def subasta(auction_id, buyout, bonus=(12843,)):
    return {
        "id": auction_id,
        "item": {"id": 5000, "bonus_lists": list(bonus)},
        "buyout": buyout,
        "quantity": 1,
        "time_left": "LONG",
    }


@pytest.fixture
def entorno(tmp_path, monkeypatch, requests_mock):
    # Sin esto, los reintentos con espera progresiva harian los tests lentisimos.
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "id")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "secret")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG, encoding="utf-8")

    requests_mock.post(TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})
    requests_mock.get(
        f"{BASE}/connected-realm/index",
        json={"connected_realms": [{"href": f"{BASE}/connected-realm/1305"}]},
    )
    requests_mock.get(
        f"{BASE}/connected-realm/1305", json={"realms": [{"name": "Dun Modr"}]}
    )
    requests_mock.get(
        f"{BASE}/media/item/5000",
        json={"assets": [{"key": "icon", "value": ICON_URL}]},
    )
    requests_mock.get(
        f"{BASE}/item/5000",
        json={"name": {"en_GB": "Greaves", "es_ES": "Grebas"}},
    )
    requests_mock.post(WEBHOOK, status_code=204)
    # El panel de ventas se reescribe en su propio canal.
    requests_mock.post(VENTAS_WEBHOOK, json={"id": "1"})

    return {
        "config": str(config_path),
        "state": str(tmp_path / "estado"),
        "mock": requests_mock,
    }


def ejecutar(entorno, *extra):
    return cli.main(
        ["--config", entorno["config"], "--state-dir", entorno["state"], *extra]
    )


def mensajes_discord(requests_mock):
    return [r.json() for r in requests_mock.request_history if r.url == WEBHOOK]


def test_una_pasada_completa_avisa_del_chollo(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK

    enviados = mensajes_discord(entorno["mock"])
    assert len(enviados) == 1
    embed = enviados[0]["embeds"][0]
    assert embed["title"] == "Greaves of the Noxious Depths"
    assert "45.000" in embed["description"]
    assert any(f["value"] == "Dun Modr" for f in embed["fields"])


def test_el_aviso_lleva_miniatura_y_hora_del_volcado(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
        headers={"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"},
    )

    ejecutar(entorno)

    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert embed["thumbnail"] == {"url": ICON_URL}
    assert embed["timestamp"].startswith("2026-08-30T11:31:16")


def test_el_icono_se_cachea_entre_pasadas(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000), subasta(2, 44_000 * 10_000)]},
    )

    ejecutar(entorno)
    ejecutar(entorno, "--ignore-state")

    peticiones = [r for r in entorno["mock"].request_history if "/media/item/" in r.url]
    assert len(peticiones) == 1


def test_un_fallo_al_pedir_el_icono_no_impide_el_aviso(entorno):
    entorno["mock"].get(f"{BASE}/media/item/5000", status_code=404)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK

    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert "thumbnail" not in embed
    assert embed["title"] == "Greaves of the Noxious Depths"


def test_ningun_chollo_se_pierde_cuando_hay_mas_de_los_que_caben(entorno):
    """Lo que no cabe en un aviso se envia en la pasada siguiente.

    El fallo que esto evita: marcar como avisados los que no se enviaron, con
    lo que desaparecerian para siempre.
    """
    from wowalerts.notifier import MAX_DEALS_PER_RUN

    total = MAX_DEALS_PER_RUN + 7
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(i, (30_000 + i) * 10_000) for i in range(total)]},
    )

    ejecutar(entorno)
    primera = sum(len(m["embeds"]) for m in mensajes_discord(entorno["mock"]))
    assert primera == MAX_DEALS_PER_RUN

    ejecutar(entorno)
    total_enviado = sum(len(m["embeds"]) for m in mensajes_discord(entorno["mock"]))
    assert total_enviado == total, "los 7 sobrantes tienen que llegar en la 2a pasada"


def test_la_segunda_pasada_no_repite_el_mismo_chollo(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    ejecutar(entorno)
    ejecutar(entorno)

    assert len(mensajes_discord(entorno["mock"])) == 1


def test_ignore_state_vuelve_a_avisar(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    ejecutar(entorno)
    ejecutar(entorno, "--ignore-state")

    assert len(mensajes_discord(entorno["mock"])) == 2


def test_sin_chollos_no_se_envia_nada(entorno):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 200_000 * 10_000)]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK
    assert mensajes_discord(entorno["mock"]) == []


def test_una_subasta_solo_con_puja_no_dispara_alerta(entorno):
    """El fallo clasico: sin buyout, el precio 0 pasaba cualquier filtro."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [{"id": 1, "item": {"id": 5000, "bonus_lists": [12843]}, "bid": 100}]},
    )

    assert ejecutar(entorno) == cli.EXIT_OK
    assert mensajes_discord(entorno["mock"]) == []


def test_dry_run_no_envia_ni_guarda_estado(entorno, tmp_path):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    assert ejecutar(entorno, "--dry-run") == cli.EXIT_OK

    assert mensajes_discord(entorno["mock"]) == []
    assert not (tmp_path / "estado" / "notified.json").exists()


def test_realms_limita_el_escaneo(entorno):
    """Con --realms no se pide el indice de reinos de toda la region."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions", json={"auctions": []}
    )

    assert ejecutar(entorno, "--realms", "1305") == cli.EXIT_OK

    urls = [r.url for r in entorno["mock"].request_history]
    assert not any("connected-realm/index" in u for u in urls)


def test_realms_mal_escrito_da_error_claro(entorno, caplog):
    assert ejecutar(entorno, "--realms", "1305,silvermoon") == cli.EXIT_CONFIG_ERROR
    assert "--realms" in caplog.text


def test_test_discord_envia_solo_el_mensaje_de_prueba(entorno):
    assert ejecutar(entorno, "--test-discord") == cli.EXIT_OK

    enviados = mensajes_discord(entorno["mock"])
    assert len(enviados) == 1
    assert "Prueba de conexion" in enviados[0]["content"]


def test_demasiados_reinos_caidos_termina_con_error(entorno):
    entorno["mock"].get(f"{BASE}/connected-realm/1305/auctions", status_code=500)

    assert ejecutar(entorno) == cli.EXIT_TOO_MANY_FAILURES

    avisos = mensajes_discord(entorno["mock"])
    assert "Escaneo incompleto" in avisos[0]["embeds"][0]["title"]


def test_credenciales_invalidas_dan_error_de_configuracion(entorno, caplog):
    entorno["mock"].post(TOKEN_URL, status_code=401)

    assert ejecutar(entorno) == cli.EXIT_CONFIG_ERROR
    assert "BLIZZARD_CLIENT_ID" in caplog.text


def test_config_inexistente(tmp_path, caplog):
    assert cli.main(["--config", str(tmp_path / "no.yaml")]) == cli.EXIT_CONFIG_ERROR
    assert "No encuentro el fichero" in caplog.text


def test_informa_de_la_antiguedad_del_volcado(entorno, caplog):
    caplog.set_level(logging.INFO)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers={"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"},
    )

    ejecutar(entorno)

    assert "11:31 UTC" in caplog.text


def test_el_estado_guardado_es_legible(entorno, tmp_path):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )

    ejecutar(entorno)

    estado = json.loads((tmp_path / "estado" / "notified.json").read_text(encoding="utf-8"))
    assert estado["auctions"] == {"1305:1": 1}


# ---------------------------------------------------------------------------
#  Reintento cuando Blizzard publica el volcado tarde
# ---------------------------------------------------------------------------
#
#  El cron dispara a y 33 y el volcado sale hacia y 23. Si Blizzard se retrasa,
#  la pasada se encuentra los datos de la hora anterior y, sin reintento, no
#  habria otra oportunidad hasta la hora siguiente.
#
#  Mientras espera no duerme a ciegas: le pregunta la hora de publicacion a un
#  reino cada pocos segundos, que cuesta unas decimas porque no baja el cuerpo
#  de la respuesta, y reescanea en cuanto sale el volcado nuevo. Esas preguntas
#  van al mismo endpoint que el escaneo, asi que aqui cuentan como peticiones.

AHORA = datetime(2026, 8, 30, 12, 33, tzinfo=timezone.utc)
# Hora y diez a las 12:33, o sea por encima del margen: Blizzard va tarde.
VOLCADO_VIEJO = {"Last-Modified": "Sun, 30 Aug 2026 11:23:30 GMT"}
# Diez minutos: es el de esta hora.
VOLCADO_NUEVO = {"Last-Modified": "Sun, 30 Aug 2026 12:23:30 GMT"}

# Los que trae config.yaml por defecto: 120 s de vigilancia preguntando cada 15.
SONDEOS_POR_INTENTO = 8
CADA = 15


@pytest.fixture
def reloj_parado(monkeypatch):
    """Congela el reloj a y 33, que es cuando corre el cron de verdad."""

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return AHORA

    monkeypatch.setattr(cli, "datetime", Reloj)


@pytest.fixture
def esperas(monkeypatch):
    """Recoge las esperas en vez de dormirlas."""
    dormido = []
    monkeypatch.setattr("time.sleep", lambda s: dormido.append(s))
    return dormido


def escaneos(requests_mock):
    """Peticiones a las subastas: los escaneos y tambien los sondeos de espera.

    No se distinguen desde aqui porque van al mismo endpoint; la diferencia es
    que el sondeo corta la respuesta antes del cuerpo, y eso no deja rastro en
    el historial del mock.
    """
    return [r for r in requests_mock.request_history if r.path.endswith("/auctions")]


def con_ajustes(entorno, tmp_path, extra):
    """Reescribe el config con opciones adicionales dentro de 'settings'."""
    path = tmp_path / "config-ajustado.yaml"
    path.write_text(CONFIG + extra, encoding="utf-8")
    entorno["config"] = str(path)
    return entorno


def test_si_el_volcado_va_tarde_se_espera_y_se_vuelve_a_mirar(
    entorno, reloj_parado, esperas
):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            # El escaneo, que se encuentra los datos de la hora anterior.
            {"json": {"auctions": []}, "headers": VOLCADO_VIEJO},
            # El primer sondeo, que ya ve el volcado nuevo.
            {"json": {"auctions": []}, "headers": VOLCADO_NUEVO},
            # El reescaneo, que trae el chollo.
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_NUEVO,
            },
        ],
    )

    assert ejecutar(entorno) == 0

    assert len(escaneos(entorno["mock"])) == 3
    # Se vuelve en cuanto aparece, no al agotar los 120 s de vigilancia.
    assert esperas == [CADA]
    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert embed["title"] == "Greaves of the Noxious Depths"


def test_un_chollo_visto_solo_en_el_primer_intento_se_envia_igual(
    entorno, reloj_parado, esperas
):
    """La garantia que importa: reintentar no puede tragarse un aviso."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_VIEJO,
            },
            {"json": {"auctions": []}, "headers": VOLCADO_NUEVO},
            {"json": {"auctions": []}, "headers": VOLCADO_NUEVO},
        ],
    )

    ejecutar(entorno)

    # Hubo segundo intento y ya no traia el chollo: el aviso salio del primero.
    assert len(escaneos(entorno["mock"])) == 3
    embeds = [e for m in mensajes_discord(entorno["mock"]) for e in m["embeds"]]
    assert len(embeds) == 1
    assert embeds[0]["title"] == "Greaves of the Noxious Depths"


def test_no_se_avisa_dos_veces_del_mismo_chollo_entre_intentos(
    entorno, reloj_parado, esperas
):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_VIEJO,
            },
            {"json": {"auctions": []}, "headers": VOLCADO_NUEVO},
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_NUEVO,
            },
        ],
    )

    ejecutar(entorno)

    embeds = [e for m in mensajes_discord(entorno["mock"]) for e in m["embeds"]]
    assert len(embeds) == 1


def test_se_deja_de_reintentar_al_agotar_los_intentos(
    entorno, reloj_parado, esperas, caplog
):
    caplog.set_level(logging.WARNING)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_VIEJO,
    )

    assert ejecutar(entorno) == 0

    # El primer escaneo, mas los dos reintentos que trae por defecto, mas los
    # sondeos de cada espera, que nunca ven nada nuevo y la agotan entera.
    assert len(escaneos(entorno["mock"])) == 3 + 2 * SONDEOS_POR_INTENTO
    assert esperas == [CADA] * (2 * SONDEOS_POR_INTENTO)
    assert "ya no quedan" in caplog.text


def test_los_reintentos_se_pueden_desactivar(
    entorno, reloj_parado, esperas, tmp_path
):
    con_ajustes(entorno, tmp_path, "  stale_retries: 0\n")
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_VIEJO,
    )

    ejecutar(entorno)

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []


# ---------------------------------------------------------------------------
#  Aviso de cron desalineado
# ---------------------------------------------------------------------------
#
#  Blizzard mueve la hora de publicacion cada pocas semanas sin avisar: el
#  2026-08-31 el volcado salia a y 31 y el 2026-09-02 ya salia a y 23. Cuando
#  eso pasa todo sigue funcionando y lo unico que se nota es que los avisos
#  llegan tarde, que es la clase de deterioro del que no te enteras nunca.


class NotificadorFalso:
    def __init__(self):
        self.avisos = []

    def send_warning(self, titulo, texto):
        self.avisos.append((titulo, texto))


def alinear(
    tmp_path,
    arranque_min,
    publicado_min,
    *,
    hora_publicacion=12,
    veces=1,
    callado=False,
):
    """Corre el mantenimiento del disparo `veces` pasadas seguidas."""
    historial = cli.HistorialDeVolcados(tmp_path / "volcados.json")
    notificador = NotificadorFalso()
    for _ in range(veces):
        cli.mantener_disparo_alineado(
            datetime(2026, 9, 2, 12, arranque_min, tzinfo=timezone.utc),
            datetime(
                2026, 9, 2, hora_publicacion, publicado_min, 30, tzinfo=timezone.utc
            ),
            historial,
            notificador,
            dry_run=False,
            callado=callado,
        )
    return notificador, historial


def test_sin_credenciales_te_avisa_por_discord(tmp_path, monkeypatch, caplog):
    """Enterrarlo en el log de Actions es lo mismo que no decirlo."""
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)
    monkeypatch.delenv("CRONJOB_JOB_ID", raising=False)
    caplog.set_level(logging.WARNING)

    notificador, _ = alinear(tmp_path, arranque_min=33, publicado_min=23, veces=3)

    assert len(notificador.avisos) == 1
    titulo, texto = notificador.avisos[0]
    assert "desalineado" in titulo
    assert "minuto 24" in texto


def test_con_credenciales_lo_mueve_solo(tmp_path, monkeypatch, requests_mock):
    monkeypatch.setenv("CRONJOB_API_KEY", "clave")
    monkeypatch.setenv("CRONJOB_JOB_ID", "7788")
    requests_mock.patch("https://api.cron-job.org/jobs/7788", json={})

    notificador, _ = alinear(tmp_path, arranque_min=33, publicado_min=23, veces=3)

    assert requests_mock.request_history[-1].json() == {
        "job": {"schedule": {"minutes": [24]}}
    }
    assert "He movido" in notificador.avisos[0][0]


def test_no_avisa_hasta_que_varias_pasadas_coinciden(tmp_path, monkeypatch):
    """Un tropiezo suelto de Blizzard no puede mover el cron."""
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)

    notificador, _ = alinear(tmp_path, arranque_min=33, publicado_min=23, veces=2)

    assert notificador.avisos == []


def test_un_disparo_bien_puesto_no_dice_nada(tmp_path, monkeypatch):
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)

    notificador, _ = alinear(tmp_path, arranque_min=24, publicado_min=23, veces=4)

    assert notificador.avisos == []


def test_tras_avisar_no_reincide_a_la_hora_siguiente(tmp_path, monkeypatch):
    """Si no, tendrias el mismo aviso cada hora hasta que lo cambiaras."""
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)

    notificador, _ = alinear(tmp_path, arranque_min=33, publicado_min=23, veces=4)

    assert len(notificador.avisos) == 1


def test_un_volcado_de_hace_horas_no_habla_del_cron(tmp_path, monkeypatch):
    """Ahi el retrasado es Blizzard, y eso ya tiene su propio aviso."""
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)

    notificador, historial = alinear(
        tmp_path, arranque_min=33, publicado_min=23, hora_publicacion=10, veces=3
    )

    assert notificador.avisos == []
    assert historial.minutos == []


def test_si_cron_job_org_falla_se_reintenta_a_la_siguiente(
    tmp_path, monkeypatch, requests_mock, caplog
):
    """Sin olvidar lo medido: un fallo pasajero no puede perder el diagnostico."""
    monkeypatch.setenv("CRONJOB_API_KEY", "clave")
    monkeypatch.setenv("CRONJOB_JOB_ID", "7788")
    requests_mock.patch("https://api.cron-job.org/jobs/7788", status_code=500)
    caplog.set_level(logging.ERROR)

    _, historial = alinear(tmp_path, arranque_min=33, publicado_min=23, veces=3)

    assert "500" in caplog.text
    assert historial.minutos != []


def test_a_mano_no_se_mide_el_desfase(monkeypatch):
    """La hora de arranque la eliges tu, asi que no dice nada del cron."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert not cli.es_pasada_programada()


def test_el_cron_externo_si(monkeypatch):
    """El disparo puntual: arranca en segundos, asi que su hora dice la verdad."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    assert cli.es_pasada_programada()


def test_el_schedule_de_github_no_cuenta(monkeypatch):
    """Sus eventos entran en cola y se retrasan entre 20 y 40 minutos.

    El 2026-09-02 una pasada de 'schedule' programada a y 25 arranco a y 49, se
    midio un descuelgue de 26 minutos y se aviso de que el disparo estaba mal
    cuando estaba perfectamente puesto.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    assert not cli.es_pasada_programada()


# ---------------------------------------------------------------------------
#  No procesar un volcado que esta a punto de caducar
# ---------------------------------------------------------------------------
#
#  Cuando el disparo se queda justo POR DELANTE de la publicacion --lo que pasa
#  en cuanto Blizzard la mueve mas tarde-- cada pasada se encontraria el volcado
#  de la hora anterior, y avisaria de chollos de hace casi una hora que ya se ha
#  llevado alguien. Mejor esperar los pocos minutos que faltan.

# A las 12:33, un volcado de las 11:39 tiene 54 min: el siguiente sale en 6.
VOLCADO_CASI_CADUCO = {"Last-Modified": "Sun, 30 Aug 2026 11:39:00 GMT"}


def test_espera_al_volcado_nuevo_si_esta_a_punto_de_salir(
    entorno, reloj_parado, esperas, monkeypatch
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        [
            {"json": {"auctions": []}, "headers": VOLCADO_CASI_CADUCO},
            {"json": {"auctions": []}, "headers": VOLCADO_NUEVO},
            {
                "json": {"auctions": [subasta(1, 45_000 * 10_000)]},
                "headers": VOLCADO_NUEVO,
            },
        ],
    )

    assert ejecutar(entorno) == 0

    # El chollo sale del volcado nuevo, no del que estaba a punto de caducar.
    embed = mensajes_discord(entorno["mock"])[0]["embeds"][0]
    assert embed["title"] == "Greaves of the Noxious Depths"
    assert esperas == [CADA]


def test_a_mano_no_se_espera_aunque_el_volcado_este_viejo(
    entorno, reloj_parado, esperas, monkeypatch
):
    """Esperar diez minutos mientras pruebas algo no lo quiere nadie."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_CASI_CADUCO,
    )

    assert ejecutar(entorno) == 0

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []


def test_deja_de_esperar_si_el_disparo_no_se_recoloca(
    entorno, reloj_parado, esperas, monkeypatch, caplog, tmp_path
):
    """El freno de mano del gasto.

    Esperar sale a cuenta mientras el disparo acabe recolocandose. Si no lo
    hiciera --la clave de cron-job.org caducada, por ejemplo-- esperar 12 min
    cada hora son 288 al dia, y en Actions el tiempo de trabajo se paga.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    caplog.set_level(logging.WARNING)
    historial = cli.HistorialDeVolcados(Path(entorno["state"]) / "volcados.json")
    for _ in range(cli.ESPERAS_SEGUIDAS_MAXIMAS):
        historial.apunta_espera()
    historial.save()

    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_CASI_CADUCO,
    )

    assert ejecutar(entorno) == 0

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []
    assert "Dejo de esperar" in caplog.text


def test_el_contador_de_esperas_se_reinicia_al_llegar_un_volcado_sano(
    entorno, reloj_parado, esperas, monkeypatch
):
    """Si no, tras un episodio malo quedaria el freno echado para siempre."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    ruta = Path(entorno["state"]) / "volcados.json"
    historial = cli.HistorialDeVolcados(ruta)
    historial.apunta_espera()
    historial.save()

    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_NUEVO,
    )
    ejecutar(entorno)

    assert cli.HistorialDeVolcados(ruta).esperas_seguidas == 0


def test_un_volcado_recien_salido_no_hace_esperar(
    entorno, reloj_parado, esperas, monkeypatch
):
    """El caso normal: el siguiente esta a 50 min, no hay nada que esperar."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_NUEVO,
    )

    assert ejecutar(entorno) == 0

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []


def test_un_volcado_al_dia_no_provoca_ninguna_espera(entorno, reloj_parado, esperas):
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": []},
        headers=VOLCADO_NUEVO,
    )

    ejecutar(entorno)

    assert len(escaneos(entorno["mock"])) == 1
    assert esperas == []


# -- Modo undercut ----------------------------------------------------------

from main import agrupar_por_reino, build_parser as _parser
from wowalerts.misubastas import MyAuction


def una_mia(auction_id=1, realm="Sanguino", slug="sanguino", item_id=200000):
    return MyAuction(
        auction_id=auction_id,
        item_id=item_id,
        item_name="Greaves of the Noxious Depths",
        ilvl=311,
        buyout_copper=90_000_000,
        quantity=1,
        character="Pepe",
        realm=realm,
        realm_slug=slug,
    )


def test_el_parser_acepta_undercut():
    assert _parser().parse_args(["--undercut"]).undercut is True


def test_el_parser_acepta_ventas():
    assert _parser().parse_args(["--ventas"]).ventas is True


def test_undercut_y_ventas_se_combinan():
    args = _parser().parse_args(["--undercut", "--ventas"])
    assert args.undercut is True
    assert args.ventas is True


def test_por_defecto_no_hay_ventas():
    assert _parser().parse_args([]).ventas is False


def test_agrupa_las_subastas_por_reino_conectado():
    mias = [
        una_mia(1, "Sanguino", "sanguino"),
        una_mia(2, "Dun Modr", "dun-modr"),
        una_mia(3, "Sanguino", "sanguino"),
    ]
    grupos = agrupar_por_reino(mias, {"Sanguino": 1379, "Dun Modr": 1379})
    # Los dos reinos comparten connected realm: una sola descarga.
    assert list(grupos) == [1379]
    assert len(grupos[1379]) == 3


def test_las_subastas_de_reinos_sin_resolver_se_omiten():
    mias = [una_mia(1, "Sanguino", "sanguino"), una_mia(2, "Fantasma", "fantasma")]
    grupos = agrupar_por_reino(mias, {"Sanguino": 1379})
    assert list(grupos) == [1379]
    assert len(grupos[1379]) == 1


# -- Aviso de personajes con datos caducados --------------------------------

from main import caducados_por_avisar


def test_se_avisa_de_los_caducados_nuevos():
    assert caducados_por_avisar(["Ana", "Luis"], []) == ["Ana", "Luis"]


def test_no_se_repite_el_aviso_de_los_mismos():
    """Si no, te lo cantaria cada hora hasta que los visites."""
    assert caducados_por_avisar(["Ana", "Luis"], ["Ana", "Luis"]) == []


def test_uno_nuevo_vuelve_a_avisar():
    assert caducados_por_avisar(["Ana", "Luis"], ["Ana"]) == ["Luis"]


def test_que_se_arregle_uno_no_dispara_aviso():
    assert caducados_por_avisar(["Ana"], ["Ana", "Luis"]) == []


# -- La pasada de mis subastas, de punta a punta -----------------------------


def test_la_pasada_de_mis_subastas_arranca(entorno, tmp_path, monkeypatch):
    """Ningun test llamaba a run_mis_subastas, y se subio con la firma rota.

    Los 416 tests pasaban mientras produccion moria con un TypeError en la
    primera linea: la funcion no la cubria nadie. Esto la ejecuta de verdad.
    """
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions", json={"auctions": []}
    )
    (tmp_path / "subastas").mkdir()
    (tmp_path / "roster").mkdir()
    (tmp_path / "ventas").mkdir()

    assert (
        ejecutar(
            entorno,
            "--undercut",
            "--ventas",
            "--mis-subastas",
            str(tmp_path / "subastas"),
            "--personajes",
            str(tmp_path / "roster"),
            "--mis-ventas",
            str(tmp_path / "ventas"),
        )
        == cli.EXIT_OK
    )


def test_la_firma_de_run_mis_subastas_acepta_la_llamada_de_run():
    """Guarda contra volver a mover un argumento al otro lado del asterisco."""
    import inspect

    firma = inspect.signature(cli.run_mis_subastas)
    posicionales = [
        n
        for n, p in firma.parameters.items()
        if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    assert posicionales == [
        "client",
        "config",
        "rules_by_item_id",
        "notifier_undercut",
        "notifier_ventas",
        "state_dir",
        "mis_subastas_path",
        "roster_path",
        "mis_ventas_path",
    ]


# -- Objetos de los que no quieres avisos de undercut -------------------------

CONFIG_SIN_UNDERCUT = """
region: eu
items:
  - name: "Greaves of the Noxious Depths"
    item_id: 5000
    max_price_by_ilvl: { 311: 90000 }
  - name: "Pattern: Arcanoweave Cord"
    item_id: 5001
    max_price: 60000
    avisar_undercut: false
bonus_ilvl_map:
  12843: 311
"""


def _mia(auction_id, item_id, nombre, oro, bonus, ilvl):
    return {
        "auctionID": auction_id,
        "itemID": item_id,
        "itemName": nombre,
        "ilvl": ilvl,
        "buyout": oro * 10_000,
        "quantity": 1,
        "character": "Ana",
        "realm": "Dun Modr",
        "bonusIDs": list(bonus),
        "exportedAt": int(datetime.now(timezone.utc).timestamp()),
    }


def _ajena(auction_id, item_id, oro, bonus):
    return {
        "id": auction_id,
        "item": {"id": item_id, "bonus_lists": list(bonus)},
        "buyout": oro * 10_000,
        "quantity": 1,
        "time_left": "LONG",
    }


def test_un_objeto_con_avisar_undercut_false_no_genera_avisos(
    entorno, tmp_path, monkeypatch, caplog
):
    """Del patron quiero chollos y ventas, pero no que me adelanten."""
    Path(entorno["config"]).write_text(CONFIG_SIN_UNDERCUT, encoding="utf-8")

    subastas_dir = tmp_path / "subastas"
    subastas_dir.mkdir()
    (subastas_dir / "pc.json").write_text(
        json.dumps(
            {
                "auctions": [
                    _mia(900, 5000, "Grebas de las profundidades", 80_000, (12843,), 311),
                    _mia(901, 5001, "Patron: cordon arcanotejido", 60_000, (), 1),
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "roster").mkdir()

    entorno["mock"].get(
        f"{BASE}/realm/dun-modr",
        json={"connected_realm": {"href": f"{BASE}/connected-realm/1305"}},
    )
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={
            "auctions": [
                _ajena(900, 5000, 80_000, (12843,)),  # la mia
                _ajena(910, 5000, 70_000, (12843,)),  # me adelanta
                _ajena(901, 5001, 60_000, ()),  # la mia
                _ajena(911, 5001, 50_000, ()),  # me adelanta, pero da igual
            ]
        },
    )

    with caplog.at_level(logging.INFO):
        assert (
            ejecutar(
                entorno,
                "--undercut",
                "--dry-run",
                "--mis-subastas",
                str(subastas_dir),
                "--personajes",
                str(tmp_path / "roster"),
            )
            == cli.EXIT_OK
        )

    assert "Grebas de las profundidades" in caplog.text
    assert "cordon arcanotejido" not in caplog.text
    assert "Te han adelantado en 1 subasta(s)" in caplog.text


def test_sin_apagarlo_ese_mismo_objeto_si_avisaria(entorno, tmp_path, caplog):
    """La otra mitad del test anterior: sin la linea, el aviso sale."""
    Path(entorno["config"]).write_text(
        CONFIG_SIN_UNDERCUT.replace("    avisar_undercut: false\n", ""),
        encoding="utf-8",
    )

    subastas_dir = tmp_path / "subastas"
    subastas_dir.mkdir()
    (subastas_dir / "pc.json").write_text(
        json.dumps(
            {
                "auctions": [
                    _mia(901, 5001, "Patron: cordon arcanotejido", 60_000, (), 1),
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "roster").mkdir()

    entorno["mock"].get(
        f"{BASE}/realm/dun-modr",
        json={"connected_realm": {"href": f"{BASE}/connected-realm/1305"}},
    )
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={
            "auctions": [
                _ajena(901, 5001, 60_000, ()),
                _ajena(911, 5001, 50_000, ()),
            ]
        },
    )

    with caplog.at_level(logging.INFO):
        ejecutar(
            entorno,
            "--undercut",
            "--dry-run",
            "--mis-subastas",
            str(subastas_dir),
            "--personajes",
            str(tmp_path / "roster"),
        )

    assert "cordon arcanotejido" in caplog.text


# -- De madrugada se arregla igual, pero sin despertarte ---------------------
#
#  Antes en silencio ni se medía, y si Blizzard cambiaba la hora a las 02:00 no
#  se enteraba hasta las 09:25: con las tres pasadas que hacen falta, hasta las
#  11:25 no quedaba arreglado. Toda la manana con los avisos desalineados.


def test_en_silencio_mueve_el_disparo_igual(tmp_path, monkeypatch, requests_mock):
    """Cambiar el minuto del cron no despierta a nadie."""
    monkeypatch.setenv("CRONJOB_API_KEY", "clave")
    monkeypatch.setenv("CRONJOB_JOB_ID", "7788")
    requests_mock.patch("https://api.cron-job.org/jobs/7788", json={})

    notificador, historial = alinear(
        tmp_path, arranque_min=33, publicado_min=23, veces=3, callado=True
    )

    assert requests_mock.request_history[-1].json() == {
        "job": {"schedule": {"minutes": [24]}}
    }
    # Lo unico que se aplaza es contarlo.
    assert notificador.avisos == []
    assert historial.aviso_pendiente is not None


def test_el_aviso_de_madrugada_se_recoge_al_despertar(tmp_path, monkeypatch):
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)
    ruta = tmp_path / "volcados.json"

    notificador, historial = alinear(
        tmp_path, arranque_min=33, publicado_min=23, veces=3, callado=True
    )
    assert notificador.avisos == []
    historial.save()

    guardado = cli.HistorialDeVolcados(ruta)
    titulo, texto = guardado.recoge_aviso()

    assert "desalineado" in titulo
    assert "minuto 24" in texto


def test_el_aviso_aplazado_no_se_manda_dos_veces(tmp_path, monkeypatch):
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)

    _, historial = alinear(
        tmp_path, arranque_min=33, publicado_min=23, veces=3, callado=True
    )

    assert historial.recoge_aviso() is not None
    assert historial.recoge_aviso() is None


def test_el_schedule_de_github_si_espera_al_volcado(monkeypatch):
    """Son dos preguntas distintas y conviene no volver a mezclarlas.

    Si la hora de arranque dice algo del cron -> solo el disparo puntual.
    Si merece la pena esperar al volcado -> cualquier pasada desatendida, y una
    de 'schedule' lo es: no hay nadie delante a quien hacer esperar.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    assert cli.es_pasada_desatendida()
    assert not cli.es_pasada_programada()


def test_a_mano_no_espera_ni_mide(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)

    assert not cli.es_pasada_desatendida()
    assert not cli.es_pasada_programada()


# -- Los nombres con los que se reconocen las ventas -------------------------


class ClienteDeNombres:
    """Un cliente de mentira que apunta a quien le han preguntado."""

    def __init__(self, objetos=None, especies=None):
        self.objetos = objetos or {}
        self.especies = especies or {}
        self.preguntas = []

    def item_names(self, item_id):
        self.preguntas.append(("item", item_id))
        return self.objetos.get(item_id, {})

    def pet_species_names(self, species_id):
        self.preguntas.append(("pet", species_id))
        return self.especies.get(species_id, {})


def test_los_nombres_llegan_en_todos_los_idiomas(tmp_path):
    """Journalator apunta el nombre que ve tu cliente, no el id."""
    cliente = ClienteDeNombres({5000: {"en_GB": "Greaves", "es_ES": "Grebas"}})
    cache = cli.JsonMapCache(tmp_path / "n.json", "nombres")

    assert cli.nombres_vigilados(cliente, cache, [5000]) == {"Greaves", "Grebas"}


def test_las_mascotas_se_preguntan_por_especie(tmp_path):
    """En la casa de subastas todas son la misma jaula; en el correo, no."""
    cliente = ClienteDeNombres(especies={242: {"en_GB": "Spectral Tiger Cub"}})
    cache = cli.JsonMapCache(tmp_path / "n.json", "nombres")

    assert cli.nombres_vigilados(cliente, cache, [], [242]) == {"Spectral Tiger Cub"}
    assert cliente.preguntas == [("pet", 242)]


def test_un_objeto_y_una_especie_con_el_mismo_numero_no_se_pisan(tmp_path):
    cliente = ClienteDeNombres({242: {"en_GB": "Objeto"}}, {242: {"en_GB": "Mascota"}})
    cache = cli.JsonMapCache(tmp_path / "n.json", "nombres")

    assert cli.nombres_vigilados(cliente, cache, [242], [242]) == {"Objeto", "Mascota"}


def test_el_nombre_ya_guardado_no_se_vuelve_a_pedir(tmp_path):
    ruta = tmp_path / "n.json"
    cliente = ClienteDeNombres({5000: {"en_GB": "Greaves"}})
    cache = cli.JsonMapCache(ruta, "nombres")
    cli.nombres_vigilados(cliente, cache, [5000])
    cache.save()

    otro = ClienteDeNombres()
    assert cli.nombres_vigilados(otro, cli.JsonMapCache(ruta, "nombres"), [5000]) == {
        "Greaves"
    }
    assert otro.preguntas == []


def test_un_nombre_que_no_llega_se_reintenta_la_proxima_vez(tmp_path):
    """Cachear el vacio dejaria ese objeto fuera del panel para siempre."""
    ruta = tmp_path / "n.json"
    cache = cli.JsonMapCache(ruta, "nombres")

    assert cli.nombres_vigilados(ClienteDeNombres(), cache, [5000]) == set()
    cache.save()

    cliente = ClienteDeNombres({5000: {"en_GB": "Greaves"}})
    assert cli.nombres_vigilados(cliente, cli.JsonMapCache(ruta, "nombres"), [5000]) == {
        "Greaves"
    }


# -- Una maquina que se calla a mitad de sesion -------------------------------
#
# El 2026-09-07 salieron ocho ventas falsas: las cancelaste en la Steam Deck y
# su volcado se corto a mitad de la ronda de personajes. Blizzard solo dice que
# la subasta ya no esta; quien puede decir que la cancelaste es esa maquina.


def _sembrar_una_desaparecida(state_dir, desaparecida_at, ahora):
    from wowalerts.state import SeguimientoVentas
    from wowalerts.ventas import SubastaVigilada, UltimoVolcado

    memoria = SeguimientoVentas(Path(state_dir) / "ventas.json")
    memoria.actualizar_reino(
        1305,
        {
            77: SubastaVigilada(
                auction_id=77,
                item_id=5000,
                item_name="Greaves of the Noxious Depths",
                ilvl=311,
                buyout_copper=200_000 * 10_000,
                quantity=1,
                character="Pepe",
                realm="Dun Modr",
                account=2,
                # Aun no podia caducar: lo unico que queda por decidir es si se
                # vendio o si la cancelaste.
                no_caduca_antes_de=ahora + timedelta(hours=5),
                visto_at=desaparecida_at - timedelta(hours=1),
                desaparecida_at=desaparecida_at,
            )
        },
        UltimoVolcado(desaparecida_at, 1000),
    )
    memoria.save()


def _pasada_con_una_desaparecida(entorno, tmp_path, exporto_hace):
    """Una pasada en la que la subasta 77 lleva una hora sin aparecer.

    `exporto_hace` es cuanto hace que la maquina dio su ultima senal de vida.
    """
    from wowalerts.misubastas import MyAuction, escribir_snapshot

    ahora = datetime.now(timezone.utc)
    desaparecida_at = ahora - timedelta(hours=1)

    subastas = tmp_path / "subastas"
    subastas.mkdir()
    (tmp_path / "roster").mkdir()
    (tmp_path / "ventas").mkdir()
    escribir_snapshot(
        subastas / "deck.json",
        [
            MyAuction(
                auction_id=99,
                item_id=5000,
                item_name="Greaves of the Noxious Depths",
                ilvl=311,
                buyout_copper=200_000 * 10_000,
                quantity=1,
                character="Pepe",
                realm="Dun Modr",
                realm_slug="dun-modr",
                account=2,
                bonus_ids=(12843,),
                exported_at=int((ahora - exporto_hace).timestamp()),
            )
        ],
    )
    _sembrar_una_desaparecida(entorno["state"], desaparecida_at, ahora)

    entorno["mock"].get(
        f"{BASE}/realm/dun-modr",
        json={"connected_realm": {"href": f"{BASE}/connected-realm/1305"}},
    )
    entorno["mock"].post(
        "https://discord.com/api/webhooks/2/undercut", json={"id": "1"}
    )
    entorno["mock"].get(
        "https://discord.com/api/webhooks/2/undercut", json={"id": "1"}
    )
    entorno["mock"].get(
        f"{BASE}/realm/dun-modr",
        json={"connected_realm": {"href": f"{BASE}/connected-realm/1305"}},
    )
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(99, 200_000 * 10_000)]},
    )

    return ejecutar(
        entorno,
        "--undercut",
        "--ventas",
        "--mis-subastas",
        str(subastas),
        "--personajes",
        str(tmp_path / "roster"),
        "--mis-ventas",
        str(tmp_path / "ventas"),
    )


def test_no_se_canta_la_venta_si_la_maquina_jugaba_y_sigue_callada(
    entorno, tmp_path, caplog
):
    with caplog.at_level(logging.INFO):
        assert (
            _pasada_con_una_desaparecida(
                entorno, tmp_path, exporto_hace=timedelta(minutes=90)
            )
            == cli.EXIT_OK
        )

    assert "💰" not in caplog.text
    assert "deck" in caplog.text


def test_se_canta_la_venta_si_no_habia_nadie_jugando(entorno, tmp_path, caplog):
    """La otra mitad: sin sesion cerca, una desaparicion si es una venta."""
    with caplog.at_level(logging.INFO):
        assert (
            _pasada_con_una_desaparecida(
                entorno, tmp_path, exporto_hace=timedelta(hours=6)
            )
            == cli.EXIT_OK
        )

    assert "💰 1 venta(s)" in caplog.text


def test_se_canta_la_venta_aunque_no_hayas_jugado_en_todo_un_listado(
    entorno, tmp_path, caplog
):
    """El 2026-09-11 las ventas de la noche no salieron hasta entrar al juego.

    Pasadas doce horas sin jugar, todo lo que exporto el addon es de un volcado
    viejo, y la pasada se despedia con "Nada que comprobar" antes de mirar el
    seguimiento. Pero lo que queda por resolver en el seguimiento lo avala
    Blizzard, no el addon: una Faja de 190.000 g vendida de madrugada se anuncio
    a las 13:22, despues de recoger el correo.
    """
    with caplog.at_level(logging.INFO):
        assert (
            _pasada_con_una_desaparecida(
                entorno, tmp_path, exporto_hace=timedelta(hours=13)
            )
            == cli.EXIT_OK
        )

    assert "💰 1 venta(s)" in caplog.text


# -- Un fallo en las ventas no hace repetir los undercuts --------------------

UNDERCUT_WEBHOOK = "https://discord.com/api/webhooks/2/undercut"


def test_si_fallan_las_ventas_los_undercuts_enviados_no_se_repiten(
    entorno, tmp_path, monkeypatch
):
    """Los undercuts van por un webhook y las ventas por otro.

    Si el de ventas fallaba, la excepcion subia antes de guardar la memoria de
    undercuts: los que ya habian llegado a Discord no constaban como avisados, y
    la pasada siguiente te los volvia a cantar.
    """
    from wowalerts.misubastas import MyAuction, escribir_snapshot

    monkeypatch.setenv("DISCORD_UNDERCUT_WEBHOOK_URL", UNDERCUT_WEBHOOK)
    monkeypatch.setenv("DISCORD_VENTAS_WEBHOOK_URL", VENTAS_WEBHOOK)
    entorno["mock"].post(UNDERCUT_WEBHOOK, json={"id": "1"})
    entorno["mock"].get(UNDERCUT_WEBHOOK, json={"id": "1"})
    # La segunda pasada reescribe el panel que creo la primera.
    entorno["mock"].patch(UNDERCUT_WEBHOOK + "/messages/1", status_code=200)
    entorno["mock"].post(VENTAS_WEBHOOK, status_code=500)

    ahora = datetime.now(timezone.utc)
    subastas = tmp_path / "subastas"
    subastas.mkdir()
    (tmp_path / "roster").mkdir()
    (tmp_path / "ventas").mkdir()
    escribir_snapshot(
        subastas / "deck.json",
        [
            MyAuction(
                auction_id=99,
                item_id=5000,
                item_name="Greaves of the Noxious Depths",
                ilvl=311,
                buyout_copper=200_000 * 10_000,
                quantity=1,
                character="Pepe",
                realm="Dun Modr",
                realm_slug="dun-modr",
                account=2,
                bonus_ids=(12843,),
                exported_at=int((ahora - timedelta(hours=6)).timestamp()),
            )
        ],
    )
    # Una venta por cantar, para que la pasada llegue a usar el webhook roto.
    _sembrar_una_desaparecida(entorno["state"], ahora - timedelta(hours=1), ahora)

    entorno["mock"].get(
        f"{BASE}/realm/dun-modr",
        json={"connected_realm": {"href": f"{BASE}/connected-realm/1305"}},
    )
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={
            "auctions": [
                subasta(99, 200_000 * 10_000),
                subasta(910, 150_000 * 10_000),  # te adelanta
            ]
        },
    )

    argumentos = (
        "--undercut",
        "--ventas",
        "--mis-subastas",
        str(subastas),
        "--personajes",
        str(tmp_path / "roster"),
        "--mis-ventas",
        str(tmp_path / "ventas"),
    )
    assert ejecutar(entorno, *argumentos) == cli.EXIT_CONFIG_ERROR

    def avisos_de_undercut():
        return [
            r
            for r in entorno["mock"].request_history
            if r.method == "POST" and r.url == UNDERCUT_WEBHOOK
        ]

    assert len(avisos_de_undercut()) == 1

    ejecutar(entorno, *argumentos)

    assert len(avisos_de_undercut()) == 1


def test_si_discord_cae_a_mitad_lo_que_ya_llego_no_se_repite(entorno):
    """Quince chollos van en dos mensajes. Si cae el segundo, los diez del
    primero ya estan en Discord: la pasada siguiente solo debe mandar los cinco
    que faltan, no los quince otra vez."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(i, 45_000 * 10_000) for i in range(1, 16)]},
    )
    entorno["mock"].post(WEBHOOK, [{"status_code": 204}] + [{"status_code": 500}] * 4)

    assert ejecutar(entorno) == cli.EXIT_CONFIG_ERROR

    entorno["mock"].post(WEBHOOK, status_code=204)
    antes = len(mensajes_discord(entorno["mock"]))
    assert ejecutar(entorno) == cli.EXIT_OK

    nuevos = mensajes_discord(entorno["mock"])[antes:]
    assert sum(len(m["embeds"]) for m in nuevos) == 5


def test_si_cae_el_webhook_de_undercuts_la_pasada_falla_limpia(
    entorno, tmp_path, monkeypatch, caplog
):
    """La rama que apunta lo entregado antes de dejar subir el error tiene que
    llegar a dejar subir el error, y no reventar por el camino."""
    Path(entorno["config"]).write_text(
        CONFIG_SIN_UNDERCUT.replace("    avisar_undercut: false\n", ""),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_UNDERCUT_WEBHOOK_URL", UNDERCUT_WEBHOOK)
    entorno["mock"].post(UNDERCUT_WEBHOOK, status_code=500)
    entorno["mock"].get(UNDERCUT_WEBHOOK, json={})

    subastas_dir = tmp_path / "subastas"
    subastas_dir.mkdir()
    (subastas_dir / "pc.json").write_text(
        json.dumps(
            {"auctions": [_mia(900, 5000, "Grebas", 80_000, (12843,), 311)]}
        ),
        encoding="utf-8",
    )
    (tmp_path / "roster").mkdir()
    entorno["mock"].get(
        f"{BASE}/realm/dun-modr",
        json={"connected_realm": {"href": f"{BASE}/connected-realm/1305"}},
    )
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={
            "auctions": [
                _ajena(900, 5000, 80_000, (12843,)),
                _ajena(910, 5000, 70_000, (12843,)),
            ]
        },
    )

    with caplog.at_level(logging.INFO):
        codigo = ejecutar(
            entorno,
            "--undercut",
            "--mis-subastas",
            str(subastas_dir),
            "--personajes",
            str(tmp_path / "roster"),
        )

    assert codigo == cli.EXIT_CONFIG_ERROR
    assert "No he podido enviar el aviso a Discord" in caplog.text


# -- Avisos pausados desde la app -------------------------------------------


def test_con_los_avisos_pausados_no_se_envia_nada_y_al_reanudar_si(entorno, caplog):
    """La pausa calla el envio como la ventana de silencio: el chollo no se
    marca como avisado, asi que al reanudar sale si sigue vivo."""
    entorno["mock"].get(
        f"{BASE}/connected-realm/1305/auctions",
        json={"auctions": [subasta(1, 45_000 * 10_000)]},
    )
    ruta = Path(entorno["config"])
    ruta.write_text(CONFIG + "  avisos_pausados: true\n", encoding="utf-8")

    with caplog.at_level(logging.INFO):
        assert ejecutar(entorno) == cli.EXIT_OK

    assert mensajes_discord(entorno["mock"]) == []
    assert "pausados" in caplog.text

    ruta.write_text(CONFIG + "  avisos_pausados: false\n", encoding="utf-8")
    assert ejecutar(entorno) == cli.EXIT_OK

    assert len(mensajes_discord(entorno["mock"])) == 1
