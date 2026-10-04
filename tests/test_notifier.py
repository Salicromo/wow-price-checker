import pytest
import requests

from wowalerts.config import COPPER_PER_GOLD
from wowalerts.notifier import (
    COLOR_STEAL,
    COLOR_UNCONFIRMED,
    MAX_DEALS_PER_RUN,
    DiscordError,
    DiscordNotifier,
    build_embed,
    build_messages,
    format_gold,
    realm_names_for,
)
from wowalerts.scanner import Deal

WEBHOOK = "https://discord.com/api/webhooks/1/abc"
REALMS = {1305: "Dun Modr / Sanguino"}


def make_deal(auction_id=1, price_gold=45_000, threshold_gold=90_000, confirmed=True):
    return Deal(
        auction_id=auction_id,
        item_id=5000,
        item_name="Greaves of the Noxious Depths",
        ilvl=311 if confirmed else None,
        ilvl_confirmed=confirmed,
        price_copper=price_gold * COPPER_PER_GOLD,
        threshold_copper=threshold_gold * COPPER_PER_GOLD,
        realm_id=1305,
        time_left="LONG",
    )


def test_formato_de_oro_a_la_espanola():
    assert format_gold(1_234_567) == "1.234.567"
    assert format_gold(999) == "999"


def test_el_embed_lleva_precio_ilvl_reino_y_enlace():
    embed = build_embed(make_deal(), REALMS[1305])

    assert embed["title"] == "Greaves of the Noxious Depths"
    assert embed["url"].startswith("https://www.wowhead.com/item=5000")
    assert "45.000" in embed["description"]
    assert "ilvl **311**" in embed["description"]
    assert "50%" in embed["description"]
    assert embed["color"] == COLOR_STEAL
    assert {"name": "Reino", "value": "Dun Modr / Sanguino", "inline": True} in embed["fields"]
    assert any(f["name"] == "Tiempo restante" for f in embed["fields"])


def test_el_embed_avisa_cuando_el_ilvl_no_esta_confirmado():
    embed = build_embed(make_deal(confirmed=False), REALMS[1305])

    assert "sin confirmar" in embed["description"]
    assert "antes de comprar" in embed["description"]
    assert embed["color"] == COLOR_UNCONFIRMED


def test_cada_embed_del_mensaje_lleva_una_url_distinta():
    """Discord fusiona los embeds de un mensaje que comparten url.

    Varias subastas del mismo objeto tienen el mismo enlace de Wowhead, asi que
    sin un ancla unica se veian todas como un solo embed.
    """
    deals = [make_deal(auction_id=i) for i in range(10)]

    urls = [e["url"] for e in build_messages(deals, REALMS)[0]["embeds"]]

    assert len(set(urls)) == len(urls)
    assert all(u.startswith("https://www.wowhead.com/item=5000") for u in urls)


def test_sin_chollos_no_se_genera_ningun_mensaje():
    assert build_messages([], REALMS) == []


def test_un_solo_mensaje_con_cabecera_para_pocos_chollos():
    messages = build_messages([make_deal(1), make_deal(2)], REALMS)

    assert len(messages) == 1
    assert "2 chollos" in messages[0]["content"]
    assert len(messages[0]["embeds"]) == 2


def test_cabecera_en_singular_con_un_solo_chollo():
    messages = build_messages([make_deal()], REALMS)
    assert "1 chollo" in messages[0]["content"]
    assert "chollos" not in messages[0]["content"]


def test_se_reparte_en_mensajes_de_diez_embeds():
    messages = build_messages([make_deal(i) for i in range(25)], REALMS)

    assert [len(m["embeds"]) for m in messages] == [10, 10, 5]
    # Solo el primer mensaje lleva cabecera, para no repetirla.
    assert "content" in messages[0]
    assert all("content" not in m for m in messages[1:])


def test_se_recorta_y_se_avisa_de_los_omitidos():
    messages = build_messages([make_deal(i) for i in range(MAX_DEALS_PER_RUN + 7)], REALMS)

    total = sum(len(m["embeds"]) for m in messages)
    assert total == MAX_DEALS_PER_RUN
    assert "7 mas" in messages[0]["content"]


