-- La ventana "Tus subastas": que tienes puesto y que te han adelantado.
--
-- Solo dibuja. Quien clasifica es WowAlertsReposteo.Subastas(), y quien manda
-- redibujar es R.refrescarPanel().

local V = {}
WowAlertsVentana = V

local ANCHO = 360
local ALTO_FILA = 34
local ALTO_TITULO = 18
local ALTO_MAXIMO = 560
-- Lo que ocupan la barra de progreso y el boton de las que caducan, cada uno
-- con su hueco. Van apilados bajo la cabecera, y la lista empieza mas abajo y
-- la ventana crece lo que sumen los que se vean.
local ALTO_BARRA = 14
local HUECO_BARRA = 20
local ALTO_BOTON = 20
local HUECO_BOTON = 24
-- El del siguiente paso es mas alto: en la Steam Deck se pulsa con el dedo.
local ALTO_SIGUIENTE = 32
local HUECO_SIGUIENTE = 36

local COLORES = {
    adelantada = { 1, 0.29, 0.24, "ADELANTADAS" },
    reposteada = { 0.35, 0.7, 1, "RECIEN REPUESTAS" },
    primera = { 0.25, 0.85, 0.29, "VAS PRIMERO" },
    sinmirar = { 0.56, 0.53, 0.48, "SIN MIRAR TODAVIA" },
    novigilada = { 0.56, 0.53, 0.48, "NO VIGILADAS" },
}
local ORDEN = { "adelantada", "reposteada", "primera", "sinmirar", "novigilada" }

-- Lo que falta por postear a WowAlertsReposteo.ILVL_FALTAN, al final de la lista.
local COLOR_FALTAN = { 1, 0.82, 0 }

-- Cada fase del ciclo pinta la barra de su color, con el mismo codigo de
-- siempre: rojo lo que hay que arreglar, verde lo que ya esta puesto.
local FASES = {
    escaneo = { 0.25, 0.55, 1, "Escaneando" },
    cancelar = { 1, 0.45, 0.2, "Cancelando" },
    postear = { 0.25, 0.8, 0.35, "Reposteando" },
}

local marco, contenido, filas, cabecera, barra, botonCaducadas, botonSiguiente, scroll
local ocultaAdrede = false

-- Los nombres nuevos de estas dos viven en C_Item; se deja el viejo de
-- recambio por si el cliente aun no los tiene.
local datosDelObjeto = (C_Item and C_Item.GetItemInfo) or GetItemInfo
local colorDeCalidad = (C_Item and C_Item.GetItemQualityColor) or GetItemQualityColor

local function oro(cobre)
    return tostring(math.floor(cobre / 10000)) .. " o"
end

-- Las subastas solo a puja no tienen buyout, ni el rival tiene por que
-- tenerlo: Reposteo.lua avisa de que en esas subastas viene nil o 0. En vez
-- de ensenar "0 o", que se entienda que no hay precio fijo.
local function precioTexto(cobre)
    if not cobre or cobre == 0 then
        return "solo puja"
    end
    return oro(cobre)
end

-- Las bandas de Blizzard, para los clientes que no dan los segundos exactos.
local BANDAS = { [0] = "corto", [1] = "medio", [2] = "largo", [3] = "muy largo" }

-- Lo que le queda de listado: "11h 32m", "45m" o, sin segundos, la banda.
local function tiempoTexto(datos)
    local segundos = datos.segundos
    if segundos and segundos > 0 then
        local horas = math.floor(segundos / 3600)
        local minutos = math.floor((segundos % 3600) / 60)
        if horas > 0 then
            return ("%dh %02dm"):format(horas, minutos)
        end
        if minutos > 0 then
            return ("%dm"):format(minutos)
        end
        return "<1m"
    end
    return BANDAS[datos.banda] or ""
end

