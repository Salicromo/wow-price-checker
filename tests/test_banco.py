"""El banco de hermandad, ejecutado fuera del juego.

Solo se puede leer con su ventana abierta: el addon lo apunta entonces y la
casa de subastas consulta lo apuntado. Necesita `lupa`; sin el, se salta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa.lua51")

CARPETA = Path(__file__).resolve().parent.parent / "addon" / "WowAlertsExport"
GREBAS = 271440
BANQUERO = 10

DOBLES = r"""
local marcos = {}
function CreateFrame()
    local registro = { eventos = {} }
    local frame = {}
    frame.RegisterEvent = function(_, evento) registro.eventos[evento] = true end
    frame.SetScript = function(_, _, fn) registro.onEvent = fn end
    marcos[#marcos + 1] = registro
    return frame
end
function DISPARAR(evento, ...)
    for _, r in ipairs(marcos) do
        if r.eventos[evento] and r.onEvent then r.onEvent(nil, evento, ...) end
    end
end

Enum = { PlayerInteractionType = { GuildBanker = 10 } }
HERMANDAD = "Los Ricos"
-- GetGuildInfo da el reino de la hermandad solo si no es el del personaje.
REINO = "Sanguino"
REINO_HERMANDAD = nil
function GetGuildInfo() return HERMANDAD, "Rango", 1, REINO_HERMANDAD end
function GetRealmName() return REINO end
function GetNormalizedRealmName() return (REINO:gsub(" ", "")) end
time = function() return 1756500000 end

-- PESTANAS[pestana][hueco] = { enlace, cantidad }. Las pestanas sin pedir no
-- traen nada, como en el juego.
PESTANAS = {}
PEDIDAS = {}
VISIBLES = { true, true }
function GetNumGuildBankTabs() return #VISIBLES end
function GetGuildBankTabInfo(p) return "Pestana", 1, VISIBLES[p] end
function QueryGuildBankTab(p) PEDIDAS[#PEDIDAS + 1] = p end
local function hueco(p, h) return (PESTANAS[p] or {})[h] end
function GetGuildBankItemLink(p, h) local x = hueco(p, h); return x and x.enlace end
function GetGuildBankItemInfo(p, h) local x = hueco(p, h); return x and 1, x and x.cantidad end
function GetDetailedItemLevelInfo(enlace) return tonumber(enlace:match("ilvl(%d+)")) end

-- hooksecurefunc de verdad: llama a la original y luego al gancho.
function hooksecurefunc(tabla, nombre, gancho)
    local original = tabla[nombre]
    tabla[nombre] = function(...)
        local r = { original(...) }
        gancho(...)
        return unpack(r)
    end
end

-- BOLSAS[bolsa][hueco] = enlace. Coger algo de la bolsa lo pone en el cursor.
BOLSAS = {}
CURSOR = nil
function GetCursorInfo()
    if CURSOR then return "item", tonumber(CURSOR:match("item:(%d+)")), CURSOR end
end
C_Container = {
    GetContainerItemLink = function(b, h) return (BOLSAS[b] or {})[h] end,
    PickupContainerItem = function(b, h) CURSOR = (BOLSAS[b] or {})[h] end,
    UseContainerItem = function() end,
}

-- La ventana del banco: 7 columnas de 14 botones, con el hueco como ID.
PESTANA_ACTUAL = 1
function GetCurrentGuildBankTab() return PESTANA_ACTUAL end
local function boton(id)
    return {
        GetID = function() return id end,
        CreateFontString = function()
            local texto = { texto = "" }
            texto.SetPoint = function() end
            texto.SetText = function(self, t) self.texto = t or "" end
            return texto
        end,
    }
end
GuildBankFrame = { Columns = {}, Update = function() end }
for c = 1, 7 do
    GuildBankFrame.Columns[c] = { Buttons = {} }
    for i = 1, 14 do
        GuildBankFrame.Columns[c].Buttons[i] = boton((c - 1) * 14 + i)
    end
end
function TEXTO_HUECO(h)
    local b = GuildBankFrame.Columns[math.ceil(h / 14)].Buttons[(h - 1) % 14 + 1]
    return b.wowAlertsIlvl and b.wowAlertsIlvl.texto or ""
end
"""


def runtime(antes=""):
    """El addon cargado como en el .toc. `antes` es Lua que se ejecuta antes
    de BancoHermandad.lua: lo que WoW habria leido de disco."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(DOBLES)
    # WowAlertsExport.lua va antes en el .toc y trae el codificador JSON.
    lua.execute("SlashCmdList = {}")
    lua.execute((CARPETA / "WowAlertsExport.lua").read_text(encoding="utf-8"))
    lua.execute(antes)
    lua.execute((CARPETA / "BancoHermandad.lua").read_text(encoding="utf-8"))
    return lua


def objeto(item_id=GREBAS, ilvl=308, cantidad=1):
    return {"enlace": f"|Hitem:{item_id}::|h[Grebas]ilvl{ilvl}|h", "cantidad": cantidad}


def con_banco(lua, pestanas):
    lua.globals().PESTANAS = lua.table_from(pestanas, recursive=True)


def abrir_banco(lua):
    lua.globals().DISPARAR("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", BANQUERO)
    lua.globals().DISPARAR("GUILDBANKBAGSLOTS_CHANGED")


def copias(lua, item_id=GREBAS, ilvl=308):
    return lua.globals().WowAlertsBanco.Copias(item_id, ilvl)


def test_al_abrir_el_banco_pide_todas_las_pestanas_que_puedes_ver():
    lua = runtime()
    lua.globals().VISIBLES = lua.table_from([True, False, True])
    abrir_banco(lua)

    assert list(lua.globals().PEDIDAS.values()) == [1, 3]


def test_cuenta_las_copias_de_cada_objeto_e_ilvl_en_todas_las_pestanas():
    lua = runtime()
    con_banco(lua, {1: {5: objeto(), 6: objeto(ilvl=311)}, 2: {1: objeto(cantidad=2)}})
    abrir_banco(lua)

    assert copias(lua) == 3
    assert copias(lua, ilvl=311) == 1
    assert copias(lua, ilvl=318) == 0


def test_sin_haber_abierto_el_banco_no_se_sabe():
    assert copias(runtime()) is None


def test_sin_hermandad_no_se_sabe():
    lua = runtime()
    lua.globals().HERMANDAD = None
    abrir_banco(lua)

    assert copias(lua) is None


def cambiar_a_alter(lua, reino, reino_hermandad):
    """Otro personaje de la misma hermandad, en otro reino conectado."""
    lua.globals().REINO = reino
    lua.globals().REINO_HERMANDAD = reino_hermandad


def test_lo_visto_con_un_personaje_vale_para_los_de_otros_reinos_conectados():
    lua = runtime()
    cambiar_a_alter(lua, "Medivh", "Naxxramas")
    con_banco(lua, {1: {1: objeto()}})
    abrir_banco(lua)
    lua.globals().DISPARAR("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", BANQUERO)

    cambiar_a_alter(lua, "Naxxramas", None)
    assert copias(lua) == 1
    cambiar_a_alter(lua, "Medivh", "Naxxramas")
    assert copias(lua) == 1


def test_el_reino_de_la_hermandad_vale_con_espacios_o_sin_ellos():
    lua = runtime()
    cambiar_a_alter(lua, "Medivh", "Bronze Dragonflight")
    con_banco(lua, {1: {1: objeto()}})
    abrir_banco(lua)

    cambiar_a_alter(lua, "Bronze Dragonflight", None)
    assert copias(lua) == 1


def test_con_el_banco_cerrado_un_cambio_no_borra_lo_apuntado():
    lua = runtime()
    con_banco(lua, {1: {1: objeto()}})
    abrir_banco(lua)
    lua.globals().DISPARAR("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", BANQUERO)
    con_banco(lua, {})
    lua.globals().DISPARAR("GUILDBANKBAGSLOTS_CHANGED")

    assert copias(lua) == 1


def test_sacar_algo_del_banco_lo_descuenta():
    lua = runtime()
    con_banco(lua, {1: {1: objeto()}})
    abrir_banco(lua)
    con_banco(lua, {})
    lua.globals().DISPARAR("GUILDBANKBAGSLOTS_CHANGED")

    assert copias(lua) == 0


# ---------------------------------------------------------------------------
#  El ilvl de verdad
#
#  El juego manda los objetos del banco sin sus bonus: un 308 llega como su
#  ilvl base, 219. El addon apunta el ilvl de la bolsa al meterlo y lo sigue.
# ---------------------------------------------------------------------------

MANTO = 271434


def en_bolsa(item_id=MANTO, ilvl=308):
    return f"|Hitem:{item_id}::5:6652|h[Manto]ilvl{ilvl}|h"


def del_banco(item_id=MANTO):
    """Como llega del banco: sin bonus, con el ilvl base."""
    return objeto(item_id, ilvl=219)


def cambia(lua, pestanas):
    con_banco(lua, pestanas)
    lua.globals().DISPARAR("GUILDBANKBAGSLOTS_CHANGED")


def con_bolsa(lua, huecos):
    lua.globals().BOLSAS = lua.table_from({0: huecos}, recursive=True)


def ilvl(lua, pestana, hueco):
    return lua.globals().WowAlertsBanco.Ilvl(pestana, hueco)


def meter_con_clic_derecho(lua, destino, hueco_bolsa=1):
    lua.globals().C_Container.UseContainerItem(0, hueco_bolsa)
    cambia(lua, destino)


def test_lo_metido_con_clic_derecho_cuenta_con_el_ilvl_de_la_bolsa():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {3: del_banco()}})

    assert ilvl(lua, 1, 3) == 308
    assert copias(lua, MANTO, 308) == 1
    assert copias(lua, MANTO, 219) == 0


