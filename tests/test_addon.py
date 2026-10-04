"""El addon de WoW, ejecutado fuera del juego.

Las APIs de WoW se sustituyen por dobles, asi que se puede comprobar lo unico
del addon que de verdad puede fallar en silencio: que el JSON que escribe sea
JSON valido y que los datos que mete sean los correctos. Lo demas (que los
eventos lleguen) solo se puede ver dentro del juego.

Necesita `lupa`, que va en requirements-dev.txt. Sin el, los tests se saltan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ADDON = Path(__file__).resolve().parent.parent / "addon" / "WowAlertsExport" / "WowAlertsExport.lua"

# Un enlace de objeto real: 3 bonus ids (6652, 7981, 1498) en las posiciones
# 14, 15 y 16, que es donde el addon los busca.
LINK = "|cffa335ee|Hitem:200000::::::::80:250::14:3:6652:7981:1498:::|h[Greaves of the Noxious Depths]|h|r"

DOBLES = """
-- Dobles de las APIs de WoW que usa el addon.
local eventos = {}
mensajes = {}

function CreateFrame()
    return {
        RegisterEvent = function() end,
        SetScript = function(self, _, handler) eventos.OnEvent = handler end,
    }
end

function print(texto) mensajes[#mensajes + 1] = texto end
function time() return AHORA end
-- Reloj monotono del juego, en segundos. Arranca en 0 y los tests lo mueven
-- con AVANZAR() cuando quieren simular que la casa lleva un rato abierta.
RELOJ = 0
function GetTime() return RELOJ end
function AVANZAR(segundos) RELOJ = RELOJ + segundos end
function UnitName() return PERSONAJE end
function GetRealmName() return REINO end
function GetDetailedItemLevelInfo() return ILVL end

SlashCmdList = {}

REPASOS = 0
C_Timer = {
    After = function(_, fn) fn() end,
    -- El repaso periodico se guarda para dispararlo a mano en los tests.
    NewTicker = function(_, fn)
        REPASOS = REPASOS + 1
        REPASAR = fn
        return { Cancel = function() REPASAR = nil end }
    end,
}

-- La ventana de la casa de subastas: el addon le pregunta si esta abierta.
CASA_ABIERTA = false
AuctionHouseFrame = { IsShown = function() return CASA_ABIERTA end }

C_AuctionHouse = {
    GetNumOwnedAuctions = function() return #SUBASTAS end,
    GetOwnedAuctionInfo = function(i) return SUBASTAS[i] end,
    -- En el juego la consulta es asincrona y su respuesta dispara el evento.
    QueryOwnedAuctions = function() DISPARAR("OWNED_AUCTIONS_UPDATED") end,
}

function DISPARAR(evento, arg1) eventos.OnEvent(nil, evento, arg1) end
"""


def runtime(personaje="Pepe", reino="Sanguino", ilvl=311, subastas=None):
    """Un Lua con el addon cargado y las APIs de WoW simuladas."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().PERSONAJE = personaje
    lua.globals().REINO = reino
    lua.globals().ILVL = ilvl
    lua.globals().AHORA = 1756500000
    lua.execute(DOBLES)

    lua.globals().SUBASTAS = lua.table_from(subastas or [])
    lua.execute(ADDON.read_text(encoding="utf-8"))
    return lua


def subasta(auction_id=1, item_id=200000, buyout=90_000_000, quantity=1, link=LINK):
    return {
        "auctionID": auction_id,
        "itemKey": {"itemID": item_id, "itemLevel": 311},
        "itemLink": link,
        "buyoutAmount": buyout,
        "quantity": quantity,
    }


def recoger(lua):
    """Abre la casa de subastas y deja que el addon recoja lo que hay."""
    lua.globals().CASA_ABIERTA = True
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")


def volcado(lua) -> dict:
    """El payload que el addon dejaria en SavedVariables, ya parseado."""
    return json.loads(lua.globals().WowAlertsExportDB.payload)


def test_el_payload_es_json_valido():
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    assert volcado(lua)["version"] == 1


def test_exporta_los_datos_de_la_subasta():
    lua = runtime(subastas=[subasta()])
    recoger(lua)

    entrada = volcado(lua)["personajes"]["Sanguino-Pepe"]
    assert entrada["character"] == "Pepe"
    assert entrada["realm"] == "Sanguino"
    assert entrada["auctions"] == [
        {
            "auctionID": 1,
            "itemID": 200000,
            "itemName": "Greaves of the Noxious Depths",
            "ilvl": 311,
            "bonusIDs": [6652, 7981, 1498],
            "buyout": 90000000,
            "quantity": 1,
        }
    ]


def test_ignora_las_subastas_sin_compra_directa():
    lua = runtime(subastas=[subasta(buyout=0), subasta(auction_id=2)])
    recoger(lua)

    subastas = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]
    assert [s["auctionID"] for s in subastas] == [2]


