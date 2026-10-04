"""El reposteo con una tecla, ejecutado fuera del juego.

Las APIs de WoW se sustituyen por dobles que apuntan cada llamada protegida
(cancelar, postear, confirmar, recoger correo). Lo que no se puede ver aqui --que
el juego acepte esas llamadas desde una tecla-- se comprueba a mano en la
Task 9 del plan.

Necesita `lupa`, que va en requirements-dev.txt. Sin el, los tests se saltan.

Corre sobre lupa.lua51, la misma version 5.1 que usa el juego.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa.lua51")

CARPETA = Path(__file__).resolve().parent.parent / "addon" / "WowAlertsExport"
GREBAS = 271440

DOBLES = r"""
-- Dobles de las APIs de WoW que usan el exportador y el reposteo.
local marcos = {}   -- frames creados, en orden de creacion, con sus eventos
mensajes = {}
LLAMADAS = {}    -- funciones protegidas, en el orden en que se llaman
BUSQUEDAS = {}   -- itemKeys pedidas a la casa y aun sin responder
BUSCADAS = 0     -- cuantas busquedas se han lanzado en total

-- Se guarda cuantos argumentos hubo (select("#", ...)) porque un nil en medio
-- no deja rastro en la tabla: sin "n" no habria forma de saber donde acababa
-- la llamada.
local function apuntar(...)
    LLAMADAS[#LLAMADAS + 1] = { n = select("#", ...), ... }
end

-- Cualquier metodo de interfaz que no importe devuelve un objeto que tampoco
-- hace nada, para poder encadenar llamadas (CreateFontString():SetText()...).
local NULO
NULO = setmetatable({}, { __index = function() return function() return NULO end end })

-- Cada frame se acuerda de que eventos ha registrado. Antes DISPARAR llamaba
-- a todos los manejadores para cualquier evento, y un RegisterEvent olvidado
-- en el addon de verdad nunca se habria notado aqui.
function CreateFrame(_, nombre, padre)
    local registro = { eventos = {} }
    local frame = setmetatable({}, { __index = function() return function() return NULO end end })
    frame.RegisterEvent = function(self, evento) registro.eventos[evento] = true end
    frame.UnregisterEvent = function(self, evento) registro.eventos[evento] = nil end
    frame.SetScript = function(self, script, fn)
        if script == "OnEvent" then registro.onEvent = fn end
        rawset(self, "script_" .. script, fn)
    end
    rawset(frame, "_texto", "")
    rawset(frame, "_habilitado", true)
    rawset(frame, "_padre", padre)
    rawset(frame, "_visible", true)
    frame.SetText = function(self, texto) rawset(self, "_texto", texto) end
    frame.GetText = function(self) return rawget(self, "_texto") end
    frame.Enable = function(self) rawset(self, "_habilitado", true) end
    frame.Disable = function(self) rawset(self, "_habilitado", false) end
    frame.IsEnabled = function(self) return rawget(self, "_habilitado") end
    frame.SetParent = function(self, p) rawset(self, "_padre", p) end
    frame.GetParent = function(self) return rawget(self, "_padre") end
    frame.Show = function(self) rawset(self, "_visible", true) end
    frame.Hide = function(self) rawset(self, "_visible", false) end
    frame.IsShown = function(self) return rawget(self, "_visible") end
    registro.frame = frame
    marcos[#marcos + 1] = registro
    if nombre then _G[nombre] = frame end
    return frame
end

function DISPARAR(evento, ...)
    for _, registro in ipairs(marcos) do
        if registro.eventos[evento] and registro.onEvent then
            registro.onEvent(registro.frame, evento, ...)
        end
    end
end

function print(texto) mensajes[#mensajes + 1] = texto end
function time() return AHORA end
RELOJ = 0
function GetTime() return RELOJ end
function UnitName() return PERSONAJE end
function GetRealmName() return REINO end
-- Los enlaces de prueba llevan el ilvl escrito: "[Grebas]ilvl311".
function GetDetailedItemLevelInfo(enlace)
    return tonumber(tostring(enlace or ""):match("ilvl(%d+)"))
end

SlashCmdList = {}
TEMPORIZADORES = {}
C_Timer = {
    After = function(segundos, fn) TEMPORIZADORES[#TEMPORIZADORES + 1] = fn end,
    NewTicker = function() return { Cancel = function() end } end,
}
-- Vence todos los temporizadores pendientes, como si pasara el tiempo.
function VENCER_TEMPORIZADORES()
    local pendientes = TEMPORIZADORES
    TEMPORIZADORES = {}
    for _, fn in ipairs(pendientes) do fn() end
end

CASA_ABIERTA = false
AuctionHouseFrame = { IsShown = function() return CASA_ABIERTA end }
BUZON_ABIERTO = false
MailFrame = { IsShown = function() return BUZON_ABIERTO end }

AVISO_VISIBLE = nil
OCULTADOS = {}
function StaticPopup_Visible(nombre) return AVISO_VISIBLE == nombre end
function StaticPopup_Hide(nombre)
    OCULTADOS[#OCULTADOS + 1] = nombre
    if AVISO_VISIBLE == nombre then AVISO_VISIBLE = nil end
end

Enum = { AuctionHouseSortOrder = { Price = 0 } }

local function clave(k)
    return k.itemID .. ":" .. (k.itemLevel or 0) .. ":" .. (k.itemSuffix or 0)
end

SUBASTAS = {}
RESULTADOS = {}
SISTEMA_LISTO = true
NECESITA_CONFIRMAR = false
CREAR_SUBASTA = true

C_AuctionHouse = {
    GetNumOwnedAuctions = function() return #SUBASTAS end,
    GetOwnedAuctionInfo = function(i) return SUBASTAS[i] end,
    QueryOwnedAuctions = function() DISPARAR("OWNED_AUCTIONS_UPDATED") end,
    IsThrottledMessageSystemReady = function() return SISTEMA_LISTO end,
    SendSearchQuery = function(itemKey)
        BUSCADAS = BUSCADAS + 1
        BUSQUEDAS[#BUSQUEDAS + 1] = itemKey
    end,
    GetNumItemSearchResults = function(k) return #(RESULTADOS[clave(k)] or {}) end,
    GetItemSearchResultInfo = function(k, i) return (RESULTADOS[clave(k)] or {})[i] end,
    CancelAuction = function(id) apuntar("CancelAuction", id) end,
    PostItem = function(loc, duracion, cantidad, puja, precio)
        apuntar("PostItem", loc.bagID, loc.slotIndex, duracion, cantidad, precio)
        -- Como el juego: el objeto queda bloqueado mientras se publica.
        local hueco = BOLSA[loc.bagID .. ":" .. loc.slotIndex]
        if hueco then hueco.isLocked = true end
        if NECESITA_CONFIRMAR then
            -- El AuctionHouseFrame de Blizzard abre su aviso de precio al
            -- pedir confirmacion.
            AVISO_VISIBLE = "AUCTION_HOUSE_POST_WARNING"
        end
        if not NECESITA_CONFIRMAR and CREAR_SUBASTA then
            DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000 + #LLAMADAS)
        end
        return NECESITA_CONFIRMAR
    end,
    ConfirmPostItem = function(loc, duracion, cantidad, puja, precio)
        apuntar("ConfirmPostItem", loc.bagID, loc.slotIndex, duracion, cantidad, precio)
        if CREAR_SUBASTA then
            DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000 + #LLAMADAS)
        end
    end,
}

-- Responde a la busqueda mas antigua, como haria el servidor.
function RESPONDER()
    local itemKey = table.remove(BUSQUEDAS, 1)
    DISPARAR("ITEM_SEARCH_RESULTS_UPDATED", itemKey)
end

-- Teclas: TECLAS dice que tecla tiene cada accion; ENLACES, que teclas ha
-- tomado prestadas el addon (SetOverrideBinding).
TECLAS = { INTERACTTARGET = "º" }
ENLACES = {}
EN_COMBATE = false
function GetBindingKey(accion) return TECLAS[accion] end
function SetOverrideBinding(_, _, tecla, accion)
    if EN_COMBATE then error("SetOverrideBinding en combate") end
    ENLACES[tecla] = accion
end
function ClearOverrideBindings()
    if EN_COMBATE then error("ClearOverrideBindings en combate") end
    ENLACES = {}
end
function InCombatLockdown() return EN_COMBATE end

CORREO_PENDIENTE = false
C_Mail = { IsCommandPending = function() return CORREO_PENDIENTE end }

-- Avisos en el centro de la pantalla y sonidos.
PANTALLA = {}
SONIDOS = {}
RaidWarningFrame = {}
ChatTypeInfo = { RAID_WARNING = {} }
function RaidNotice_AddMessage(_, texto) PANTALLA[#PANTALLA + 1] = texto end
SOUNDKIT = { READY_CHECK = 8960 }
function PlaySound(id) SONIDOS[#SONIDOS + 1] = id end

AUCTION_REMOVED_MAIL_SUBJECT = "Auction cancelled: %s"
AUCTION_EXPIRED_MAIL_SUBJECT = "Auction expired: %s"
CORREO = {}   -- { asunto, nombre, itemID, enlace }
function GetInboxNumItems() return #CORREO, #CORREO end
function GetInboxHeaderInfo(i)
    local carta = CORREO[i]
    return nil, nil, "Auction House", carta.asunto, 0, 0, 30, carta.itemID and 1 or nil
end
function GetInboxItem(i)
    local carta = CORREO[i]
    return carta.nombre, carta.itemID, nil, 1, 4, true
end
function GetInboxItemLink(i) return CORREO[i].enlace end
function TakeInboxItem(i, adjunto) apuntar("TakeInboxItem", i, adjunto) end

NUM_BAG_SLOTS = 4
BOLSA = {}    -- ["bolsa:hueco"] = { itemID, hyperlink, isLocked }
C_Container = {
    GetContainerNumSlots = function() return 16 end,
    GetContainerItemInfo = function(bolsa, hueco) return BOLSA[bolsa .. ":" .. hueco] end,
}
ItemLocation = {}
function ItemLocation:CreateFromBagAndSlot(bolsa, hueco) return { bagID = bolsa, slotIndex = hueco } end

local function enHueco(loc) return BOLSA[loc.bagID .. ":" .. loc.slotIndex] end
C_Item = {
    DoesItemExist = function(loc) return enHueco(loc) ~= nil end,
    GetItemID = function(loc) local h = enHueco(loc); return h and h.itemID end,
    GetItemLink = function(loc) local h = enHueco(loc); return h and h.hyperlink end,
    IsBound = function(loc) local h = enHueco(loc); return h ~= nil and h.isBound == true end,
}
C_AuctionHouse.IsSellItemValid = function(loc)
    local h = enHueco(loc)
    return h ~= nil and h.isBound ~= true
end
"""

VIGILADOS = """
WowAlertsVigilados = {
    objetos = { [271440] = "Greaves of the Noxious Depths" },
    personajes = { "Pepe", "Mbarval" },
    duracion = 1,
}
"""


def poner(lua, nombre, valor):
    lua.globals()[nombre] = lua.table_from(valor, recursive=True)


def runtime(subastas=None):
    """Un Lua con el exportador y el reposteo cargados, como en el juego."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.PERSONAJE = "Pepe"
    g.REINO = "Sanguino"
    g.AHORA = 1756500000
    lua.execute(DOBLES)
    lua.execute(VIGILADOS)
    poner(lua, "SUBASTAS", subastas or [])
    for nombre in ("WowAlertsExport.lua", "Reposteo.lua"):
        lua.execute((CARPETA / nombre).read_text(encoding="utf-8"))
    return lua


def a_python(valor):
    """Una tabla de Lua convertida en lista o diccionario de Python."""
    if lupa.lua_type(valor) != "table":
        return valor
    claves = list(valor.keys())
    if claves and all(isinstance(k, int) for k in claves) and sorted(claves) == list(
        range(1, len(claves) + 1)
    ):
        return [a_python(valor[k]) for k in sorted(claves)]
    if not claves:
        return []
    return {k: a_python(valor[k]) for k in claves}


def mia(auction_id, precio, item_id=GREBAS, ilvl=311, status=0, segundos=None, banda=None):
    """Una subasta tuya, como la devuelve GetOwnedAuctionInfo."""
    info = {
        "auctionID": auction_id,
        "itemKey": {"itemID": item_id, "itemLevel": ilvl},
        "itemLink": f"[Grebas]ilvl{ilvl}",
        "buyoutAmount": precio,
        "quantity": 1,
        "status": status,
    }
    # Lo que le queda de listado: en segundos, o en la banda de Blizzard para
    # los clientes que no dan el numero exacto.
    if segundos is not None:
        info["timeLeftSeconds"] = segundos
    if banda is not None:
        info["timeLeft"] = banda
    return info


def en_venta(auction_id, precio, dueno="Extrano", propia=False, de_la_cuenta=False):
    """Una fila de resultados de busqueda, como la devuelve GetItemSearchResultInfo."""
    return {
        "auctionID": auction_id,
        "buyoutAmount": precio,
        "owners": [dueno],
        "containsOwnerItem": propia,
        "containsAccountItem": de_la_cuenta,
    }


def en_la_casa(lua, filas, item_id=GREBAS, ilvl=311):
    """Lo que devolvera la busqueda de ese objeto e ilvl."""
    poner(lua, "RESULTADOS", {f"{item_id}:{ilvl}:0": filas})


def abrir_casa(lua, esperar=True):
    """Abre la casa y, salvo que se pida lo contrario, deja pasar los segundos
    que hacen falta para fiarse de la lista de subastas propias."""
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    if esperar:
        lua.globals().RELOJ = lua.globals().RELOJ + 5


def pulsar(lua):
    return lua.globals().WowAlertsReposteo.Siguiente()


def responder_todo(lua):
    while lua.eval("#BUSQUEDAS") > 0:
        lua.globals().RESPONDER()


def cola(lua):
    return a_python(lua.eval('((WowAlertsExportDB.reposteo or {})["Sanguino-Pepe"]) or {}'))


def llamadas(lua):
    """Las llamadas protegidas registradas, leyendo cada una por su "n" para
    no perder los argumentos nil de en medio (p.ej. duracion o puja)."""
    tabla = lua.globals().LLAMADAS
    total = int(lua.eval("#LLAMADAS"))
    resultado = []
    for i in range(1, total + 1):
        llamada = tabla[i]
        n = int(llamada["n"])
        resultado.append(tuple(a_python(llamada[j]) for j in range(1, n + 1)))
    return resultado


# -- La regla del rival --------------------------------------------------------


def _regla(lua, rival, mia_):
    return lua.globals().WowAlertsReposteo.vaPorDelante(
        lua.table_from(rival), lua.table_from(mia_)
    )


def test_una_mas_barata_va_por_delante():
    lua = runtime()
    assert _regla(lua, {"auctionID": 1, "buyout": 90}, {"auctionID": 5, "buyout": 100})


def test_al_mismo_precio_solo_adelanta_la_publicada_despues():
    lua = runtime()
    assert _regla(lua, {"auctionID": 6, "buyout": 100}, {"auctionID": 5, "buyout": 100})
    assert not _regla(lua, {"auctionID": 4, "buyout": 100}, {"auctionID": 5, "buyout": 100})


def test_una_mas_cara_no_adelanta():
    lua = runtime()
    assert not _regla(lua, {"auctionID": 9, "buyout": 101}, {"auctionID": 5, "buyout": 100})


def test_lo_tuyo_y_lo_de_tus_alts_no_cuenta_como_rival():
    lua = runtime()
    es_nuestro = lua.globals().WowAlertsReposteo.esNuestro

    def fila(**kw):
        return lua.table_from(en_venta(1, 100, **kw), recursive=True)

    assert es_nuestro(fila(propia=True))
    assert es_nuestro(fila(de_la_cuenta=True))
    assert es_nuestro(fila(dueno="Mbarval"))
    assert es_nuestro(fila(dueno="Mbarval-Sanguino"))
    assert not es_nuestro(fila(dueno="Extrano"))

    # Sin duenos y sin banderas de propiedad tampoco es nuestro: una fila asi
    # no puede colarse como "propia" por defecto.
    sin_duenos = lua.table_from(
        {
            "auctionID": 1,
            "buyoutAmount": 100,
            "owners": [],
            "containsOwnerItem": False,
            "containsAccountItem": False,
        },
        recursive=True,
    )
    assert not es_nuestro(sin_duenos)


# -- El arnes de eventos --------------------------------------------------------


def test_disparar_solo_entrega_a_quien_registro_el_evento():
    """Un RegisterEvent olvidado en el addon de verdad no debe pasar aqui
    desapercibido: DISPARAR solo tiene que llegar a quien se apunto."""
    lua = runtime()
    lua.execute(
        """
        VISTOS = {}
        local marco = CreateFrame("Frame")
        marco:RegisterEvent("EVENTO_APUNTADO")
        marco:SetScript("OnEvent", function(self, evento) VISTOS[#VISTOS + 1] = evento end)
        """
    )

    lua.globals().DISPARAR("EVENTO_NO_APUNTADO")
    assert a_python(lua.globals().VISTOS) == []

    lua.globals().DISPARAR("EVENTO_APUNTADO")
    assert a_python(lua.globals().VISTOS) == ["EVENTO_APUNTADO"]


# -- Llamadas protegidas --------------------------------------------------------


def test_llamadas_tolera_un_argumento_nulo_en_medio():
    lua = runtime()
    lua.execute('C_AuctionHouse.PostItem({bagID = 0, slotIndex = 3}, nil, 1, nil, 500)')
    assert llamadas(lua) == [("PostItem", 0, 3, None, 1, 500)]


def test_el_toc_carga_los_ficheros_en_orden():
    # El orden no es capricho: cada fichero usa lo que deja el anterior.
    # Vigilados.lua no depende de nadie. Personajes.lua rellena la lista de
    # personajes de WowAlertsVigilados, y no se sube a git: si falta, WoW se
    # lo salta y la lista se queda vacia. WowAlertsExport.lua lee
    # WowAlertsVigilados. Reposteo.lua lee WowAlertsVigilados y
    # WowAlertsExportDB. BancoHermandad.lua usa WowAlertsExportDB y el
    # codificador JSON de WowAlertsExport.lua (WowAlertsJSON).
    # Ventana.lua lee WowAlertsReposteo y WowAlertsBanco, asi que tiene que
    # ir el ultimo. Si añades un fichero nuevo, piensa que
    # necesita antes de cargar y ponlo en el sitio que le toque, no al final
    # sin mas.
    toc = (CARPETA / "WowAlertsExport.toc").read_text(encoding="utf-8")
    ficheros = [l.strip() for l in toc.splitlines() if l.strip() and not l.startswith("##")]
    assert ficheros == [
        "Vigilados.lua",
        "Personajes.lua",
        "WowAlertsExport.lua",
        "Reposteo.lua",
        "BancoHermandad.lua",
        "Ventana.lua",
    ]


# -- Ventana.lua: solo dibuja, no hay dobles que lo prueben de verdad --------
# Lo que sigue no comprueba que WoW lo pinte bien (eso es cosa de la Task 9),
# pero si puede pillar erratas de sintaxis, texto no-ASCII colado sin querer,
# y el fallo concreto que ya nos pillo una vez: un CreateFrame con nombre que
# pisa el global de la tabla del modulo.


def test_ventana_compila():
    codigo = (CARPETA / "Ventana.lua").read_text(encoding="utf-8")
    lupa.LuaRuntime().compile(codigo)


def test_ventana_es_ascii_puro():
    # El resto del addon se escribe sin tildes ni enie (Reposteo.lua escribe
    # "dueno", no "dueño"), asi que un caracter fuera de ASCII es una errata.
    datos = (CARPETA / "Ventana.lua").read_bytes()
    datos.decode("ascii")


def test_ventana_no_pisa_su_propio_global_con_createframe():
    # El bug real: CreateFrame("Frame", "WowAlertsVentana", ...) escribe
    # _G["WowAlertsVentana"] = marco en cuanto se crea el marco, pisando la
    # tabla del modulo (WowAlertsVentana = V, arriba del fichero). A partir
    # de ahi WowAlertsVentana.Refrescar deja de existir sin dar ningun error
    # en pantalla, y Reposteo.lua no puede volver a avisar a la ventana. El
    # marco tiene que llamarse distinto al global del modulo, y lo mismo vale
    # para cualquier otro frame con nombre que se añada mas adelante (el de
    # eventos, por ejemplo): se comprueban TODOS los CreateFrame con nombre,
    # no solo el primero.
    codigo = (CARPETA / "Ventana.lua").read_text(encoding="utf-8")

    asignacion_modulo = re.search(r"^(\w+)\s*=\s*V\s*$", codigo, re.MULTILINE)
    assert asignacion_modulo, "no se encontro la asignacion del modulo (ej. WowAlertsVentana = V)"
    nombre_modulo = asignacion_modulo.group(1)

    nombres_de_marco = re.findall(r'CreateFrame\(\s*"[^"]*"\s*,\s*"([^"]+)"', codigo)
    assert nombres_de_marco, "no se encontro ningun CreateFrame con nombre"
    assert nombre_modulo not in nombres_de_marco


def test_el_exportador_sigue_funcionando_con_el_reposteo_cargado():
    lua = runtime(subastas=[mia(1, 100)])
    abrir_casa(lua)

    payload = json.loads(lua.globals().WowAlertsExportDB.payload)
    subastas = payload["personajes"]["Sanguino-Pepe"]["auctions"]
    assert [s["auctionID"] for s in subastas] == [1]


# -- La busqueda -----------------------------------------------------------------


def detectar(lua):
    """Abre la casa, pulsa para buscar y deja que el servidor responda a todo."""
    abrir_casa(lua)
    pulsar(lua)
    responder_todo(lua)


def test_la_primera_pulsacion_busca_y_no_cancela_nada():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)

    assert pulsar(lua) == "buscar"
    assert lua.globals().BUSCADAS == 1
    assert llamadas(lua) == []


def test_sin_la_casa_abierta_no_busca():
    lua = runtime(subastas=[mia(10, 100_000)])
    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == 0


def test_si_te_adelantan_entra_en_la_cola_al_precio_del_rival():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000), en_venta(10, 100_000, dueno="Pepe", propia=True)])
    detectar(lua)

    [entrada] = cola(lua)
    assert entrada["auctionID"] == 10
    assert entrada["estado"] == "cancelar"
    assert entrada["precio"] == 90_000
    assert entrada["precioAnterior"] == 100_000
    assert (entrada["itemID"], entrada["ilvl"]) == (GREBAS, 311)


def test_al_mismo_precio_y_publicada_despues_tambien_te_adelanta():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 100_000)])
    detectar(lua)

    assert [e["precio"] for e in cola(lua)] == [100_000]


def test_si_vas_primero_no_entra_nada():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(9, 100_000), en_venta(12, 120_000)])
    detectar(lua)

    assert cola(lua) == []


