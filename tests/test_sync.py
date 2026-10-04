"""Sincronizacion del volcado del addon al repositorio."""

import json
import re
from dataclasses import replace
from datetime import datetime, timezone

from sync_subastas import detectar_wow_root, nombre_de_maquina
from wowalerts.misubastas import (
    MyAuction,
    actividad_por_maquina,
    escribir_snapshot,
    leer_snapshot,
    leer_snapshots,
)


def una(auction_id=1, character="Pepe"):
    return MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name="Greaves of the Noxious Depths",
        ilvl=311,
        buyout_copper=90_000_000,
        quantity=1,
        character=character,
        realm="Sanguino",
        realm_slug="sanguino",
        bonus_ids=(12817, 6652),
    )


def test_el_primer_volcado_cuenta_como_cambio(tmp_path):
    assert escribir_snapshot(tmp_path / "mis.json", [una()]) is True


def test_el_mismo_contenido_no_cuenta_como_cambio(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert escribir_snapshot(path, [una()]) is False


def test_un_precio_distinto_si_cuenta_como_cambio(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert escribir_snapshot(path, [replace(una(), buyout_copper=80_000_000)]) is True


def test_el_snapshot_no_cambia_si_no_has_jugado(tmp_path):
    """Sin esto, la tarea programada generaria un commit cada cuarto de hora
    aunque no hubieras tocado nada.

    El volcado si lleva la hora a la que exporto el addon, que es lo que permite
    despues desconfiar de una maquina que se ha quedado atras. Pero esa hora la
    estampa el addon al recoger los datos de un personaje, no el sincronizador
    al escribir el fichero: si no juegas no cambia, y los bytes salen iguales.
    """
    path = tmp_path / "mis.json"
    assert escribir_snapshot(path, [una()]) is True
    primero = path.read_text(encoding="utf-8")

    assert escribir_snapshot(path, [una()]) is False
    assert path.read_text(encoding="utf-8") == primero


def test_lo_escrito_se_puede_volver_a_leer(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert leer_snapshot(path) == [una()]


def test_leer_un_snapshot_que_no_existe_son_cero_subastas(tmp_path):
    assert leer_snapshot(tmp_path / "no-existe.json") == []


def test_el_snapshot_es_json_valido(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una(), una(auction_id=2, character="Ana")])
    datos = json.loads(path.read_text(encoding="utf-8"))
    assert len(datos["auctions"]) == 2


def test_detecta_la_carpeta_de_wow(tmp_path):
    raiz = tmp_path / "World of Warcraft" / "_retail_"
    (raiz / "WTF").mkdir(parents=True)
    assert detectar_wow_root([str(raiz)]) == raiz


def test_sin_carpeta_de_wow_devuelve_none(tmp_path):
    assert detectar_wow_root([str(tmp_path / "no-existe")]) is None


# -- Varias maquinas --------------------------------------------------------


def test_une_las_subastas_de_dos_maquinas(tmp_path):
    """El PC y la Steam Deck escriben cada uno su fichero: si compartieran uno,
    cada maquina borraria al subir los personajes del otro."""
    escribir_snapshot(tmp_path / "pc.json", [una(1, "Pepe")])
    escribir_snapshot(tmp_path / "deck.json", [una(2, "Ana")])

    assert {s.character for s in leer_snapshots(tmp_path)} == {"Pepe", "Ana"}


def test_una_subasta_en_las_dos_maquinas_se_cuenta_una_vez(tmp_path):
    escribir_snapshot(tmp_path / "pc.json", [una(1), una(2)])
    escribir_snapshot(tmp_path / "deck.json", [una(2), una(3)])

    assert [s.auction_id for s in leer_snapshots(tmp_path)] == [1, 2, 3]


def test_tambien_lee_un_fichero_suelto(tmp_path):
    """Como estaba antes de haber dos maquinas."""
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [una()])
    assert len(leer_snapshots(path)) == 1


def test_una_carpeta_que_no_existe_son_cero_subastas(tmp_path):
    assert leer_snapshots(tmp_path / "no-existe") == []


def test_el_nombre_de_maquina_vale_como_nombre_de_fichero():
    nombre = nombre_de_maquina()
    assert nombre
    assert re.fullmatch(r"[a-z0-9_-]+", nombre), nombre


# -- Sin ventanas de consola en Windows -------------------------------------


def test_git_se_lanza_sin_abrir_ventana(monkeypatch):
    """La tarea corre con pythonw, que no tiene consola.

    Un proceso de consola lanzado desde ahi se abre la suya, y con cuatro
    llamadas a git por pasada eso son cuatro parpadeos cada quince minutos.
    """
    import subprocess as sp

    from sync_subastas import git

    visto = {}

    def falso(*args, **kwargs):
        visto.update(kwargs)
        return sp.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(sp, "run", falso)
    git("status")

    esperado = getattr(sp, "CREATE_NO_WINDOW", 0)
    assert visto.get("creationflags") == esperado


# ---------------------------------------------------------------------------
#  Vigilar la salida del juego
# ---------------------------------------------------------------------------
#
#  El addon solo vuelca al salir al selector o cerrar WoW. Si hubiera que
#  esperar al temporizador, lo normal seria apagar el equipo antes: lo exportado
#  se quedaria sin subir hasta el siguiente encendido, y para entonces las
#  subastas ya han caducado y no se puede saber si alguna se vendio.

import sync_subastas as sync


def con_volcado(tmp_path, cuenta="403840080#1", contenido="x"):
    ruta = tmp_path / "WTF" / "Account" / cuenta / "SavedVariables"
    ruta.mkdir(parents=True, exist_ok=True)
    fichero = ruta / "WowAlertsExport.lua"
    fichero.write_text(contenido, encoding="utf-8")
    return fichero


def test_la_firma_cambia_cuando_wow_guarda(tmp_path):
    con_volcado(tmp_path, contenido="antes")
    antes = sync.firma_de_los_volcados(tmp_path)

    con_volcado(tmp_path, contenido="despues, mas largo")

    assert sync.firma_de_los_volcados(tmp_path) != antes


def test_la_firma_no_cambia_sola(tmp_path):
    """Si cambiara sin motivo, se sincronizaria en bucle sin parar."""
    con_volcado(tmp_path)

    assert sync.firma_de_los_volcados(tmp_path) == sync.firma_de_los_volcados(tmp_path)


def test_la_firma_cubre_todas_las_cuentas(tmp_path):
    """Con varias cuentas de WoW hay un fichero por cada una."""
    con_volcado(tmp_path, cuenta="403840080#1")
    con_volcado(tmp_path, cuenta="403840080#3")

    assert len(sync.firma_de_los_volcados(tmp_path)) == 2


def test_una_carpeta_sin_volcados_da_firma_vacia(tmp_path):
    assert sync.firma_de_los_volcados(tmp_path) == ()


# -- Un solo sincronizador a la vez -----------------------------------------
#
#  Hay dos disparadores (el vigilante y la tarea programada) y ambos hacen git
#  en la misma carpeta. El 2026-09-02 coincidieron y el rebase de uno se
#  encontro el del otro a medias: "fatal: Cannot rebase onto multiple branches".


def test_el_segundo_no_entra_mientras_el_primero_trabaja(tmp_path):
    with sync.en_exclusiva(tmp_path) as primero:
        assert primero is True
        with sync.en_exclusiva(tmp_path) as segundo:
            assert segundo is False


def test_el_cerrojo_se_suelta_al_terminar(tmp_path):
    with sync.en_exclusiva(tmp_path):
        pass

    with sync.en_exclusiva(tmp_path) as despues:
        assert despues is True


def test_el_cerrojo_se_suelta_aunque_falle(tmp_path):
    """Si no, un fallo dejaria la sincronizacion parada para siempre."""
    try:
        with sync.en_exclusiva(tmp_path):
            raise RuntimeError("algo ha petado")
    except RuntimeError:
        pass

    with sync.en_exclusiva(tmp_path) as despues:
        assert despues is True


def test_un_cerrojo_viejo_se_da_por_muerto(tmp_path):
    """Si apagas el equipo a media pasada, nadie lo suelta."""
    import os
    import time as _t

    cerrojo = tmp_path / "sync.lock"
    cerrojo.write_text("999999")
    viejo = _t.time() - sync.CERROJO_CADUCA_EN - 60
    os.utime(cerrojo, (viejo, viejo))

    with sync.en_exclusiva(tmp_path) as mio:
        assert mio is True


# -- Cuando exporto por ultima vez cada maquina -----------------------------


def test_la_actividad_es_lo_ultimo_que_exporto_cada_maquina(tmp_path):
    """La hora de la ultima senal de vida de cada maquina, por su nombre.

    Es lo que permite saber si estabas jugando cuando una subasta desaparecio:
    una maquina que exporto hace un rato pudo cancelarla sin que me haya
    llegado, y hasta que no vuelva a hablar no hay veredicto.
    """
    escribir_snapshot(
        tmp_path / "pc.json",
        [replace(una(1), exported_at=1000), replace(una(2), exported_at=3000)],
    )
    escribir_snapshot(tmp_path / "deck.json", [replace(una(3), exported_at=2000)])

    assert actividad_por_maquina(tmp_path) == {
        "pc": datetime.fromtimestamp(3000, tz=timezone.utc),
        "deck": datetime.fromtimestamp(2000, tz=timezone.utc),
    }


def test_una_maquina_sin_hora_de_exportacion_no_cuenta(tmp_path):
    """Los volcados viejos no la llevaban: de esos no se puede afirmar nada."""
    escribir_snapshot(tmp_path / "pc.json", [una(1)])

    assert actividad_por_maquina(tmp_path) == {}


def test_sin_carpeta_no_hay_actividad(tmp_path):
    assert actividad_por_maquina(tmp_path / "no-existe") == {}


def test_un_fichero_suelto_tambien_da_actividad(tmp_path):
    path = tmp_path / "mis.json"
    escribir_snapshot(path, [replace(una(1), exported_at=1500)])

    assert actividad_por_maquina(path) == {
        "mis": datetime.fromtimestamp(1500, tz=timezone.utc)
    }


# ---------------------------------------------------------------------------
#  Publicar el volcado sin ensuciar el historial
# ---------------------------------------------------------------------------
#
#  El vigilante sincroniza cada vez que sales al selector de personajes, unas
#  veinte veces por tarde de juego. Mientras eso fue a main, tapaba el historial
#  de verdad --765 de los primeros 954 commits del proyecto eran volcados-- y
#  GitHub los contaba a todos como trabajo del dia. Ahora van a una rama aparte,
#  que ademas se rehace entera en cada pasada para que no crezca sin fin.

import subprocess as sp


def git_en(carpeta, *args):
    """git con una identidad fija, que en CI no hay ninguna configurada."""
    return sp.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        cwd=carpeta,
        capture_output=True,
        text=True,
        check=True,
    )