def test_reino_desconocido_se_muestra_por_su_id():
    embed = build_messages([make_deal()], {})[0]["embeds"][0]
    assert any(f["value"] == "Reino 1305" for f in embed["fields"])


def test_realm_names_for_consulta_una_vez_por_reino():
    llamadas = []

    def lookup(realm_id):
        llamadas.append(realm_id)
        return f"Reino {realm_id}"

    deals = [make_deal(1), make_deal(2), make_deal(3)]
    names = realm_names_for(deals, lookup)

    assert llamadas == [1305]
    assert names == {1305: "Reino 1305"}


def test_webhook_vacio_da_un_error_explicativo():
    with pytest.raises(DiscordError, match="DISCORD_WEBHOOK_URL"):
        DiscordNotifier("")


def test_envio_correcto(requests_mock):
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    deal = make_deal()
    assert notifier.send_deals([deal], REALMS) == [deal]
    assert requests_mock.call_count == 1


def test_send_deals_devuelve_solo_lo_que_ha_salido(requests_mock):
    """Con mas chollos de los que caben, devuelve unicamente los enviados.

    Quien llama marca como avisados los devueltos: si devolviera todos, los
    que no cupieron quedarian marcados sin haberse enviado y no volverian a
    notificarse nunca.
    """
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    deals = [make_deal(auction_id=i) for i in range(MAX_DEALS_PER_RUN + 7)]

    enviados = notifier.send_deals(deals, REALMS)

    assert len(enviados) == MAX_DEALS_PER_RUN
    assert enviados == deals[:MAX_DEALS_PER_RUN]


def test_reintenta_cuando_discord_limita_los_envios(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        [
            {"status_code": 429, "json": {"retry_after": 0.5}},
            {"status_code": 204},
        ],
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_deals([make_deal()], REALMS)

    assert esperas == [0.5]
    assert requests_mock.call_count == 2


def test_un_webhook_borrado_falla_sin_reintentar(requests_mock):
    requests_mock.post(WEBHOOK, status_code=404)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=lambda _: None)

    with pytest.raises(DiscordError, match="rechaza el webhook"):
        notifier.send_deals([make_deal()], REALMS)
    assert requests_mock.call_count == 1


def test_se_rinde_tras_agotar_los_reintentos(requests_mock):
    requests_mock.post(WEBHOOK, status_code=500)
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=2, sleep=lambda _: None
    )

    with pytest.raises(DiscordError):
        notifier.send_deals([make_deal()], REALMS)
    assert requests_mock.call_count == 3


def test_mensaje_de_prueba(requests_mock):
    requests_mock.post(WEBHOOK, status_code=204)
    DiscordNotifier(WEBHOOK, session=requests.Session()).send_test()

    assert "Prueba de conexion" in requests_mock.last_request.json()["content"]


# -- Avisos de undercut -----------------------------------------------------

from wowalerts.misubastas import MyAuction
from wowalerts.notifier import COLOR_UNDERCUT, build_undercut_messages
from wowalerts.undercut import Undercut


def un_undercut(
    objeto="Grebas de las profundidades nocivas",
    oro_mio=9000,
    oro_rival=8000,
    personaje="Pepe",
    reino="Sanguino",
    cuenta=2,
    auction_id=1,
    ilvl=311,
):
    mine = MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name=objeto,
        ilvl=ilvl,
        buyout_copper=oro_mio * 10_000,
        quantity=1,
        character=personaje,
        realm=reino,
        realm_slug=reino.lower(),
        account=cuenta,
    )
    return Undercut(
        mine=mine,
        realm_id=1379,
        rival_auction_id=99,
        rival_price_copper=oro_rival * 10_000,
        rivals_ahead=1,
    )


def texto(mensaje) -> str:
    """Titulo y descripcion de la tarjeta, juntos, para poder buscar en ellos."""
    embed = mensaje["embeds"][0]
    return embed["title"] + "\n" + embed["description"]


def test_sin_undercuts_no_hay_mensajes():
    assert build_undercut_messages([]) == []


def test_la_cabecera_lleva_personaje_y_cuenta():
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "Pepe" in contenido
    assert "WoW 2" in contenido


def test_la_cabecera_no_lleva_el_reino():
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "Sanguino" not in contenido