def test_tus_alts_no_te_adelantan():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 50_000, dueno="Mbarval-Sanguino")])
    detectar(lua)

    assert cola(lua) == []


def test_solo_se_revisan_los_objetos_vigilados_y_activos():
    lua = runtime(subastas=[mia(10, 100_000, item_id=999), mia(11, 100_000, status=1)])
    detectar(lua)

    assert lua.globals().BUSCADAS == 0
    assert cola(lua) == []


def test_una_busqueda_por_objeto_e_ilvl_y_de_una_en_una():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1
    assert lua.eval("BUSQUEDAS[1].itemID") == GREBAS
    assert lua.eval("BUSQUEDAS[1].itemLevel") == 311

    lua.globals().RESPONDER()
    assert lua.globals().BUSCADAS == 2

    responder_todo(lua)
    # Las dos de ilvl 311 comparten busqueda.
    assert lua.globals().BUSCADAS == 2


def test_si_la_casa_no_admite_consultas_espera_a_que_avise():
    lua = runtime(subastas=[mia(10, 100_000)])
    lua.globals().SISTEMA_LISTO = False
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 0

    lua.globals().SISTEMA_LISTO = True
    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
    assert lua.globals().BUSCADAS == 1


def test_mientras_busca_otra_pulsacion_no_hace_nada():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)

    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == 1


def test_la_cola_se_guarda_en_savedvariables_por_personaje():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)

    assert lua.eval('WowAlertsExportDB.reposteo["Sanguino-Pepe"][1].auctionID') == 10


def test_volver_a_buscar_actualiza_el_precio_sin_duplicar():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    en_la_casa(lua, [en_venta(11, 90_000), en_venta(13, 80_000)])
    detectar(lua)

    assert [e["precio"] for e in cola(lua)] == [80_000]


def test_si_ya_no_te_adelantan_sale_de_la_cola():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []


def test_no_busca_hasta_fiarse_de_la_lista_de_subastas():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    detectar(lua)
    assert cola(lua) != []

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    buscadas_antes = lua.globals().BUSCADAS

    poner(lua, "SUBASTAS", [])
    abrir_casa(lua, esperar=False)
    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == buscadas_antes
    assert cola(lua) != []

    poner(lua, "SUBASTAS", [mia(10, 100_000)])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert pulsar(lua) == "buscar"


def test_si_la_respuesta_no_llega_se_salta_ese_objeto():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1

    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.globals().BUSCADAS == 2

    lua.globals().RESPONDER()
    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == 2


def test_una_respuesta_a_tiempo_no_la_salta_el_temporizador():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 90_000)])
    abrir_casa(lua)
    pulsar(lua)
    lua.globals().RESPONDER()

    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.globals().BUSCADAS == 1
    assert [e["precio"] for e in cola(lua)] == [90_000]


def test_si_el_servidor_descarta_la_consulta_se_vuelve_a_pedir():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
    assert lua.globals().BUSCADAS == 2


def test_cerrar_la_casa_a_mitad_para_la_busqueda():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)
    assert lua.globals().BUSCADAS == 1

    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.globals().BUSCADAS == 1


def test_de_dos_subastas_solo_entra_la_que_va_por_detras():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)

    assert [e["auctionID"] for e in cola(lua)] == [10]


def test_no_busca_si_la_lista_de_subastas_no_ha_llegado_tras_abrir():
    """La espera de unos segundos no basta: tiene que haber llegado la lista."""
    lua = runtime(subastas=[mia(10, 100_000)])
    lua.execute("C_AuctionHouse.QueryOwnedAuctions = function() end")
    abrir_casa(lua)
    assert pulsar(lua) is None

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert pulsar(lua) == "buscar"


def contar_peticiones_de_lista(lua, responde=True):
    """Cuenta las QueryOwnedAuctions en PEDIDAS; sin `responde`, nunca llega
    la respuesta."""
    lua.execute("PEDIDAS = 0")
    lua.execute(
        "local original = C_AuctionHouse.QueryOwnedAuctions\n"
        "C_AuctionHouse.QueryOwnedAuctions = function(...)\n"
        "    PEDIDAS = PEDIDAS + 1\n"
        + ("    original(...)\n" if responde else "")
        + "end"
    )


def test_al_abrir_pide_la_lista_y_busca_en_cuanto_llega():
    """Sin esperar los segundos de margen: como Auctionator, la respuesta a la
    peticion propia es de fiar."""
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua, esperar=False)
    # La lista puede llegar a trozos: se deja medio segundo sin cambios.
    assert pulsar(lua) is None

    lua.globals().RELOJ = lua.globals().RELOJ + 0.5
    assert pulsar(lua) == "buscar"


def test_una_lista_vacia_no_basta_y_se_esperan_los_segundos_de_margen():
    lua = runtime(subastas=[])
    abrir_casa(lua, esperar=False)
    lua.globals().RELOJ = lua.globals().RELOJ + 0.5
    assert pulsar(lua) is None

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert pulsar(lua) == "buscar"


def test_una_lista_de_antes_de_pedirla_no_vale():
    lua = runtime(subastas=[mia(10, 100_000)])
    contar_peticiones_de_lista(lua)
    lua.globals().SISTEMA_LISTO = False
    abrir_casa(lua, esperar=False)
    peticiones = lua.globals().PEDIDAS  # la del exportador, que no mira si la casa esta libre

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    lua.globals().RELOJ = lua.globals().RELOJ + 0.5
    assert pulsar(lua) is None

    lua.globals().SISTEMA_LISTO = True
    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
    assert lua.globals().PEDIDAS == peticiones + 1
    # Ahora si: la lista llega despues de pedirla, y la busqueda sale sola.
    assert lua.eval("#BUSQUEDAS") == 1