def test_un_enlace_sin_bonus_ids_no_rompe():
    sin_bonus = "|cffffffff|Hitem:200000::::::::80:250::14:0:::|h[Cosa]|h|r"
    lua = runtime(subastas=[subasta(link=sin_bonus)])
    recoger(lua)

    entrada = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"][0]
    assert entrada["bonusIDs"] == []
    assert entrada["itemName"] == "Cosa"


def test_sin_subastas_el_personaje_sale_igualmente_con_lista_vacia():
    lua = runtime(subastas=[])
    recoger(lua)
    assert volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"] == []


def test_los_nombres_con_comillas_no_rompen_el_json():
    lua = runtime(personaje='Pe"pe', subastas=[subasta()])
    recoger(lua)
    assert volcado(lua)["personajes"]['Sanguino-Pe"pe']["character"] == 'Pe"pe'


def test_avisa_de_que_falta_volcar_a_disco():
    lua = runtime(subastas=[subasta()])
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" in mensajes


def test_al_abrir_nunca_recuerda_lo_del_reload():
    """La casa de subastas entrega tus subastas por partes: a mitad de la
    entrega lo guardado no coincide con el disco, y el aviso saltaria siempre.
    Ademas, al abrir todavia no has hecho nada."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "registradas" in mensajes
    assert "/reload" not in mensajes


def test_no_avisa_cuando_no_ha_cambiado_nada():
    lua = runtime(subastas=[subasta()])
    # Primera pasada: se recoge y se "guarda a disco".
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    # Se simula el arranque siguiente con eso ya en disco.
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" not in mensajes


def test_no_avisa_cuando_solo_ha_pasado_el_tiempo():
    """El volcado lleva la hora de exportacion, que cambia en cada lectura. Si
    se compara eso, el aviso de 'sin guardar a disco' sale siempre."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    lua.globals().mensajes = lua.table_from([])

    # Vuelves a entrar mas tarde, con las mismas subastas.
    lua.globals().AHORA = 1756599999
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" not in mensajes


