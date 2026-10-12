-- La ventana "Te han adelantado": el mismo resumen que el aviso de Discord,
-- para no tener que mirarlo cada vez que cambias de personaje.
--
-- El resumen llega en Adelantadas.lua (WowAlertsAdelantadas), que escribe
-- sync_subastas.py y WoW solo lee al cargar la interfaz. Lo que repones en el
-- juego lo apunta Reposteo.lua en WowAlertsExportDB.adelantadasVistas, y aqui
-- se cruza con el resumen para ir tachando sin esperar a la pasada siguiente.

local V = {}
WowAlertsVentanaAdelantadas = V

local ANCHO_COLUMNA = 170
local ALTO_LINEA = 14
local ICONO_ORO = "|TInterface\\MoneyFrame\\UI-GoldIcon:0|t"
-- WoW no tiene texto tachado: lo repuesto sale en gris con el visto bueno.
local ICONO_HECHO = "|TInterface\\RaidFrame\\ReadyCheck-Ready:0|t"
local COLOR_HECHO = "|cff808080"
local COLOR_ACTUAL = "|cffffd100"
local COLOR_SIGUIENTE = "|cff40ff40"
-- La franja detras de la linea del personaje actual y la del siguiente.
local FRANJA_ACTUAL = { 1, 0.82, 0, 0.18 }
local FRANJA_SIGUIENTE = { 0.25, 1, 0.25, 0.15 }
local ALTO_PIE = 18

local marco, titulo, pie
local columnas = {}

local function valido(apunte)
    return type(apunte) == "table" and type(apunte.en) == "number"
end

-- El apunte de ese personaje, si es de despues del volcado del resumen: uno
-- anterior ya esta reflejado en el resumen, o es mas viejo que el. Puede venir
-- de esta cuenta (Reposteo.lua, en WowAlertsExportDB) o de la otra (lo trae
-- sync_subastas.py en WowAlertsAdelantadas.vistas); gana el mas reciente.
local function apunteDe(reino, nombre, volcado)
    local clave = reino .. "-" .. nombre
    local propias = WowAlertsExportDB and WowAlertsExportDB.adelantadasVistas
    local deFuera = WowAlertsAdelantadas and WowAlertsAdelantadas.vistas
    local apunte = propias and propias[clave]
    local otro = type(deFuera) == "table" and deFuera[clave] or nil
    if not valido(apunte) or (valido(otro) and otro.en > apunte.en) then
        apunte = otro
    end
    if not valido(apunte) or apunte.en <= volcado then
        return nil
    end
    return apunte
end

local function hace(segundos)
    local minutos = math.floor(math.max(segundos, 0) / 60)
    if minutos < 60 then
        return "hace " .. minutos .. " min"
    end
    return "hace " .. math.floor(minutos / 60) .. " h"
end