def repo_de_trabajo(tmp_path, nombre="repo"):
    """Un repositorio con algo en main, como la carpeta del proyecto."""
    raiz = tmp_path / nombre
    raiz.mkdir(parents=True)
    git_en(raiz, "init", "-q", "-b", "main")
    (raiz / "main.py").write_text("# codigo de verdad\n", encoding="utf-8")
    # Como en el proyecto: los volcados viven en la carpeta pero main no los
    # sigue, que para eso se fueron a su rama.
    (raiz / ".gitignore").write_text(
        ".state/\nmis_subastas/\nmis_personajes/\nmis_ventas/\n", encoding="utf-8"
    )
    git_en(raiz, "add", "-A")
    git_en(raiz, "commit", "-q", "-m", "El codigo")
    return raiz


def escribir_volcado(raiz, maquina, contenido):
    fichero = raiz / "mis_subastas" / f"{maquina}.json"
    fichero.parent.mkdir(parents=True, exist_ok=True)
    fichero.write_text(contenido, encoding="utf-8")
    return f"mis_subastas/{maquina}.json"


def test_el_volcado_no_deja_ni_un_commit_en_main(tmp_path):
    """Lo que se quiso arreglar: main no se entera de que esto ha pasado."""
    raiz = repo_de_trabajo(tmp_path)
    antes = git_en(raiz, "rev-parse", "main").stdout

    relativo = escribir_volcado(raiz, "pc", '{"subastas": 1}')
    assert sync.subir([relativo], push=False, raiz=raiz) == sync.EXIT_OK

    assert git_en(raiz, "rev-parse", "main").stdout == antes
    # Y tampoco se queda a medias, con el volcado preparado para el commit
    # siguiente: main no lo tiene ni en el indice.
    assert git_en(raiz, "status", "--short").stdout.strip() == ""