def test_si_se_descarta_la_peticion_de_la_lista_se_repite():
    lua = runtime(subastas=[mia(10, 100_000)])
    contar_peticiones_de_lista(lua, responde=False)
    abrir_casa(lua, esperar=False)
    peticiones = lua.globals().PEDIDAS

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
    assert lua.globals().PEDIDAS == peticiones + 1


def test_el_boton_deja_de_decir_leyendo_cuando_la_lista_se_calma():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua, esperar=False)
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Leyendo tus subastas..."

    lua.globals().RELOJ = lua.globals().RELOJ + 0.5
    lua.globals().VENCER_TEMPORIZADORES()
    # En cuanto la lista esta entera la busqueda arranca sola, sin pulsar.
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Buscando 1/1..."


# -- La busqueda sola al abrir -----------------------------------------------


def test_al_abrir_la_casa_busca_sin_pulsar_la_tecla():
    """Al entrar con un personaje quieres ver quien te adelanta sin tocar nada.
    Buscar no es una funcion protegida, asi que puede salir solo."""
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(99, 90_000)])
    abrir_casa(lua, esperar=False)
    assert lua.eval("#BUSQUEDAS") == 0

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    responder_todo(lua)

    assert [e["auctionID"] for e in cola(lua)] == [10]
    assert llamadas(lua) == []   # buscar no toca ninguna funcion protegida


def test_la_busqueda_sola_actualiza_la_ventana_con_cada_respuesta():
    """Sin pulsaciones, la ventana solo se entera si la busqueda la refresca."""
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua, esperar=False)
    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Buscando 1/2..."

    lua.globals().RESPONDER()
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Buscando 2/2..."


def test_la_busqueda_sola_no_avisa_en_el_chat_hasta_que_pulsas():
    """Abrir la casa para comprar no puede soltarte un aviso con sonido."""
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(99, 200_000)])
    abrir_casa(lua, esperar=False)
    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    responder_todo(lua)
    assert avisos(lua) == []

    assert pulsar(lua) is None
    assert avisos(lua) == ["|cff33ccffReposteo:|r Nada que repostear"]


def test_no_busca_sola_si_hay_algo_devuelto_que_postear():
    """Al volver del buzon, postear va antes que buscar, y postear es una
    funcion protegida: eso lo tiene que hacer la tecla."""
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    abrir_casa(lua, esperar=False)

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.eval("#BUSQUEDAS") == 0
    assert estado(lua) == "Postear"


# -- Lo visto hace poco ----------------------------------------------------------


def cerrar_casa(lua):
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")


def test_no_repite_la_busqueda_de_lo_que_acaba_de_ver_sin_adelantar():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)
    assert lua.globals().BUSCADAS == 1
    cerrar_casa(lua)

    detectar(lua)
    assert lua.globals().BUSCADAS == 1
    assert estado(lua) == "Nada que repostear"


def test_pasados_unos_minutos_si_vuelve_a_buscarlo():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)
    cerrar_casa(lua)

    # Se mueven los dos relojes, como al pasar el rato de verdad. El que manda
    # aqui es AHORA (time()), porque la marca sobrevive a la sesion.
    lua.globals().RELOJ = lua.globals().RELOJ + 300
    lua.globals().AHORA = lua.globals().AHORA + 300
    detectar(lua)
    assert lua.globals().BUSCADAS == 2


def recargar(lua, subastas):
    """Otro Lua con lo guardado del anterior, como al hacer /reload o al
    cambiar de personaje: WoW vuelve a ejecutar los ficheros del addon y
    despues le devuelve su tabla de disco."""
    guardado = a_python(lua.globals().WowAlertsExportDB)
    otra = runtime(subastas=subastas)
    poner(otra, "WowAlertsExportDB", guardado)
    otra.globals().AHORA = lua.globals().AHORA
    return otra


def test_lo_visto_hace_poco_sobrevive_a_un_reload():
    """Con 21 personajes, cambiar de personaje recargaba el addon y borraba
    esta memoria: se volvia a buscar todo en cada salto."""
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    otra = recargar(lua, [mia(10, 100_000)])
    en_la_casa(otra, [])
    detectar(otra)
    assert otra.globals().BUSCADAS == 0


def test_al_reiniciar_el_juego_las_marcas_viejas_si_caducan():
    """GetTime() vuelve a cero al arrancar el cliente. Si la marca se guardara
    con el, al reiniciar quedaria en el futuro y no se buscaria nunca mas."""
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    otra = recargar(lua, [mia(10, 100_000)])
    otra.globals().RELOJ = 0            # el cliente acaba de arrancar
    otra.globals().AHORA = lua.globals().AHORA + 300
    en_la_casa(otra, [])
    detectar(otra)
    assert otra.globals().BUSCADAS == 1


def test_lo_adelantado_borra_su_marca_y_se_vuelve_a_mirar_tras_recargar():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)

    otra = recargar(lua, [mia(10, 100_000)])
    en_la_casa(otra, [en_venta(999, 90_000)])
    detectar(otra)
    assert otra.globals().BUSCADAS == 1


def test_lo_visto_hace_poco_no_crece_sin_fin():
    """La tabla se guarda en disco: sin podar tendria una entrada por cada
    subasta que haya pasado por la casa."""
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)
    cerrar_casa(lua)

    lua.globals().AHORA = lua.globals().AHORA + 300
    poner(lua, "SUBASTAS", [mia(12, 100_000)])
    detectar(lua)

    guardado = a_python(lua.eval("WowAlertsExportDB.vistaLimpia"))
    assert list(guardado) == [12]


def test_lo_adelantado_se_vuelve_a_buscar_en_cada_visita():
    """Cancelar cuesta el deposito: se confirma con datos de esta visita."""
    lua = runtime()
    adelantadas(lua, 10)
    cerrar_casa(lua)

    detectar(lua)
    assert lua.globals().BUSCADAS == 2
    assert pulsar(lua) == "cancelar"


def test_una_subasta_nueva_del_mismo_objeto_se_busca():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)
    cerrar_casa(lua)

    poner(lua, "SUBASTAS", [mia(10, 100_000), mia(12, 100_000)])
    detectar(lua)
    assert lua.globals().BUSCADAS == 2


def test_lo_devuelto_se_busca_aunque_su_objeto_se_viera_hace_poco():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)  # la 12 va primera; la 10 esta adelantada
    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    cerrar_casa(lua)

    poner(lua, "SUBASTAS", [mia(12, 80_000)])
    en_la_bolsa(lua, 3)
    envejecer_precios(lua)
    detectar(lua)
    assert lua.globals().BUSCADAS == 2
    assert pulsar(lua) == "postear"


# -- Cancelar --------------------------------------------------------------------


def adelantadas(lua, *ids, precio=100_000, rival=90_000):
    """Tus subastas `ids`, todas adelantadas por un rival mas barato, ya buscadas."""
    poner(lua, "SUBASTAS", [mia(i, precio) for i in ids])
    en_la_casa(lua, [en_venta(999, rival)])
    detectar(lua)


def test_cada_pulsacion_cancela_una_sola():
    lua = runtime()
    adelantadas(lua, 10, 12, 14)

    for esperadas, id_ in ((1, 10), (2, 12), (3, 14)):
        assert pulsar(lua) == "cancelar"
        assert len(llamadas(lua)) == esperadas
        lua.globals().DISPARAR("AUCTION_CANCELED", id_)

    assert llamadas(lua) == [("CancelAuction", 10), ("CancelAuction", 12), ("CancelAuction", 14)]


def test_no_cancela_otra_hasta_que_el_juego_confirma_la_anterior():
    lua = runtime()
    adelantadas(lua, 10, 12)
    assert pulsar(lua) == "cancelar"

    assert pulsar(lua) is None
    assert llamadas(lua) == [("CancelAuction", 10)]

    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert pulsar(lua) == "cancelar"


def test_si_la_cancelacion_no_responde_pasado_el_margen_sigue_con_la_siguiente():
    lua = runtime()
    adelantadas(lua, 10, 12)
    assert pulsar(lua) == "cancelar"

    lua.globals().RELOJ = lua.globals().RELOJ + 10
    assert pulsar(lua) == "cancelar"
    assert llamadas(lua) == [("CancelAuction", 10), ("CancelAuction", 12)]


def test_cuando_el_juego_confirma_la_cancelacion_pasa_a_devuelta():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    assert cola(lua)[0]["estado"] == "cancelando"

    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert cola(lua)[0]["estado"] == "devuelta"


def test_una_que_se_esta_cancelando_no_se_vuelve_a_cancelar():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)

    assert pulsar(lua) is None
    assert len(llamadas(lua)) == 1


def test_la_cancelacion_la_apunta_tambien_el_exportador():
    """Es lo que evita que el vigilante la cuente como venta."""
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)

    assert lua.eval('WowAlertsExportDB.canceladas["10"]') is not None


def test_si_el_juego_rechaza_la_cancelacion_vuelve_a_la_fila():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)  # sin AUCTION_CANCELED: el juego no la ha cancelado
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    detectar(lua)
    assert cola(lua)[0]["estado"] == "cancelar"


def test_si_desaparece_antes_de_cancelarla_sale_de_la_cola():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    poner(lua, "SUBASTAS", [])  # se vendio mientras tanto
    detectar(lua)
    assert cola(lua) == []


def test_mientras_busca_no_cancela_lo_de_la_visita_anterior():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    poner(lua, "SUBASTAS", [mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_si_la_busqueda_no_confirma_una_adelantada_no_se_cancela():
    """Cancelar cuesta el deposito: sin datos de esta visita, no se cancela."""
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    abrir_casa(lua)
    pulsar(lua)
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_una_cancelada_a_mano_pasa_a_devuelta():
    lua = runtime()
    adelantadas(lua, 10)

    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert cola(lua)[0]["estado"] == "devuelta"


def test_no_cancela_lo_que_el_juego_no_deja_cancelar():
    lua = runtime()
    adelantadas(lua, 10, 12)
    lua.execute("C_AuctionHouse.CanCancelAuction = function(id) return id ~= 10 end")

    assert pulsar(lua) == "cancelar"
    assert llamadas(lua) == [("CancelAuction", 12)]


def test_cancela_lo_ya_confirmado_mientras_sigue_buscando_lo_demas():
    """Abrir y machacar: se cancela en cuanto se sabe, sin esperar a buscar todo."""
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().RESPONDER()  # la de ilvl 311 esta adelantada; falta la de 298

    assert estado(lua) == "Cancelar (1)"
    assert lua.eval("WowAlertsReposteoBoton:IsEnabled()") is True
    assert pulsar(lua) == "cancelar"
    assert llamadas(lua) == [("CancelAuction", 10)]
    assert lua.eval("#BUSQUEDAS") == 1


def test_mientras_busca_no_postea_aunque_haya_algo_listo():
    """Postear si necesita la casa libre, y la busqueda la ocupa: se deja para
    el final."""
    lua = runtime(subastas=[mia(10, 100_000), mia(11, 100_000, ilvl=298)])
    poner(lua, "RESULTADOS", {
        f"{GREBAS}:311:0": [en_venta(999, 90_000)],
        f"{GREBAS}:298:0": [en_venta(998, 90_000)],
    })
    detectar(lua)
    for i in (10, 11):
        assert pulsar(lua) == "cancelar"
        lua.globals().DISPARAR("AUCTION_CANCELED", i)
    cerrar_casa(lua)

    poner(lua, "SUBASTAS", [])
    poner(lua, "LLAMADAS", [])
    en_la_bolsa(lua, 3, ilvl=298)
    envejecer_precios(lua)
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().RESPONDER()  # repasada la de 298, que esta en la bolsa; falta la de 311
    assert lua.eval("#BUSQUEDAS") == 1

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_cancela_aunque_la_casa_este_ocupada_con_consultas():
    """Como Auctionator: cancelar no espera a que la casa atienda consultas,
    solo a que el juego responda a la cancelacion anterior."""
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().SISTEMA_LISTO = False

    assert pulsar(lua) == "cancelar"
    assert llamadas(lua) == [("CancelAuction", 10)]


# -- El correo -------------------------------------------------------------------


def devolver(lua, *ids, precio=100_000, rival=90_000):
    """Deja `ids` en la cola como devueltas: buscadas, canceladas y confirmadas."""
    adelantadas(lua, *ids, precio=precio, rival=rival)
    for i in ids:
        pulsar(lua)
        lua.globals().DISPARAR("AUCTION_CANCELED", i)
    poner(lua, "SUBASTAS", [])
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "LLAMADAS", [])
    # El aviso de "todas canceladas" de esta preparacion no es lo que se prueba.
    lua.execute("mensajes = {}; PANTALLA = {}; SONIDOS = {}")


def carta(item_id=GREBAS, ilvl=311, asunto="Auction cancelled: Greaves of the Noxious Depths"):
    return {"asunto": asunto, "nombre": "Greaves", "itemID": item_id, "enlace": f"[Grebas]ilvl{ilvl}"}


def abrir_buzon(lua):
    lua.globals().BUZON_ABIERTO = True
    lua.globals().DISPARAR("MAIL_SHOW")


def test_en_el_buzon_recoge_la_carta_de_lo_cancelado():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]


def test_no_recoge_cartas_que_no_son_de_la_cola():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta(asunto="Hola"), carta(item_id=999), carta(ilvl=298)])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_no_recoge_si_el_objeto_ya_esta_en_la_bolsa():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(lua, "BOLSA", {"0:1": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False}})
    abrir_buzon(lua)

    assert pulsar(lua) is None


def test_no_pide_dos_cartas_para_una_sola_devuelta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"
    assert pulsar(lua) is None
    assert len(llamadas(lua)) == 1


def test_con_dos_devueltas_recoge_dos_cartas_de_una_en_una():
    lua = runtime()
    devolver(lua, 10, 12)
    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)

    pulsar(lua)
    pulsar(lua)
    assert llamadas(lua) == [("TakeInboxItem", 1, 1), ("TakeInboxItem", 2, 1)]


