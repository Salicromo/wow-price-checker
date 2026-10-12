"""El resumen de lo adelantado: el JSON que publica el vigilante y el Lua del addon."""

import json

import pytest

from wowalerts.adelantadas import a_lua, escribir

lupa = pytest.importorskip("lupa.lua51")

CUENTAS = [
    {"cuenta": 2, "personajes": [{"nombre": "Pepe", "reino": "Sanguino", "n": 4, "caras": 1}]},
    {"cuenta": None, "personajes": [{"nombre": "Ana", "reino": "Kazzak", "n": 1, "caras": 0}]},
]


def test_escribe_el_resumen_con_el_total(tmp_path):
    ruta = tmp_path / "publicar" / "adelantadas.json"
    assert escribir(ruta, CUENTAS, pasada=2000, volcado=1000) is True
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos == {"version": 1, "pasada": 2000, "volcado": 1000, "total": 5, "cuentas": CUENTAS}


def test_sin_cambios_no_reescribe(tmp_path):
    ruta = tmp_path / "adelantadas.json"
    escribir(ruta, CUENTAS, pasada=2000, volcado=1000)
    assert escribir(ruta, CUENTAS, pasada=2000, volcado=1000) is False


def test_el_json_es_ascii_aunque_haya_tildes(tmp_path):
    ruta = tmp_path / "adelantadas.json"
    cuentas = [{"cuenta": 2, "personajes": [{"nombre": "Pepé", "reino": "Zul'jin", "n": 1, "caras": 0}]}]
    escribir(ruta, cuentas, pasada=1, volcado=1)
    ruta.read_bytes().decode("ascii")
    assert json.loads(ruta.read_text(encoding="utf-8"))["cuentas"] == cuentas


def leer_lua(texto):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(texto)
    return lua.globals().WowAlertsAdelantadas


def test_el_lua_lleva_todo_el_resumen():
    datos = {"version": 1, "pasada": 2000, "volcado": 1000, "total": 5, "cuentas": CUENTAS}
    t = leer_lua(a_lua(datos))
    assert (t.pasada, t.volcado, t.total) == (2000, 1000, 5)
    pepe = t.cuentas[1].personajes[1]
    assert (t.cuentas[1].cuenta, pepe.nombre, pepe.reino, pepe.n, pepe.caras) == (2, "Pepe", "Sanguino", 4, 1)
    assert t.cuentas[2].cuenta is None
    assert t.cuentas[2].personajes[1].nombre == "Ana"


def test_el_lua_escapa_comillas_y_barras():
    datos = {
        "version": 1, "pasada": 1, "volcado": 1, "total": 1,
        "cuentas": [{"cuenta": 2, "personajes": [{"nombre": 'Pe"pe\\', "reino": "Zul'jin", "n": 1, "caras": 0}]}],
    }
    p = leer_lua(a_lua(datos)).cuentas[1].personajes[1]
    assert (p.nombre, p.reino) == ('Pe"pe\\', "Zul'jin")


def test_el_lua_conserva_las_tildes():
    datos = {
        "version": 1, "pasada": 1, "volcado": 1, "total": 1,
        "cuentas": [{"cuenta": 2, "personajes": [{"nombre": "Pepé", "reino": "Sanguino", "n": 1, "caras": 0}]}],
    }
    lua = lupa.LuaRuntime(unpack_returned_tuples=True, encoding="utf-8")
    lua.execute(a_lua(datos))
    assert lua.eval("WowAlertsAdelantadas.cuentas[1].personajes[1].nombre") == "Pepé"


def test_sin_nada_adelantado_el_lua_tiene_las_cuentas_vacias():
    t = leer_lua(a_lua({"version": 1, "pasada": 1, "volcado": 1, "total": 0, "cuentas": []}))
    assert t.total == 0
    assert len(t.cuentas) == 0


@pytest.mark.parametrize(
    "datos",
    [
        [],
        {"pasada": 1, "volcado": 1, "total": 0},
        {"pasada": "1", "volcado": 1, "total": 0, "cuentas": []},
        {"pasada": 1, "volcado": 1, "total": 0, "cuentas": [{"cuenta": 2, "personajes": [{"nombre": 3}]}]},
        {"pasada": 1, "volcado": 1, "total": 0, "cuentas": [{"cuenta": "2", "personajes": []}]},
    ],
)
def test_un_resumen_con_otra_forma_se_rechaza(datos):
    with pytest.raises(ValueError):
        a_lua(datos)
