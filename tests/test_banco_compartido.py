"""El banco de hermandad, de una cuenta de WoW a las demas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wowalerts.banco import banco_de, compartir_banco, con_pendiente

CLAVE = "Grobworld-Naxxramas"


def banco(en, copias=None, ilvls=None):
    return {CLAVE: {"en": en, "copias": copias or {"271434:308": 1}, "ilvls": ilvls or []}}


def volcado(datos=None, nl="\r\n"):
    """Un WowAlertsExport.lua como lo escribe WoW, con bancoJSON si se da."""
    lineas = ["", "WowAlertsExportDB = {", '["payload"] = "{}",']
    if datos is not None:
        cadena = json.dumps(datos).replace("\\", "\\\\").replace('"', '\\"')
        lineas.append(f'["bancoJSON"] = "{cadena}",')
    lineas += ["}", ""]
    return nl.join(lineas)


def cuentas(tmp_path, *textos):
    ficheros = []
    for n, texto in enumerate(textos, start=1):
        f = tmp_path / f"403840080#{n}" / "SavedVariables" / "WowAlertsExport.lua"
        f.parent.mkdir(parents=True)
        f.write_bytes(texto.encode("utf-8"))
        ficheros.append(f)
    return ficheros


def leer(f: Path) -> str:
    return f.read_bytes().decode("utf-8")


def test_lee_el_banco_que_exporta_el_addon():
    assert banco_de(volcado(banco(5))) == banco(5)
    assert banco_de(volcado()) == {}


def test_lleva_lo_mas_nuevo_a_las_cuentas_que_lo_tienen_viejo_o_no_lo_tienen(tmp_path):
    vieja, nueva, sin = cuentas(tmp_path, volcado(banco(1)), volcado(banco(9)), volcado())

    assert compartir_banco([vieja, nueva, sin]) == [vieja, sin]
    assert '["bancoDeOtraCuenta"] = ' in leer(vieja)
    assert '["bancoDeOtraCuenta"]' not in leer(nueva)
    assert '["bancoDeOtraCuenta"] = ' in leer(sin)


def test_respeta_los_saltos_de_linea_del_fichero(tmp_path):
    vieja, nueva = cuentas(tmp_path, volcado(banco(1), nl="\n"), volcado(banco(9)))
    compartir_banco([vieja, nueva])

    assert "\r" not in leer(vieja)


def test_la_segunda_vez_no_toca_nada(tmp_path):
    ficheros = cuentas(tmp_path, volcado(banco(1)), volcado(banco(9)))
    compartir_banco(ficheros)

    assert compartir_banco(ficheros) == []


def test_lo_pendiente_se_cambia_por_lo_mas_nuevo(tmp_path):
    vieja, nueva = cuentas(tmp_path, volcado(banco(1)), volcado(banco(5)))
    compartir_banco([vieja, nueva])
    nueva.write_bytes(volcado(banco(9)).encode("utf-8"))
    compartir_banco([vieja, nueva])

    assert leer(vieja).count('["bancoDeOtraCuenta"]') == 1
    assert '["en"] = 9' in leer(vieja)


def test_sin_cabecera_reconocible_no_toca_el_fichero():
    assert con_pendiente("basura", banco(9)) == "basura"


# -- De punta a punta: lo que escribe esto lo entiende el addon --------------

lupa = pytest.importorskip("lupa.lua51")
TESTS = Path(__file__).resolve().parent


def test_el_addon_entiende_lo_que_se_le_deja(tmp_path):
    import sys

    sys.path.insert(0, str(TESTS))
    import test_banco as addon

    ilvls = {"1:3": {"itemID": 271434, "ilvl": 308}}
    vieja, nueva = cuentas(tmp_path, volcado(banco(1)), volcado(banco(9, ilvls=ilvls)))
    compartir_banco([vieja, nueva])

    lua = addon.runtime(antes=leer(vieja))
    lua.globals().HERMANDAD = "Grobworld"
    addon.cambiar_a_alter(lua, "Medivh", "Naxxramas")
    addon.con_banco(lua, {1: {3: addon.del_banco()}})
    assert addon.copias(lua, 271434, 308) == 1
    assert addon.ilvl(lua, 1, 3) == 308


def test_junta_los_ilvl_de_todas_las_cuentas_hueco_a_hueco(tmp_path):
    manto = {"itemID": 271434, "ilvl": 308, "en": 5}
    grebas = {"itemID": 271440, "ilvl": 311, "en": 6}
    viejo = {"itemID": 271434, "ilvl": 305, "en": 1}
    vieja, nueva = cuentas(
        tmp_path,
        volcado(banco(1, ilvls={"1:3": manto, "1:4": viejo})),
        volcado(banco(9, ilvls={"1:4": grebas})),
    )

    assert compartir_banco([vieja, nueva]) == [vieja, nueva]
    juntos = {"1:3": manto, "1:4": grebas}
    for f in (vieja, nueva):
        pendiente = leer(f).split('["bancoDeOtraCuenta"] = ')[1].split("\n")[0]
        assert '["en"] = 9' in pendiente
        assert pendiente.count('["itemID"]') == 2
        assert '["ilvl"] = 305' not in pendiente