def test_si_la_bolsa_estaba_llena_se_reintenta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    pulsar(lua)

    # La carta sigue ahi porque el objeto no cabia.
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    assert pulsar(lua) == "recoger"


def test_funciona_con_el_asunto_en_castellano():
    lua = runtime()
    lua.globals().AUCTION_REMOVED_MAIL_SUBJECT = "Subasta cancelada: %s"
    devolver(lua, 10)
    poner(lua, "CORREO", [carta(asunto="Subasta cancelada: Grebas de las profundidades nocivas")])
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"


def test_una_carta_sin_datos_del_objeto_todavia_no_rompe_la_tecla():
    """El enlace de un adjunto puede no estar cargado aun."""
    lua = runtime()
    devolver(lua, 10)
    lua.execute(
        """
        local original = GetDetailedItemLevelInfo
        GetDetailedItemLevelInfo = function(enlace)
            assert(enlace ~= nil, "enlace nil")
            return original(enlace)
        end
        """
    )
    sin_enlace = carta()
    del sin_enlace["enlace"]
    poner(lua, "CORREO", [sin_enlace])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_una_copia_de_otro_ilvl_en_la_bolsa_no_frena_la_carta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(lua, "BOLSA", {"0:1": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl298", "isLocked": False}})
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"


def test_cuenta_las_copias_de_todas_las_bolsas():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(lua, "BOLSA", {"4:16": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False}})
    abrir_buzon(lua)

    assert pulsar(lua) is None


def test_no_recoge_para_una_que_aun_no_se_ha_cancelado():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_cerrar_y_abrir_el_buzon_permite_reintentar():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"


# -- Postear ---------------------------------------------------------------------


def en_la_bolsa(lua, *huecos, ilvl=311):
    poner(
        lua,
        "BOLSA",
        {
            f"0:{h}": {"itemID": GREBAS, "hyperlink": f"[Grebas]ilvl{ilvl}", "isLocked": False}
            for h in huecos
        },
    )


def envejecer_precios(lua):
    """Pasan minutos: el precio de la ultima busqueda ya no vale para postear
    sin buscar otra vez."""
    lua.globals().AHORA = lua.globals().AHORA + 600


def volver_a_la_casa(lua, filas):
    """Con lo devuelto ya recogido, vuelves a la casa pasados unos minutos, con el
    precio de la cancelacion ya viejo, y pulsas para buscar."""
    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    lua.globals().AHORA = lua.globals().AHORA + 600
    en_la_casa(lua, filas)
    detectar(lua)
    poner(lua, "LLAMADAS", [])


def test_postea_lo_devuelto_al_precio_del_rival():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua) == [("PostItem", 0, 3, 1, 1, 90_000)]
    assert cola(lua) == []


def test_si_el_rival_ha_bajado_se_iguala_su_precio_nuevo():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 85_000)])

    pulsar(lua)
    assert llamadas(lua)[-1][-1] == 85_000


def test_si_el_rival_ya_no_esta_se_repostea_al_precio_anterior():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [])

    pulsar(lua)
    assert llamadas(lua)[-1][-1] == 100_000


def test_un_rival_mas_caro_que_tu_precio_anterior_no_sube_el_precio():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 150_000)])

    pulsar(lua)
    assert llamadas(lua)[-1][-1] == 100_000


def test_sin_buscar_en_esta_visita_no_postea():
    """Con el precio de hace minutos, se recalcula antes de postear."""
    lua = runtime()
    devolver(lua, 10)
    envejecer_precios(lua)
    en_la_bolsa(lua, 3)
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)

    assert pulsar(lua) == "buscar"
    responder_todo(lua)
    assert pulsar(lua) == "postear"


def test_sin_el_objeto_en_la_bolsa_no_postea():
    lua = runtime()
    devolver(lua, 10)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_una_copia_bloqueada_no_se_usa():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    lua.execute('BOLSA["0:3"].isLocked = true')
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) is None


def test_con_dos_devueltas_postea_dos_con_dos_pulsaciones():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    pulsar(lua)
    pulsar(lua)
    assert [(c[0], c[2]) for c in llamadas(lua)] == [("PostItem", 3), ("PostItem", 4)]


def test_si_el_juego_pide_confirmacion_la_siguiente_pulsacion_confirma():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True

    assert pulsar(lua) == "postear"
    assert len(cola(lua)) == 1

    assert pulsar(lua) == "confirmar"
    assert llamadas(lua)[-1] == ("ConfirmPostItem", 0, 3, 1, 1, 90_000)
    assert cola(lua) == []


def test_cancelar_va_antes_que_postear():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    poner(lua, "SUBASTAS", [mia(20, 100_000)])
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "cancelar"
    assert pulsar(lua) == "postear"


def test_con_la_casa_saturada_de_consultas_no_postea():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().SISTEMA_LISTO = False

    assert pulsar(lua) is None
    assert llamadas(lua) == []
    lua.globals().SISTEMA_LISTO = True
    assert pulsar(lua) == "postear"


def test_cerrar_la_casa_olvida_la_confirmacion_pendiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    assert [c[0] for c in llamadas(lua)] == ["PostItem"]


def test_una_confirmacion_no_se_repite():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    pulsar(lua)
    assert pulsar(lua) == "confirmar"

    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)].count("ConfirmPostItem") == 1


def test_si_la_busqueda_no_repasa_el_precio_no_se_postea():
    lua = runtime()
    devolver(lua, 10)
    envejecer_precios(lua)
    en_la_bolsa(lua, 3)
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_el_precio_repasado_no_vale_para_la_visita_siguiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    envejecer_precios(lua)

    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().VENCER_TEMPORIZADORES()  # esta vez la respuesta no llega

    assert pulsar(lua) is None
    assert llamadas(lua) == []


def test_postea_con_la_duracion_de_vigilados():
    lua = runtime()
    lua.execute("WowAlertsVigilados.duracion = 2")
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    pulsar(lua)
    assert llamadas(lua)[-1][3] == 2


def test_si_el_objeto_cambia_de_hueco_antes_de_confirmar_no_se_confirma():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: en el hueco 3 queda otra cosa y las grebas pasan al 4.
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": 999, "hyperlink": "[Otra]ilvl311", "isLocked": False},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    assert pulsar(lua) is None
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]
    # Se descarto la confirmacion, pero la entrada sigue "posteando": lo
    # decide la busqueda siguiente (I-2).
    assert [e["estado"] for e in cola(lua)] == ["posteando"]
    assert pulsar(lua) is None

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])  # SUBASTAS no tiene nada a ese precio
    assert [e["estado"] for e in cola(lua)] == ["devuelta"]

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_no_postea_una_copia_que_la_casa_no_acepta():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3, 4)
    lua.execute("C_AuctionHouse.IsSellItemValid = function(loc) return loc.slotIndex ~= 3 end")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_una_copia_ligada_no_se_postea_aunque_la_casa_la_acepte():
    lua = runtime()
    devolver(lua, 10)
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False, "isBound": True},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    lua.execute("C_AuctionHouse.IsSellItemValid = function() return true end")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_la_misma_pieza_de_otro_ilvl_en_el_hueco_no_se_confirma():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: en el hueco 3 queda la misma pieza pero de otro ilvl.
    poner(
        lua,
        "BOLSA",
        {"0:3": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl298", "isLocked": False}},
    )
    assert pulsar(lua) is None
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]


def test_al_confirmar_se_cierra_el_aviso_de_precio_de_blizzard():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True

    assert pulsar(lua) == "postear"
    assert lua.eval("AVISO_VISIBLE") == "AUCTION_HOUSE_POST_WARNING"

    assert pulsar(lua) == "confirmar"
    assert a_python(lua.globals().OCULTADOS) == ["AUCTION_HOUSE_POST_WARNING"]


def test_si_se_descarta_la_confirmacion_tambien_se_cierra_el_aviso():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: en el hueco 3 queda otra cosa y las grebas pasan al 4.
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": 999, "hyperlink": "[Otra]ilvl311", "isLocked": False},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    assert pulsar(lua) is None
    assert a_python(lua.globals().OCULTADOS) == ["AUCTION_HOUSE_POST_WARNING"]
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]


def test_sin_confirmacion_no_se_toca_ningun_aviso():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert a_python(lua.globals().OCULTADOS) == []


def test_con_la_casa_saturada_la_confirmacion_espera():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    pulsar(lua)
    lua.globals().SISTEMA_LISTO = False

    assert pulsar(lua) is None
    assert a_python(lua.globals().OCULTADOS) == []
    assert lua.eval("AVISO_VISIBLE") == "AUCTION_HOUSE_POST_WARNING"
    assert "ConfirmPostItem" not in [c[0] for c in llamadas(lua)]
    lua.globals().SISTEMA_LISTO = True
    assert pulsar(lua) == "confirmar"


def test_no_postea_una_copia_que_no_se_puede_vender():
    lua = runtime()
    devolver(lua, 10)
    poner(
        lua,
        "BOLSA",
        {
            "0:3": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False, "isBound": True},
            "0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False},
        },
    )
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1][:3] == ("PostItem", 0, 4)


def test_una_copia_ligada_en_la_bolsa_no_frena_la_carta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    poner(
        lua,
        "BOLSA",
        {"0:1": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False, "isBound": True}},
    )
    abrir_buzon(lua)

    assert pulsar(lua) == "recoger"


# -- Panel, tecla y garantias ----------------------------------------------------


def estado(lua):
    return lua.globals().WowAlertsReposteo.Estado()


def test_el_panel_dice_que_toca():
    lua = runtime()
    abrir_casa(lua, esperar=False)
    assert estado(lua) == "Leyendo tus subastas..."

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert estado(lua) == "Buscar undercuts"

    adelantadas(lua, 10, 12)
    assert estado(lua) == "Cancelar (2)"


def test_mientras_busca_el_panel_lo_dice():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua)
    pulsar(lua)

    assert estado(lua) == "Buscando 1/2..."


def test_sin_nada_que_repostear_el_panel_lo_dice():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert estado(lua) == "Nada que repostear"


def test_con_una_confirmacion_pendiente_el_panel_la_pide():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    pulsar(lua)

    assert estado(lua) == "Confirmar posteo"


def test_en_el_buzon_el_panel_dice_si_hay_que_recoger():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert estado(lua) == "Recoger del buzon"

    poner(lua, "CORREO", [])
    assert estado(lua) == "Vuelve a la casa a postear"

    otro = runtime()
    abrir_buzon(otro)
    assert estado(otro) == "Nada que recoger"


def test_en_la_casa_el_panel_dice_si_postear_o_ir_al_buzon():
    lua = runtime()
    devolver(lua, 10)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert estado(lua) == "Recoge lo devuelto en el buzon"

    en_la_bolsa(lua, 3)
    assert estado(lua) == "Postear"


def test_si_no_se_pudo_repasar_el_precio_el_panel_lo_dice():
    lua = runtime()
    devolver(lua, 10)
    envejecer_precios(lua)
    en_la_bolsa(lua, 3)
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    pulsar(lua)
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_el_boton_dice_que_toca_y_se_desactiva_mientras_busca():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    abrir_casa(lua, esperar=False)
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Leyendo tus subastas..."
    assert lua.eval("WowAlertsReposteoBoton:IsEnabled()")

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Buscando 1/2..."
    assert not lua.eval("WowAlertsReposteoBoton:IsEnabled()")


def test_el_boton_se_muda_al_buzon():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == AuctionHouseFrame")

    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    abrir_buzon(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == MailFrame")


def test_si_la_casa_aun_no_habia_cargado_el_boton_aparece_despues():
    lua = runtime(subastas=[mia(10, 100_000)])
    original = lua.globals().AuctionHouseFrame
    lua.globals().AuctionHouseFrame = None
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().AuctionHouseFrame = original

    assert lua.eval("WowAlertsReposteoBoton") is None

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert lua.eval("WowAlertsReposteoBoton") is not None
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == AuctionHouseFrame")


def test_las_entradas_de_mas_de_48_horas_se_descartan():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 49 * 3600
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])

    assert cola(lua) == []
    assert pulsar(lua) is None


def test_el_boton_hace_lo_mismo_que_la_tecla():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)

    lua.eval("WowAlertsReposteoBoton.script_OnClick")()
    assert lua.globals().BUSCADAS == 1


def test_la_tecla_asignable_llama_a_siguiente():
    import xml.etree.ElementTree as ET

    arbol = ET.parse(CARPETA / "Bindings.xml")
    [binding] = arbol.getroot().findall("Binding")
    assert binding.get("name") == "WOWALERTS_SIGUIENTE"
    assert binding.text.strip() == "WowAlertsReposteo.Siguiente()"

    assert binding.get("header") == "WOWALERTS"

    lua = runtime()
    assert lua.globals().BINDING_NAME_WOWALERTS_SIGUIENTE
    assert lua.globals().BINDING_HEADER_WOWALERTS


def test_ninguna_pulsacion_llama_a_mas_de_una_funcion_protegida():
    """La regla que mantiene esto dentro de lo que el juego permite."""
    lua = runtime()

    def pulsar_contando(veces):
        for _ in range(veces):
            antes = len(llamadas(lua))
            pulsar(lua)
            assert len(llamadas(lua)) - antes <= 1

    adelantadas(lua, 10, 12)
    for i in (10, 12):
        pulsar_contando(2)
        lua.globals().DISPARAR("AUCTION_CANCELED", i)
    poner(lua, "SUBASTAS", [])
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)
    pulsar_contando(3)

    lua.globals().BUZON_ABIERTO = False
    en_la_bolsa(lua, 3, 4)
    lua.globals().NECESITA_CONFIRMAR = True
    en_la_casa(lua, [en_venta(999, 90_000)])
    abrir_casa(lua)
    pulsar_contando(1)
    responder_todo(lua)
    pulsar_contando(5)

    assert [c[0] for c in llamadas(lua)] == [
        "CancelAuction", "CancelAuction",
        "TakeInboxItem", "TakeInboxItem",
        "PostItem", "ConfirmPostItem", "PostItem", "ConfirmPostItem",
    ]