def test_sin_cuenta_conocida_solo_va_el_personaje():
    contenido = texto(build_undercut_messages([un_undercut(cuenta=None)])[0])
    assert "Pepe" in contenido
    assert "WoW" not in contenido


def test_el_mismo_personaje_en_cuentas_distintas_son_mensajes_distintos():
    mensajes = build_undercut_messages(
        [
            un_undercut(personaje="Pepe", cuenta=1, auction_id=1),
            un_undercut(personaje="Pepe", cuenta=3, auction_id=2),
        ]
    )
    assert len(mensajes) == 2


def test_un_mensaje_por_personaje():
    mensajes = build_undercut_messages(
        [
            un_undercut(personaje="Pepe", auction_id=1),
            un_undercut(personaje="Ana", auction_id=2),
            un_undercut(personaje="Pepe", auction_id=3),
        ]
    )
    assert len(mensajes) == 2
    assert "Pepe" in texto(mensajes[0])
    assert "Ana" in texto(mensajes[1])


def test_las_subastas_de_un_personaje_van_juntas():
    mensajes = build_undercut_messages(
        [
            un_undercut(objeto="Grebas", personaje="Pepe", auction_id=1),
            un_undercut(objeto="Zapatillas", personaje="Pepe", auction_id=2),
        ]
    )
    assert len(mensajes) == 1
    assert "Grebas" in texto(mensajes[0])
    assert "Zapatillas" in texto(mensajes[0])


def test_un_undercut_de_verdad_muestra_los_dos_precios():
    contenido = texto(
        build_undercut_messages([un_undercut(oro_mio=50000, oro_rival=30000)])[0]
    )
    assert "50.000" in contenido
    assert "30.000" in contenido


def test_un_empate_se_dice_como_empate():
    contenido = texto(
        build_undercut_messages([un_undercut(oro_mio=9000, oro_rival=9000)])[0]
    )
    assert "igualan" in contenido
    assert "9.000" in contenido


def test_el_recuento_va_en_la_cabecera():
    mensajes = build_undercut_messages(
        [un_undercut(auction_id=1), un_undercut(auction_id=2)]
    )
    assert "2 subastas" in texto(mensajes[0])


def test_una_sola_subasta_va_en_singular():
    contenido = texto(build_undercut_messages([un_undercut()])[0])
    assert "1 subasta" in contenido
    assert "subastas" not in contenido


def test_las_ya_avisadas_van_con_las_nuevas_del_personaje():
    """Acumuladas en la misma tarjeta: no hay bloque de repetidas."""
    ya = [un_undercut(objeto="Zapatillas", auction_id=7)]
    mensajes = build_undercut_messages(
        [un_undercut(objeto="Grebas", auction_id=1)], ya_avisados=ya
    )
    assert len(mensajes) == 1
    contenido = texto(mensajes[0])
    assert "Grebas" in contenido
    assert "Zapatillas" in contenido


def test_el_recuento_incluye_las_ya_avisadas():
    """El numero es lo que hay adelantado ahora, no solo lo nuevo."""
    ya = [un_undercut(objeto="Zapatillas", auction_id=7)]
    mensajes = build_undercut_messages([un_undercut(auction_id=1)], ya_avisados=ya)
    assert "2 subastas" in texto(mensajes[0])


def test_una_ya_avisada_no_se_marca_como_repetida():
    """Decir que ya se aviso no cambia nada: solo estorba."""
    ya = [un_undercut(objeto="Zapatillas", auction_id=7)]
    contenido = texto(
        build_undercut_messages([un_undercut(auction_id=1)], ya_avisados=ya)[0]
    )
    for palabra in ("ya te avise", "repetid", "sigue adelantada"):
        assert palabra not in contenido.lower()


def test_una_ya_avisada_de_otro_personaje_va_en_su_mensaje():
    ya = [un_undercut(personaje="Ana", objeto="Zapatillas", auction_id=7)]
    mensajes = build_undercut_messages([un_undercut(personaje="Pepe")], ya_avisados=ya)
    assert len(mensajes) == 2
    assert "Zapatillas" in texto(mensajes[1])
    assert "Ana" in texto(mensajes[1])