local function crearMarco()
    -- OJO: el nombre que se le da aqui a CreateFrame se convierte en un
    -- global (_G[nombre] = marco). Si se llamara "WowAlertsVentana", igual
    -- que la tabla del modulo de la linea 7, lo pisaria en cuanto se creara
    -- el marco por primera vez: WowAlertsVentana dejaria de ser esta tabla y
    -- pasaria a ser el Frame, que no tiene .Refrescar. A partir de ahi
    -- Reposteo.lua nunca mas conseguiria avisar a la ventana, sin ningun
    -- error en pantalla. Por eso el marco lleva un nombre distinto, como
    -- hace Reposteo.lua con su boton (WowAlertsReposteoBoton).
    marco = CreateFrame("Frame", "WowAlertsVentanaMarco", UIParent, "BasicFrameTemplateWithInset")
    marco:SetSize(ANCHO, 200)
    marco:SetFrameStrata("HIGH")
    -- Sin esto los clics le atraviesan y llegan al mundo 3D de detras (mueven
    -- la camara, cambian de objetivo...). No es movible a proposito -- cada
    -- Refrescar() la vuelve a anclar junto a la casa, asi que arrastrarla
    -- solo la haria saltar de vuelta en el primer evento -- pero si tiene que
    -- parar el raton.
    marco:EnableMouse(true)

    -- Consultado como hace RoutePlanner: solo se engancha si el campo existe,
    -- para que un cambio de Blizzard en la plantilla no reviente esto.
    if marco.CloseButton then
        marco.CloseButton:HookScript("OnClick", function()
            -- Solo cuenta como "cerrada a proposito" si la cierra el usuario
            -- con este boton. AUCTION_HOUSE_CLOSED tambien la esconde, pero
            -- eso no activa ocultaAdrede: se resetea a false en
            -- AUCTION_HOUSE_SHOW para que vuelva a salir la proxima vez que
            -- abras la casa.
            ocultaAdrede = true
        end)
    end

    -- No se toca marco.TitleText: segun el cliente, la plantilla lo trae
    -- directo o metido dentro de un TitleContainer, y no siempre existe de
    -- la misma forma. Se pone un titulo propio anclado a TitleBg, que es
    -- estable en BasicFrameTemplateWithInset desde hace mucho.
    marco.titulo = marco:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    marco.titulo:SetPoint("TOP", marco.TitleBg, "TOP", 0, -3)
    marco.titulo:SetText("Tus subastas")

    cabecera = marco:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cabecera:SetPoint("TOPLEFT", marco, "TOPLEFT", 14, -30)

    -- Lo mismo que la tecla de interaccion, para quien no tiene teclado (la
    -- Steam Deck). El clic es una pulsacion de verdad, asi que vale para
    -- cancelar y postear igual que la tecla.
    botonSiguiente = CreateFrame("Button", nil, marco, "UIPanelButtonTemplate")
    botonSiguiente:SetHeight(ALTO_SIGUIENTE)
    botonSiguiente:SetScript("OnClick", function()
        if WowAlertsReposteo and WowAlertsReposteo.Siguiente then
            WowAlertsReposteo.Siguiente()
        end
    end)
    botonSiguiente:Hide()

    -- El boton de las que caducan y la barra se anclan al pintarse: segun
    -- cuales se vean, van uno debajo del otro o solos pegados a la cabecera.
    botonCaducadas = CreateFrame("Button", nil, marco, "UIPanelButtonTemplate")
    botonCaducadas:SetHeight(ALTO_BOTON)
    -- Cancelar es una funcion protegida, igual que en la X de cada fila: este
    -- clic vale como cancelacion, pero solo como UNA. Por eso el boton no
    -- recorre la lista: cancela la mas urgente y el numero baja al refrescar.
    botonCaducadas:SetScript("OnClick", function()
        if not WowAlertsReposteo or not WowAlertsReposteo.Caducadas then
            return
        end
        local primera = WowAlertsReposteo.Caducadas()[1]
        if not primera then
            return
        end
        local motivo = WowAlertsReposteo.Cancelar(primera.auctionID)
        if motivo then
            print("|cff33ccffReposteo:|r no la he cancelado: " .. motivo)
        end
    end)
    botonCaducadas:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_LEFT")
        GameTooltip:SetText("Cancelar la mas urgente")
        GameTooltip:AddLine("Una por clic: el juego no deja encadenarlas.", 1, 1, 1)
        GameTooltip:AddLine("Solo las vigiladas, para poder reponerlas.", 1, 1, 1)
        GameTooltip:Show()
    end)
    botonCaducadas:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)
    botonCaducadas:Hide()

    barra = CreateFrame("StatusBar", nil, marco)
    barra:SetHeight(ALTO_BARRA)
    barra:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
    barra:SetMinMaxValues(0, 1)
    barra.fondo = barra:CreateTexture(nil, "BACKGROUND")
    barra.fondo:SetAllPoints(barra)
    barra.fondo:SetColorTexture(0, 0, 0, 0.5)
    barra.texto = barra:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    barra.texto:SetPoint("CENTER", barra, "CENTER", 0, 0)
    barra:Hide()

    scroll = CreateFrame("ScrollFrame", nil, marco, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", marco, "TOPLEFT", 10, -48)
    scroll:SetPoint("BOTTOMRIGHT", marco, "BOTTOMRIGHT", -30, 10)
    contenido = CreateFrame("Frame", nil, scroll)
    contenido:SetSize(ANCHO - 46, 10)
    scroll:SetScrollChild(contenido)

    filas = {}
end

-- Una fila reutilizable: icono, nombre, detalle e ilvl. El mismo indice se
-- reusa a veces como titulo de grupo y a veces como fila de subasta entre un
-- Refrescar() y el siguiente, asi que quien la pinte tiene que dejarla en su
-- estado completo (alto, anclas, visibilidad de icono) sin dar nada por
-- puesto de la vez anterior.
local function fila(indice)
    if filas[indice] then
        return filas[indice]
    end
    local f = CreateFrame("Frame", nil, contenido)
    f:SetSize(ANCHO - 50, ALTO_FILA)
    f.icono = f:CreateTexture(nil, "ARTWORK")
    f.icono:SetSize(26, 26)
    f.icono:SetPoint("LEFT", f, "LEFT", 0, 0)
    f.nombre = f:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    f.nombre:SetWidth(ANCHO - 170)
    f.nombre:SetJustifyH("LEFT")
    f.nombre:SetWordWrap(false)
    f.detalle = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    f.detalle:SetPoint("TOPLEFT", f.nombre, "BOTTOMLEFT", 0, -2)
    f.detalle:SetWidth(ANCHO - 170)
    f.detalle:SetJustifyH("LEFT")
    f.detalle:SetWordWrap(false)

    -- La columna de la derecha va pegada al lado del boton, y cada linea a la
    -- altura de la suya de la izquierda: dos anclas, una para la x (RIGHT del
    -- marco) y otra para la y (TOP de nombre y de detalle). Asi sigue cuadrada
    -- aunque el ilvl venga vacio, que pasa en las recetas.
    f.ilvl = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    f.ilvl:SetPoint("RIGHT", f, "RIGHT", -26, 0)
    f.ilvl:SetPoint("TOP", f.nombre, "TOP", 0, 0)
    f.tiempo = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    f.tiempo:SetPoint("RIGHT", f, "RIGHT", -26, 0)
    f.tiempo:SetPoint("TOP", f.detalle, "TOP", 0, 0)

    -- Cancelar es una funcion protegida: el juego solo la deja en respuesta a
    -- una tecla o un clic tuyo. Este clic lo es, asi que vale igual que la
    -- tecla del reposteo. Un clic, una cancelacion: nada encadenado.
    f.boton = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
    f.boton:SetSize(22, 20)
    f.boton:SetPoint("RIGHT", f, "RIGHT", 0, 0)
    f.boton:SetText("X")
    f.boton:SetScript("OnClick", function(self)
        local id = self:GetParent().auctionID
        if not id or not WowAlertsReposteo or not WowAlertsReposteo.Cancelar then
            return
        end
        local motivo = WowAlertsReposteo.Cancelar(id)
        if motivo then
            print("|cff33ccffReposteo:|r no la he cancelado: " .. motivo)
        end
    end)
    f.boton:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_LEFT")
        GameTooltip:SetText("Cancelar esta subasta")
        GameTooltip:Show()
    end)
    f.boton:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)

    -- Al pasar el raton, la ficha del objeto, como en las bolsas: la ventana
    -- solo cabe el nombre recortado, y con el mismo objeto puesto a varios
    -- ilvl a veces hay que ver cual es. Solo tiene `datos` una fila de
    -- subasta; los titulos de grupo la dejan a nil y no ensenan nada.
    -- EnableMouse no se come la rueda: esa va aparte (EnableMouseWheel), asi
    -- que la lista sigue desplazandose con el raton encima.
    f:EnableMouse(true)
    f:SetScript("OnEnter", function(self)
        local datos = self.datos
        if not datos then
            return
        end
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        -- Una mascota trae un enlace battlepet:, que la ficha de objetos no
        -- sabe pintar: esas van por el itemID. Y con pcall, porque una ficha
        -- que falla no debe dejar un error en pantalla por pasar el raton.
        local ok = false
        if datos.enlace and datos.enlace:find("|Hitem:", 1, true) then
            ok = pcall(GameTooltip.SetHyperlink, GameTooltip, datos.enlace)
        end
        if not ok and datos.itemID then
            ok = pcall(GameTooltip.SetItemByID, GameTooltip, datos.itemID)
        end
        if not ok then
            GameTooltip:SetText(self.nombre:GetText() or "")
        end
        if datos.grupo == "adelantada" then
            GameTooltip:AddLine(" ")
            GameTooltip:AddDoubleLine("Tu precio", precioTexto(datos.precio), 1, 1, 1, 1, 1, 1)
            if datos.igualada then
                GameTooltip:AddLine("Un rival te iguala al mismo precio.", 1, 0.29, 0.24)
            else
                GameTooltip:AddDoubleLine("Rival", precioTexto(datos.precioRival), 1, 1, 1, 1, 0.29, 0.24)
            end
        end
        GameTooltip:Show()
    end)
    f:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)

    filas[indice] = f
    return f