def test_si_el_aviso_ya_no_esta_abierto_no_se_intenta_cerrar():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # El jugador ha cerrado el aviso a mano.
    lua.globals().AVISO_VISIBLE = None
    # Se ordena la bolsa: en el hueco 3 queda otra cosa, y la confirmacion se
    # descarta.
    poner(
        lua,
        "BOLSA",
        {"0:3": {"itemID": 999, "hyperlink": "[Otra]ilvl311", "isLocked": False}},
    )
    assert pulsar(lua) is None
    assert a_python(lua.globals().OCULTADOS) == []


def test_mientras_se_cancela_el_panel_lo_dice():
    lua = runtime()
    adelantadas(lua, 10)
    assert pulsar(lua) == "cancelar"
    assert estado(lua) == "Cancelando..."


def test_si_el_boton_estaba_en_el_buzon_y_la_casa_carga_tarde_se_muda():
    lua = runtime()
    abrir_buzon(lua)
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == MailFrame")

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")

    original = lua.globals().AuctionHouseFrame
    lua.globals().AuctionHouseFrame = None
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().AuctionHouseFrame = original

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert lua.eval("WowAlertsReposteoBoton:GetParent() == AuctionHouseFrame")


def test_si_la_busqueda_no_confirmo_una_adelantada_el_panel_pide_repasar():
    lua = runtime()
    adelantadas(lua, 10)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().VENCER_TEMPORIZADORES()  # la respuesta no llega

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_el_recuento_de_cancelar_solo_cuenta_lo_que_se_puede_cancelar():
    lua = runtime()
    adelantadas(lua, 10, 12)
    lua.execute("C_AuctionHouse.CanCancelAuction = function(id) return id ~= 10 end")

    assert estado(lua) == "Cancelar (1)"


def test_en_el_buzon_no_mira_la_bolsa_por_cartas_ajenas():
    lua = runtime()
    lua.execute(
        """
        MIRADAS = 0
        local original = C_Container.GetContainerItemInfo
        C_Container.GetContainerItemInfo = function(bolsa, hueco)
            MIRADAS = MIRADAS + 1
            return original(bolsa, hueco)
        end
        """
    )
    poner(lua, "CORREO", [carta(), carta(), carta()])
    abrir_buzon(lua)

    assert pulsar(lua) is None
    assert lua.eval("MIRADAS") == 0


def test_la_version_del_toc_es_la_del_addon():
    """/wa dice la version del codigo; la lista de addons del juego, la del .toc."""
    import re

    toc = (CARPETA / "WowAlertsExport.toc").read_text(encoding="utf-8")
    lua = (CARPETA / "WowAlertsExport.lua").read_text(encoding="utf-8")

    en_toc = re.search(r"^## Version: (.+)$", toc, re.MULTILINE).group(1).strip()
    en_lua = re.search(r'^local ADDON_VERSION = "(.+)"$', lua, re.MULTILINE).group(1)
    assert en_toc == en_lua == "1.35"


# -- Lo que el juego confirma y lo que se repone por fuera --------------------


def test_postear_deja_la_entrada_hasta_que_el_juego_crea_la_subasta():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False

    assert pulsar(lua) == "postear"
    assert [e["estado"] for e in cola(lua)] == ["posteando"]
    assert estado(lua) == "Posteando..."

    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000)
    assert cola(lua) == []


def test_aceptar_en_el_aviso_de_blizzard_no_postea_otra_copia():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Aceptar en el aviso de Blizzard publica la copia del hueco 3.
    lua.execute('BOLSA["0:3"] = nil')
    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 5000)

    assert cola(lua) == []
    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)] == ["PostItem"]
    assert lua.globals().AVISO_VISIBLE is None


def test_un_posteo_sin_respuesta_vuelve_a_la_fila_en_la_visita_siguiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    lua.execute('BOLSA["0:3"].isLocked = false')  # el posteo no llego a hacerse
    lua.globals().CREAR_SUBASTA = True
    detectar(lua)

    assert pulsar(lua) == "postear"
    assert cola(lua) == []


def test_si_la_vendiste_o_la_enviaste_se_olvida_al_abrir_el_buzon():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "SUBASTAS", [])  # sin subasta nueva: en la casa no hay pista
    volver_a_la_casa(lua, [])
    assert len(cola(lua)) == 1

    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    assert len(cola(lua)) == 1  # primera vez que falta: aun no se olvida

    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().VENCER_TEMPORIZADORES()
    assert cola(lua) == []


def test_otra_copia_puesta_antes_de_cancelar_no_cuenta_como_repuesta():
    lua = runtime()
    poner(lua, "SUBASTAS", [mia(10, 100_000), mia(12, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    poner(lua, "SUBASTAS", [mia(12, 80_000)])
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert [e["auctionID"] for e in cola(lua)] == [10]
    assert pulsar(lua) == "postear"


def test_lo_devuelto_que_ya_no_esta_ni_en_el_buzon_ni_en_la_bolsa_se_olvida():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    assert len(cola(lua)) == 1

    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().VENCER_TEMPORIZADORES()
    assert cola(lua) == []


def test_no_olvida_lo_devuelto_si_la_carta_puede_no_haber_llegado():
    lua = runtime()
    devolver(lua, 10)
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_no_olvida_lo_devuelto_con_el_buzon_a_medio_cargar():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    lua.execute("GetInboxNumItems = function() return 0, 3 end")
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_no_olvida_lo_devuelto_justo_despues_de_recogerlo():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"

    # La carta ya no esta y el objeto aun no ha llegado a la bolsa.
    poner(lua, "CORREO", [])
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_una_carta_pedida_hace_rato_se_puede_volver_a_pedir():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"

    # La bolsa estaba llena y el buzon no ha cambiado.
    lua.globals().RELOJ = lua.globals().RELOJ + 5
    assert pulsar(lua) == "recoger"


def test_una_cancelacion_sin_respuesta_no_deja_el_panel_en_cancelando():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().RELOJ = lua.globals().RELOJ + 11

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_un_posteo_sin_respuesta_no_deja_el_panel_en_posteando():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)
    lua.globals().RELOJ = lua.globals().RELOJ + 11

    assert estado(lua) == "Cierra y abre la casa para repasar precios"


def test_la_cola_sobrevive_a_un_reload():
    lua = runtime()
    devolver(lua, 10)
    guardado = a_python(lua.globals().WowAlertsExportDB)

    otra = runtime()
    # WoW carga SavedVariables despues de ejecutar los ficheros del addon.
    poner(otra, "WowAlertsExportDB", guardado)
    en_la_bolsa(otra, 3)
    volver_a_la_casa(otra, [en_venta(999, 90_000)])

    assert pulsar(otra) == "postear"
    assert llamadas(otra)[-1][-1] == 90_000


def test_con_las_ventanas_cerradas_el_panel_no_recalcula():
    lua = runtime()
    devolver(lua, 10)
    abrir_buzon(lua)  # crea el boton
    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    lua.execute(
        """
        MIRADAS = 0
        local original = C_Container.GetContainerItemInfo
        C_Container.GetContainerItemInfo = function(...)
            MIRADAS = MIRADAS + 1
            return original(...)
        end
        """
    )
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")

    assert lua.globals().MIRADAS == 0


def test_la_segunda_copia_sigue_en_la_cola_tras_postear_la_primera():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000)])  # la que acaba de crear la tecla
    poner(lua, "BOLSA", {"0:4": {"itemID": GREBAS, "hyperlink": "[Grebas]ilvl311", "isLocked": False}})
    volver_a_la_casa(lua, [])

    assert [e["auctionID"] for e in cola(lua)] == [12]
    assert pulsar(lua) == "postear"


def test_poner_otra_copia_a_mano_no_saca_de_la_cola_lo_devuelto():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "SUBASTAS", [mia(50, 70_000)])  # stock nuevo puesto a mano
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [])

    assert [e["auctionID"] for e in cola(lua)] == [10]
    assert pulsar(lua) == "postear"


def test_un_posteo_creado_sin_aviso_sale_en_la_visita_siguiente():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000)])  # si se creo, a ese precio
    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []


def test_una_subasta_del_mismo_objeto_a_otro_precio_no_cierra_un_posteo():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 95_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert [(e["auctionID"], e["estado"]) for e in cola(lua)] == [(10, "devuelta")]


def test_no_olvida_lo_que_llega_a_la_bolsa_poco_despues():
    """Una carta recogida a mano o por otro addon tarda en llegar a la bolsa."""
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    en_la_bolsa(lua, 3)
    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().VENCER_TEMPORIZADORES()

    assert len(cola(lua)) == 1


def test_con_el_buzon_cerrado_no_olvida_nada():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().RELOJ = lua.globals().RELOJ + 4
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().VENCER_TEMPORIZADORES()

    assert len(cola(lua)) == 1


def test_una_subasta_creada_mucho_despues_no_cierra_un_posteo_viejo():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    pulsar(lua)

    lua.globals().RELOJ = lua.globals().RELOJ + 60
    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED", 7777)  # un posteo a mano de otra cosa

    assert len(cola(lua)) == 1


# -- Lo que no sobrevive a una visita, y lo que no se duplica -----------------


def test_una_marca_de_otra_visita_al_buzon_no_olvida_de_golpe():
    """La marca de que algo falta no se guarda: es de esta visita al buzon."""
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")  # marca que falta, en esta visita

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    lua.globals().RELOJ = lua.globals().RELOJ + 3600
    lua.globals().AHORA = lua.globals().AHORA + 3600
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_aceptar_sin_aviso_de_creada_no_postea_otra_copia():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True

    assert pulsar(lua) == "postear"

    # Se acepta desde el aviso de Blizzard, pero el aviso de creacion se pierde.
    lua.execute('BOLSA["0:3"] = nil')
    assert pulsar(lua) is None
    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)].count("PostItem") == 1

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000)])  # la que se creo al aceptar
    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []
    assert pulsar(lua) is None


def test_no_postea_otra_mientras_espera_a_que_se_cree_la_anterior():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False

    assert pulsar(lua) == "postear"
    assert pulsar(lua) is None
    assert [c[0] for c in llamadas(lua)].count("PostItem") == 1

    lua.globals().RELOJ = lua.globals().RELOJ + 11
    assert pulsar(lua) is None
    assert estado(lua) == "Cierra y abre la casa para repasar precios"
    assert [c[0] for c in llamadas(lua)].count("PostItem") == 1

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    lua.globals().CREAR_SUBASTA = True
    lua.execute('BOLSA["0:3"].isLocked = false')  # el primer posteo no se creo
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert sorted(e["auctionID"] for e in cola(lua)) == [10, 12]
    assert all(e["estado"] == "devuelta" for e in cola(lua))
    assert pulsar(lua) == "postear"


def test_un_posteo_creado_sin_aviso_y_ya_vendido_tambien_sale():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    poner(lua, "SUBASTAS", [mia(60, 90_000, status=1)])  # se creo y ya se vendio
    en_la_casa(lua, [])
    detectar(lua)

    assert cola(lua) == []


def test_el_buzon_programa_una_sola_revision():
    lua = runtime()
    devolver(lua, 10)
    lua.globals().AHORA = lua.globals().AHORA + 120
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    n = lua.eval("#TEMPORIZADORES")
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")
    lua.globals().DISPARAR("BAG_UPDATE_DELAYED")
    assert lua.eval("#TEMPORIZADORES") == n


def test_una_confirmacion_descartada_no_hace_olvidar_la_otra_copia():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    # Se ordena la bolsa: las grebas pasan a los huecos 5 y 6.
    en_la_bolsa(lua, 5, 6)
    assert pulsar(lua) is None  # se descarta la confirmacion
    lua.globals().NECESITA_CONFIRMAR = False
    lua.globals().RELOJ = lua.globals().RELOJ + 11

    # No se sabe si la primera llego a crearse: la otra copia espera.
    assert pulsar(lua) is None
    assert estado(lua) == "Cierra y abre la casa para repasar precios"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert sorted(e["auctionID"] for e in cola(lua)) == [10, 12]
    assert pulsar(lua) == "postear"


def test_cerrar_la_casa_con_una_confirmacion_pendiente_deja_que_decida_la_busqueda():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().NECESITA_CONFIRMAR = True
    assert pulsar(lua) == "postear"

    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    assert [e["estado"] for e in cola(lua)] == ["posteando"]

    lua.execute('BOLSA["0:3"].isLocked = false')  # no llego a crearse
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)
    assert [e["estado"] for e in cola(lua)] == ["devuelta"]


def test_mientras_espera_a_que_se_cree_un_posteo_el_panel_no_dice_postear():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"

    assert estado(lua) == "Posteando..."


def test_el_boton_deja_de_decir_posteando_al_pasar_la_espera():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().CREAR_SUBASTA = False
    assert pulsar(lua) == "postear"
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Posteando..."

    lua.globals().RELOJ = lua.globals().RELOJ + 11
    lua.globals().VENCER_TEMPORIZADORES()
    assert lua.eval("WowAlertsReposteoBoton:GetText()") == "Cierra y abre la casa para repasar precios"


# ---------------------------------------------------------------------------
#  El chat
# ---------------------------------------------------------------------------


def avisos(lua):
    """Lo que el reposteo ha escrito en el chat."""
    m = lua.globals().mensajes
    return [m[i] for i in range(1, len(m) + 1) if "Reposteo" in m[i]]


def test_mientras_hay_trabajo_no_escribe_nada_en_el_chat():
    lua = runtime()
    adelantadas(lua, 10, 12)
    pulsar(lua)
    pulsar(lua)

    assert avisos(lua) == []


def test_avisa_una_sola_vez_cuando_ya_no_queda_nada_que_cancelar():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    for _ in range(3):
        assert pulsar(lua) is None

    assert len(avisos(lua)) == 1
    assert "Recoge lo devuelto en el buzon" in avisos(lua)[0]


def test_no_avisa_mientras_espera_a_que_el_juego_cancele():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    pulsar(lua)
    pulsar(lua)

    assert avisos(lua) == []


def test_no_avisa_si_la_casa_esta_ocupada():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    lua.globals().SISTEMA_LISTO = False
    pulsar(lua)
    pulsar(lua)

    assert avisos(lua) == []


