-- Exporta tus subastas activas a SavedVariables como una cadena JSON.
--
-- El lado Python solo tiene que extraer esa cadena y hacer json.loads, en vez
-- de interpretar tablas de Lua. WoW unicamente escribe SavedVariables a disco
-- al salir del juego, al hacer logout o con /reload, asi que el addon avisa en
-- pantalla cuando hay subastas recogidas que todavia no se han volcado.

local FORMAT_VERSION = 1
-- Version del addon, para saber que codigo se esta ejecutando de verdad.
local ADDON_VERSION = "1.35"

WowAlertsExportDB = WowAlertsExportDB or {}

-- La huella de lo que habia en disco al arrancar. Comparar contra esto es lo
-- que permite saber si queda algo sin volcar.
--
-- Es una huella y no el volcado entero porque el volcado lleva la hora de cada
-- exportacion, que cambia cada vez que se lee aunque las subastas sean las
-- mismas: comparando eso, el aviso saltaba siempre.
local huellaEnDisco = nil


-- ---------------------------------------------------------------------------
--  Codificacion JSON minima (solo los tipos que usamos)
-- ---------------------------------------------------------------------------

local function escapeString(s)
    s = tostring(s)
    s = s:gsub("\\", "\\\\")
    s = s:gsub('"', '\\"')
    s = s:gsub("\n", "\\n")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\t", "\\t")
    return '"' .. s .. '"'
end

local encode