end

-- Un titulo de grupo: mas bajo que una fila y con el texto pegado al borde,
-- no indentado como si colgara de un icono que ni siquiera se ve.
local function titulo(indice, texto, r, g, b)
    local f = fila(indice)
    f:SetHeight(ALTO_TITULO)
    f.icono:Hide()
    f.nombre:ClearAllPoints()
    f.nombre:SetPoint("TOPLEFT", f, "TOPLEFT", 0, 0)
    f.nombre:SetText(texto)
    f.nombre:SetTextColor(r, g, b)
    f.detalle:SetText("")
    f.ilvl:SetText("")
    f.tiempo:SetText("")
    f.auctionID = nil
    f.datos = nil
    f.boton:Hide()
    f:Show()
    return f
end

local function pintarFila(indice, datos)
    local f = fila(indice)
    f:SetHeight(ALTO_FILA)
    f.auctionID = datos.auctionID
    f.datos = datos
    f.boton:Show()
    -- Apagada si ya se pidio cancelarla: un clic de mas no hace nada.
    f.boton:SetEnabled(not datos.cancelada)
    f.nombre:ClearAllPoints()
    f.nombre:SetPoint("TOPLEFT", f.icono, "TOPRIGHT", 6, 0)

    -- GetOwnedAuctionInfo deja el enlace a nil en las mercancias (Reposteo.lua
    -- ya se protege de lo mismo). Sin enlace, GetItemInfo acepta el itemID.
    -- Si faltaran los dos (no deberia pasar), cadena vacia antes que nil.
    local nombre, _, calidad, _, _, _, _, _, _, icono =
        datosDelObjeto(datos.enlace or datos.itemID or "")
    f.icono:SetTexture(icono or "Interface\\Icons\\INV_Misc_QuestionMark")
    f.icono:Show()

    local r, g, b = colorDeCalidad(calidad or 1)
    -- Si colorDeCalidad no devuelve nada (calidad rara, cache a medias),
    -- que no reviente por un SetTextColor(nil).
    r, g, b = r or 1, g or 1, b or 1
    f.nombre:SetText(nombre or (datos.enlace or ("Objeto " .. tostring(datos.itemID))))
    f.nombre:SetTextColor(r, g, b)

    if datos.grupo == "adelantada" then
        if datos.igualada then
            f.detalle:SetText(("%s  |cffff4a3d> te igualan|r"):format(precioTexto(datos.precio)))
        else
            f.detalle:SetText(("%s  |cffff4a3d> rival %s|r"):format(
                precioTexto(datos.precio), precioTexto(datos.precioRival)))
        end
    else
        f.detalle:SetText(precioTexto(datos.precio))
    end
    -- Las recetas y lo que no escala salen con ilvl 1: no se muestra.
    f.ilvl:SetText((datos.ilvl and datos.ilvl > 1) and tostring(datos.ilvl) or "")
    f.tiempo:SetText(tiempoTexto(datos))
    f:Show()