-- A que personaje entrar al salir de este: en la columna de tu cuenta, el
-- primero sin tachar por debajo del actual, volviendo arriba al acabar. Solo de
-- tu cuenta, que son los unicos del selector. Si este personaje no sale en el
-- resumen, su cuenta la dice WowAlertsAdelantadas.personajes (la escribe
-- sync_subastas.py desde las carpetas de WoW) y se empieza por arriba.
-- Marca la fila con `siguiente` y devuelve su nombre, o nil.
local function marcarSiguiente(cuentas, personajes, clave)
    local columna, desde = nil, 0
    for _, cuenta in ipairs(cuentas) do
        for i, f in ipairs(cuenta.filas) do
            if f.actual then
                columna, desde = cuenta, i
            end
        end
    end
    if not columna then
        local miCuenta = type(personajes) == "table" and personajes[clave] or nil
        for _, cuenta in ipairs(cuentas) do
            if miCuenta and cuenta.cuenta == miCuenta then
                columna = cuenta
            end
        end
    end
    if not columna then
        return nil
    end
    local filas = columna.filas
    for paso = 1, #filas do
        local f = filas[(desde + paso - 1) % #filas + 1]
        if not f.hecho and not f.actual then
            f.siguiente = true
            return f.nombre
        end
    end
    return nil
end

function V.Lineas()
    local datos = WowAlertsAdelantadas
    if type(datos) ~= "table" or type(datos.cuentas) ~= "table" then
        return nil
    end
    local volcado = tonumber(datos.volcado) or 0
    local yo, miReino = UnitName("player"), GetRealmName()
    local total = 0
    local cuentas = {}
    for _, grupo in ipairs(datos.cuentas) do
        local filas = {}
        for _, p in ipairs(grupo.personajes or {}) do
            local n, caras = p.n or 0, p.caras or 0
            local apunte = apunteDe(p.reino or "", p.nombre or "", volcado)
            if apunte then
                n = (apunte.quedan or 0) + (apunte.pendientes or 0)
                caras = math.min(caras, n)
            end
            total = total + n
            filas[#filas + 1] = {
                nombre = p.nombre,
                n = n,
                caras = caras,
                hecho = n == 0,
                actual = p.nombre == yo and p.reino == miReino,
            }
        end
        cuentas[#cuentas + 1] = {
            nombre = grupo.cuenta and ("WoW " .. grupo.cuenta) or "Otros",
            cuenta = grupo.cuenta,
            filas = filas,
        }
    end
    local siguiente = marcarSiguiente(cuentas, datos.personajes, miReino .. "-" .. yo)
    local cuando = hace(time() - (tonumber(datos.pasada) or 0))
    local texto
    if total == 0 then
        texto = "Nada adelantado - " .. cuando
    else
        texto = ("Te han adelantado - %d %s - %s"):format(
            total, total == 1 and "subasta" or "subastas", cuando)
    end
    return { titulo = texto, total = total, cuentas = cuentas, siguiente = siguiente }
end

local function textoDeFila(f)
    if f.hecho then
        return COLOR_HECHO .. f.nombre .. "|r " .. ICONO_HECHO
    end
    local texto = f.nombre .. " - " .. f.n
    if f.caras > 0 then
        texto = texto .. " (" .. ICONO_ORO .. " " .. f.caras .. ")"
    end
    if f.actual then
        texto = COLOR_ACTUAL .. "> " .. texto .. "|r"
    elseif f.siguiente then
        texto = COLOR_SIGUIENTE .. texto .. "|r"
    end
    return texto
end

local function crearMarco()
    -- El nombre no puede ser el de la tabla del modulo: CreateFrame con nombre
    -- crea un global y pisaria WowAlertsVentanaAdelantadas (ver Ventana.lua).
    marco = CreateFrame("Frame", "WowAlertsAdelantadasMarco", UIParent, "BasicFrameTemplateWithInset")
    -- Por encima de la casa de subastas, que va en HIGH y la tapaba. No en
    -- DIALOG: ahi van los avisos de confirmacion del juego (el del precio al
    -- postear, por ejemplo) y esta ventana no debe taparlos.
    marco:SetFrameStrata("HIGH")
    marco:SetFrameLevel(100)
    marco:EnableMouse(true)
    marco:SetMovable(true)
    marco:SetClampedToScreen(true)
    marco:RegisterForDrag("LeftButton")
    marco:SetScript("OnDragStart", function(self) self:StartMoving() end)
    marco:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        local punto, _, relativo, x, y = self:GetPoint()
        WowAlertsExportDB = WowAlertsExportDB or {}
        WowAlertsExportDB.posicionAdelantadas = { punto = punto, relativo = relativo, x = x, y = y }
    end)
    local pos = WowAlertsExportDB and WowAlertsExportDB.posicionAdelantadas
    if type(pos) == "table" and pos.punto then
        marco:SetPoint(pos.punto, UIParent, pos.relativo or pos.punto, pos.x or 0, pos.y or 0)
    else
        marco:SetPoint("TOP", UIParent, "TOP", 0, -120)
    end
    -- Titulo propio anclado a TitleBg, como en Ventana.lua.
    titulo = marco:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    titulo:SetPoint("TOP", marco.TitleBg, "TOP", 0, -3)
    pie = marco:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    pie:SetPoint("BOTTOMLEFT", marco, "BOTTOMLEFT", 14, 10)
