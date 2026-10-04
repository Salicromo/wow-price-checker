-- Lo que tienes en el banco de hermandad, para ver desde la casa de subastas si
-- lo que falta por postear lo puedes sacar de alli.
--
-- El juego solo deja leer el banco con su ventana abierta, y la casa no se
-- puede tener abierta a la vez: se apunta al abrir el banco y se guarda en
-- WowAlertsExportDB, por hermandad, para consultarlo luego.
--
-- El ilvl no se puede leer del banco: el juego manda sus objetos sin los bonus,
-- y un 308 llega como su ilvl base (219). Asi que se apunta el de la bolsa al
-- meterlo, se sigue si lo mueves dentro del banco y se pinta encima del icono.
-- Lo que ya estaba en el banco antes se queda sin apuntar hasta que lo saques
-- y lo vuelvas a meter.

local B = {}
WowAlertsBanco = B

local HUECOS_POR_PESTANA = MAX_GUILDBANK_SLOTS_PER_TAB or 98

local abierto = false

-- Lo cogido de la bolsa con el banco abierto, { itemID, ilvl }: lo siguiente
-- que aparezca en el banco con ese itemID es eso.
local cogidos = {}

-- Que habia en cada hueco ("pestana:hueco" -> itemID) en la ultima lectura con
-- el banco abierto. nil hasta la primera: sin ella no se sabe que es nuevo.
local vistos = nil

-- Con el reino de la hermandad y no el del personaje: los alters de reinos
-- conectados comparten banco. GetGuildInfo solo da ese reino si no es el del
-- personaje; se le quitan espacios y guiones para que se escriba igual que
-- GetNormalizedRealmName, por si viene como el nombre que se ve.
local function claveHermandad()
    local hermandad, _, _, reino = GetGuildInfo("player")
    reino = (reino and reino:gsub("[%s%-]", "")) or GetNormalizedRealmName()
    if not (hermandad and reino) then
        return nil
    end
    return hermandad .. "-" .. reino
end

-- WoW guarda esto por cuenta de WoW y una cuenta no ve lo de otra. Asi que se
-- deja en JSON en bancoJSON, y la sincronizacion trae a bancoDeOtraCuenta lo
-- mas nuevo de las demas (ver wowalerts/banco.py).
local function exportar()
    local db = WowAlertsExportDB
    local banco = {}
    for clave, b in pairs(db.bancoHermandad or {}) do
        banco[clave] = {
            en = b.en,
            copias = b.copias,
            ilvls = (db.ilvlBancoHermandad or {})[clave] or {},
        }
    end
    db.bancoJSON = WowAlertsJSON(banco)
end

-- Se queda con lo de otra cuenta si es mas nuevo que lo de esta.
local function importar()
    local db = WowAlertsExportDB
    local otra = db.bancoDeOtraCuenta
    if type(otra) ~= "table" then
        return
    end
    db.bancoDeOtraCuenta = nil
    db.bancoHermandad = db.bancoHermandad or {}
    db.ilvlBancoHermandad = db.ilvlBancoHermandad or {}
    for clave, b in pairs(otra) do
        local mio = db.bancoHermandad[clave]
        if not mio or (mio.en or 0) < (b.en or 0) then
            db.bancoHermandad[clave] = { copias = b.copias or {}, en = b.en }
            db.ilvlBancoHermandad[clave] = b.ilvls or {}
        end
    end
    exportar()
end

-- Se lee WowAlertsExportDB cada vez: WoW reemplaza esa tabla por la de disco
-- despues de cargar este fichero.
local function apuntado()
    WowAlertsExportDB = WowAlertsExportDB or {}
    importar()
    WowAlertsExportDB.bancoHermandad = WowAlertsExportDB.bancoHermandad or {}
    return WowAlertsExportDB.bancoHermandad
end