def test_sin_ninguna_nueva_no_se_avisa_de_las_ya_avisadas():
    """Si no hay novedad, el mismo aviso cada pasada seria ruido."""
    ya = [un_undercut(objeto="Zapatillas", auction_id=7)]
    assert build_undercut_messages([], ya_avisados=ya) == []


def test_sin_repetidos_no_se_anade_nada():
    mensajes = build_undercut_messages([un_undercut()], ya_avisados=[])
    assert len(mensajes) == 1
    assert "content" not in mensajes[0]


def test_un_personaje_con_muchisimas_se_parte_en_varios_mensajes():
    muchas = [un_undercut(auction_id=i) for i in range(1, 26)]
    mensajes = build_undercut_messages(muchas)
    assert len(mensajes) == 2
    assert "Pepe" in texto(mensajes[1])


def test_cada_mensaje_es_una_tarjeta_con_su_color():
    mensaje = build_undercut_messages([un_undercut()])[0]
    assert len(mensaje["embeds"]) == 1
    assert mensaje["embeds"][0]["color"] == COLOR_UNDERCUT


def test_ninguna_tarjeta_pasa_de_los_limites_de_discord():
    muchas = [
        un_undercut(objeto="Objeto con un nombre larguisimo " * 3, auction_id=i)
        for i in range(1, 51)
    ]
    for mensaje in build_undercut_messages(muchas):
        embed = mensaje["embeds"][0]
        assert len(embed["description"]) <= 4096
        assert len(embed["title"]) <= 256


# -- Panel de estado --------------------------------------------------------

from wowalerts.notifier import build_undercut_messages as _bum  # noqa: F401

PANEL = {"embeds": [{"title": "📊 Tus subastas"}]}