def test_el_volcado_llega_a_la_rama_de_datos(tmp_path):
    raiz = repo_de_trabajo(tmp_path)
    relativo = escribir_volcado(raiz, "pc", '{"subastas": 1}')

    sync.subir([relativo], push=False, raiz=raiz)

    copia = raiz / ".state" / "rama-datos"
    guardado = git_en(copia, "show", f"{sync.RAMA_DATOS}:{relativo}").stdout
    assert guardado == '{"subastas": 1}'


def test_una_pasada_sin_cambios_no_commitea(tmp_path):
    raiz = repo_de_trabajo(tmp_path)
    relativo = escribir_volcado(raiz, "pc", "igual")
    sync.subir([relativo], push=False, raiz=raiz)

    copia = raiz / ".state" / "rama-datos"
    antes = git_en(copia, "rev-parse", sync.RAMA_DATOS).stdout

    assert sync.subir([relativo], push=False, raiz=raiz) == sync.EXIT_OK
    assert git_en(copia, "rev-parse", sync.RAMA_DATOS).stdout == antes


def remoto_vacio(tmp_path):
    bare = tmp_path / "remoto.git"
    bare.mkdir()
    git_en(bare, "init", "-q", "--bare", "-b", "main")
    return bare


def test_la_rama_no_crece_por_muchas_pasadas_que_haya(tmp_path):
    """Un volcado son 100 KB reescritos enteros; con historial, el repositorio
    engordaria un par de MB al dia para siempre."""
    raiz = repo_de_trabajo(tmp_path)
    git_en(raiz, "remote", "add", "privado", str(remoto_vacio(tmp_path)))

    for vuelta in range(3):
        relativo = escribir_volcado(raiz, "pc", f'{{"vuelta": {vuelta}}}')
        assert sync.subir([relativo], push=True, raiz=raiz) == sync.EXIT_OK

    copia = raiz / ".state" / "rama-datos"
    assert git_en(copia, "rev-list", "--count", sync.RAMA_DATOS).stdout.strip() == "1"


