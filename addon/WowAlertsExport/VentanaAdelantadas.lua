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

local marco, titulo
local columnas = {}

-- El apunte de Reposteo.lua de ese personaje, si es de despues del volcado del
-- resumen. Uno anterior ya esta reflejado en el resumen, o es mas viejo que el.
local function apunteDe(reino, nombre, volcado)
    local vistas = WowAlertsExportDB and WowAlertsExportDB.adelantadasVistas
    local apunte = vistas and vistas[reino .. "-" .. nombre]
    if type(apunte) ~= "table" or type(apunte.en) ~= "number" or apunte.en <= volcado then
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
            filas = filas,
        }
    end
    local cuando = hace(time() - (tonumber(datos.pasada) or 0))
    local texto
    if total == 0 then
        texto = "Nada adelantado - " .. cuando
    else
        texto = ("Te han adelantado - %d %s - %s"):format(
            total, total == 1 and "subasta" or "subastas", cuando)
    end
    return { titulo = texto, total = total, cuentas = cuentas }
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
        texto = COLOR_ACTUAL .. texto .. "|r"
    end
    return texto
end

local function crearMarco()
    -- El nombre no puede ser el de la tabla del modulo: CreateFrame con nombre
    -- crea un global y pisaria WowAlertsVentanaAdelantadas (ver Ventana.lua).
    marco = CreateFrame("Frame", "WowAlertsAdelantadasMarco", UIParent, "BasicFrameTemplateWithInset")
    marco:SetFrameStrata("MEDIUM")
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
        c.lineas[j] = l
    end
    return l
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
        end
        for j = #cuenta.filas + 1, #c.lineas do
            c.lineas[j]:Hide()
        end
        masFilas = math.max(masFilas, #cuenta.filas)
    end
    for i = #datos.cuentas + 1, #columnas do
        columnas[i].cabecera:Hide()
        for _, l in ipairs(columnas[i].lineas) do
            l:Hide()
        end
    end
    marco:SetSize(math.max(1, #datos.cuentas) * ANCHO_COLUMNA + 28, 56 + masFilas * ALTO_LINEA)
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