end

-- Una fila de lo que falta: no es una subasta, asi que sin X ni tiempo.
local function pintarFalta(indice, falta)
    local f = fila(indice)
    f:SetHeight(ALTO_FILA)
    f.auctionID = nil
    -- Con `datos` la ficha del objeto sale al pasar el raton, como en las demas.
    f.datos = { itemID = falta.itemID }
    f.boton:Hide()
    f.nombre:ClearAllPoints()
    f.nombre:SetPoint("TOPLEFT", f.icono, "TOPRIGHT", 6, 0)
    f.icono:SetTexture(falta.icono or "Interface\\Icons\\INV_Misc_QuestionMark")
    f.icono:Show()
    -- En el idioma del juego si ya esta en la cache; si no, el de config.yaml.
    f.nombre:SetText(datosDelObjeto(falta.itemID) or falta.nombre)
    f.nombre:SetTextColor(1, 1, 1)
    -- El precio llega con el escaneo: hasta entonces no se sabe.
    local precio
    if falta.precio == false then
        precio = "nadie lo vende"
    elseif falta.precio then
        precio = precioTexto(falta.precio)
    else
        precio = "|cff8f877asin mirar|r"
    end
    -- Lo del banco es de la ultima vez que lo abriste (ver BancoHermandad.lua).
    local copias = WowAlertsBanco and WowAlertsBanco.Copias(falta.itemID, WowAlertsReposteo.ILVL_FALTAN)
    local banco
    if copias == nil then
        banco = "|cff8f877abanco sin ver|r"
    elseif copias > 0 then
        banco = ("|cff40d84ben el banco: %d|r"):format(copias)
    else
        banco = "|cffff4a3dno en el banco|r"
    end
    f.detalle:SetText(precio .. "  -  " .. banco)
    f.ilvl:SetText(tostring(WowAlertsReposteo.ILVL_FALTAN))
    -- Un ilvl mejor que se lleva al comprador: mas barato o hasta 10k mas.
    if falta.pisa then
        f.tiempo:SetText(("|cffff4a3d%d a %s|r"):format(falta.pisa.ilvl, precioTexto(falta.pisa.precio)))
    else
        f.tiempo:SetText("")
    end
    f:Show()