-- El ilvl de verdad de cada hueco, "pestana:hueco" -> { itemID, ilvl }.
local function ilvlsApuntados(clave)
    WowAlertsExportDB = WowAlertsExportDB or {}
    importar()
    WowAlertsExportDB.ilvlBancoHermandad = WowAlertsExportDB.ilvlBancoHermandad or {}
    local todos = WowAlertsExportDB.ilvlBancoHermandad
    if not todos[clave] then
        -- Hasta la 1.30 la clave llevaba el reino del personaje: lo apuntado
        -- con cada alter se junta aqui. Lo que no cuadre con el hueco no se
        -- usa, porque ilvlDelHueco mira el itemID.
        todos[clave] = {}
        local prefijo = clave:match("^(.*%-)")
        for vieja, huecos in pairs(todos) do
            if vieja ~= clave and vieja:sub(1, #prefijo) == prefijo then
                for k, a in pairs(huecos) do
                    todos[clave][k] = a
                end
                todos[vieja] = nil
            end
        end
    end
    return todos[clave]
end

local function itemDe(enlace)
    return enlace and tonumber(enlace:match("item:(%d+)"))
end

local function sacarCogido(itemID)
    for i = #cogidos, 1, -1 do
        if cogidos[i].itemID == itemID then
            return table.remove(cogidos, i).ilvl
        end
    end
end

-- Pone al dia lo apuntado comparando el banco de ahora con la ultima lectura.
-- Lo que deja un hueco suelta su ilvl; lo que llega a otro lo toma de ahi (lo
-- has movido) o de lo cogido de la bolsa (lo has metido).
local function seguir(clave, ahora)
    if not vistos then
        vistos = ahora
        return
    end
    local apuntados = ilvlsApuntados(clave)
    local sueltos = {}
    for k, itemID in pairs(vistos) do
        local a = apuntados[k]
        if ahora[k] ~= itemID and a and a.itemID == itemID then
            sueltos[itemID] = sueltos[itemID] or {}
            table.insert(sueltos[itemID], a.ilvl)
            apuntados[k] = nil
        end
    end
    for k, itemID in pairs(ahora) do
        if vistos[k] ~= itemID then
            local ilvl = (sueltos[itemID] and table.remove(sueltos[itemID])) or sacarCogido(itemID)
            if ilvl then
                apuntados[k] = { itemID = itemID, ilvl = ilvl }
            elseif apuntados[k] and apuntados[k].itemID ~= itemID then
                apuntados[k] = nil
            end
        end
    end
    vistos = ahora
end

-- El ilvl apuntado de ese hueco, si lo que hay es lo que se apunto.
local function ilvlDelHueco(clave, pestana, hueco, itemID)
    local a = ilvlsApuntados(clave)[pestana .. ":" .. hueco]
    return a and a.itemID == itemID and a.ilvl or nil
end

-- Recuenta todo el banco y sustituye lo apuntado. Se llama con cada pestana
-- que llega: mientras faltan pestanas el recuento sale corto, pero la ultima
-- respuesta lo deja entero.
local function leer()
    local clave = claveHermandad()
    if not abierto or not clave then
        return
    end
    local ahora = {}
    for pestana = 1, GetNumGuildBankTabs() do
        local _, _, visible = GetGuildBankTabInfo(pestana)
        if visible then
            for hueco = 1, HUECOS_POR_PESTANA do
                local itemID = itemDe(GetGuildBankItemLink(pestana, hueco))
                if itemID then
                    ahora[pestana .. ":" .. hueco] = itemID
                end
            end
        end
    end
    seguir(clave, ahora)

    local copias = {}
    for k, itemID in pairs(ahora) do
        local pestana, hueco = k:match("(%d+):(%d+)")
        pestana, hueco = tonumber(pestana), tonumber(hueco)
        local ilvl = ilvlDelHueco(clave, pestana, hueco, itemID)
            or GetDetailedItemLevelInfo(GetGuildBankItemLink(pestana, hueco))
        if ilvl then
            local _, cantidad = GetGuildBankItemInfo(pestana, hueco)
            local c = itemID .. ":" .. ilvl
            copias[c] = (copias[c] or 0) + (cantidad or 1)
        end
    end
    apuntado()[clave] = { copias = copias, en = time() }
    exportar()
end

-- Cuantas copias de ese objeto e ilvl hay en el banco de la hermandad de este
-- personaje, segun la ultima vez que se abrio. nil si no se sabe: sin
-- hermandad, o sin haber abierto nunca su banco.
function B.Copias(itemID, ilvl)
    local clave = claveHermandad()
    local banco = clave and apuntado()[clave]
    if not banco then
        return nil
    end
    return banco.copias[itemID .. ":" .. ilvl] or 0
end

-- El ilvl apuntado del objeto de ese hueco, o nil si no se apunto al meterlo.
function B.Ilvl(pestana, hueco)
    local clave = claveHermandad()
    local itemID = itemDe(GetGuildBankItemLink(pestana, hueco))
    return clave and itemID and ilvlDelHueco(clave, pestana, hueco, itemID) or nil
end

-- Escribe el ilvl apuntado encima de cada icono de la pestana que miras.
local function pintar()
    if not (GuildBankFrame and GuildBankFrame.Columns) then
        return
    end
    local pestana = GetCurrentGuildBankTab()
    for _, columna in ipairs(GuildBankFrame.Columns) do
        for _, boton in ipairs(columna.Buttons) do
            if not boton.wowAlertsIlvl then
                boton.wowAlertsIlvl = boton:CreateFontString(nil, "OVERLAY", "NumberFontNormal")
                boton.wowAlertsIlvl:SetPoint("TOPLEFT", 2, -2)
            end
            local ilvl = B.Ilvl(pestana, boton:GetID())
            boton.wowAlertsIlvl:SetText(ilvl and tostring(ilvl) or "")
        end
    end
end

-- La ventana del banco es de un addon de Blizzard que se carga la primera vez
-- que se abre, asi que al cargar este fichero puede no existir todavia.
local enganchado = false
local function engancharVentana()
    if not enganchado and GuildBankFrame and GuildBankFrame.Update then
        hooksecurefunc(GuildBankFrame, "Update", pintar)
        enganchado = true
    end
end

local function apuntarCogido(enlace)
    local itemID = itemDe(enlace)
    local ilvl = enlace and GetDetailedItemLevelInfo(enlace)
    if abierto and itemID and ilvl then
        table.insert(cogidos, { itemID = itemID, ilvl = ilvl })
    end
end

-- Arrastrar desde la bolsa: lo que queda en el cursor es lo de la bolsa, con
-- sus bonus. Si no queda nada es que se ha soltado algo en la bolsa.
hooksecurefunc(C_Container, "PickupContainerItem", function()
    local tipo, _, enlace = GetCursorInfo()
    if tipo == "item" then
        apuntarCogido(enlace)
    end
end)
-- Clic derecho: el objeto sigue en la bolsa hasta que responde el servidor.
hooksecurefunc(C_Container, "UseContainerItem", function(bolsa, hueco)
    apuntarCogido(C_Container.GetContainerItemLink(bolsa, hueco))
end)

local function esBanquero(tipo)
    return Enum and Enum.PlayerInteractionType and tipo == Enum.PlayerInteractionType.GuildBanker
end

local eventos = CreateFrame("Frame")
eventos:RegisterEvent("PLAYER_INTERACTION_MANAGER_FRAME_SHOW")
eventos:RegisterEvent("PLAYER_INTERACTION_MANAGER_FRAME_HIDE")
eventos:RegisterEvent("GUILDBANKBAGSLOTS_CHANGED")
eventos:RegisterEvent("ADDON_LOADED")
eventos:SetScript("OnEvent", function(_, evento, tipo)
    if evento == "PLAYER_INTERACTION_MANAGER_FRAME_SHOW" then
        if esBanquero(tipo) then
            abierto = true
            engancharVentana()
            -- El juego solo trae la pestana que miras: se piden todas.
            for pestana = 1, GetNumGuildBankTabs() do
                local _, _, visible = GetGuildBankTabInfo(pestana)
                if visible then
                    QueryGuildBankTab(pestana)
                end
            end
        end
    elseif evento == "PLAYER_INTERACTION_MANAGER_FRAME_HIDE" then
        if esBanquero(tipo) then
            abierto = false
            cogidos = {}
            vistos = nil
        end
    elseif evento == "GUILDBANKBAGSLOTS_CHANGED" then
        leer()
        pintar()
    elseif evento == "ADDON_LOADED" then
        engancharVentana()
    end
end)