def test_lo_metido_arrastrando_cuenta_con_el_ilvl_de_la_bolsa():
    lua = runtime()
    con_bolsa(lua, {4: en_bolsa(ilvl=328)})
    abrir_banco(lua)
    lua.globals().C_Container.PickupContainerItem(0, 4)
    cambia(lua, {2: {7: del_banco()}})

    assert ilvl(lua, 2, 7) == 328


def test_moverlo_dentro_del_banco_se_lleva_el_ilvl():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {3: del_banco()}})
    cambia(lua, {2: {9: del_banco()}})

    assert ilvl(lua, 2, 9) == 308
    assert ilvl(lua, 1, 3) is None


def test_intercambiar_dos_huecos_cambia_los_ilvl_de_sitio():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa(ilvl=308), 2: en_bolsa(GREBAS, ilvl=328)})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {1: del_banco()}}, hueco_bolsa=1)
    meter_con_clic_derecho(lua, {1: {1: del_banco(), 2: del_banco(GREBAS)}}, hueco_bolsa=2)
    cambia(lua, {1: {1: del_banco(GREBAS), 2: del_banco()}})

    assert ilvl(lua, 1, 1) == 328
    assert ilvl(lua, 1, 2) == 308


def test_al_sacarlo_se_olvida_y_otro_igual_no_hereda_el_ilvl():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {3: del_banco()}})
    cambia(lua, {})
    cambia(lua, {1: {3: del_banco()}})

    assert ilvl(lua, 1, 3) is None
    assert copias(lua, MANTO, 308) == 0