end

-- Donde empieza lo que va apilado bajo la cabecera, mas lo que ya ocupe lo
-- que se haya pintado antes.
local function apilar(elemento, desplazamiento)
    elemento:ClearAllPoints()
    elemento:SetPoint("TOPLEFT", marco, "TOPLEFT", 14, -46 - desplazamiento)
    elemento:SetPoint("TOPRIGHT", marco, "TOPRIGHT", -16, -46 - desplazamiento)
end

-- El boton que cancela lo que esta a punto de caducar, con cuantas quedan.
-- Escondido si no hay ninguna: un boton en gris solo gastaria sitio.
-- Devuelve lo que ocupa, como la barra.
local function pintarBotonCaducadas(desplazamiento)
    if not WowAlertsReposteo.Caducadas then
        botonCaducadas:Hide()
        return 0
    end
    local cuantas = #WowAlertsReposteo.Caducadas()
    if cuantas == 0 then
        botonCaducadas:Hide()
        return 0
    end
    botonCaducadas:SetText(("Cancelar <8h (%d)"):format(cuantas))
    apilar(botonCaducadas, desplazamiento)
    botonCaducadas:Show()
    return HUECO_BOTON
end

-- El boton del siguiente paso, con lo que hara al pulsarlo. Devuelve lo que
-- ocupa, como la barra.
local function pintarBotonSiguiente(desplazamiento)
    if not WowAlertsReposteo.Siguiente or not WowAlertsReposteo.Estado then
        botonSiguiente:Hide()
        return 0
    end
    botonSiguiente:SetText(WowAlertsReposteo.Estado())
    if not WowAlertsReposteo.SePuedePulsar or WowAlertsReposteo.SePuedePulsar() then
        botonSiguiente:Enable()
    else
        botonSiguiente:Disable()
    end
    apilar(botonSiguiente, desplazamiento)
    botonSiguiente:Show()
    return HUECO_SIGUIENTE