def test_el_panel_se_crea_la_primera_vez_y_devuelve_su_id(requests_mock):
    requests_mock.post(WEBHOOK + "?wait=true", json={"id": "12345"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, None) == "12345"


def test_el_panel_reescribe_el_mensaje_que_ya_existe(requests_mock):
    editar = requests_mock.patch(WEBHOOK + "/messages/12345", status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, "12345") == "12345"
    assert editar.call_count == 1


def test_si_el_mensaje_del_panel_ya_no_existe_se_crea_otro(requests_mock):
    """Lo puedes haber borrado, o haberse perdido la memoria entre pasadas."""
    requests_mock.patch(WEBHOOK + "/messages/viejo", status_code=404)
    requests_mock.post(WEBHOOK + "?wait=true", json={"id": "nuevo"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, "viejo") == "nuevo"


def test_un_fallo_del_panel_no_tumba_la_pasada(requests_mock):
    """El panel es un extra; los avisos son lo importante."""
    requests_mock.post(WEBHOOK + "?wait=true", status_code=500)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, None) is None


# -- Avisos de venta --------------------------------------------------------

from datetime import datetime, timezone

from wowalerts.notifier import COLOR_VENTA, build_venta_messages
from wowalerts.ventas import SubastaVigilada, Venta

CUANDO = datetime(2026, 8, 31, 14, 31, tzinfo=timezone.utc)


def una_venta(
    objeto="Grebas de las profundidades nocivas",
    personaje="Pepe",
    cuenta=3,
    oro=10000,
    auction_id=1,
    cantidad=1,
    ilvl=295,
):
    return Venta(
        subasta=SubastaVigilada(
            auction_id=auction_id,
            item_id=200000,
            item_name=objeto,
            ilvl=ilvl,
            buyout_copper=oro * 10_000,
            quantity=cantidad,
            character=personaje,
            realm="Sanguino",
            account=cuenta,
            no_caduca_antes_de=CUANDO,
            visto_at=CUANDO,
        ),
        realm_id=1305,
        detectada_at=CUANDO,
        ah_cut_pct=5,
    )


def test_sin_ventas_no_hay_mensajes():
    assert build_venta_messages([]) == []


def test_una_venta_muestra_el_neto():
    contenido = texto(build_venta_messages([una_venta(oro=10000)])[0])
    assert "9.500 g" in contenido


def test_el_titulo_lleva_personaje_y_cuenta():
    mensaje = build_venta_messages([una_venta()])[0]
    assert mensaje["embeds"][0]["title"] == "💰 Pepe · WoW 3 — 1 venta"


def test_sin_cuenta_el_titulo_solo_lleva_el_personaje():
    mensaje = build_venta_messages([una_venta(cuenta=None)])[0]
    assert mensaje["embeds"][0]["title"] == "💰 Pepe — 1 venta"


def test_una_sola_venta_no_lleva_total():
    contenido = texto(build_venta_messages([una_venta()])[0])
    assert "Total" not in contenido


def test_varias_ventas_del_mismo_personaje_llevan_total():
    mensajes = build_venta_messages(
        [
            una_venta(objeto="Grebas", oro=10000, auction_id=1),
            una_venta(objeto="Zapatillas", oro=20000, auction_id=2),
        ]
    )
    assert len(mensajes) == 1
    # 9.500 + 19.000
    assert "Total: 28.500 g" in texto(mensajes[0])


def test_cada_personaje_va_en_su_mensaje():
    mensajes = build_venta_messages(
        [
            una_venta(personaje="Pepe", auction_id=1),
            una_venta(personaje="Ana", auction_id=2),
            una_venta(personaje="Pepe", auction_id=3),
        ]
    )
    assert len(mensajes) == 2


def test_el_mismo_nombre_en_cuentas_distintas_no_se_mezcla():
    mensajes = build_venta_messages(
        [
            una_venta(personaje="Pepe", cuenta=1, auction_id=1),
            una_venta(personaje="Pepe", cuenta=3, auction_id=2),
        ]
    )
    assert len(mensajes) == 2


def test_el_embed_lleva_color_y_hora_del_volcado():
    embed = build_venta_messages([una_venta()])[0]["embeds"][0]
    assert embed["color"] == COLOR_VENTA
    assert embed["timestamp"] == CUANDO.isoformat()


def test_una_venta_de_varias_unidades_lo_dice():
    contenido = texto(build_venta_messages([una_venta(cantidad=5)])[0])
    assert "×5" in contenido


def test_muchas_ventas_de_un_personaje_se_trocean():
    """Discord tiene un tope por mensaje; el segundo se marca como sigue."""
    muchas = [una_venta(auction_id=i) for i in range(25)]
    mensajes = build_venta_messages(muchas)
    assert len(mensajes) > 1
    assert mensajes[1]["embeds"][0]["title"] == "💰 Pepe · WoW 3 · sigue"


# -- Enlace al panel --------------------------------------------------------


def test_el_enlace_del_panel_se_monta_con_los_tres_ids(requests_mock):
    requests_mock.get(
        WEBHOOK, json={"guild_id": "111", "channel_id": "222"}, status_code=200
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    assert (
        notifier.panel_url("333") == "https://discord.com/channels/111/222/333"
    )


def test_sin_guild_no_hay_enlace(requests_mock):
    """Un webhook fuera de un servidor no da guild_id; mejor sin enlace."""
    requests_mock.get(WEBHOOK, json={"channel_id": "222"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    assert notifier.panel_url("333") is None


def test_el_enlace_del_panel_va_una_vez_al_final():
    ya = [un_undercut(personaje="Ana", objeto="Zapatillas", auction_id=7)]
    mensajes = build_undercut_messages(
        [un_undercut()], ya_avisados=ya, panel_url="https://discord.com/channels/1/2/3"
    )
    enlaces = [
        m for m in mensajes if "channels/1/2/3" in m["embeds"][0]["description"]
    ]
    assert len(enlaces) == 1
    assert enlaces[0] is mensajes[-1]



def make_deal_sin_ilvl(price_gold=45_000, threshold_gold=60_000):
    return Deal(
        auction_id=7,
        item_id=5001,
        item_name="Pattern: Arcanoweave Cord",
        ilvl=None,
        ilvl_confirmed=False,
        price_copper=price_gold * COPPER_PER_GOLD,
        threshold_copper=threshold_gold * COPPER_PER_GOLD,
        realm_id=1305,
        time_left="LONG",
        sin_ilvl=True,
    )


def test_un_objeto_sin_ilvl_no_se_avisa_como_ilvl_sin_confirmar():
    embed = build_embed(make_deal_sin_ilvl(), REALMS[1305])

    assert "ilvl" not in embed["description"]
    assert "sin confirmar" not in embed["description"]
    # Y no sale en gris: el precio es tan fiable como el de cualquier otro.
    assert embed["color"] != COLOR_UNCONFIRMED


# ----------------------------------------------------------------------------
#  El enlace para ajustar el tope sin abrir config.yaml
# ----------------------------------------------------------------------------

def _campo(embed, nombre):
    return next((c for c in embed["fields"] if c["name"] == nombre), None)


def test_el_embed_lleva_enlace_para_ajustar_el_tope():
    from urllib.parse import parse_qs, urlparse

    embed = build_embed(make_deal(), REALMS[1305])
    campo = _campo(embed, "Ajustar tope")
    assert campo is not None

    url = campo["value"].split("(")[1].rstrip(")")
    partes = urlparse(url)
    assert partes.path.endswith("/issues/new")

    query = parse_qs(partes.query)
    assert query["template"] == ["tope-aviso.yml"]
    assert query["objeto"] == ["Greaves of the Noxious Depths"]
    assert query["ilvl"] == ["311"]


def test_el_enlace_escapa_lo_que_haga_falta():
    """Los nombres llevan apostrofos y espacios; sin escapar, la URL se rompe."""
    from urllib.parse import parse_qs, urlparse

    deal = make_deal()
    deal = type(deal)(**{**deal.__dict__, "item_name": "Temple Delver's Mystic Helm"})
    embed = build_embed(deal, REALMS[1305])

    url = _campo(embed, "Ajustar tope")["value"].split("(")[1].rstrip(")")
    assert " " not in url
    query = parse_qs(urlparse(url).query)
    assert query["objeto"] == ["Temple Delver's Mystic Helm"]


def test_un_chollo_de_precio_unico_no_lleva_ilvl_en_el_enlace():
    from urllib.parse import parse_qs, urlparse

    deal = make_deal()
    deal = type(deal)(**{**deal.__dict__, "sin_ilvl": True, "ilvl": None})
    embed = build_embed(deal, REALMS[1305])

    url = _campo(embed, "Ajustar tope")["value"].split("(")[1].rstrip(")")
    assert "ilvl" not in parse_qs(urlparse(url).query)


def test_un_ilvl_sin_confirmar_no_lleva_ilvl_en_el_enlace():
    """Con el ilvl en duda, prerrellenarlo invitaria a cambiar el tope del que no es."""
    from urllib.parse import parse_qs, urlparse

    embed = build_embed(make_deal(confirmed=False), REALMS[1305])

    url = _campo(embed, "Ajustar tope")["value"].split("(")[1].rstrip(")")
    assert "ilvl" not in parse_qs(urlparse(url).query)


def test_el_repositorio_sale_del_entorno_en_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "otro/repo")
    embed = build_embed(make_deal(), REALMS[1305])

    assert "github.com/otro/repo/issues/new" in _campo(embed, "Ajustar tope")["value"]


# -- El ilvl en las lineas de undercut y de venta ----------------------------


def test_un_undercut_dice_el_ilvl_de_la_subasta():
    """El mismo objeto se pone a muchos ilvl: sin el, no sabes cual cambiar."""
    contenido = texto(build_undercut_messages([un_undercut(ilvl=308)])[0])
    assert "Grebas de las profundidades nocivas (308)" in contenido


def test_el_mismo_objeto_a_dos_ilvl_se_distingue():
    contenido = texto(
        build_undercut_messages(
            [un_undercut(ilvl=298, auction_id=1), un_undercut(ilvl=311, auction_id=2)]
        )[0]
    )
    assert "(298)" in contenido
    assert "(311)" in contenido


def test_un_empate_tambien_dice_el_ilvl():
    contenido = texto(
        build_undercut_messages([un_undercut(oro_mio=9000, oro_rival=9000, ilvl=295)])[0]
    )
    assert "(295) — te igualan" in contenido


def test_una_receta_no_lleva_ilvl_en_el_undercut():
    """Lo que no escala sale del juego con ilvl 1, y eso no dice nada."""
    contenido = texto(
        build_undercut_messages([un_undercut(objeto="Patrón: cordón", ilvl=1)])[0]
    )
    assert "Patrón: cordón —" in contenido
    assert "(1)" not in contenido


def test_una_receta_vendida_no_lleva_ilvl():
    contenido = texto(build_venta_messages([una_venta(objeto="Patrón: cordón", ilvl=1)])[0])
    assert "Patrón: cordón —" in contenido
    assert "(1)" not in contenido


def test_una_venta_de_equipo_si_lleva_el_ilvl():
    contenido = texto(build_venta_messages([una_venta(ilvl=295)])[0])
    assert "Grebas de las profundidades nocivas (295)" in contenido


# -- Ritmo de envio ---------------------------------------------------------


def test_si_discord_dice_que_no_quedan_envios_espera_antes_del_siguiente(requests_mock):
    """Con muchos personajes adelantados salen rafagas de mensajes, y el webhook
    solo admite unos pocos seguidos. Discord dice en cada respuesta cuantos
    quedan: esperando cuando llega a cero no se llega a chocar con el 429."""
    esperas = []
    requests_mock.post(
        WEBHOOK,
        status_code=204,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "1.25"},
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_warning("titulo", "texto")

    assert esperas == [1.25]


def test_si_quedan_envios_no_espera(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        status_code=204,
        headers={"X-RateLimit-Remaining": "3", "X-RateLimit-Reset-After": "1.25"},
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_warning("titulo", "texto")

    assert esperas == []


def test_unas_cabeceras_raras_no_rompen_el_envio(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        status_code=204,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "mucho"},
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_warning("titulo", "texto")

    assert esperas == []


def test_esperar_al_limite_no_gasta_los_reintentos_de_los_fallos(requests_mock):
    """Un 429 no es un fallo: Discord dice cuanto esperar y luego acepta. Con
    los reintentos contados juntos, tres 429 seguidos tiraban un aviso bueno."""
    requests_mock.post(
        WEBHOOK,
        [{"status_code": 429, "json": {"retry_after": 0.5}}] * 3 + [{"status_code": 204}],
    )
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=2, sleep=lambda _: None
    )

    notifier.send_warning("titulo", "texto")

    assert requests_mock.call_count == 4


def test_un_429_eterno_acaba_rindiendose(requests_mock):
    requests_mock.post(WEBHOOK, status_code=429, json={"retry_after": 0.5})
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=lambda _: None)

    with pytest.raises(DiscordError, match="429"):
        notifier.send_warning("titulo", "texto")


# -- Lo que llega antes de un fallo cuenta como entregado --------------------


def test_si_falla_a_mitad_el_error_dice_que_chollos_si_llegaron(requests_mock):
    """Diez chollos por mensaje: si cae el segundo, los del primero ya estan en
    Discord y hay que poder marcarlos, o la pasada siguiente los repite."""
    requests_mock.post(WEBHOOK, [{"status_code": 204}, {"status_code": 500}])
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=0, sleep=lambda _: None
    )
    deals = [make_deal(auction_id=i) for i in range(15)]

    with pytest.raises(DiscordError) as fallo:
        notifier.send_deals(deals, REALMS)

    assert fallo.value.entregados == deals[:10]


def test_si_falla_a_mitad_el_error_dice_que_undercuts_si_llegaron(requests_mock):
    requests_mock.post(WEBHOOK, [{"status_code": 204}, {"status_code": 500}])
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=0, sleep=lambda _: None
    )
    pepe = un_undercut(personaje="Pepe", auction_id=1)
    ana = un_undercut(personaje="Ana", auction_id=2)
    ya = un_undercut(personaje="Pepe", auction_id=3)

    with pytest.raises(DiscordError) as fallo:
        notifier.send_undercuts([pepe, ana], ya_avisados=[ya])

    # Solo las nuevas: las ya avisadas ya constan, y la de Ana no llego.
    assert fallo.value.entregados == [pepe]


def test_si_falla_el_primero_no_se_entrego_nada(requests_mock):
    requests_mock.post(WEBHOOK, status_code=500)
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=0, sleep=lambda _: None
    )

    with pytest.raises(DiscordError) as fallo:
        notifier.send_deals([make_deal()], REALMS)

    assert fallo.value.entregados == []