def test_lo_que_ya_estaba_en_el_banco_no_tiene_ilvl_apuntado():
    lua = runtime()
    con_banco(lua, {1: {1: del_banco()}})
    abrir_banco(lua)

    assert ilvl(lua, 1, 1) is None
    assert copias(lua, MANTO, 219) == 1


def test_lo_apuntado_sigue_al_volver_a_abrir_el_banco():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {3: del_banco()}})
    lua.globals().DISPARAR("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", BANQUERO)
    abrir_banco(lua)

    assert ilvl(lua, 1, 3) == 308
    assert copias(lua, MANTO, 308) == 1


def test_coger_algo_de_la_bolsa_con_el_banco_cerrado_no_se_apunta():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    lua.globals().C_Container.UseContainerItem(0, 1)
    abrir_banco(lua)
    cambia(lua, {1: {3: del_banco()}})

    assert ilvl(lua, 1, 3) is None


def test_pinta_el_ilvl_apuntado_encima_del_icono():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {17: del_banco(), 18: del_banco(GREBAS)}})
    lua.globals().GuildBankFrame.Update()

    assert lua.globals().TEXTO_HUECO(17) == "308"
    assert lua.globals().TEXTO_HUECO(18) == ""


def test_el_ilvl_apuntado_con_un_personaje_lo_ve_otro_de_otro_reino_conectado():
    lua = runtime()
    cambiar_a_alter(lua, "Medivh", "Naxxramas")
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {3: del_banco()}})
    lua.globals().DISPARAR("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", BANQUERO)

    cambiar_a_alter(lua, "Naxxramas", None)
    abrir_banco(lua)
    assert ilvl(lua, 1, 3) == 308