end

-- Deja la barra contando lo que haya en marcha, o escondida si no hay nada.
-- Devuelve lo que ocupa, para que la lista y la ventana se ajusten.
local function pintarBarra(progreso, desplazamiento)
    local fase = progreso and FASES[progreso.fase]
    if not fase or (progreso.total or 0) <= 0 then
        barra:Hide()
        return 0
    end
    apilar(barra, desplazamiento)
    local hechos = math.min(progreso.hechos or 0, progreso.total)
    barra:SetStatusBarColor(fase[1], fase[2], fase[3])
    barra:SetValue(hechos / progreso.total)

    local que = ""
    -- Mientras escanea dice cual esta mirando: es lo que se tarda en ver, y
    -- asi sabes que no se ha quedado colgada. El nombre puede no estar aun en
    -- la cache del cliente, y entonces se queda solo con el recuento.
    if progreso.itemID and hechos < progreso.total then
        local nombre = datosDelObjeto(progreso.itemID)
        if nombre then
            que = " " .. nombre
        end
    end
    barra.texto:SetText(("%s%s  %s/%s"):format(fase[4], que, hechos, progreso.total))
    barra:Show()
    return HUECO_BARRA
end

function V.Refrescar()
    -- Se pregunta a AuctionHouseFrame, no a un flag propio tipo "casaAbierta"
    -- actualizado en AUCTION_HOUSE_SHOW/CLOSED. Un flag asi no arreglaria la
    -- carrera entre manejadores del mismo evento (seguiria dependiendo de si
    -- el de aqui corre antes o despues que el de Reposteo.lua, exactamente
    -- igual que con IsShown()) y encima rompe un caso real: si haces /reload
    -- con la casa ya abierta, el flag nace en false y la ventana no
    -- aparece hasta el siguiente cierre y apertura. Reposteo.lua tiene el
    -- mismo dilema y tambien resuelve casaAbierta() mirando IsShown()
    -- directamente. El caso de la carrera en si (un redibujado de mas en el
    -- mismo instante en que se cierra la casa) ya queda cubierto sin que se
    -- note: el manejador de AUCTION_HOUSE_CLOSED de aqui abajo esconde el
    -- marco decidiendo por el evento, no por este IsShown().
    if not AuctionHouseFrame or not AuctionHouseFrame:IsShown() then
        if marco then
            marco:Hide()
        end
        return
    end
    if ocultaAdrede then
        return
    end
    -- Si alguien desactiva Reposteo.lua, esto no debe reventar: no hay datos
    -- que pintar, asi que no se hace nada.
    if not WowAlertsReposteo or not WowAlertsReposteo.Subastas then
        return
    end
    if not marco then
        crearMarco()
    end

    local porGrupo = {}
    local total, adelantadas = 0, 0
    for _, datos in ipairs(WowAlertsReposteo.Subastas()) do
        porGrupo[datos.grupo] = porGrupo[datos.grupo] or {}
        table.insert(porGrupo[datos.grupo], datos)
        total = total + 1
        if datos.grupo == "adelantada" then
            adelantadas = adelantadas + 1
        end
    end

    cabecera:SetText(("%s  -  %s puestas  -  |cffff4a3d%s adelantadas|r"):format(
        UnitName("player"), total, adelantadas))

    local hueco = pintarBotonSiguiente(0)
    hueco = hueco + pintarBotonCaducadas(hueco)
    if WowAlertsReposteo.Progreso then
        hueco = hueco + pintarBarra(WowAlertsReposteo.Progreso(), hueco)
    end
    scroll:ClearAllPoints()
    scroll:SetPoint("TOPLEFT", marco, "TOPLEFT", 10, -48 - hueco)
    scroll:SetPoint("BOTTOMRIGHT", marco, "BOTTOMRIGHT", -30, 10)

    local indice, alto = 0, 0
    for _, grupo in ipairs(ORDEN) do
        local lista = porGrupo[grupo]
        if lista then
            local color = COLORES[grupo]
            indice = indice + 1
            local t = titulo(indice, color[4], color[1], color[2], color[3])
            t:ClearAllPoints()
            t:SetPoint("TOPLEFT", contenido, "TOPLEFT", 0, -alto)
            alto = alto + ALTO_TITULO
            for _, datos in ipairs(lista) do
                indice = indice + 1
                pintarFila(indice, datos)
                local f = filas[indice]
                f:ClearAllPoints()
                f:SetPoint("TOPLEFT", contenido, "TOPLEFT", 0, -alto)
                alto = alto + ALTO_FILA
            end
        end
    end
    local faltan = WowAlertsReposteo.Faltan and WowAlertsReposteo.Faltan() or {}
    if #faltan > 0 then
        indice = indice + 1
        local t = titulo(indice, ("FALTAN A %d (%d)"):format(WowAlertsReposteo.ILVL_FALTAN, #faltan),
            COLOR_FALTAN[1], COLOR_FALTAN[2], COLOR_FALTAN[3])
        t:ClearAllPoints()
        t:SetPoint("TOPLEFT", contenido, "TOPLEFT", 0, -alto)
        alto = alto + ALTO_TITULO
        for _, falta in ipairs(faltan) do
            indice = indice + 1
            pintarFalta(indice, falta)
            local f = filas[indice]
            f:ClearAllPoints()
            f:SetPoint("TOPLEFT", contenido, "TOPLEFT", 0, -alto)
            alto = alto + ALTO_FILA
        end
    end

    for sobra = indice + 1, #filas do
        filas[sobra]:Hide()
    end

    contenido:SetHeight(math.max(alto, 10))
    marco:SetHeight(math.min(alto + 70 + hueco, ALTO_MAXIMO))
    marco:ClearAllPoints()
    marco:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 4, 0)
    marco:Show()