def test_si_avisa_cuando_de_verdad_hay_algo_nuevo():
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().DISPARAR("ADDON_LOADED", "WowAlertsExport")
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SUBASTAS = lua.table_from([subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "/reload" in mensajes


def test_leer_cero_no_borra_lo_ya_recogido():
    """La regresion que costo un viaje al juego: con la casa de subastas
    cerrada el juego devuelve cero subastas, y eso machacaba las buenas."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2

    # Cierras la casa de subastas: el juego ya no sabe que tienes puesto.
    lua.globals().CASA_ABIERTA = False
    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_con_la_casa_abierta_un_rato_un_cero_si_se_guarda():
    """Se le acaban todas las subastas a un personaje. Pasados unos segundos el
    cero es de verdad, y si no se guarda el recuento viejo se queda para
    siempre."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2

    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().AVANZAR(10)
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"] == []


def test_el_cero_de_recien_abierta_no_borra_las_subastas():
    """La casa entrega tus subastas de forma asincrona.

    El primer OWNED_AUCTIONS_UPDATED tras abrirla llega vacio, y guardarlo
    dejaba al personaje con cero subastas hasta la visita siguiente. Es lo que
    dejo a Mbargor sin nada que vigilar.
    """
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2

    # Se cierra y se vuelve a abrir: llega el evento vacio del principio.
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")
    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_el_comando_funciona_sin_haber_visto_abrir_la_casa():
    """La segunda regresion: un /reload con la casa de subastas ya abierta.

    El evento de apertura no vuelve a dispararse, asi que el addon no puede
    fiarse de haberlo visto para saber si puede leer.
    """
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    lua.globals().SlashCmdList["WOWALERTS"]()

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_el_comando_dice_la_version_y_lo_guardado():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SlashCmdList["WOWALERTS"]()

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "WoW Alerts v" in mensajes
    assert "tengo guardadas" in mensajes


def test_postear_sin_cerrar_la_casa_actualiza():
    """Antes habia que cerrar y volver a abrir la casa de subastas: el addon
    solo miraba al abrirla, asi que se quedaba con la foto de ese momento."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 1

    lua.globals().SUBASTAS = lua.table_from([subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_cancelar_sin_cerrar_la_casa_actualiza():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)

    lua.globals().SUBASTAS = lua.table_from([subasta(auction_id=2)])
    # Con el id, que es como llega en el juego: es lo que distingue "la has
    # cancelado tu" de "la lista viene a medias", porque las dos cosas se ven
    # igual desde fuera (hay menos que antes).
    lua.globals().DISPARAR("AUCTION_CANCELED", 1)

    subastas = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]
    assert [s["auctionID"] for s in subastas] == [2]


def test_una_tanda_de_posteos_no_dispara_una_consulta_por_cada_uno():
    lua = runtime(subastas=[subasta()])
    # El temporizador deja de ejecutar al momento: se cuenta cuantos se piden,
    # que es lo que mide si las peticiones seguidas se agrupan.
    lua.execute("""
        PENDIENTES = 0
        C_Timer = { After = function() PENDIENTES = PENDIENTES + 1 end }
    """)

    for _ in range(5):
        lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    # Cinco posteos seguidos, un unico temporizador pendiente.
    assert lua.globals().PENDIENTES == 1


def test_el_comando_no_cuenta_antes_de_que_llegue_la_respuesta():
    """La consulta es asincrona: contar en la misma linea que se pide daba cero
    y hacia creer que el addon no leia nada."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    lua.globals().SlashCmdList["WOWALERTS"]()

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "tengo guardadas" in mensajes
    assert "no puedo leer nada" not in mensajes


def test_al_abrir_la_casa_sale_un_mensaje():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("AUCTION_HOUSE_SHOW")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "2 subasta(s) tuyas registradas" in mensajes


def test_al_cerrar_la_casa_sale_un_mensaje_con_lo_guardado():
    lua = runtime(subastas=[subasta(), subasta(auction_id=2)])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    # Con la casa cerrada el juego ya no devuelve nada, pero lo guardado sigue.
    lua.globals().CASA_ABIERTA = False
    lua.globals().SUBASTAS = lua.table_from([])
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    mensajes = " ".join(lua.globals().mensajes.values())
    assert "2 subasta(s) tuyas registradas" in mensajes


def test_postear_y_cancelar_no_llena_el_chat():
    """El resumen es solo al abrir y al cerrar: mientras trabajas, silencio."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().mensajes = lua.table_from([])

    for i in range(2, 12):
        lua.globals().SUBASTAS = lua.table_from([subasta(auction_id=j) for j in range(1, i + 1)])
        lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    assert " ".join(lua.globals().mensajes.values()) == ""
    # Pero si que se ha ido guardando por el camino.
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 11


def test_mientras_la_casa_esta_abierta_se_repasa_solo():
    """La red por si algun evento de publicar no llega: publicar treinta
    objetos y cerrar dejaba el recuento viejo hasta la visita siguiente."""
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 1

    # Posteas mas, sin que llegue ningun evento de creacion.
    lua.globals().SUBASTAS = lua.table_from([subasta(auction_id=i) for i in range(1, 33)])
    lua.globals().REPASAR()

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 32


def test_el_repaso_se_para_al_cerrar_la_casa():
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    lua.globals().CASA_ABIERTA = False
    lua.globals().DISPARAR("AUCTION_HOUSE_CLOSED")

    assert lua.globals().REPASAR is None


def test_no_se_acumula_un_repaso_por_cada_apertura():
    lua = runtime(subastas=[subasta()])
    recoger(lua)
    recoger(lua)
    recoger(lua)

    assert lua.globals().REPASOS == 1


# -- Aviso al entrar con un personaje cuyos datos ya no valen ----------------


def test_avisa_al_entrar_si_sus_subastas_son_viejas():
    """Recargar sin abrir la Casa de Subastas no actualiza nada.

    Es el fallo que dejo diez personajes sin vigilar un dia entero: entras,
    haces /reload y el volcado sigue siendo el de ayer.
    """
    lua = runtime(subastas=[subasta()])
    recoger(lua)

    # Al dia siguiente: los datos guardados tienen mas de doce horas.
    lua.globals().AHORA = lua.globals().AHORA + 13 * 3600
    lua.execute("mensajes = {}")
    lua.globals().DISPARAR("PLAYER_ENTERING_WORLD")

    texto = " ".join(lua.globals().mensajes.values())
    assert "Casa de Subastas" in texto


def test_no_avisa_si_los_datos_son_de_hace_un_rato():
    lua = runtime(subastas=[subasta()])
    recoger(lua)

    lua.execute("mensajes = {}")
    lua.globals().DISPARAR("PLAYER_ENTERING_WORLD")

    assert list(lua.globals().mensajes.values()) == []


def test_no_avisa_de_un_personaje_que_nunca_ha_vendido():
    """Sin subastas guardadas no hay nada que refrescar: seria puro ruido."""
    lua = runtime(subastas=[])
    lua.execute("mensajes = {}")
    lua.globals().DISPARAR("PLAYER_ENTERING_WORLD")

    assert list(lua.globals().mensajes.values()) == []


def test_al_salir_se_regenera_el_volcado():
    """El payload es lo unico que lee el sincronizador, y puede quedarse atras.

    Paso el 2026-09-01: la tabla del addon tenia 36 personajes de hoy y el
    payload 30 de ayer, asi que el vigilante llevaba un dia entero leyendo datos
    muertos de treinta personajes.
    """
    lua = runtime(subastas=[subasta()])
    recoger(lua)

    # Se ensucia el volcado a mano, como si se hubiera quedado atras.
    lua.execute('WowAlertsExportDB.payload = "viejo"')
    lua.globals().DISPARAR("PLAYER_LOGOUT")

    assert lua.globals().WowAlertsExportDB.payload != "viejo"
    assert "Sanguino-Pepe" in lua.globals().WowAlertsExportDB.payload


def test_al_salir_sin_datos_no_pasa_nada():
    lua = runtime(subastas=[])
    lua.globals().DISPARAR("PLAYER_LOGOUT")


# -- Precios grandes ---------------------------------------------------------


def test_un_precio_de_mas_de_dos_mil_millones_se_exporta_entero():
    """WoW usa enteros de 32 bits: 249.999 de oro son 2.499.990.000 de cobre.

    Con "%d" eso reventaba el codificador entero --"integer overflow"-- y el
    volcado se quedaba con los datos del dia anterior, en silencio y para TODOS
    los personajes de esa cuenta. Costo un dia de vigilancia y una venta.
    """
    lua = runtime(subastas=[subasta(buyout=2_499_990_000)])
    recoger(lua)

    subastas = volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]
    assert subastas[0]["buyout"] == 2_499_990_000


def test_el_codificador_no_usa_el_formato_de_32_bits():
    """El arnes no puede reproducir el desbordamiento: lupa es Lua 5.5, con
    enteros de 64 bits, y ahi "%d" traga cualquier cosa. WoW es Lua 5.1 y no.

    Asi que se comprueba sobre el codigo: los numeros no se formatean con "%d".
    """
    fuente = ADDON.read_text(encoding="utf-8")
    assert 'string.format("%d"' not in fuente


# ---------------------------------------------------------------------------
#  Lecturas a medias
# ---------------------------------------------------------------------------
#
#  El juego entrega los datos de forma perezosa, y guardar() reemplaza la lista
#  entera. Si posteas y sales rapido, una lectura incompleta se guardaba encima
#  de la buena y perdias subastas sin enterarte.


def test_leer_menos_de_las_que_habia_no_borra_el_resto():
    """El caso que se escapaba: leer 1 de 3 pasaba el filtro del cero."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2), subasta(auction_id=3)])
    recoger(lua)
    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 3

    # El servidor entrega solo una parte en el siguiente evento.
    lua.globals().SUBASTAS = lua.table_from([subasta()])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 3


def test_con_la_casa_abierta_un_rato_si_se_guardan_menos():
    """Vender o cancelar reduce el numero de verdad, y hay que reflejarlo."""
    lua = runtime(subastas=[subasta(), subasta(auction_id=2), subasta(auction_id=3)])
    recoger(lua)

    lua.globals().SUBASTAS = lua.table_from([subasta()])
    lua.globals().AVANZAR(10)
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 1


def test_una_subasta_sin_ilvl_todavia_no_se_guarda_a_medias():
    """Sin los datos del objeto cargados no se puede leer su ilvl.

    Antes esa subasta se saltaba en silencio y se guardaba la lista sin ella,
    que es una subasta perdida. Ahora la lectura entera se descarta y se
    reintenta en el siguiente evento.
    """
    a_medias = subasta(auction_id=2)
    a_medias["itemKey"] = {"itemID": 200000, "itemLevel": None}  # aun sin ilvl
    a_medias["itemLink"] = None  # y sin enlace del que sacarlo

    lua = runtime(subastas=[subasta(), a_medias])
    recoger(lua)

    # No se guarda nada: mejor sin datos que con una subasta de menos, porque
    # una lista incompleta se toma por buena y la que falta se da por vendida.
    assert lua.globals().WowAlertsExportDB.payload is None


def test_cuando_cargan_los_datos_se_guarda_entera():
    """Y el reintento llega solo: el siguiente evento ya la trae completa."""
    a_medias = subasta(auction_id=2)
    a_medias["itemKey"] = {"itemID": 200000, "itemLevel": None}
    a_medias["itemLink"] = None

    lua = runtime(subastas=[subasta(), a_medias])
    recoger(lua)

    lua.globals().SUBASTAS = lua.table_from([subasta(), subasta(auction_id=2)])
    lua.globals().DISPARAR("OWNED_AUCTIONS_UPDATED")

    assert len(volcado(lua)["personajes"]["Sanguino-Pepe"]["auctions"]) == 2


def test_al_postear_se_pregunta_al_momento():
    """Postear uno y cerrar es el caso normal, y antes pagaba la espera.

    El agrupado esperaba un segundo SIEMPRE, asi que si cerrabas la casa de
    subastas antes de que venciera, la subasta recien puesta no se recogia hasta
    la visita siguiente.
    """
    lua = runtime(subastas=[subasta()])
    lua.execute("""
        CONSULTAS = 0
        C_AuctionHouse.QueryOwnedAuctions = function() CONSULTAS = CONSULTAS + 1 end
        C_Timer = { After = function() end, NewTicker = function() return { Cancel = function() end } end }
    """)

    lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    assert lua.globals().CONSULTAS == 1


def test_una_tanda_seguida_sigue_agrupandose():
    """Y el motivo de agrupar no desaparece: la casa limita las consultas."""
    lua = runtime(subastas=[subasta()])
    lua.execute("""
        CONSULTAS = 0
        PENDIENTES = 0
        C_AuctionHouse.QueryOwnedAuctions = function() CONSULTAS = CONSULTAS + 1 end
        C_Timer = { After = function() PENDIENTES = PENDIENTES + 1 end,
                    NewTicker = function() return { Cancel = function() end } end }
    """)

    for _ in range(20):
        lua.globals().DISPARAR("AUCTION_HOUSE_AUCTION_CREATED")

    # Veinte posteos: una consulta al momento y un unico temporizador para el
    # resto, no veinte consultas.
    assert lua.globals().CONSULTAS == 1
    assert lua.globals().PENDIENTES == 1