local function encodeArray(t)
    local parts = {}
    for i = 1, #t do
        parts[#parts + 1] = encode(t[i])
    end
    return "[" .. table.concat(parts, ",") .. "]"
end

local function encodeObject(t)
    -- Claves ordenadas: asi dos volcados con los mismos datos producen la misma
    -- cadena y el sincronizador puede saltarse el commit.
    local keys = {}
    for key in pairs(t) do
        keys[#keys + 1] = key
    end
    table.sort(keys)

    local parts = {}
    for _, key in ipairs(keys) do
        parts[#parts + 1] = escapeString(key) .. ":" .. encode(t[key])
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

encode = function(value)
    local kind = type(value)
    if kind == "number" then
        -- Con "%d" y no con "%.0f" esto reventaba: WoW formatea %d como entero
        -- de 32 bits, cuyo tope son 2.147.483.647, y una subasta de 249.999 de
        -- oro son 2.499.990.000 de cobre. El error tumbaba el codificador
        -- entero, asi que el volcado se quedaba con los datos del dia anterior
        -- para TODOS los personajes de esa cuenta, y sin decir nada.
        --
        -- Ojo si tocas esto: los tests corren sobre lupa, que es Lua 5.5 con
        -- enteros de 64 bits, y ahi "%d" traga cualquier cosa sin quejarse.
        return string.format("%.0f", value)
    elseif kind == "string" then
        return escapeString(value)
    elseif kind == "boolean" then
        return value and "true" or "false"
    elseif kind == "table" then
        if #value > 0 or next(value) == nil then
            return encodeArray(value)
        end
        return encodeObject(value)
    end
    return "null"
end

-- BancoHermandad.lua tambien exporta en JSON.
WowAlertsJSON = encode

-- ---------------------------------------------------------------------------
--  Lectura de tus subastas
-- ---------------------------------------------------------------------------

-- Los bonus ids viven dentro del enlace del objeto. No los usa la deteccion,
-- pero se exportan para poder ampliar el mapa de ilvl del config mas adelante.
local function bonusIDsFromLink(link)
    local ids = {}
    if not link then
        return ids
    end
    local payload = link:match("|Hitem:([%-%d:]*)")
    if not payload then
        return ids
    end

    local parts = {}
    for value in (payload .. ":"):gmatch("([^:]*):") do
        parts[#parts + 1] = value
    end

    -- Posicion 13 del enlace: cuantos bonus ids vienen detras.
    local count = tonumber(parts[13]) or 0
    for i = 1, count do
        local id = tonumber(parts[13 + i])
        if id then
            ids[#ids + 1] = id
        end
    end
    return ids
end

-- Devuelve la lista y cuantas no se han podido leer todavia.
--
-- Lo segundo importa mas de lo que parece. El juego entrega los datos de cada
-- objeto de forma perezosa: recien abierta la casa, o nada mas postear, el
-- itemLink puede no tener ilvl aun. Antes esas subastas se saltaban en silencio
-- y se guardaba la lista incompleta encima de la buena, asi que si posteabas y
-- salias rapido perdias subastas sin enterarte.
local function recogerSubastas()
    local subastas = {}
    local incompletas = 0
    local total = C_AuctionHouse.GetNumOwnedAuctions()

    for index = 1, total do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(index)
        if not info then
            incompletas = incompletas + 1
        end
        -- Sin compra directa no hay nada que comparar: una subasta que solo
        -- admite pujas no compite en precio con las demas.
        if info and info.buyoutAmount and info.buyoutAmount > 0 then
            local itemKey = info.itemKey or {}
            local link = info.itemLink
            local ilvl = nil
            if link then
                ilvl = GetDetailedItemLevelInfo(link)
            end
            ilvl = ilvl or itemKey.itemLevel

            local nombre = nil
            if link then
                nombre = link:match("%[(.-)%]")
            end

            if not (itemKey.itemID and ilvl) then
                -- El juego la conoce pero aun no ha cargado sus datos. No es
                -- una subasta menos: es una lectura a medias.
                incompletas = incompletas + 1
            else
                subastas[#subastas + 1] = {
                    auctionID = info.auctionID,
                    itemID = itemKey.itemID,
                    itemName = nombre or ("Objeto " .. itemKey.itemID),
                    ilvl = ilvl,
                    bonusIDs = bonusIDsFromLink(link),
                    buyout = info.buyoutAmount,
                    quantity = info.quantity or 1,
                }
            end
        end
    end

    return subastas, incompletas
end

-- ---------------------------------------------------------------------------
--  Volcado
-- ---------------------------------------------------------------------------

-- Si la ventana de la casa de subastas esta abierta ahora mismo. Se le
-- pregunta al juego en vez de recordarlo en una bandera: una bandera se pierde
-- con cualquier /reload, y entonces el addon se queda creyendo que esta
-- cerrada para siempre.
local function casaAbierta()
    return AuctionHouseFrame ~= nil and AuctionHouseFrame:IsShown()
end

-- Cuando se abrio la casa de subastas, para saber si ha dado tiempo a que
-- llegue la respuesta del servidor.
local abiertaDesde = nil

-- Segundos que hay que esperar antes de creerse un cero. La casa de subastas
-- entrega tus subastas de forma asincrona: el primer OWNED_AUCTIONS_UPDATED
-- tras abrirla llega vacio, y guardarlo borraba las subastas del personaje.
local SEGUNDOS_PARA_FIARSE_DE_UN_CERO = 5

-- Pedirle al servidor tus subastas. Con la casa de subastas cerrada esto no
-- vale para nada y puede protestar, asi que se envuelve en pcall.
local function pedirSubastas()
    pcall(C_AuctionHouse.QueryOwnedAuctions, {})
end

-- Igual, pero agrupando las peticiones seguidas. Al postear una tanda de veinte
-- objetos llegan veinte eventos, y la casa de subastas limita cuantas consultas
-- admite seguidas.
--
-- El agrupado pregunta en el PRIMER evento, no al final del segundo de espera.
-- Antes esperaba siempre, y eso penalizaba el caso normal --postear una cosa y
-- cerrar-- por culpa del caso de la tanda: si cerrabas antes de que venciera la
-- espera, la subasta recien puesta no se recogia hasta la visita siguiente.
-- Asi el primero entra al momento y el resto de la tanda se agrupa igual.
local SEGUNDOS_ENTRE_CONSULTAS = 1
local refrescoPendiente = false
local ultimaConsulta = nil

local function pedirSubastasPronto()
    if refrescoPendiente then
        return
    end

    local ahora = GetTime()
    if not ultimaConsulta or (ahora - ultimaConsulta) >= SEGUNDOS_ENTRE_CONSULTAS then
        ultimaConsulta = ahora
        pedirSubastas()
        return
    end

    refrescoPendiente = true
    C_Timer.After(SEGUNDOS_ENTRE_CONSULTAS, function()
        refrescoPendiente = false
        ultimaConsulta = GetTime()
        pedirSubastas()
    end)
end

-- Mientras la casa de subastas este abierta se vuelve a preguntar cada pocos
-- segundos. Es la red que hace que el recuento acabe cuadrando aunque algun
-- evento de publicar o cancelar no llegue: publicar treinta objetos y cerrar
-- dejaba el numero de antes hasta la visita siguiente.
local repaso = nil

local function empezarRepaso()
    if repaso then
        return
    end
    repaso = C_Timer.NewTicker(10, function()
        if casaAbierta() then
            pedirSubastas()
        end
    end)
end

local function pararRepaso()
    if repaso then
        repaso:Cancel()
        repaso = nil
    end
end


-- ---------------------------------------------------------------------------
--  Cancelaciones
-- ---------------------------------------------------------------------------
--  Cancelar una subasta y venderla se ven igual desde fuera: en las dos
--  desaparece de la casa de subastas. El unico que sabe cual ha sido es el
--  juego, asi que se apunta aqui y el vigilante lo consulta antes de cantar una
--  venta.

-- Cuantos dias se recuerda una cancelacion. Con la pasada cada hora sobra de
-- largo; el limite existe solo para que la lista no crezca sin fin.
local DIAS_CANCELADAS = 3

local function apuntarCancelada(auctionID)
    if type(auctionID) ~= "number" then
        return
    end

    local canceladas = WowAlertsExportDB.canceladas or {}
    canceladas[tostring(auctionID)] = time()

    local corte = time() - DIAS_CANCELADAS * 86400
    for id, cuando in pairs(canceladas) do
        if type(cuando) ~= "number" or cuando < corte then
            canceladas[id] = nil
        end
    end

    WowAlertsExportDB.canceladas = canceladas
end


local function claveDePersonaje()
    local nombre = UnitName("player")
    local reino = GetRealmName()
    return reino .. "-" .. nombre, nombre, reino
end

-- Las subastas de cada personaje, sin horas ni nada que cambie solo. Dos
-- lecturas con las mismas subastas dan la misma huella.
local function huellaDe(datos)
    local limpio = {}
    for clave, entrada in pairs(datos) do
        limpio[clave] = entrada.auctions or {}
    end
    return encode(limpio)
end

-- Si cada subasta que ha dejado de aparecer es una que cancelaste tu.
--
-- Es lo que separa "has cancelado" de "la lista viene a medias", que desde
-- fuera se ven igual: en los dos casos hay menos que antes.
local function todoLoQueFaltaLoCancelasteTu(antes, ahora)
    local canceladas = WowAlertsExportDB.canceladas or {}
    local siguen = {}
    for _, s in ipairs(ahora) do
        siguen[s.auctionID] = true
    end

    for _, s in ipairs(antes or {}) do
        if not siguen[s.auctionID] and not canceladas[tostring(s.auctionID)] then
            return false
        end
    end
    return true
end


local function guardar()
    -- Se parte de lo ya guardado para no borrar las subastas de los demas
    -- personajes: cada uno actualiza solo su propia entrada.
    local datos = WowAlertsExportDB.personajes or {}

    local clave, nombre, reino = claveDePersonaje()
    local recogidas, incompletas = recogerSubastas()
    local previo = datos[clave]

    -- Una lectura a medias no se guarda nunca: machacaria la lista buena con
    -- uno menos. Se reintenta sola, porque el repaso periodico y el siguiente
    -- OWNED_AUCTIONS_UPDATED vuelven a pasar por aqui.
    if incompletas > 0 then
        return nil
    end

    -- Leer cero no significa que las hayas cancelado: puede significar que
    -- ahora mismo no se pueden leer. Con la casa cerrada nunca es fiable, y
    -- recien abierta tampoco, porque la respuesta del servidor tarda un
    -- momento y el primer evento llega vacio. Pasados unos segundos con la casa
    -- abierta, un cero si es un cero: hay que guardarlo, o un personaje al que
    -- se le acaban las subastas se quedaria con el recuento viejo para siempre.
    -- Ojo: la comparacion es "menos que", no "cero". Que el servidor entregue
    -- la lista a trozos es normal, y con "cero" solo se protegia el caso
    -- extremo: leer 3 de tus 13 pasaba el filtro y se perdian 10.
    --
    -- Pero bajar tambien es legitimo: si acabas de cancelar una, tiene que
    -- reflejarse ya. Eso no se adivina por tiempo, se sabe: el addon apunta el
    -- id en cuanto cancelas. Si todo lo que falta lo cancelaste tu, la lectura
    -- es de fiar; si falta algo que nadie ha cancelado, es una lectura a medias.
    if previo and #recogidas < #(previo.auctions or {}) then
        if not todoLoQueFaltaLoCancelasteTu(previo.auctions, recogidas) then
            local segundos = abiertaDesde and (GetTime() - abiertaDesde) or 0
            if not casaAbierta() or segundos < SEGUNDOS_PARA_FIARSE_DE_UN_CERO then
                return nil
            end
        end
    end

    datos[clave] = {
        character = nombre,
        realm = reino,
        exportedAt = time(),
        auctions = recogidas,
    }

    WowAlertsExportDB.personajes = datos
    WowAlertsExportDB.version = FORMAT_VERSION
    WowAlertsExportDB.payload = encode({
        version = FORMAT_VERSION,
        personajes = datos,
        canceladas = WowAlertsExportDB.canceladas or {},
    })
    WowAlertsExportDB.huella = huellaDe(datos)

    return #recogidas
end

-- Rehace la cadena JSON a partir de la tabla del addon.
--
-- El payload es lo UNICO que lee el sincronizador, y puede quedarse atras
-- respecto a la tabla: el 2026-09-01 la tabla tenia 36 personajes de ese dia y
-- el payload 30 del anterior, con lo que treinta personajes se pasaron un dia
-- entero sin vigilar. Rehacerlo al salir cierra esa deriva pase lo que pase
-- durante la sesion, y no necesita la casa de subastas abierta.
local function regenerarPayload()
    local datos = WowAlertsExportDB.personajes
    if not datos or next(datos) == nil then
        return
    end

    WowAlertsExportDB.version = FORMAT_VERSION
    WowAlertsExportDB.payload = encode({
        version = FORMAT_VERSION,
        personajes = datos,
        canceladas = WowAlertsExportDB.canceladas or {},
    })
    WowAlertsExportDB.huella = huellaDe(datos)
end

-- Cuantas subastas hay guardadas de este personaje ahora mismo.
local function guardadas()
    local previo = (WowAlertsExportDB.personajes or {})[claveDePersonaje()]
    return #((previo or {}).auctions or {})
end

local function avisarSiFaltaVolcar()
    if WowAlertsExportDB.huella == huellaEnDisco then
        return
    end
    print(
        "|cffffd200WoW Alerts:|r subastas actualizadas pero |cffff7f7fsin guardar"
            .. " a disco|r. Haz |cff00ff00/reload|r (o sal del juego) para que el"
            .. " vigilante de undercuts se entere."
    )
end

-- El resumen sale al abrir y al cerrar la casa de subastas, y en ningun otro
-- momento: mientras posteas o cancelas el addon se actualiza en silencio. Dos
-- mensajes por visita, no uno por cada cosa que hagas.
-- `conAviso` solo se pide al cerrar. Al abrir, la casa de subastas entrega tus
-- subastas por partes, asi que lo guardado a mitad de la entrega no coincide
-- con el disco y el recordatorio saltaria siempre. Y aun coincidiendo no
-- vendria a cuento: al abrir todavia no has hecho nada.
local function resumir(conAviso)
    print(("|cffffd200WoW Alerts:|r %d subasta(s) tuyas registradas."):format(guardadas()))
    if conAviso then
        avisarSiFaltaVolcar()
    end
end

-- Al abrir hay que esperar un momento: el evento de apertura llega antes que
-- los datos, y la primera lectura viene vacia.
local resumenPendiente = false

local function resumirPronto()
    if resumenPendiente then
        return
    end
    resumenPendiente = true
    C_Timer.After(1, function()
        resumenPendiente = false
        resumir(false)
    end)
end

-- Horas a partir de las cuales lo guardado de un personaje deja de servir.
-- Con listados de 12 horas, un volcado mas viejo que eso ya no describe ninguna
-- subasta viva: sus ids estan muertos y el vigilante no puede comparar nada.
local HORAS_PARA_QUEDARSE_VIEJO = 12

-- Recordatorio al entrar con un personaje cuyas subastas guardadas ya no valen.
--
-- Hace falta porque recargar NO actualiza nada: el addon solo puede leer tus
-- subastas con la Casa de Subastas abierta. Entrar, hacer /reload y salir deja
-- el volcado igual que estaba, y el vigilante se queda comparando contra ids
-- muertos sin que nada lo cante desde dentro del juego.
local function avisarSiEstaViejo()
    local previo = (WowAlertsExportDB.personajes or {})[claveDePersonaje()]
    if not previo or #(previo.auctions or {}) == 0 then
        -- Sin subastas guardadas no hay nada que refrescar: avisar aqui seria
        -- ruido en todos los personajes con los que no vendes.
        return
    end

    local edad = time() - (previo.exportedAt or 0)
    if edad < HORAS_PARA_QUEDARSE_VIEJO * 3600 then
        return
    end

    print(
        ("|cffffd200WoW Alerts:|r lo que tengo de este personaje son |cffff7f7f%d subasta(s) de hace %d h|r."):format(
            #previo.auctions, math.floor(edad / 3600)
        )
    )
    print("  Abre la |cff00ff00Casa de Subastas|r y haz |cff00ff00/reload|r, o dejo de vigilarlo.")
end

-- ---------------------------------------------------------------------------
--  Eventos
-- ---------------------------------------------------------------------------

-- Durante mucho tiempo no hizo falta engancharse a PLAYER_LOGOUT: lo recogido
-- ya vive en WowAlertsExportDB y WoW escribe esa tabla a disco por su cuenta.
-- Ahora si, pero por otro motivo: no para guardar la tabla, sino para rehacer
-- la copia en JSON que se lee desde fuera, que puede quedarse atras.
local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
-- WoW escribe SavedVariables justo despues de este evento, asi que es el ultimo
-- momento util para dejar el volcado al dia.
frame:RegisterEvent("PLAYER_LOGOUT")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("OWNED_AUCTIONS_UPDATED")
-- Postear o cancelar cambia tus subastas sin cerrar la casa. Sin estos dos, el
-- addon se quedaba con la foto de cuando la abriste.
frame:RegisterEvent("AUCTION_HOUSE_AUCTION_CREATED")
frame:RegisterEvent("AUCTION_CANCELED")

frame:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 == "WowAlertsExport" then
            huellaEnDisco = WowAlertsExportDB.huella
        end
    elseif event == "PLAYER_ENTERING_WORLD" then
        avisarSiEstaViejo()
    elseif event == "PLAYER_LOGOUT" then
        regenerarPayload()
    elseif event == "AUCTION_HOUSE_SHOW" then
        abiertaDesde = GetTime()
        pedirSubastas()
        empezarRepaso()
        resumirPronto()
    elseif event == "AUCTION_HOUSE_CLOSED" then
        abiertaDesde = nil
        pararRepaso()
        -- Al cerrar ya esta todo entregado y guardado: se cuenta sin esperar, y
        -- es el momento en que el recordatorio de /reload sirve para algo.
        resumir(true)
    elseif event == "AUCTION_CANCELED" then
        -- arg1 es el id de la subasta cancelada. Se guarda antes de nada y se
        -- vuelca ya: si esperaramos a OWNED_AUCTIONS_UPDATED y ese evento no
        -- llegara, la cancelacion se perderia y saldria como venta.
        apuntarCancelada(arg1)
        guardar()
        pedirSubastasPronto()
    elseif event == "AUCTION_HOUSE_AUCTION_CREATED" then
        pedirSubastasPronto()
    elseif event == "OWNED_AUCTIONS_UPDATED" then
        guardar()
    end
end)

-- Pedir los datos y contarlos en la misma linea no funciona: la consulta es
-- asincrona y la respuesta tarda un instante. Este comando solo informa de lo
-- que hay guardado y lanza la peticion; quien cuenta lo nuevo es el manejador
-- de OWNED_AUCTIONS_UPDATED, cuando llega la respuesta.
SLASH_WOWALERTS1 = "/wowalerts"
SLASH_WOWALERTS2 = "/wa"
SlashCmdList["WOWALERTS"] = function()
    local _, nombre, reino = claveDePersonaje()

    print(("|cffffd200WoW Alerts v%s|r · %s de %s"):format(ADDON_VERSION, nombre, reino))
    print(("  tengo guardadas |cff00ff00%d|r subasta(s) de este personaje."):format(guardadas()))

    local n = 0
    for _ in pairs(WowAlertsExportDB.canceladas or {}) do
        n = n + 1
    end
    print(("  y |cff00ff00%d|r cancelacion(es) apuntada(s), para no cantarlas como ventas."):format(n))
    print("  pidiendo las de ahora mismo...")

    pedirSubastas()
end