end

-- ITEM_DATA_LOAD_RESULT llega en rafagas (un evento por cada objeto que se
-- cachea) mientras algo como TSM o Auctionator esta escaneando. Se agrupan
-- los redibujados igual que revisionProgramada en Reposteo.lua: si ya hay
-- uno pendiente, no se programa otro.
local SEGUNDOS_AGRUPADOS = 0.2
local redibujoProgramado = false

local function pedirRedibujado()
    if redibujoProgramado then
        return
    end
    redibujoProgramado = true
    C_Timer.After(SEGUNDOS_AGRUPADOS, function()
        redibujoProgramado = false
        V.Refrescar()
    end)
end

local eventos = CreateFrame("Frame")
eventos:RegisterEvent("AUCTION_HOUSE_SHOW")
eventos:RegisterEvent("AUCTION_HOUSE_CLOSED")
eventos:RegisterEvent("ITEM_DATA_LOAD_RESULT")
eventos:SetScript("OnEvent", function(_, evento)
    if evento == "AUCTION_HOUSE_CLOSED" then
        -- Se decide por el evento, no mirando IsShown(): este marco se
        -- registra al cargar el addon, pero la ventana de Blizzard carga
        -- bajo demanda, asi que este manejador puede correr ANTES de que la
        -- suya desaparezca. Si aqui se mirara AuctionHouseFrame:IsShown(),
        -- saldria verdadero todavia y Refrescar() volveria a mostrar la
        -- ventana justo cuando la casa se cierra.
        if marco then
            marco:Hide()
        end
        return
    end
    if evento == "AUCTION_HOUSE_SHOW" then
        -- Al abrir la casa vuelve, aunque la hubieras cerrado en la visita
        -- anterior.
        ocultaAdrede = false
        V.Refrescar()
        return
    end
    pedirRedibujado()
end)