def test_no_avisa_mientras_busca():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    pulsar(lua)
    pulsar(lua)

    assert avisos(lua) == []


def test_avisa_si_no_hay_nada_que_repostear():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)
    pulsar(lua)
    pulsar(lua)

    assert len(avisos(lua)) == 1
    assert "Nada que repostear" in avisos(lua)[0]


def test_vuelve_a_avisar_en_otra_visita():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)
    pulsar(lua)
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    detectar(lua)
    pulsar(lua)

    assert len(avisos(lua)) == 2


def test_en_el_buzon_avisa_cuando_ya_no_queda_nada_que_recoger():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"
    assert avisos(lua) == []

    poner(lua, "CORREO", [])
    en_la_bolsa(lua, 3)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    pulsar(lua)
    pulsar(lua)

    assert len(avisos(lua)) == 1
    assert "Vuelve a la casa a postear" in avisos(lua)[0]


def test_en_el_buzon_no_avisa_mientras_llega_la_carta_pedida():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    assert pulsar(lua) == "recoger"
    pulsar(lua)

    assert avisos(lua) == []


# ---------------------------------------------------------------------------
#  El ciclo rapido: entrar, cancelar, buzon, repostear y cambiar de personaje
# ---------------------------------------------------------------------------


def test_si_la_casa_descarta_la_cancelacion_se_puede_volver_a_pulsar():
    """Visto en el juego: una cancelacion descartada dejaba la tecla 10 s parada."""
    lua = runtime()
    adelantadas(lua, 10, 12)
    assert pulsar(lua) == "cancelar"

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
    assert cola(lua)[0]["estado"] == "cancelar"
    assert pulsar(lua) == "cancelar"
    assert llamadas(lua) == [("CancelAuction", 10), ("CancelAuction", 10)]


def test_un_descarte_de_bastante_despues_no_toca_la_cancelacion():
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().RELOJ = lua.globals().RELOJ + 2

    lua.globals().DISPARAR("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
    assert cola(lua)[0]["estado"] == "cancelando"


def test_dos_listas_seguidas_iguales_bastan_para_fiarse():
    """Visto en el juego: la lista llega varias veces por segundo, siempre igual."""
    lua = runtime(subastas=[mia(10, 100_000)])
    contar_peticiones_de_lista(lua, responde=False)
    abrir_casa(lua, esperar=False)
    assert pulsar(lua) is None

    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert pulsar(lua) is None
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    assert pulsar(lua) == "buscar"


def test_si_la_lista_cambia_entre_dos_llegadas_no_se_fia_aun():
    lua = runtime(subastas=[mia(10, 100_000)])
    contar_peticiones_de_lista(lua, responde=False)
    abrir_casa(lua, esperar=False)
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    poner(lua, "SUBASTAS", [mia(10, 100_000), mia(12, 100_000)])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert pulsar(lua) is None


def test_dos_listas_vacias_no_bastan():
    lua = runtime(subastas=[])
    contar_peticiones_de_lista(lua, responde=False)
    abrir_casa(lua, esperar=False)
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert pulsar(lua) is None


def test_al_volver_enseguida_postea_sin_buscar_otra_vez():
    """El precio de hace un momento vale: se ahorra la busqueda y la espera."""
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    buscadas = lua.globals().BUSCADAS
    abrir_casa(lua, esperar=False)

    assert estado(lua) == "Postear"
    assert pulsar(lua) == "postear"
    assert llamadas(lua) == [("PostItem", 0, 3, 1, 1, 90_000)]
    assert lua.globals().BUSCADAS == buscadas


def test_con_el_precio_de_hace_minutos_si_vuelve_a_buscar():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    lua.globals().AHORA = lua.globals().AHORA + 121
    abrir_casa(lua)

    assert pulsar(lua) == "buscar"
    assert llamadas(lua) == []


def test_no_empieza_a_buscar_mientras_un_posteo_espera_respuesta():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    lua.globals().CREAR_SUBASTA = False
    abrir_casa(lua)
    assert pulsar(lua) == "postear"
    buscadas = lua.globals().BUSCADAS

    assert pulsar(lua) is None
    assert lua.globals().BUSCADAS == buscadas


def test_tras_postear_lo_reciente_la_siguiente_pulsacion_busca():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    assert pulsar(lua) == "postear"

    assert pulsar(lua) == "buscar"


def test_lo_devuelto_que_repusiste_a_mano_sale_de_la_cola():
    """Con el buzon de TSM el addon no ve el correo: lo nota en la casa, al ver
    una subasta nueva de ese objeto y ninguna copia en la bolsa."""
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "SUBASTAS", [mia(50, 95_000)])
    en_la_casa(lua, [])
    lua.globals().AHORA = lua.globals().AHORA + 600
    detectar(lua)

    assert cola(lua) == []
    assert estado(lua) == "Nada que repostear"


def test_si_la_copia_sigue_en_la_bolsa_no_se_olvida():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "SUBASTAS", [mia(50, 95_000)])
    en_la_casa(lua, [])
    en_la_bolsa(lua, 3)
    lua.globals().AHORA = lua.globals().AHORA + 600
    detectar(lua)

    assert [e["auctionID"] for e in cola(lua)] == [10]


def test_una_subasta_de_antes_de_cancelar_no_cuenta_como_repuesta():
    """Otra copia que ya estaba puesta no dice nada de la cancelada, que puede
    seguir en el buzon."""
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    cerrar_casa(lua)

    poner(lua, "SUBASTAS", [mia(20, 80_000)])
    lua.globals().AHORA = lua.globals().AHORA + 600
    detectar(lua)

    assert [e["auctionID"] for e in cola(lua)] == [10]


# ---------------------------------------------------------------------------
#  Todo con una tecla: la de interaccion, el buzon de TSM y recoger solo
# ---------------------------------------------------------------------------


def test_el_buzon_de_tsm_tambien_cuenta_como_buzon():
    """TSM oculta el buzon de Blizzard, pero el juego avisa igual al abrirlo."""
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    lua.globals().DISPARAR("MAIL_SHOW")  # MailFrame sigue oculto

    assert pulsar(lua) == "recoger"


def test_al_abrir_el_buzon_recoge_solo_las_cartas_de_lo_cancelado():
    lua = runtime()
    devolver(lua, 10, 12)
    poner(lua, "CORREO", [carta(), carta(asunto="Hola"), carta()])
    abrir_buzon(lua)
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]

    # La carta sale del buzon y el objeto llega a la bolsa.
    poner(lua, "CORREO", [carta(asunto="Hola"), carta()])
    en_la_bolsa(lua, 3)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1), ("TakeInboxItem", 2, 1)]

    poner(lua, "CORREO", [carta(asunto="Hola")])
    en_la_bolsa(lua, 3, 4)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().VENCER_TEMPORIZADORES()
    assert len(llamadas(lua)) == 2
    assert len(avisos(lua)) == 1
    assert "Vuelve a la casa a postear" in avisos(lua)[0]


def test_no_recoge_solo_mientras_el_juego_atiende_otra_carta():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    lua.globals().CORREO_PENDIENTE = True
    abrir_buzon(lua)
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == []

    lua.globals().CORREO_PENDIENTE = False
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]


def test_si_el_juego_da_un_error_en_el_buzon_deja_de_recoger_solo():
    """Con la bolsa llena, por ejemplo: no se insiste cada pocos segundos."""
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    lua.globals().VENCER_TEMPORIZADORES()
    lua.globals().DISPARAR("UI_ERROR_MESSAGE", 1, "Inventario lleno")

    lua.globals().RELOJ = lua.globals().RELOJ + 5
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]


def test_cerrar_el_buzon_para_la_recogida():
    lua = runtime()
    devolver(lua, 10)
    poner(lua, "CORREO", [carta()])
    abrir_buzon(lua)
    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    lua.globals().VENCER_TEMPORIZADORES()

    assert llamadas(lua) == []


def enlaces(lua):
    return a_python(lua.globals().ENLACES)


def test_con_la_casa_abierta_la_tecla_de_interaccion_hace_el_reposteo():
    lua = runtime()
    abrir_casa(lua)
    assert enlaces(lua) == {"º": "WOWALERTS_SIGUIENTE"}

    cerrar_casa(lua)
    assert enlaces(lua) == []


def test_con_el_buzon_abierto_tambien():
    lua = runtime()
    abrir_buzon(lua)
    assert enlaces(lua) == {"º": "WOWALERTS_SIGUIENTE"}

    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")
    assert enlaces(lua) == []


def test_sin_tecla_de_interaccion_no_toma_ninguna():
    lua = runtime()
    lua.execute("TECLAS = {}")
    abrir_casa(lua)

    assert enlaces(lua) == []


def test_en_combate_no_toca_las_teclas_y_las_suelta_al_salir():
    lua = runtime()
    abrir_casa(lua)
    lua.globals().EN_COMBATE = True
    cerrar_casa(lua)
    assert enlaces(lua) == {"º": "WOWALERTS_SIGUIENTE"}

    lua.globals().EN_COMBATE = False
    lua.globals().DISPARAR("PLAYER_REGEN_ENABLED")
    assert enlaces(lua) == []


# ---------------------------------------------------------------------------
#  Avisar al terminar, sin pulsar mas
# ---------------------------------------------------------------------------


def pantalla(lua):
    return a_python(lua.globals().PANTALLA)


def test_avisa_en_cuanto_el_juego_confirma_la_ultima_cancelacion():
    lua = runtime()
    adelantadas(lua, 10, 12)
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert avisos(lua) == []

    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 12)
    assert len(avisos(lua)) == 1
    assert "Todas canceladas (2)" in avisos(lua)[0]
    assert "Recoge lo devuelto en el buzon" in avisos(lua)[0]


def test_el_aviso_no_suena_ni_sale_en_el_centro_de_la_pantalla():
    """El boton del addon ya dice como esta la cosa: el aviso grande estorbaba."""
    lua = runtime()
    adelantadas(lua, 10)
    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)

    assert pantalla(lua) == []
    assert a_python(lua.globals().SONIDOS) == []


def test_no_avisa_de_cancelado_todo_mientras_sigue_buscando():
    lua = runtime(subastas=[mia(10, 100_000), mia(20, 50_000, ilvl=298)])
    poner(lua, "RESULTADOS", {
        f"{GREBAS}:311:0": [en_venta(900, 90_000)],
        f"{GREBAS}:298:0": [en_venta(901, 40_000)],
    })
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    lua.globals().RESPONDER()
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert avisos(lua) == []

    lua.globals().RESPONDER()
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 20)
    assert len(avisos(lua)) == 1
    assert "Todas canceladas (2)" in avisos(lua)[0]


def test_si_la_busqueda_acaba_sin_nada_adelantado_lo_dice_sin_pulsar():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert len(avisos(lua)) == 1
    assert "Nada que repostear" in avisos(lua)[0]


def test_avisa_en_cuanto_se_crea_el_ultimo_posteo():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    envejecer_precios(lua)
    volver_a_la_casa(lua, [en_venta(999, 90_000)])
    assert pulsar(lua) == "postear"
    assert avisos(lua) == []
    assert pulsar(lua) == "postear"

    assert len(avisos(lua)) == 1
    assert "Nada que repostear" in avisos(lua)[0]


# ---------------------------------------------------------------------------
#  Lo recien posteado y el orden del buzon
# ---------------------------------------------------------------------------


def test_lo_que_acabas_de_postear_no_se_vuelve_a_buscar():
    """Visto en el juego: tras postear, la busqueda miraba otra vez lo recien
    puesto, que va el primero a precio de rival."""
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    assert pulsar(lua) == "postear"  # el juego la crea como 5001
    buscadas = lua.globals().BUSCADAS

    poner(lua, "SUBASTAS", [mia(5001, 90_000)])
    assert pulsar(lua) == "buscar"
    assert lua.globals().BUSCADAS == buscadas
    assert len(avisos(lua)) == 1
    assert "Nada que repostear" in avisos(lua)[0]


def test_tras_recoger_una_carta_espera_a_que_el_buzon_cambie():
    """Visto en el juego: pedir la siguiente antes de que el buzon se reordene
    daba "No se ha encontrado el objeto" y paraba la recogida."""
    lua = runtime()
    devolver(lua, 10, 12)
    poner(lua, "CORREO", [carta(), carta()])
    abrir_buzon(lua)
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]

    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")  # aun con las dos cartas
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]

    poner(lua, "CORREO", [carta()])
    en_la_bolsa(lua, 3)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1), ("TakeInboxItem", 1, 1)]


# ---------------------------------------------------------------------------
#  La lista para la ventana
# ---------------------------------------------------------------------------


def subastas(lua):
    return a_python(lua.globals().WowAlertsReposteo.Subastas())


def test_la_lista_marca_lo_adelantado_y_lo_que_va_primero():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)

    filas = subastas(lua)
    assert [(f["auctionID"], f["grupo"]) for f in filas] == [
        (10, "adelantada"),
        (12, "primera"),
    ]
    adelantada = filas[0]
    assert adelantada["precio"] == 100_000
    assert adelantada["precioRival"] == 90_000
    assert adelantada["igualada"] is False
    assert adelantada["itemID"] == GREBAS
    assert adelantada["ilvl"] == 311


def test_la_lista_avisa_de_que_te_igualan():
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [en_venta(11, 100_000)])
    detectar(lua)

    (fila,) = subastas(lua)
    assert fila["grupo"] == "adelantada"
    assert fila["igualada"] is True


def test_antes_de_buscar_todo_esta_sin_mirar():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)

    (fila,) = subastas(lua)
    assert fila["grupo"] == "sinmirar"


def test_lo_que_no_esta_vigilado_sale_al_final_y_sin_estado():
    lua = runtime(subastas=[mia(10, 100_000, item_id=999), mia(12, 80_000)])
    en_la_casa(lua, [])
    detectar(lua)

    filas = subastas(lua)
    assert [(f["auctionID"], f["grupo"]) for f in filas] == [
        (12, "primera"),
        (10, "novigilada"),
    ]
    assert filas[1].get("precioRival") is None