end

local function columna(i)
    local c = columnas[i]
    if not c then
        c = { lineas = {} }
        c.cabecera = marco:CreateFontString(nil, "OVERLAY", "GameFontNormal")
        c.cabecera:SetPoint("TOPLEFT", marco, "TOPLEFT", 14 + (i - 1) * ANCHO_COLUMNA, -30)
        columnas[i] = c
    end
    return c
end

local function linea(c, j)
    local l = c.lineas[j]
    if not l then
        l = marco:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        l:SetPoint("TOPLEFT", c.cabecera, "BOTTOMLEFT", 0, -4 - (j - 1) * ALTO_LINEA)
        l.franja = marco:CreateTexture(nil, "BACKGROUND")
        l.franja:SetPoint("TOPLEFT", l, "TOPLEFT", -4, 2)
        l.franja:SetSize(ANCHO_COLUMNA - 6, ALTO_LINEA)
        c.lineas[j] = l
    end
    return l
end

local function pintarFranja(l, f)
    local color = (f.actual and FRANJA_ACTUAL) or (f.siguiente and FRANJA_SIGUIENTE)
    if color then
        l.franja:SetColorTexture(color[1], color[2], color[3], color[4])
        l.franja:Show()
    else
        l.franja:Hide()
    end
end

local function dibujar(datos)
    titulo:SetText(datos.titulo)
    local masFilas = 0
    for i, cuenta in ipairs(datos.cuentas) do
        local c = columna(i)
        c.cabecera:SetText(cuenta.nombre)
        c.cabecera:Show()
        for j, f in ipairs(cuenta.filas) do
            local l = linea(c, j)
            l:SetText(textoDeFila(f))
            l:Show()
            pintarFranja(l, f)
        end
        for j = #cuenta.filas + 1, #c.lineas do
            c.lineas[j]:Hide()
            c.lineas[j].franja:Hide()
        end
        masFilas = math.max(masFilas, #cuenta.filas)
    end
    for i = #datos.cuentas + 1, #columnas do
        columnas[i].cabecera:Hide()
        for _, l in ipairs(columnas[i].lineas) do
            l:Hide()
            l.franja:Hide()
        end
    end
    -- Abajo, a quien entrar al salir: en el selector de personajes no corre
    -- ningun addon, asi que hay que verlo antes de salir.
    local alto = 56 + masFilas * ALTO_LINEA
    if datos.siguiente then
        pie:SetText(COLOR_SIGUIENTE .. "Siguiente: " .. datos.siguiente .. "|r")
        pie:Show()
        alto = alto + ALTO_PIE
    else
        pie:Hide()
    end
    -- Nunca mas estrecha que dos columnas: con una sola no cabria el titulo.
    marco:SetSize(math.max(2, #datos.cuentas) * ANCHO_COLUMNA + 28, alto)
end

-- La redibuja si esta abierta. No la abre: eso solo al entrar o con /wa.
function V.Refrescar()
    if not marco or not marco:IsShown() then
        return
    end
    local datos = V.Lineas()
    if not datos then
        marco:Hide()
        return
    end
    dibujar(datos)
end

function V.Mostrar()
    local datos = V.Lineas()
    if not datos then
        print("|cffffd200WoW Alerts|r: todavia no ha llegado ningun resumen de lo adelantado.")
        return
    end
    if not marco then
        crearMarco()
    end
    dibujar(datos)
    marco:Show()
end

function V.Alternar()
    if marco and marco:IsShown() then
        marco:Hide()
    else
        V.Mostrar()
    end
end

-- Al entrar con un personaje (o tras /reload) se abre sola si queda algo. Si la
-- cierras, no vuelve hasta la siguiente carga de la interfaz.
local eventos = CreateFrame("Frame")
eventos:RegisterEvent("PLAYER_LOGIN")
eventos:SetScript("OnEvent", function()
    local datos = V.Lineas()
    if datos and datos.total > 0 then
        V.Mostrar()
    end
end)