def test_no_borra_el_volcado_de_la_otra_maquina(tmp_path):
    """El PC y la Steam Deck publican en la misma rama, cada uno su fichero."""
    bare = remoto_vacio(tmp_path)

    deck = repo_de_trabajo(tmp_path, "deck")
    git_en(deck, "remote", "add", "privado", str(bare))
    sync.subir([escribir_volcado(deck, "deck", "de la deck")], push=True, raiz=deck)

    pc = repo_de_trabajo(tmp_path, "pc")
    git_en(pc, "remote", "add", "privado", str(bare))
    sync.subir([escribir_volcado(pc, "pc", "del pc")], push=True, raiz=pc)

    salida = git_en(bare, "ls-tree", "-r", "--name-only", sync.RAMA_DATOS).stdout
    assert "mis_subastas/deck.json" in salida
    assert "mis_subastas/pc.json" in salida


def test_sin_red_no_publica_nada(tmp_path):
    """Publicar rehace la rama entera. Si no se puede mirar antes que hay en
    ella, empujar borraria el volcado de la otra maquina."""
    raiz = repo_de_trabajo(tmp_path)
    git_en(raiz, "remote", "add", "privado", str(tmp_path / "no-existe.git"))
    relativo = escribir_volcado(raiz, "pc", "algo")

    assert sync.subir([relativo], push=True, raiz=raiz) == sync.EXIT_ERROR


def test_sin_el_remoto_privado_no_sube_al_publico(tmp_path):
    """'origin' es el repositorio publico: los volcados nunca van ahi."""
    raiz = repo_de_trabajo(tmp_path)
    bare = remoto_vacio(tmp_path)
    git_en(raiz, "remote", "add", "origin", str(bare))
    relativo = escribir_volcado(raiz, "pc", "algo")

    assert sync.subir([relativo], push=True, raiz=raiz) == sync.EXIT_ERROR
    assert git_en(bare, "branch", "--list", sync.RAMA_DATOS).stdout.strip() == ""