def test_las_vendidas_no_salen_en_la_lista():
    lua = runtime(subastas=[mia(10, 100_000, status=1), mia(12, 80_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert [f["auctionID"] for f in subastas(lua)] == [12]


def test_el_orden_dentro_del_mismo_grupo_es_por_precio_y_luego_por_id():
    lua = runtime(subastas=[mia(10, 120_000), mia(11, 100_000), mia(20, 100_000)])
    en_la_casa(lua, [en_venta(999, 90_000)])
    detectar(lua)

    filas = subastas(lua)
    assert [(f["auctionID"], f["grupo"]) for f in filas] == [
        (11, "adelantada"),
        (20, "adelantada"),
        (10, "adelantada"),
    ]


def test_una_entrada_devuelta_con_el_id_viejo_no_saca_fila():
    lua = runtime()
    devolver(lua, 10)
    assert [(e["auctionID"], e["estado"]) for e in cola(lua)] == [(10, "devuelta")]

    poner(lua, "SUBASTAS", [mia(12, 80_000)])
    en_la_casa(lua, [])
    detectar(lua)

    filas = subastas(lua)
    assert [f["auctionID"] for f in filas] == [12]
    assert filas[0]["grupo"] == "primera"


def test_la_lista_cambia_al_cancelar_y_al_postear():
    lua = runtime()
    adelantadas(lua, 10)
    assert [f["grupo"] for f in subastas(lua)] == ["adelantada"]

    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    poner(lua, "SUBASTAS", [])
    assert subastas(lua) == []

    en_la_bolsa(lua, 3)
    assert pulsar(lua) == "postear"
    # El doble crea la subasta con 5000 + el numero de llamadas protegidas.
    nueva = 5000 + len(llamadas(lua))
    poner(lua, "SUBASTAS", [mia(nueva, 90_000)])
    assert [(f["auctionID"], f["grupo"]) for f in subastas(lua)] == [(nueva, "reposteada")]


def test_lo_recien_repuesto_sale_aunque_la_lista_del_juego_no_lo_traiga():
    """La lista de tus subastas tarda en traer la nueva, y machacando la tecla
    quieres ver ya que esa esta hecha."""
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    assert pulsar(lua) == "postear"

    nueva = 5000 + len(llamadas(lua))
    (fila,) = subastas(lua)   # SUBASTAS sigue vacia
    assert (fila["auctionID"], fila["grupo"]) == (nueva, "reposteada")
    assert fila["itemID"] == GREBAS
    assert fila["ilvl"] == 311


def test_la_fila_de_lo_recien_repuesto_no_se_queda_colgada():
    """Si se vende, sale de la lista del juego sin avisar: pasado un rato esa
    fila inventada desaparece en vez de mentir."""
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    pulsar(lua)
    assert len(subastas(lua)) == 1

    lua.globals().RELOJ = lua.globals().RELOJ + 31
    assert subastas(lua) == []


def test_lo_repuesto_deja_de_serlo_al_volver_a_abrir_la_casa():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    pulsar(lua)
    nueva = 5000 + len(llamadas(lua))
    poner(lua, "SUBASTAS", [mia(nueva, 90_000)])
    assert [f["grupo"] for f in subastas(lua)] == ["reposteada"]

    # En la visita siguiente ya es una mas: sigue sabiendose que va la primera
    # (eso dura cinco minutos), pero el grupo de "recien repuestas" es de la
    # visita en la que la pusiste.
    cerrar_casa(lua)
    abrir_casa(lua)
    assert [f["grupo"] for f in subastas(lua)] == ["primera"]


def test_la_lista_dice_lo_que_le_queda_a_cada_subasta():
    lua = runtime(subastas=[mia(10, 100_000, segundos=41_520, banda=3)])
    abrir_casa(lua)

    (fila,) = subastas(lua)
    assert fila["segundos"] == 41_520
    assert fila["banda"] == 3


# -- La barra de progreso ----------------------------------------------------


def progreso(lua):
    return a_python(lua.globals().WowAlertsReposteo.Progreso())


def test_la_barra_dice_por_donde_va_el_escaneo():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000, ilvl=298)])
    en_la_casa(lua, [])
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"

    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("escaneo", 0, 2)
    assert p["itemID"] == GREBAS   # la que esta mirando ahora

    lua.globals().RESPONDER()
    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("escaneo", 1, 2)


def test_al_acabar_el_escaneo_la_barra_se_queda_llena():
    """Sin nada pendiente no desaparece de golpe: dice que se miro todo."""
    lua = runtime(subastas=[mia(10, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("escaneo", 1, 1)


def test_la_barra_cuenta_las_cancelaciones():
    lua = runtime()
    adelantadas(lua, 10, 12)
    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("cancelar", 0, 2)

    pulsar(lua)
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("cancelar", 1, 2)


def test_la_barra_cuenta_lo_que_llevas_repuesto():
    lua = runtime()
    devolver(lua, 10, 12)
    en_la_bolsa(lua, 3, 4)
    abrir_casa(lua)
    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("postear", 0, 2)

    assert pulsar(lua) == "postear"
    p = progreso(lua)
    assert (p["fase"], p["hechos"], p["total"]) == ("postear", 1, 2)


def test_sin_la_casa_abierta_no_hay_barra():
    lua = runtime(subastas=[mia(10, 100_000)])
    assert progreso(lua) is None


# -- El boton de cancelar de cada fila ---------------------------------------


def cancelar(lua, auction_id):
    return lua.globals().WowAlertsReposteo.Cancelar(auction_id)


def test_el_boton_de_la_fila_cancela_esa_subasta():
    """Un clic es un evento de raton de verdad: vale igual que la tecla."""
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000)])
    abrir_casa(lua)

    assert cancelar(lua, 12) is None
    assert llamadas(lua) == [("CancelAuction", 12)]


def test_cancelar_desde_la_ventana_deja_la_subasta_lista_para_reponerla():
    """Aunque nadie te haya adelantado: entra en la cola para recogerla del
    buzon y volver a ponerla, como lo que cancela la tecla."""
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    cancelar(lua, 10)
    assert [(e["auctionID"], e["estado"]) for e in cola(lua)] == [(10, "cancelando")]

    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    entrada = cola(lua)[0]
    assert entrada["estado"] == "devuelta"
    assert entrada["precioAnterior"] == 100_000
    assert entrada["itemID"] == GREBAS
    assert entrada["ilvl"] == 311


def test_cancelar_desde_la_ventana_no_encola_lo_que_no_se_repostea():
    """De lo que no esta vigilado el addon no sabe el precio ni la duracion:
    se cancela y ya, sin prometer que lo va a reponer."""
    lua = runtime(subastas=[mia(10, 100_000, item_id=999)])
    abrir_casa(lua)

    assert cancelar(lua, 10) is None
    assert llamadas(lua) == [("CancelAuction", 10)]
    assert cola(lua) == []


def test_cancelar_desde_la_ventana_espera_a_la_cancelacion_anterior():
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 80_000)])
    abrir_casa(lua)
    cancelar(lua, 10)

    assert cancelar(lua, 12) is not None
    assert llamadas(lua) == [("CancelAuction", 10)]


def test_cancelar_desde_la_ventana_respeta_lo_que_el_juego_no_deja():
    lua = runtime(subastas=[mia(10, 100_000)])
    abrir_casa(lua)
    lua.execute("C_AuctionHouse.CanCancelAuction = function(id) return id ~= 10 end")

    assert cancelar(lua, 10) is not None
    assert llamadas(lua) == []


def test_cancelar_desde_la_ventana_con_la_casa_cerrada_no_hace_nada():
    lua = runtime(subastas=[mia(10, 100_000)])

    assert cancelar(lua, 10) is not None
    assert llamadas(lua) == []


def test_una_segunda_x_en_la_fila_ya_cancelada_no_bloquea_las_demas():
    """Visto en el juego: la fila sigue en pantalla un momento despues de
    cancelarse. Pedir otra vez la cancelacion de una subasta que ya no existe
    no recibe respuesta, dejaba todas las X bloqueadas 10 s y sacaba el objeto
    del reposteo."""
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 120_000)])
    abrir_casa(lua)
    assert cancelar(lua, 10) is None
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)

    assert cancelar(lua, 10) is not None            # ya esta cancelada
    assert [(e["auctionID"], e["estado"]) for e in cola(lua)] == [(10, "devuelta")]
    assert cancelar(lua, 12) is None                # la siguiente X funciona
    assert llamadas(lua) == [("CancelAuction", 10), ("CancelAuction", 12)]


def test_pulsar_una_x_no_mueve_las_filas_mientras_responde_el_juego():
    """La fila pulsada saltaba a ADELANTADAS hasta que el juego respondia, y
    volvia despues: aparecia un titulo de grupo, todo lo de debajo bajaba y
    subia bajo el raton, y los clics rapidos caian fuera de las X."""
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 120_000), mia(14, 130_000)])
    en_la_casa(lua, [])
    detectar(lua)
    antes = [(f["auctionID"], f["grupo"]) for f in subastas(lua)]

    cancelar(lua, 10)
    assert [(f["auctionID"], f["grupo"]) for f in subastas(lua)] == antes


def test_la_fila_dice_si_ya_se_ha_pedido_cancelarla():
    """Para apagar su X: la fila sigue en pantalla hasta que llega la lista."""
    lua = runtime(subastas=[mia(10, 100_000), mia(12, 120_000)])
    abrir_casa(lua)
    assert [f.get("cancelada") for f in subastas(lua)] == [None, None]

    cancelar(lua, 10)
    assert {f["auctionID"]: f.get("cancelada") for f in subastas(lua)} == {10: True, 12: None}
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    assert {f["auctionID"]: f.get("cancelada") for f in subastas(lua)} == {10: True, 12: None}


def test_una_adelantada_sigue_adelantada_al_pulsar_su_x():
    lua = runtime()
    adelantadas(lua, 10)
    cancelar(lua, 10)

    (fila,) = subastas(lua)
    assert (fila["grupo"], fila["precioRival"]) == ("adelantada", 90_000)


def test_cancelar_lo_recien_repuesto_lo_saca_de_su_grupo():
    lua = runtime()
    devolver(lua, 10)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    pulsar(lua)
    nueva = 5000 + len(llamadas(lua))
    poner(lua, "SUBASTAS", [mia(nueva, 90_000)])
    assert [f["grupo"] for f in subastas(lua)] == ["reposteada"]

    cancelar(lua, nueva)
    lua.globals().DISPARAR("AUCTION_CANCELED", nueva)
    poner(lua, "SUBASTAS", [])
    assert subastas(lua) == []


def test_la_ventana_se_redibuja_con_el_boton():
    lua = runtime(subastas=[mia(10, 100_000)])
    lua.execute("REDIBUJOS = 0; WowAlertsVentana = { Refrescar = function() REDIBUJOS = REDIBUJOS + 1 end }")
    abrir_casa(lua)
    antes = lua.globals().REDIBUJOS

    lua.globals().WowAlertsReposteo.refrescarPanel()
    assert lua.globals().REDIBUJOS == antes + 1


# -- El boton de las que caducan pronto --------------------------------------


def caducadas(lua):
    return [f["auctionID"] for f in a_python(lua.globals().WowAlertsReposteo.Caducadas())]


def test_las_que_caducan_salen_de_la_mas_urgente_a_la_menos():
    lua = runtime(subastas=[
        mia(10, 100_000, segundos=7 * 3600),
        mia(12, 120_000, segundos=40 * 3600),
        mia(14, 130_000, segundos=3600),
    ])
    abrir_casa(lua)

    assert caducadas(lua) == [14, 10]


def test_las_ocho_horas_justas_aun_no_caducan():
    lua = runtime(subastas=[mia(10, 100_000, segundos=8 * 3600)])
    abrir_casa(lua)

    assert caducadas(lua) == []


def test_no_cuenta_lo_que_el_addon_no_sabe_reponer():
    """Sin vigilar no hay precio con el que volver a ponerla, y a solo puja no
    hay precio de compra del que partir: el boton no las toca."""
    lua = runtime(subastas=[
        mia(10, 100_000, item_id=999, segundos=3600),
        mia(12, 0, segundos=3600),
        mia(14, 130_000, segundos=3600),
    ])
    abrir_casa(lua)

    assert caducadas(lua) == [14]


def test_la_ya_cancelada_deja_de_contar():
    """El numero del boton baja con el clic, sin esperar a la lista nueva."""
    lua = runtime(subastas=[mia(10, 100_000, segundos=3600), mia(12, 120_000, segundos=7200)])
    abrir_casa(lua)
    assert caducadas(lua) == [10, 12]

    cancelar(lua, 10)
    assert caducadas(lua) == [12]


def test_no_cuenta_lo_que_el_juego_no_deja_cancelar():
    """Una con puja no se puede cancelar: contarla dejaria el boton atascado
    siempre en la misma."""
    lua = runtime(subastas=[mia(10, 100_000, segundos=3600), mia(12, 120_000, segundos=3600)])
    abrir_casa(lua)
    lua.execute("C_AuctionHouse.CanCancelAuction = function(id) return id ~= 10 end")

    assert caducadas(lua) == [12]


def test_sin_los_segundos_solo_cuentan_las_bandas_que_no_dejan_duda():
    """Corto (<30 min) y medio (30 min - 2 h) estan por debajo de las 8 h
    seguro. Largo va de 2 a 12 h, y cancelar cuesta el deposito."""
    lua = runtime(subastas=[
        mia(10, 100_000, banda=0),
        mia(12, 120_000, banda=1),
        mia(14, 130_000, banda=2),
        mia(16, 140_000, banda=3),
    ])
    abrir_casa(lua)

    assert sorted(caducadas(lua)) == [10, 12]


# ---------------------------------------------------------------------------
#  Lo caducado
# ---------------------------------------------------------------------------

CADUCADA = "Auction expired: Greaves of the Noxious Depths"


def caducar(lua, precio=100_000):
    """Tu subasta de Grebas a `precio`, vista en la casa, que despues caduca:
    ya no esta entre tus subastas y su carta espera en el buzon."""
    poner(lua, "SUBASTAS", [mia(10, precio)])
    en_la_casa(lua, [])
    detectar(lua)
    cerrar_casa(lua)
    poner(lua, "SUBASTAS", [])
    poner(lua, "LLAMADAS", [])
    poner(lua, "CORREO", [carta(asunto=CADUCADA)])