def test_los_ilvl_apuntados_con_la_clave_vieja_del_reino_del_personaje_se_recuperan():
    lua = runtime()
    lua.execute("""
        WowAlertsExportDB = { ilvlBancoHermandad = {
            ["Los Ricos-Medivh"] = { ["1:3"] = { itemID = 271434, ilvl = 308 } },
            ["Otra-Medivh"] = { ["1:4"] = { itemID = 271434, ilvl = 328 } },
        } }
    """)
    cambiar_a_alter(lua, "Aszune", "Naxxramas")
    con_banco(lua, {1: {3: del_banco(), 4: del_banco()}})
    abrir_banco(lua)

    assert ilvl(lua, 1, 3) == 308
    assert ilvl(lua, 1, 4) is None
    assert copias(lua, MANTO, 308) == 1


# ---------------------------------------------------------------------------
#  Compartido entre cuentas de WoW
#
#  Cada cuenta guarda lo suyo y no ve lo de las demas. El addon deja su banco
#  en bancoJSON; la sincronizacion trae el mas nuevo de otra cuenta en
#  bancoDeOtraCuenta (ver wowalerts/banco.py).
# ---------------------------------------------------------------------------

CLAVE = "Los Ricos-Sanguino"


def test_al_leer_el_banco_lo_deja_en_json_para_las_otras_cuentas():
    lua = runtime()
    con_bolsa(lua, {1: en_bolsa()})
    abrir_banco(lua)
    meter_con_clic_derecho(lua, {1: {3: del_banco()}})

    banco = json.loads(lua.globals().WowAlertsExportDB.bancoJSON)
    assert banco[CLAVE]["en"] == 1756500000
    assert banco[CLAVE]["copias"] == {f"{MANTO}:308": 1}
    assert banco[CLAVE]["ilvls"] == {"1:3": {"itemID": MANTO, "ilvl": 308}}


OTRA_CUENTA = """
WowAlertsExportDB = { bancoDeOtraCuenta = { ["Los Ricos-Sanguino"] = {
    en = %d,
    copias = { ["271434:308"] = 1 },
    ilvls = { ["1:3"] = { itemID = 271434, ilvl = 308 } },
} } }
"""


def test_lo_que_trae_otra_cuenta_vale_sin_abrir_el_banco():
    lua = runtime(OTRA_CUENTA % 1756500000)
    lua.globals().PESTANAS = lua.table_from({1: {3: del_banco()}}, recursive=True)

    assert copias(lua, MANTO, 308) == 1
    assert ilvl(lua, 1, 3) == 308
    assert lua.globals().WowAlertsExportDB.bancoDeOtraCuenta is None
    assert CLAVE in json.loads(lua.globals().WowAlertsExportDB.bancoJSON)


def test_lo_que_trae_otra_cuenta_no_pisa_algo_mas_nuevo():
    lua = runtime(OTRA_CUENTA % 1)
    con_banco(lua, {1: {1: objeto()}})
    abrir_banco(lua)
    lua.globals().DISPARAR("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", BANQUERO)

    assert copias(lua) == 1
    assert copias(lua, MANTO, 308) == 0
