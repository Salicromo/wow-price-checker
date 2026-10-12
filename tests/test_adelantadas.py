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


# -- Los apuntes de cada cuenta ----------------------------------------------------

from wowalerts.adelantadas import juntar_vistas, vistas_de  # noqa: E402


def savedvariables(vistas):
    """Como lo escribe WoW: el JSON va como cadena de Lua."""
    cadena = json.dumps(vistas).replace("\\", "\\\\").replace('"', '\\"')
    return 'WowAlertsExportDB = {\n["payload"] = "{}",\n' f'["adelantadasJSON"] = "{cadena}",\n' "}\n"


def test_lee_los_apuntes_de_una_cuenta():
    vistas = {"Sanguino-Pepe": {"en": 100, "quedan": 0, "pendientes": 1}}
    assert vistas_de(savedvariables(vistas)) == vistas


def test_sin_apuntes_o_con_basura_no_hay_nada():
    assert vistas_de("WowAlertsExportDB = {\n}\n") == {}
    assert vistas_de('WowAlertsExportDB = {\n["adelantadasJSON"] = "{roto",\n}\n') == {}
    raro = {"Sanguino-Pepe": {"quedan": 0}, "Kazzak-Ana": "x", "Zul'jin-Bea": {"en": 5, "quedan": 0, "pendientes": 0}}
    assert vistas_de(savedvariables(raro)) == {"Zul'jin-Bea": {"en": 5, "quedan": 0, "pendientes": 0}}


def test_al_juntar_gana_el_apunte_mas_reciente():
    una = {"Sanguino-Pepe": {"en": 100, "quedan": 2, "pendientes": 0}, "Kazzak-Ana": {"en": 50, "quedan": 0, "pendientes": 0}}
    otra = {"Sanguino-Pepe": {"en": 200, "quedan": 0, "pendientes": 0}}
    assert juntar_vistas([una, otra]) == {
        "Sanguino-Pepe": {"en": 200, "quedan": 0, "pendientes": 0},
        "Kazzak-Ana": {"en": 50, "quedan": 0, "pendientes": 0},
    }


def test_el_lua_lleva_los_apuntes():
    datos = {"version": 1, "pasada": 1, "volcado": 1, "total": 0, "cuentas": []}
    vistas = {"Zul'jin-Pe\"pe": {"en": 100, "quedan": 0, "pendientes": 1}}
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(a_lua(datos, vistas))
    apunte = lua.eval("WowAlertsAdelantadas.vistas")["Zul'jin-Pe\"pe"]
    assert (apunte.en, apunte.quedan, apunte.pendientes) == (100, 0, 1)


def test_sin_apuntes_el_lua_lleva_la_tabla_vacia():
    datos = {"version": 1, "pasada": 1, "volcado": 1, "total": 0, "cuentas": []}
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(a_lua(datos))
    assert len(lua.eval("WowAlertsAdelantadas.vistas")) == 0