def test_la_carta_de_lo_caducado_lo_mete_en_la_cola_y_se_recoge_sola():
    lua = runtime()
    caducar(lua)
    abrir_buzon(lua)

    (e,) = cola(lua)
    assert (e["estado"], e["caducada"], e["precioAnterior"]) == ("devuelta", True, 100_000)
    lua.globals().VENCER_TEMPORIZADORES()
    assert llamadas(lua) == [("TakeInboxItem", 1, 1)]


@pytest.mark.parametrize(
    "rivales, precio",
    [
        ([], 100_000),                          # nadie mas: el que tenia
        ([en_venta(999, 90_000)], 90_000),      # mas barato ahora: baja
        ([en_venta(999, 120_000)], 120_000),    # mas caro ahora: sube
    ],
)
def test_lo_caducado_se_repone_al_precio_de_ahora_o_al_que_tenia(rivales, precio):
    """A diferencia de lo cancelado, que nunca sube: nadie adelanto a esta, no
    se vendio, y lo que marca el mercado es el mas barato de ahora."""
    lua = runtime()
    caducar(lua)
    abrir_buzon(lua)
    # Recogida: la carta sale del buzon y la copia llega a la bolsa.
    poner(lua, "CORREO", [])
    en_la_bolsa(lua, 3)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().BUZON_ABIERTO = False
    lua.globals().DISPARAR("MAIL_CLOSED")

    en_la_casa(lua, rivales)
    abrir_casa(lua)
    assert pulsar(lua) == "buscar"
    responder_todo(lua)
    assert pulsar(lua) == "postear"
    assert llamadas(lua)[-1] == ("PostItem", 0, 3, 1, 1, precio)


def test_la_misma_carta_de_caducada_no_crea_dos_entradas():
    lua = runtime()
    caducar(lua)
    abrir_buzon(lua)
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")
    lua.globals().DISPARAR("MAIL_INBOX_UPDATE")

    assert len(cola(lua)) == 1


def test_una_copia_que_ya_tenias_en_la_bolsa_no_cuenta_como_caducada():
    lua = runtime()
    caducar(lua)
    en_la_bolsa(lua, 3)
    abrir_buzon(lua)

    assert len(cola(lua)) == 1


def test_dos_cartas_de_caducada_del_mismo_objeto_son_dos_entradas():
    lua = runtime()
    caducar(lua)
    poner(lua, "CORREO", [carta(asunto=CADUCADA), carta(asunto=CADUCADA)])
    abrir_buzon(lua)

    ids = [e["auctionID"] for e in cola(lua)]
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_la_carta_de_caducada_junto_a_una_cancelada_suma_una_entrada_mas():
    lua = runtime()
    devolver(lua, 10)                       # una cancelada, con su entrada
    poner(lua, "CORREO", [carta(), carta(asunto=CADUCADA)])
    abrir_buzon(lua)

    assert sorted(bool(e.get("caducada")) for e in cola(lua)) == [False, True]


def test_la_carta_de_caducada_de_algo_sin_precio_conocido_no_se_toca():
    """Sin el precio que tenia no se puede cumplir la regla cuando nadie mas lo
    vende: esa carta se deja para recogerla a mano."""
    lua = runtime()
    poner(lua, "CORREO", [carta(asunto=CADUCADA)])
    abrir_buzon(lua)
    lua.globals().VENCER_TEMPORIZADORES()

    assert cola(lua) == []
    assert llamadas(lua) == []


def test_la_carta_de_caducada_de_algo_no_vigilado_no_se_toca():
    lua = runtime()
    caducar(lua)
    poner(lua, "CORREO", [carta(item_id=999, asunto="Auction expired: Otra cosa")])
    abrir_buzon(lua)
    lua.globals().VENCER_TEMPORIZADORES()

    assert cola(lua) == []
    assert llamadas(lua) == []


def precio_apuntado(lua, clave=f"{GREBAS}:311"):
    return a_python(lua.eval(
        f'((WowAlertsExportDB.preciosPuestos or {{}})["Sanguino-Pepe"] or {{}})["{clave}"]'
    ))


def test_de_varias_copias_puestas_se_apunta_la_mas_barata():
    lua = runtime(subastas=[mia(10, 120_000), mia(12, 100_000)])
    en_la_casa(lua, [])
    detectar(lua)

    assert precio_apuntado(lua)["precio"] == 100_000


def test_lo_que_pones_a_mano_o_con_tsm_tambien_apunta_su_precio():
    """Visto en el juego: lo puesto a mano despues de la busqueda no se
    apuntaba, y la busqueda de la visita siguiente llega tarde, cuando ya ha
    caducado. Se apunta con cada lista que llega, sin buscar."""
    lua = runtime()
    abrir_casa(lua)
    poner(lua, "SUBASTAS", [mia(10, 100_000)])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert precio_apuntado(lua)["precio"] == 100_000


def test_con_la_casa_cerrada_no_apunta_precios():
    lua = runtime()
    poner(lua, "SUBASTAS", [mia(10, 100_000)])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert precio_apuntado(lua) is None


def test_lo_que_pones_con_la_tecla_apunta_su_precio_para_cuando_caduque():
    lua = runtime()
    devolver(lua, 10, precio=100_000, rival=90_000)
    en_la_bolsa(lua, 3)
    abrir_casa(lua)
    assert pulsar(lua) == "postear"

    assert precio_apuntado(lua)["precio"] == 90_000


# -- Lo que falta por postear a 308 --------------------------------------------

COIF = 271441
PATRON = 258126


def con_faltan(subastas=None):
    """Un runtime con tres vigilados: dos de equipo y un patron.

    GetItemInfoInstant devuelve la clase del objeto en el sexto valor: 4 es
    armadura y 9 receta. Los demas tests no lo tienen, y entonces no falta nada.
    """
    lua = runtime(subastas=subastas)
    lua.execute(f"""
        WowAlertsVigilados.objetos[{COIF}] = "Crushing Coiler Coif"
        WowAlertsVigilados.objetos[{PATRON}] = "Pattern: Arcanoweave Cord"
        C_Item.GetItemInfoInstant = function(id)
            if id == {PATRON} then return id, "", "", "INVTYPE_NON_EQUIP_IGNORE", 1, 9 end
            return id, "", "", "INVTYPE_HEAD", 2, 4
        end
        -- La busqueda por nombre: una fila por ilvl con su minimo.
        NAVEGACION = {{}}
        C_AuctionHouse.SendBrowseQuery = function(consulta)
            BUSCADAS = BUSCADAS + 1
            BUSQUEDAS[#BUSQUEDAS + 1] = consulta
        end
        C_AuctionHouse.GetBrowseResults = function() return NAVEGACION end
    """)
    return lua


def responder_faltan(lua):
    """Responde a todo, sea busqueda de un objeto o por nombre. Devuelve lo pedido."""
    g = lua.globals()
    pedidas = []
    while len(g.BUSQUEDAS) > 0:
        consulta = g.BUSQUEDAS[1]
        if consulta.searchString:
            pedidas.append(consulta.searchString)
            g.table.remove(g.BUSQUEDAS, 1)
            g.DISPARAR("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED")
        else:
            pedidas.append((consulta.itemID, consulta.itemLevel))
            g.RESPONDER()
    return pedidas


def en_la_navegacion(lua, filas):
    """{(itemID, ilvl): minimo} como lo devuelve GetBrowseResults."""
    poner(lua, "NAVEGACION", [
        {"itemKey": {"itemID": i, "itemLevel": n}, "minPrice": precio}
        for (i, n), precio in filas.items()
    ])


def faltan(lua):
    return a_python(lua.globals().WowAlertsReposteo.Faltan())


def test_faltan_los_de_equipo_sin_ninguno_puesto_a_308():
    """Las grebas puestas a 311 no tapan las de 308; el patron no cuenta."""
    lua = con_faltan(subastas=[mia(10, 100_000, item_id=COIF, ilvl=308), mia(11, 100_000)])

    assert [f["itemID"] for f in faltan(lua)] == [GREBAS]


def test_al_escanear_busca_lo_que_falta_a_308_y_apunta_el_mas_barato():
    lua = con_faltan(subastas=[mia(10, 100_000, item_id=COIF, ilvl=308)])
    poner(lua, "RESULTADOS", {
        f"{GREBAS}:308:0": [en_venta(1, 30_000), en_venta(2, 25_000), en_venta(3, 20_000, dueno="Mbarval")],
    })
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()
    buscadas = responder_faltan(lua)

    assert (GREBAS, 308) in buscadas
    # El de 20.000 es de otro personaje tuyo: no es el precio al que esta.
    assert faltan(lua)[0]["precio"] == 25_000


def test_si_nadie_lo_vende_el_precio_es_false():
    lua = con_faltan()
    poner(lua, "RESULTADOS", {})
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()
    responder_faltan(lua)

    assert {f["itemID"]: f["precio"] for f in faltan(lua)} == {GREBAS: False, COIF: False}


def test_sin_buscar_todavia_no_hay_precio():
    lua = con_faltan()

    assert all("precio" not in f for f in faltan(lua))


def pisa_de_las_grebas(lua, a_308, ilvls):
    """Con las grebas a 308 a `a_308` y los ilvl de arriba a `ilvls`, el aviso."""
    poner(lua, "RESULTADOS", {f"{GREBAS}:308:0": [en_venta(1, a_308)]})
    en_la_navegacion(lua, {(GREBAS, n): p for n, p in ilvls.items()})
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()
    pedidas = responder_faltan(lua)
    assert "Greaves of the Noxious Depths" in pedidas
    grebas = next(f for f in faltan(lua) if f["itemID"] == GREBAS)
    return grebas.get("pisa")


def test_un_ilvl_superior_mas_barato_pisa():
    pisa = pisa_de_las_grebas(con_faltan(), 250_000, {311: 240_000, 318: 300_000})

    assert pisa == {"ilvl": 311, "precio": 240_000}


def test_un_ilvl_superior_hasta_10k_mas_caro_tambien_pisa():
    oro = 10_000  # cobre por oro
    pisa = pisa_de_las_grebas(con_faltan(), 25_000 * oro, {318: 35_000 * oro})

    assert pisa == {"ilvl": 318, "precio": 35_000 * oro}


def test_mas_de_10k_por_encima_no_pisa():
    oro = 10_000
    assert pisa_de_las_grebas(con_faltan(), 25_000 * oro, {318: 35_001 * oro}) is None


def test_de_los_superiores_cuenta_el_mas_barato():
    pisa = pisa_de_las_grebas(con_faltan(), 300_000, {311: 290_000, 318: 280_000, 305: 1})

    assert pisa == {"ilvl": 318, "precio": 280_000}


def test_si_nadie_vende_el_308_no_hay_con_que_comparar():
    lua = con_faltan()
    en_la_navegacion(lua, {(GREBAS, 311): 1})
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()
    responder_faltan(lua)

    assert all("pisa" not in f for f in faltan(lua))


def test_la_navegacion_de_otro_objeto_no_cuenta():
    """El nombre puede casar con otros objetos: solo cuentan las filas suyas."""
    lua = con_faltan(subastas=[mia(10, 100_000, item_id=COIF, ilvl=308)])
    poner(lua, "RESULTADOS", {f"{GREBAS}:308:0": [en_venta(1, 300_000)]})
    en_la_navegacion(lua, {(COIF, 311): 1})
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()
    responder_faltan(lua)

    assert faltan(lua)[0].get("pisa") is None


def test_la_busqueda_por_nombre_va_en_el_idioma_del_juego():
    """En un cliente en espanol, el nombre de config.yaml no casa con nada."""
    lua = con_faltan(subastas=[mia(10, 100_000, item_id=COIF, ilvl=308)])
    lua.execute(f"""
        C_Item.GetItemInfo = function(id)
            if id == {GREBAS} then return "Grebas de las profundidades nocivas" end
        end
    """)
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()

    assert "Grebas de las profundidades nocivas" in responder_faltan(lua)


def test_lo_que_falta_se_busca_una_vez_y_no_en_cada_visita():
    """Volver a abrir la casa no repite las busquedas; pasada la hora, si."""
    lua = con_faltan(subastas=[mia(10, 100_000, item_id=COIF, ilvl=308)])
    poner(lua, "RESULTADOS", {f"{GREBAS}:308:0": [en_venta(1, 25_000)]})
    g = lua.globals()

    abrir_casa(lua)
    g.WowAlertsReposteo.Siguiente()
    assert responder_faltan(lua)  # la primera vez si busca
    g.CASA_ABIERTA = False
    g.DISPARAR("AUCTION_HOUSE_CLOSED")

    abrir_casa(lua)
    g.WowAlertsReposteo.Siguiente()
    assert responder_faltan(lua) == []
    assert faltan(lua)[0]["precio"] == 25_000
    g.CASA_ABIERTA = False
    g.DISPARAR("AUCTION_HOUSE_CLOSED")

    g.AHORA = g.AHORA + 3601
    abrir_casa(lua)
    g.WowAlertsReposteo.Siguiente()
    assert (GREBAS, 308) in responder_faltan(lua)


def test_con_un_personaje_que_no_trackeas_no_falta_nada_ni_se_busca():
    """Solo los de personajes.yaml: los demas de la cuenta no necesitan el 308."""
    lua = con_faltan()
    lua.globals().PERSONAJE = "Otro"
    abrir_casa(lua)
    lua.globals().WowAlertsReposteo.Siguiente()

    assert faltan(lua) == []
    assert responder_faltan(lua) == []


def test_lo_cancelado_para_repostear_no_sale_como_que_falta():
    """Al cancelarla desaparece de tus subastas, pero va a volver: no falta."""
    coif = mia(20, 100_000, item_id=COIF, ilvl=308)
    lua = con_faltan(subastas=[mia(10, 100_000, ilvl=308), coif])
    en_la_casa(lua, [en_venta(999, 90_000)], ilvl=308)
    detectar(lua)
    assert pulsar(lua) == "cancelar"
    lua.globals().DISPARAR("AUCTION_CANCELED", 10)
    poner(lua, "SUBASTAS", [coif])

    assert faltan(lua) == []
