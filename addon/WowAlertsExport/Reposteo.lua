-- Reposteo con una tecla.
--
-- Cancelar lo adelantado, recoger el correo y volver a postear, pulsando una
-- sola tecla. Cada pulsacion hace UNA accion y nunca mas: cancelar, postear,
-- confirmar y recoger correo solo funcionan en respuesta directa a una tecla o
-- un clic, y encadenarlas es justo lo que el juego bloquea. Es lo mismo que
-- hace la tecla de "Cancel Undercut" de Auctionator.
--
-- Que objetos se repostean y que personajes son tuyos lo dice Vigilados.lua,
-- que genera generar_vigilados.py desde config.yaml.

local R = {}
WowAlertsReposteo = R

local function vigilados()
    return WowAlertsVigilados or { objetos = {}, personajes = {}, duracion = 1 }
end

-- Traza de cada pulsacion y de lo que responde el juego, para averiguar por
-- que una pulsacion no hace nada. No sale en el chat: se guarda en disco y se
-- lee tras un /reload.
local TRAZA = true

-- Como string.format con %s, pero un nil o un fallo no rompe nada: la traza
-- nunca debe romper lo que esta contando.
local function formatear(texto, ...)
    local n = select("#", ...)
    local valores = { ... }
    for i = 1, n do
        valores[i] = tostring(valores[i])
    end
    local ok, linea = pcall(string.format, texto, unpack(valores, 1, n))
    return ok and linea or texto
end

-- Lineas de traza que se guardan en WowAlertsExportDB.trazaReposteo, para
-- leerlas desde fuera del juego tras un /reload.
local LINEAS_GUARDADAS = 500

local function traza(texto, ...)
    if not TRAZA then
        return
    end
    local linea = formatear(texto, ...)
    WowAlertsExportDB = WowAlertsExportDB or {}
    local guardadas = WowAlertsExportDB.trazaReposteo or {}
    WowAlertsExportDB.trazaReposteo = guardadas
    local hora = (date and date("%H:%M:%S")) or ""
    guardadas[#guardadas + 1] = formatear("%s %s %s", hora, ("%.1f"):format(GetTime()), linea)
    while #guardadas > LINEAS_GUARDADAS do
        table.remove(guardadas, 1)
    end
end

local function oro(cobre)
    if not cobre then
        return "?"
    end
    return tostring(math.floor(cobre / 10000)) .. "g"
end

-- Se definen mas abajo, con las funciones de la bolsa.
local resumenCola
local copiasEnBolsa
local comprobarFin

-- ---------------------------------------------------------------------------
--  Quien te adelanta
-- ---------------------------------------------------------------------------

-- La misma regla que wowalerts/undercut.py: mas barata adelanta siempre; al
-- mismo precio, solo la publicada despues, y el id de subasta crece con el
-- tiempo.
function R.vaPorDelante(rival, mia)
    if rival.buyout < mia.buyout then
        return true
    end
    return rival.buyout == mia.buyout and rival.auctionID > mia.auctionID
end

local function sinReino(nombre)
    return (tostring(nombre):match("^([^%-]+)"))
end

-- Tus personajes como conjunto, para mirar un nombre de un vistazo. Se
-- rehace solo si cambia la lista: esto se consulta por cada fila de cada
-- resultado de busqueda, y cada subasta tuya repasa todas las filas.
local listaDeMios, mios = nil, {}

local function misPersonajes()
    local lista = vigilados().personajes
    if lista ~= listaDeMios then
        mios = {}
        for _, nombre in ipairs(lista) do
            mios[nombre] = true
        end
        listaDeMios = lista
    end
    return mios
end

-- Lo tuyo no compite contigo. El juego marca lo de este personaje y lo de su
-- cuenta de juego, pero no lo de tus otras cuentas (WoW 2 y WoW 3): esos se
-- reconocen por el nombre.
function R.esNuestro(resultado)
    if resultado.containsOwnerItem or resultado.containsAccountItem then
        return true
    end
    local mios = misPersonajes()
    for _, dueno in ipairs(resultado.owners or {}) do
        if mios[sinReino(dueno)] then
            return true
        end
    end
    return false
end

-- ---------------------------------------------------------------------------
--  La cola
-- ---------------------------------------------------------------------------
--  Una lista por personaje en WowAlertsExportDB.reposteo, para que sobreviva a
--  la ida al buzon, a un /reload y a cerrar el juego. Cada entrada pasa por
--  cuatro estados: "cancelar", "cancelando" (esperando AUCTION_CANCELED),
--  "devuelta" y "posteando" (esperando AUCTION_HOUSE_AUCTION_CREATED), y sale
--  de la cola cuando el juego crea la subasta (o cuando se olvida).

-- Horas que vive una entrada. Con listados de 12 h, algo que lleva dos dias en
-- la cola ya no describe nada que haya que repostear.
local HORAS_DE_VIDA = 48

local function clavePersonaje()
    return GetRealmName() .. "-" .. UnitName("player")
end

-- Se lee WowAlertsExportDB cada vez y no se guarda en una local: WoW reemplaza
-- esa tabla por la de disco despues de cargar este fichero.
local function cola()
    WowAlertsExportDB = WowAlertsExportDB or {}
    WowAlertsExportDB.reposteo = WowAlertsExportDB.reposteo or {}
    local clave = clavePersonaje()
    WowAlertsExportDB.reposteo[clave] = WowAlertsExportDB.reposteo[clave] or {}
    return WowAlertsExportDB.reposteo[clave]
end

local function buscarEntrada(auctionID)
    for i, entrada in ipairs(cola()) do
        if entrada.auctionID == auctionID then
            return entrada, i
        end
    end
    return nil, nil
end

local function quitarEntrada(auctionID)
    local _, i = buscarEntrada(auctionID)
    if i then
        table.remove(cola(), i)
    end
end

local function claveObjeto(itemID, ilvl)
    return tostring(itemID) .. ":" .. tostring(ilvl)
end

-- claveObjeto -> { itemKey, precio }: lo ultimo que se sabe que tenias puesto
-- de cada objeto e ilvl, por personaje. Una subasta que caduca vuelve por
-- correo sin su precio, y sin nadie mas vendiendo ese objeto se repone a este.
-- Se guarda en disco: la subasta caduca horas despues, con el juego cerrado o
-- en otro personaje.
local function preciosPuestos()
    WowAlertsExportDB = WowAlertsExportDB or {}
    WowAlertsExportDB.preciosPuestos = WowAlertsExportDB.preciosPuestos or {}
    local clave = clavePersonaje()
    WowAlertsExportDB.preciosPuestos[clave] = WowAlertsExportDB.preciosPuestos[clave] or {}
    return WowAlertsExportDB.preciosPuestos[clave]
end

-- ---------------------------------------------------------------------------
--  La busqueda
-- ---------------------------------------------------------------------------

local function casaAbierta()
    return AuctionHouseFrame ~= nil and AuctionHouseFrame:IsShown()
end

local function claveDe(itemKey)
    return itemKey.itemID .. ":" .. (itemKey.itemLevel or 0) .. ":" .. (itemKey.itemSuffix or 0)
end

-- Todo esto vive en locales a proposito: cerrar la casa o hacer /reload obliga
-- a buscar otra vez, que es lo correcto, porque los precios han podido moverse.
local buscadoEnEstaVisita = false
local grupos = {}        -- clave -> { itemKey, mias = {...}, devueltas = {...} }
local ordenGrupos = {}
local siguienteGrupo = 1
local esperando = nil    -- clave del grupo cuya respuesta se espera
local repasadas = {}     -- auctionID -> true: devueltas con el precio al dia

-- auctionID -> true: adelantadas que la busqueda de esta visita ha confirmado.
-- Cancelar cuesta el deposito, asi que no se cancela con datos de otra visita.
local confirmadas = {}

-- auctionID -> lo que hace falta para pintar en la ventana una subasta que
-- acabas de poner con la tecla, hasta que cierres la casa. La lista de tus
-- subastas tarda un momento en traer la nueva, asi que mientras tanto la
-- ventana la pinta con esto (ver SEGUNDOS_SIN_LISTA y R.Subastas).
local reposteadas = {}
local SEGUNDOS_SIN_LISTA = 30

-- auctionID -> time() de la ultima busqueda que la vio sin nadie delante. Al
-- volver a repostear un momento despues no hace falta mirar otra vez esos
-- objetos, solo lo devuelto.
--
-- Vive en WowAlertsExportDB y no en una local. Cambiar de personaje recarga el
-- entorno de Lua igual que un /reload, asi que con una local esto se borraba
-- en cada salto y no llegaba a servir de nada: se volvia a buscar todo. Y
-- buscar es justo lo caro, porque la casa reparte sus consultas con
-- cuentagotas: medido sobre la traza, el 79 % de un escaneo es esperar a que
-- admita la siguiente, no la respuesta en si.
--
-- Se guarda time() y no GetTime() porque esta tabla ya no muere con la sesion:
-- GetTime() cuenta desde que arranco el cliente, asi que al reiniciar el juego
-- vuelve a cero y las marcas guardadas quedarian en el futuro, es decir,
-- recientes para siempre, y no se buscaria nada nunca mas.
local SEGUNDOS_VISTA_LIMPIA = 300

-- Se lee WowAlertsExportDB cada vez, como en cola(): WoW reemplaza esa tabla
-- por la de disco despues de cargar este fichero.
local function vistaLimpia()
    WowAlertsExportDB = WowAlertsExportDB or {}
    WowAlertsExportDB.vistaLimpia = WowAlertsExportDB.vistaLimpia or {}
    return WowAlertsExportDB.vistaLimpia
end

local function esReciente(cuando)
    return type(cuando) == "number" and time() - cuando < SEGUNDOS_VISTA_LIMPIA
end

local function vistaLimpiaReciente(auctionID)
    return esReciente(vistaLimpia()[auctionID])
end

-- Apunta que esa subasta va primera, o lo borra con `cuando` a nil. De paso
-- tira lo caducado: sin podar, la tabla se quedaria con una entrada por cada
-- subasta que haya pasado por la casa y se escribiria entera en disco.
local function apuntarVistaLimpia(auctionID, cuando)
    local tabla = vistaLimpia()
    tabla[auctionID] = cuando
    -- Se poda con la misma regla que se consulta: con dos reglas distintas,
    -- una marca justo en el borde se guardaria para siempre sin que nadie la
    -- diera nunca por buena.
    for id, visto in pairs(tabla) do
        if not esReciente(visto) then
            tabla[id] = nil
        end
    end
end

-- El mayor id de subasta propia visto en la ultima busqueda. Los ids crecen
-- con el tiempo: sirve solo para reconocer, al buscar, un posteo de la tecla
-- cuyo aviso de creacion nunca llego, comparando con el id apuntado al postear.
local maxIdVisto = 0

-- La lista de subastas propias llega por partes, y la primera respuesta tras
-- abrir la casa viene vacia (ver WowAlertsExport.lua). Buscar con la lista a
-- medias borraria de la cola lo que no apareciera. Al abrir se pide la lista
-- (la peticion del exportador suele descartarse, porque la casa aun esta
-- ocupada) y, como Auctionator, se fia de lo que llegue despues de pedirla,
-- en cuanto lleva un momento sin cambiar. Si llega vacia no se sabe si es de
-- verdad, y se espera a que la casa lleve unos segundos abierta.
local SEGUNDOS_PARA_FIARSE = 5
local SEGUNDOS_DE_CALMA = 0.5
local abiertaEn = nil       -- GetTime() al abrir la casa
local recibidasEn = nil     -- GetTime() de la ultima OWNED_AUCTIONS_UPDATED
local listaPedidaEn = nil   -- GetTime() de la ultima peticion propia de la lista
local faltaPedirLista = false
-- En el juego la lista llega varias veces por segundo tras abrir. Si llega dos
-- veces seguidas con las mismas subastas, y no vacia, ya esta entera.
local cuentaAnterior = nil
local listaRepetida = false

local function subastasListas()
    if abiertaEn == nil or recibidasEn == nil or recibidasEn < abiertaEn then
        return false
    end
    if GetTime() - abiertaEn >= SEGUNDOS_PARA_FIARSE or listaRepetida then
        return true
    end
    return listaPedidaEn ~= nil and recibidasEn >= listaPedidaEn
        and C_AuctionHouse.GetNumOwnedAuctions() > 0
        and GetTime() - recibidasEn >= SEGUNDOS_DE_CALMA
end

-- Pide la lista si falta y la casa la admite ahora; si no, se reintenta con
-- AUCTION_HOUSE_THROTTLED_SYSTEM_READY.
local function pedirLista()
    if not faltaPedirLista or not casaAbierta() or not C_AuctionHouse.IsThrottledMessageSystemReady() then
        return
    end
    faltaPedirLista = false
    listaPedidaEn = GetTime()
    traza("pido la lista de tus subastas")
    C_AuctionHouse.QueryOwnedAuctions({})
end

-- Si la respuesta a una busqueda no llega en este tiempo (mensaje perdido,
-- otra busqueda del juego o de otro addon por medio), se salta ese objeto en
-- esta visita sin tocar su cola.
local SEGUNDOS_DE_ESPERA = 10
local consulta = 0        -- numero de la ultima busqueda enviada

-- El ilvl del que quieres tener puesto un ejemplar de cada objeto vigilado.
-- Lo que falte sale en la ventana, con el precio al que esta en la casa.
R.ILVL_FALTAN = 308

-- Lo que se sabe del precio de lo que falta, por personaje e itemID:
--   precio: buyout del mas barato que no es tuyo a R.ILVL_FALTAN, o false si
--           nadie lo vende; con `en`, el time() en que se busco.
--   mejores: { [ilvl] = minimo } de los ilvl por encima, de la busqueda por
--           nombre, para avisar de cuando uno mejor te pisa (ver R.Faltan);
--           con `mejoresEn`.
-- Se busca una vez y vale SEGUNDOS_PRECIOS_FALTAN: abrir otra vez la casa, un
-- /reload o cambiar de personaje no lo repite. Vive en WowAlertsExportDB y se
-- lee cada vez, como cola(): WoW reemplaza esa tabla al cargar.
local SEGUNDOS_PRECIOS_FALTAN = 3600

local function preciosFaltan()
    WowAlertsExportDB = WowAlertsExportDB or {}
    WowAlertsExportDB.preciosFaltan = WowAlertsExportDB.preciosFaltan or {}
    local clave = clavePersonaje()
    WowAlertsExportDB.preciosFaltan[clave] = WowAlertsExportDB.preciosFaltan[clave] or {}
    return WowAlertsExportDB.preciosFaltan[clave]
end

local function alDia(cuando)
    return type(cuando) == "number" and time() - cuando < SEGUNDOS_PRECIOS_FALTAN
end

-- Lo apuntado de ese objeto: el precio a R.ILVL_FALTAN (nil si no esta al dia)
-- y los ilvl mejores (nil igual).
local function apuntadoDe(itemID)
    local e = preciosFaltan()[itemID] or {}
    local precio, mejores = nil, nil
    if alDia(e.en) then
        precio = e.precio
    end
    if alDia(e.mejoresEn) then
        mejores = e.mejores
    end
    return precio, mejores
end

local function apuntarFalta(itemID, campo, valor, campoEn)
    local tabla = preciosFaltan()
    -- De paso se tira lo viejo, para que la tabla no crezca en disco.
    for id, e in pairs(tabla) do
        if not alDia(e.en) and not alDia(e.mejoresEn) then
            tabla[id] = nil
        end
    end
    tabla[itemID] = tabla[itemID] or {}
    tabla[itemID][campo] = valor
    tabla[itemID][campoEn] = time()
end

-- Lo que un comprador paga de mas sin pensarlo por el ilvl mejor: lo mismo que
-- MARGEN_PISA_ORO en la app.
local MARGEN_PISA = 10000 * 10000

local function reiniciarBusqueda()
    grupos, ordenGrupos, siguienteGrupo, esperando = {}, {}, 1, nil
end

local function buscando()
    return buscadoEnEstaVisita and siguienteGrupo <= #ordenGrupos
end

local function anadirAGrupo(itemKey)
    local clave = claveDe(itemKey)
    if not grupos[clave] then
        grupos[clave] = {
            itemKey = {
                itemID = itemKey.itemID,
                itemLevel = itemKey.itemLevel,
                itemSuffix = itemKey.itemSuffix,
            },
            mias = {},
            devueltas = {},
        }
        ordenGrupos[#ordenGrupos + 1] = clave
    end
    return grupos[clave]
end

-- El ilvl del enlace manda; el del itemKey es solo el recambio cuando el
-- enlace no esta (WoW no siempre lo rellena). La cola y la ventana tienen
-- que decir el mismo ilvl para la misma subasta, asi que las dos llaman aqui.
local function ilvlDe(info, itemKey)
    return (info.itemLink and GetDetailedItemLevelInfo(info.itemLink)) or itemKey.itemLevel
end

-- Agrupa por objeto e ilvl lo que hay que mirar, y de paso limpia la cola.
-- Apunta el precio de lo que tienes puesto, para cuando caduque (ver
-- preciosPuestos). Se llama con cada lista de tus subastas que llega, y no solo
-- al buscar: lo que pones a mano o con TSM despues de la busqueda tambien
-- caduca, y la busqueda de la visita siguiente llega tarde. Solo anade o
-- actualiza, nunca borra, asi que una lista a medias no hace dano.
local function apuntarPrecios()
    local objetos = vigilados().objetos
    local baratas = {}  -- claveObjeto -> { itemKey, precio } de la mas barata
    for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(i)
        local itemKey = info and info.itemKey
        if info and info.status == 0 and (info.buyoutAmount or 0) > 0
            and itemKey and objetos[itemKey.itemID] then
            local clave = claveObjeto(itemKey.itemID, ilvlDe(info, itemKey))
            if not baratas[clave] or info.buyoutAmount < baratas[clave].precio then
                baratas[clave] = { itemKey = itemKey, precio = info.buyoutAmount }
            end
        end
    end

    -- De varias copias puestas no se sabe cual caducara: se apunta la mas
    -- barata. Lo que ya no esta puesto conserva lo ultimo que se supo.
    local precios = preciosPuestos()
    for clave, barata in pairs(baratas) do
        precios[clave] = {
            itemKey = {
                itemID = barata.itemKey.itemID,
                itemLevel = barata.itemKey.itemLevel,
                itemSuffix = barata.itemKey.itemSuffix,
            },
            precio = barata.precio,
        }
    end
end

local function prepararBusqueda()
    reiniciarBusqueda()
    local objetos = vigilados().objetos
    local activas = {}
    local nuevas = {}   -- claveObjeto -> ids de subastas activas de ese objeto

    for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(i)
        local itemKey = info and info.itemKey
        if info and info.auctionID and info.auctionID > maxIdVisto then
            maxIdVisto = info.auctionID
        end
        -- status 0 es activa, 1 es vendida y pendiente de cobro. Las dos
        -- prueban que el juego creo un posteo de la tecla, aunque no llegara
        -- el aviso, pero solo la activa entra en la busqueda de undercuts.
        if info and (info.status == 0 or info.status == 1) and (info.buyoutAmount or 0) > 0
            and itemKey and objetos[itemKey.itemID] then
            local ilvl = ilvlDe(info, itemKey)
            if info.status == 0 then
                activas[info.auctionID] = true
                local grupo = anadirAGrupo(itemKey)
                grupo.mias[#grupo.mias + 1] = {
                    auctionID = info.auctionID,
                    buyout = info.buyoutAmount,
                    itemID = itemKey.itemID,
                    ilvl = ilvl,
                }
            end
            local clave = claveObjeto(itemKey.itemID, ilvl)
            nuevas[clave] = nuevas[clave] or {}
            table.insert(nuevas[clave], { id = info.auctionID, buyout = info.buyoutAmount })
        end
    end

    apuntarPrecios()

    -- Si hay una subasta activa de ese objeto posterior a `tope` y a `precio`
    -- que no haya servido ya para otra entrada.
    local usadas = {}
    local function hayUnaPosterior(clave, tope, precio)
        for _, s in ipairs(nuevas[clave] or {}) do
            if s.id > tope and s.buyout == precio and not usadas[s.id] then
                usadas[s.id] = true
                return true
            end
        end
        return false
    end

    -- Cualquier subasta de ese objeto posterior a `tope`, a cualquier precio.
    local function hayUnaNueva(clave, tope)
        for _, s in ipairs(nuevas[clave] or {}) do
            if s.id > tope and not usadas[s.id] then
                usadas[s.id] = true
                return true
            end
        end
        return false
    end

    local ahora = time()
    local entradas = cola()
    local porRepasar = {}   -- devueltas que siguen en la cola, de la mas nueva a la mas vieja
    for i = #entradas, 1, -1 do
        local e = entradas[i]
        if ahora - (e.desde or 0) > HORAS_DE_VIDA * 3600 then
            traza("olvido %s: lleva mas de %s h en la cola", e.auctionID, HORAS_DE_VIDA)
            table.remove(entradas, i)
        elseif e.estado == "cancelar" or e.estado == "cancelando" then
            if activas[e.auctionID] then
                -- Sigue activa: si estaba "cancelando", el juego rechazo la
                -- cancelacion, y vuelve a la fila.
                if e.estado == "cancelando" then
                    traza("%s sigue activa: el juego no la cancelo", e.auctionID)
                end
                e.estado = "cancelar"
            else
                -- Ya no esta: vendida o caducada antes de poder cancelarla.
                traza("olvido %s: ya no esta entre tus subastas", e.auctionID)
                table.remove(entradas, i)
            end
        elseif e.estado == "devuelta" or e.estado == "posteando" then
            if e.estado == "posteando" and e.idTope
                and hayUnaPosterior(claveObjeto(e.itemID, e.ilvl), e.idTope, e.precio) then
                -- El posteo de la tecla si se creo aunque no llegara el aviso
                -- (o se acepto desde el aviso de Blizzard): hay una subasta tuya
                -- de ese objeto, posterior y a ese precio. Con lo devuelto no se
                -- hace: otra copia puesta a mano no dice nada de esta.
                traza("olvido %s: su posteo si se creo", e.auctionID)
                table.remove(entradas, i)
            else
                -- Un posteo del que no llego respuesta vuelve a la fila.
                e.estado = "devuelta"
                porRepasar[#porRepasar + 1] = e
            end
        end
    end

    -- Lo devuelto que ya no esta en la bolsa, cuando hay una subasta tuya de
    -- ese objeto creada despues de cancelarlo: lo has vuelto a poner a mano.
    -- Con el buzon de TSM el addon no ve el correo y no podria notarlo alli, y
    -- se quedaria en la cola pidiendo ir al buzon. Una subasta que ya estaba
    -- antes de cancelar no cuenta: la copia cancelada puede seguir en el correo.
    local porObjeto, objetosEnOrden = {}, {}
    for _, e in ipairs(porRepasar) do
        local clave = claveObjeto(e.itemID, e.ilvl)
        if not porObjeto[clave] then
            porObjeto[clave] = {}
            objetosEnOrden[#objetosEnOrden + 1] = clave
        end
        table.insert(porObjeto[clave], e)
    end
    local olvidadas = {}
    for _, clave in ipairs(objetosEnOrden) do
        local lista = porObjeto[clave]
        local sinCopia = #lista - copiasEnBolsa(lista[1].itemID, lista[1].ilvl)
        for k = #lista, 1, -1 do   -- de la mas vieja a la mas nueva
            local e = lista[k]
            if sinCopia <= 0 then
                break
            end
            if hayUnaNueva(clave, e.idTopeCancelada or e.auctionID) then
                traza("olvido %s: repuesta a mano (sin copia en la bolsa y con una subasta nueva)", e.auctionID)
                olvidadas[e] = true
                sinCopia = sinCopia - 1
            end
        end
    end
    for i = #entradas, 1, -1 do
        if olvidadas[entradas[i]] then
            table.remove(entradas, i)
        end
    end
    for _, e in ipairs(porRepasar) do
        if not olvidadas[e] then
            local grupo = anadirAGrupo(e.itemKey)
            grupo.devueltas[#grupo.devueltas + 1] = e
        end
    end

    -- Se salta lo que se acaba de ver sin nadie delante, si no hay nada
    -- devuelto de ese objeto que necesite su precio al dia.
    local quedan = {}
    for _, clave in ipairs(ordenGrupos) do
        local grupo = grupos[clave]
        local reciente = #grupo.devueltas == 0
        for _, m in ipairs(grupo.mias) do
            if not vistaLimpiaReciente(m.auctionID) then
                reciente = false
            end
        end
        if reciente then
            traza("me salto %s: visto hace poco sin nadie delante", clave)
            grupos[clave] = nil
        else
            quedan[#quedan + 1] = clave
        end
    end
    ordenGrupos = quedan

    -- Lo que falta a R.ILVL_FALTAN, al final: solo es para ver su precio, y
    -- lo que hay que arreglar va antes. No se salta nunca, no hay subasta
    -- tuya que haya visto nadie.
    -- Lo que ya se busco hace poco no se repite (ver SEGUNDOS_PRECIOS_FALTAN).
    for _, falta in ipairs(R.Faltan()) do
        local precio, mejores = apuntadoDe(falta.itemID)
        if precio == nil then
            local grupo = anadirAGrupo({ itemID = falta.itemID, itemLevel = R.ILVL_FALTAN, itemSuffix = 0 })
            grupo.precioDe = falta.itemID
        end
        if mejores == nil then
            -- Y una busqueda por nombre, que trae una fila por ilvl con su minimo:
            -- de ahi salen los ilvl mejores sin una busqueda por cada uno.
            -- Con el nombre en el idioma del juego: el de Vigilados.lua es el de
            -- config.yaml, en ingles, y en un cliente en espanol no casa con nada.
            local clave = "nombre:" .. falta.itemID
            local datos = (C_Item and C_Item.GetItemInfo) or GetItemInfo
            grupos[clave] = {
                itemKey = { itemID = falta.itemID, itemLevel = 0, itemSuffix = 0 },
                navegar = (datos and datos(falta.itemID)) or falta.nombre,
                mias = {},
                devueltas = {},
            }
            ordenGrupos[#ordenGrupos + 1] = clave
        end
    end

    local vigiladas = 0
    for _ in pairs(activas) do
        vigiladas = vigiladas + 1
    end
    traza("leo %s subastas tuyas, %s de objetos vigilados; %s objetos que buscar. Cola: %s",
        C_AuctionHouse.GetNumOwnedAuctions(), vigiladas, #ordenGrupos, resumenCola())
end

local function lanzarSiguiente()
    if esperando or not buscando() or not casaAbierta() then
        return
    end
    if not C_AuctionHouse.IsThrottledMessageSystemReady() then
        -- La casa limita las consultas seguidas. Se reintenta con
        -- AUCTION_HOUSE_THROTTLED_SYSTEM_READY.
        traza("casa ocupada: la busqueda %s/%s espera", siguienteGrupo, #ordenGrupos)
        return
    end
    esperando = ordenGrupos[siguienteGrupo]
    consulta = consulta + 1
    local esta = consulta
    traza("busco %s (%s/%s)", esperando, siguienteGrupo, #ordenGrupos)
    local orden = { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }
    if grupos[esperando].navegar then
        C_AuctionHouse.SendBrowseQuery({
            searchString = grupos[esperando].navegar,
            sorts = orden,
            filters = {},
            itemClassFilters = {},
        })
    else
        C_AuctionHouse.SendSearchQuery(grupos[esperando].itemKey, orden, true)
    end
    C_Timer.After(SEGUNDOS_DE_ESPERA, function()
        if esperando and consulta == esta then
            traza("sin respuesta de %s en %s s: se salta", esperando, SEGUNDOS_DE_ESPERA)
            esperando = nil
            siguienteGrupo = siguienteGrupo + 1
            if not buscando() then
                traza("busqueda terminada. Cola: %s", resumenCola())
                comprobarFin()
            end
            lanzarSiguiente()
            R.refrescarPanel()
        end
    end)
end

-- El precio del rival mas barato que va por delante de `mia`, o nil.
local function mejorRival(itemKey, mia)
    local mejor = nil
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local fila = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        if fila and (fila.buyoutAmount or 0) > 0 and not R.esNuestro(fila) then
            local rival = { auctionID = fila.auctionID, buyout = fila.buyoutAmount }
            if R.vaPorDelante(rival, mia) and (not mejor or rival.buyout < mejor) then
                mejor = rival.buyout
            end
        end
    end
    return mejor
end

local function procesarGrupo(grupo)
    local adelantadas = 0
    for _, m in ipairs(grupo.mias) do
        local precio = mejorRival(grupo.itemKey, m)
        local entrada = buscarEntrada(m.auctionID)
        if precio then
            apuntarVistaLimpia(m.auctionID, nil)
        else
            apuntarVistaLimpia(m.auctionID, time())
        end
        if precio then
            adelantadas = adelantadas + 1
            traza("  tu %s a %s: te adelanta uno a %s", m.auctionID, oro(m.buyout), oro(precio))
            if not entrada then
                entrada = {
                    auctionID = m.auctionID,
                    itemKey = grupo.itemKey,
                    itemID = m.itemID,
                    ilvl = m.ilvl,
                    precioAnterior = m.buyout,
                    estado = "cancelar",
                    desde = time(),
                }
                local entradas = cola()
                entradas[#entradas + 1] = entrada
            end
            if entrada.estado == "cancelar" then
                entrada.precio = precio
                entrada.precioEn = time()
                confirmadas[m.auctionID] = true
            end
        elseif entrada and entrada.estado == "cancelar" then
            traza("olvido %s: ya nadie la adelanta", m.auctionID)
            quitarEntrada(m.auctionID)
        end
    end

    -- Repaso de lo devuelto: tu subasta nueva sera la mas reciente, asi que
    -- solo te adelanta lo que este por debajo de tu precio anterior. Si ya no
    -- queda nadie ahi, se repostea a ese precio: igualar, nunca subir.
    -- Lo caducado es distinto: nadie te adelanto, simplemente no se vendio, y
    -- se pone al precio del mas barato de ahora aunque sea mas alto. Solo sin
    -- nadie mas vendiendolo se queda con el que tenia.
    for _, e in ipairs(grupo.devueltas) do
        local tope = e.caducada and math.huge or e.precioAnterior
        local rival = mejorRival(grupo.itemKey, { auctionID = math.huge, buyout = tope })
        e.precio = rival or e.precioAnterior
        e.precioEn = time()
        repasadas[e.auctionID] = true
        traza("  devuelta %s: se repostea a %s (antes %s)", e.auctionID, oro(e.precio), oro(e.precioAnterior))
    end
    if grupo.precioDe then
        -- Un rival cualquiera va por delante de una subasta infinita: sale el
        -- mas barato que no es tuyo.
        apuntarFalta(grupo.precioDe, "precio",
            mejorRival(grupo.itemKey, { auctionID = math.huge, buyout = math.huge }) or false, "en")
    end
    traza("%s: %s resultados, %s tuyas, %s adelantadas, %s devueltas",
        claveDe(grupo.itemKey), C_AuctionHouse.GetNumItemSearchResults(grupo.itemKey),
        #grupo.mias, adelantadas, #grupo.devueltas)
end

-- La respuesta a una busqueda por nombre: apunta el minimo de cada ilvl por
-- encima de R.ILVL_FALTAN. Lo que no es ese objeto (el nombre puede casar con
-- otros) no cuenta.
local function alNavegar()
    local grupo = esperando and grupos[esperando]
    if not grupo or not grupo.navegar then
        return
    end
    local itemID = grupo.itemKey.itemID
    local mejores = {}
    for _, fila in ipairs(C_AuctionHouse.GetBrowseResults() or {}) do
        local k = fila.itemKey
        if k and k.itemID == itemID and (k.itemLevel or 0) > R.ILVL_FALTAN and (fila.minPrice or 0) > 0 then
            if not mejores[k.itemLevel] or fila.minPrice < mejores[k.itemLevel] then
                mejores[k.itemLevel] = fila.minPrice
            end
        end
    end
    apuntarFalta(itemID, "mejores", mejores, "mejoresEn")
    traza("%s por nombre: ilvl mejores vistos", esperando)
    esperando = nil
    siguienteGrupo = siguienteGrupo + 1
    if not buscando() then
        traza("busqueda terminada. Cola: %s", resumenCola())
        comprobarFin()
    end
    lanzarSiguiente()
    R.refrescarPanel()
end

local function alResponder(itemKey)
    if not esperando or not itemKey then
        return
    end
    if claveDe(itemKey) ~= esperando then
        traza("llega la respuesta de otra busqueda (%s); espero %s", claveDe(itemKey), esperando)
        return
    end
    procesarGrupo(grupos[esperando])
    esperando = nil
    siguienteGrupo = siguienteGrupo + 1
    if not buscando() then
        traza("busqueda terminada. Cola: %s", resumenCola())
        comprobarFin()
    end
    lanzarSiguiente()
    -- La busqueda puede ir sola, sin pulsaciones: el boton y la ventana se
    -- refrescan aqui para que cuenten lo que va apareciendo.
    R.refrescarPanel()
end

local function empezarBusqueda()
    buscadoEnEstaVisita = true
    prepararBusqueda()
    lanzarSiguiente()
    if not buscando() then
        -- No habia nada que mirar: el aviso sale ya.
        comprobarFin()
    end
end

-- ---------------------------------------------------------------------------
--  El buzon y la bolsa
-- ---------------------------------------------------------------------------

-- TSM oculta la ventana del buzon de Blizzard y pone la suya, pero el juego
-- avisa igual con MAIL_SHOW y MAIL_CLOSED.
local buzonPorEventos = false

local function buzonAbierto()
    return buzonPorEventos or (MailFrame ~= nil and MailFrame:IsShown())
end

-- Un asunto de carta del juego como patron. Sale del texto del propio juego
-- para funcionar en cualquier idioma ("Subasta cancelada: %s").
local function patronDe(formato)
    local escapado = (formato:gsub("[%^%$%(%)%.%[%]%*%+%-%?]", "%%%0"))
    return "^" .. (escapado:gsub("%%s", "(.+)")) .. "$"
end

local function esCancelada(asunto)
    return asunto:match(patronDe(AUCTION_REMOVED_MAIL_SUBJECT or "Auction cancelled: %s")) ~= nil
end

local function esCaducada(asunto)
    return asunto:match(patronDe(AUCTION_EXPIRED_MAIL_SUBJECT or "Auction expired: %s")) ~= nil
end

-- Las cartas que traen de vuelta algo que estaba puesto: lo cancelado y lo
-- caducado. El resto del correo no se toca.
local function esDevuelta(asunto)
    return asunto ~= nil and (esCancelada(asunto) or esCaducada(asunto))
end

-- Recorre la bolsa llamando a `fn(bolsa, hueco, info)` en cada copia de ese
-- objeto e ilvl. Si `fn` devuelve true, se para.
local function enLaBolsa(itemID, ilvl, fn)
    for bolsa = 0, NUM_BAG_SLOTS do
        for hueco = 1, C_Container.GetContainerNumSlots(bolsa) do
            local info = C_Container.GetContainerItemInfo(bolsa, hueco)
            if info and info.itemID == itemID
                and GetDetailedItemLevelInfo(info.hyperlink) == ilvl then
                if fn(bolsa, hueco, info) then
                    return
                end
            end
        end
    end
end

-- Si esa copia se puede poner a la venta. Una copia ligada tiene el mismo
-- objeto e ilvl pero no se puede subastar: contarla o elegirla dejaria la
-- entrada atascada. La funcion se consulta solo si existe.
local function sePuedeVender(bolsa, hueco)
    if C_Item and C_Item.IsBound then
        return not C_Item.IsBound(ItemLocation:CreateFromBagAndSlot(bolsa, hueco))
    end
    return true
end

copiasEnBolsa = function(itemID, ilvl)
    local n = 0
    enLaBolsa(itemID, ilvl, function(bolsa, hueco)
        if sePuedeVender(bolsa, hueco) then
            n = n + 1
        end
    end)
    return n
end

resumenCola = function()
    local por = { cancelar = 0, cancelando = 0, devuelta = 0, posteando = 0 }
    local sinConfirmar, sinRepasar = 0, 0
    local copias, contadas = 0, {}
    for _, e in ipairs(cola()) do
        por[e.estado] = (por[e.estado] or 0) + 1
        if e.estado == "cancelar" and not confirmadas[e.auctionID] then
            sinConfirmar = sinConfirmar + 1
        elseif e.estado == "devuelta" then
            if not repasadas[e.auctionID] then
                sinRepasar = sinRepasar + 1
            end
            local clave = claveObjeto(e.itemID, e.ilvl)
            if not contadas[clave] then
                contadas[clave] = true
                copias = copias + copiasEnBolsa(e.itemID, e.ilvl)
            end
        end
    end
    return formatear("%s por cancelar (%s sin confirmar), %s cancelando, %s devueltas (%s sin repasar, %s copias en la bolsa), %s posteando",
        por.cancelar, sinConfirmar, por.cancelando, por.devuelta, sinRepasar, copias, por.posteando)
end

-- Cartas ya pedidas y aun sin respuesta: indice -> { clave, en }. Se olvidan
-- con los eventos del buzon o a los pocos segundos, por si una recogida falla
-- sin que el buzon cambie (bolsa llena).
local tomadas = {}
local SEGUNDOS_DE_TOMA = 3

local function tomaReciente(t)
    return t ~= nil and GetTime() - t.en < SEGUNDOS_DE_TOMA
end

local function hayTomasRecientes()
    for _, t in pairs(tomadas) do
        if tomaReciente(t) then
            return true
        end
    end
    return false
end

local function cartaPorRecoger()
    for i = 1, (GetInboxNumItems()) do
        if not tomaReciente(tomadas[i]) then
            local _, _, _, asunto, _, _, _, tieneObjeto = GetInboxHeaderInfo(i)
            if tieneObjeto and esDevuelta(asunto) then
                local _, itemID = GetInboxItem(i, 1)
                -- El enlace del adjunto puede no estar cargado todavia: sin el
                -- no se sabe el ilvl, y esa carta se deja para otra pulsacion.
                local enlace = GetInboxItemLink(i, 1)
                local ilvl = enlace and GetDetailedItemLevelInfo(enlace)
                if itemID and ilvl then
                    local clave = claveObjeto(itemID, ilvl)

                    local devueltas = 0
                    for _, e in ipairs(cola()) do
                        if e.estado == "devuelta" and claveObjeto(e.itemID, e.ilvl) == clave then
                            devueltas = devueltas + 1
                        end
                    end
                    local pedidas = 0
                    for _, otra in pairs(tomadas) do
                        if tomaReciente(otra) and otra.clave == clave then
                            pedidas = pedidas + 1
                        end
                    end

                    -- Sin entradas de ese objeto no hace falta mirar la bolsa:
                    -- con muchas cartas ajenas eso seria recorrerla por cada una.
                    if devueltas > 0 and devueltas > copiasEnBolsa(itemID, ilvl) + pedidas then
                        return i, clave
                    end
                end
            end
        end
    end
    return nil, nil
end

-- Segundos desde la cancelacion antes de dar por hecho que la carta ya ha
-- tenido tiempo de llegar.
local SEGUNDOS_PARA_QUE_LLEGUE_LA_CARTA = 60

-- Segundos que tiene que seguir faltando algo antes de olvidarlo: una carta
-- recogida a mano o por otro addon tarda un momento en llegar a la bolsa.
local SEGUNDOS_FALTANDO = 3

-- auctionID -> GetTime() de la primera vez que se vio faltar. No se guarda en
-- la entrada a proposito: una marca de otra visita o sesion se saltaria la
-- espera de arriba. Se reinicia al abrir el buzon.
local faltan = {}

-- Para no programar mas de una revision pendiente a la vez.
local revisionProgramada = false

-- Devueltas cuyo objeto ya no esta ni en el buzon ni en la bolsa (se vendio,
-- se envio o se puso a mano): se olvidan, para que el boton no mande de la
-- casa al buzon y vuelta. Solo con el buzon abierto y entero cargado, con
-- todas las cartas de subastas canceladas legibles, pasado un rato desde la
-- cancelacion, y si sigue faltando unos segundos despues de verlo faltar.
local function olvidarSinCarta()
    if not buzonAbierto() then
        return
    end
    local mostradas, total = GetInboxNumItems()
    if mostradas ~= total then
        return
    end

    local cartas = {}
    for i = 1, mostradas do
        local _, _, _, asunto, _, _, _, tieneObjeto = GetInboxHeaderInfo(i)
        if tieneObjeto and esDevuelta(asunto) then
            local _, itemID = GetInboxItem(i, 1)
            local enlace = GetInboxItemLink(i, 1)
            local ilvl = enlace and GetDetailedItemLevelInfo(enlace)
            if not (itemID and ilvl) then
                return
            end
            local clave = claveObjeto(itemID, ilvl)
            cartas[clave] = (cartas[clave] or 0) + 1
        end
    end

    local ahora = time()
    local entradas = cola()
    local vistas = {}
    local pendiente = false
    for i = #entradas, 1, -1 do
        local e = entradas[i]
        if e.estado == "devuelta" and e.canceladaEn
            and ahora - e.canceladaEn > SEGUNDOS_PARA_QUE_LLEGUE_LA_CARTA then
            local clave = claveObjeto(e.itemID, e.ilvl)
            vistas[clave] = (vistas[clave] or 0) + 1
            if vistas[clave] > (cartas[clave] or 0) + copiasEnBolsa(e.itemID, e.ilvl) then
                if not faltan[e.auctionID] then
                    faltan[e.auctionID] = GetTime()
                    pendiente = true
                elseif GetTime() - faltan[e.auctionID] >= SEGUNDOS_FALTANDO then
                    faltan[e.auctionID] = nil
                    traza("olvido %s: no esta ni en el buzon ni en la bolsa", e.auctionID)
                    table.remove(entradas, i)
                else
                    pendiente = true
                end
            else
                faltan[e.auctionID] = nil
            end
        end
    end

    if pendiente and not revisionProgramada then
        revisionProgramada = true
        -- Se vuelve a mirar pasado el margen, llegue o no otro evento.
        C_Timer.After(SEGUNDOS_FALTANDO, function()
            revisionProgramada = false
            olvidarSinCarta()
            R.refrescarPanel()
        end)
    end
end

-- Mete en la cola, como devuelto, lo que ha vuelto por caducar. El juego no
-- avisa de que una subasta caduca: se sabe por la carta. No se reconoce una
-- carta concreta, sino que se cuentan copias: cada entrada devuelta de un
-- objeto es una carta suya en el buzon o una copia en la bolsa, y lo que sobre
-- de ahi solo lo explica una carta de caducada que aun no tiene entrada. Asi
-- la misma carta nunca crea dos entradas, y una copia que ya tenias en la
-- bolsa no se confunde con lo caducado.
local function apuntarCaducadas()
    if not buzonAbierto() or hayTomasRecientes() then
        return
    end
    local mostradas = GetInboxNumItems()
    local cartas, caducadas, enlaces = {}, {}, {}
    for i = 1, mostradas do
        local _, _, _, asunto, _, _, _, tieneObjeto = GetInboxHeaderInfo(i)
        if tieneObjeto and esDevuelta(asunto) then
            local _, itemID = GetInboxItem(i, 1)
            local enlace = GetInboxItemLink(i, 1)
            local ilvl = enlace and GetDetailedItemLevelInfo(enlace)
            if itemID and ilvl and vigilados().objetos[itemID] then
                local clave = claveObjeto(itemID, ilvl)
                cartas[clave] = (cartas[clave] or 0) + 1
                if esCaducada(asunto) then
                    caducadas[clave] = (caducadas[clave] or 0) + 1
                    enlaces[clave] = { itemID = itemID, ilvl = ilvl }
                end
            end
        end
    end

    local entradas = cola()
    for clave, cuantas in pairs(caducadas) do
        local objeto = enlaces[clave]
        local conocido = preciosPuestos()[clave]
        local devueltas = 0
        local idLibre = -1   -- las caducadas no tienen subasta: id inventado
        for _, e in ipairs(entradas) do
            if claveObjeto(e.itemID, e.ilvl) == clave
                and (e.estado == "devuelta" or e.estado == "posteando") then
                devueltas = devueltas + 1
            end
            if e.auctionID <= idLibre then
                idLibre = e.auctionID - 1
            end
        end
        local sobran = cartas[clave] + copiasEnBolsa(objeto.itemID, objeto.ilvl) - devueltas
        local nuevas = math.min(sobran, cuantas)
        if nuevas > 0 and not conocido then
            -- Sin el precio que tenia no se puede cumplir la regla cuando nadie
            -- mas lo vende. Pasa con lo puesto antes de que el addon lo
            -- apuntara: esa carta se deja para recogerla a mano.
            traza("carta de caducada de %s sin precio conocido: no la toco", clave)
        elseif nuevas > 0 then
            for _ = 1, nuevas do
                traza("caducada %s: vuelve a la cola, antes a %s", clave, oro(conocido.precio))
                entradas[#entradas + 1] = {
                    auctionID = idLibre,
                    itemKey = conocido.itemKey,
                    itemID = objeto.itemID,
                    ilvl = objeto.ilvl,
                    precioAnterior = conocido.precio,
                    estado = "devuelta",
                    caducada = true,
                    desde = time(),
                    canceladaEn = time(),
                    -- Lo que se ponga despues de la ultima busqueda puede ser
                    -- esta, repuesta a mano. Sin busqueda en esta sesion no hay
                    -- con que comparar, y ese caso lo resuelve el buzon.
                    idTopeCancelada = (maxIdVisto > 0 and maxIdVisto) or math.huge,
                }
                idLibre = idLibre - 1
            end
        end
    end
end

-- ---------------------------------------------------------------------------
--  La tecla
-- ---------------------------------------------------------------------------

-- Si esa entrada se puede cancelar ya: adelantada confirmada en esta visita y
-- que el juego deja cancelar. CanCancelAuction se consulta solo si existe: una
-- subasta con puja, por ejemplo, no se puede cancelar y no debe gastar
-- pulsaciones.
local function sePuedeCancelar(e)
    return e.estado == "cancelar" and confirmadas[e.auctionID]
        and (not C_AuctionHouse.CanCancelAuction or C_AuctionHouse.CanCancelAuction(e.auctionID))
end

local function primeraPorCancelar()
    for _, e in ipairs(cola()) do
        if sePuedeCancelar(e) then
            return e
        end
    end
    return nil
end

-- Si hay un posteo de ese objeto e ilvl esperando a saber si se creo. Hasta la
-- busqueda siguiente no se postea otra copia: su subasta se confundiria con la
-- de ese posteo y la busqueda podria dar por puesta una copia que sigue en la
-- bolsa.
local function hayPosteandoDe(clave)
    for _, e in ipairs(cola()) do
        if e.estado == "posteando" and claveObjeto(e.itemID, e.ilvl) == clave then
            return true
        end
    end
    return false
end

-- Segundos que vale el precio de una busqueda para repostear sin buscar otra
-- vez. Tu ciclo (cancelar, buzon, volver a la casa) dura menos de un minuto:
-- en ese rato el rival rara vez se mueve, y ahorra la busqueda y la espera.
local SEGUNDOS_PRECIO_RECIENTE = 120

local function precioReciente(e)
    return e.precio ~= nil and e.precioEn ~= nil and time() - e.precioEn < SEGUNDOS_PRECIO_RECIENTE
end

-- La primera devuelta con el precio al dia (repasado en esta visita, o de hace
-- un momento) y una copia libre y vendible en la bolsa, y donde esta esa copia.
local function paraPostear()
    for _, e in ipairs(cola()) do
        if e.estado == "devuelta" and (repasadas[e.auctionID] or precioReciente(e)) and e.precio
            and not hayPosteandoDe(claveObjeto(e.itemID, e.ilvl)) then
            local sitio = nil
            enLaBolsa(e.itemID, e.ilvl, function(bolsa, hueco, info)
                if not info.isLocked and sePuedeVender(bolsa, hueco) then
                    local candidato = ItemLocation:CreateFromBagAndSlot(bolsa, hueco)
                    if not C_AuctionHouse.IsSellItemValid
                        or C_AuctionHouse.IsSellItemValid(candidato, false) then
                        sitio = candidato
                        return true
                    end
                end
            end)
            if sitio then
                return e, sitio
            end
        end
    end
    return nil, nil
end

-- Lo que falta por confirmar del ultimo PostItem, si el juego pidio
-- confirmacion. Confirmar tambien es una funcion protegida, asi que va en su
-- propia pulsacion.
local confirmacion = nil

-- Si en el hueco guardado sigue el mismo objeto. Entre postear y confirmar se
-- puede ordenar la bolsa, y confirmar leeria lo que haya ahora en ese hueco.
-- El ilvl se lee del enlace, igual que al buscar en la bolsa: otra funcion
-- podria dar otro numero y la confirmacion no llegaria nunca.
local function sigueEnSuSitio(c)
    if not (C_Item and C_Item.DoesItemExist) then
        return true
    end
    if not C_Item.DoesItemExist(c.sitio) or C_Item.GetItemID(c.sitio) ~= c.itemID then
        return false
    end
    local enlace = C_Item.GetItemLink(c.sitio)
    return enlace ~= nil and GetDetailedItemLevelInfo(enlace) == c.ilvl
end

-- La casa de Blizzard abre su propio aviso de precio al postear, y tapa la
-- ventana hasta que se cierra. Su boton de aceptar no confirma lo nuestro, asi
-- que en cuanto la confirmacion se usa o se descarta, el aviso sobra.
local function cerrarAvisoDePrecio()
    if StaticPopup_Visible and StaticPopup_Hide and StaticPopup_Visible("AUCTION_HOUSE_POST_WARNING") then
        StaticPopup_Hide("AUCTION_HOUSE_POST_WARNING")
    end
end

-- Segundos tras los que una cancelacion o un posteo sin respuesta se da por
-- atascado: el boton deja de decir que espera y pide volver a buscar.
local SEGUNDOS_SIN_RESPUESTA = 10

-- Segundos tras pedir una cancelacion en los que un aviso de consulta
-- descartada se toma por ella. En el juego el descarte llega en una decima.
local SEGUNDOS_DESCARTE = 1

local function hayReciente(estadoBuscado, campo)
    for _, e in ipairs(cola()) do
        if e.estado == estadoBuscado and e[campo]
            and GetTime() - e[campo] < SEGUNDOS_SIN_RESPUESTA then
            return true
        end
    end
    return false
end

-- Si hay un posteo de esta visita esperando respuesta. Uno de una visita
-- anterior ya no va a responder: de ese se encarga la busqueda.
local function posteoEnCurso()
    for _, e in ipairs(cola()) do
        if e.estado == "posteando" and e.posteandoEn and abiertaEn and e.posteandoEn > abiertaEn
            and GetTime() - e.posteandoEn < SEGUNDOS_SIN_RESPUESTA then
            return true
        end
    end
    return false
end

local function hayAtascada()
    for _, e in ipairs(cola()) do
        if e.estado == "cancelando" or e.estado == "posteando" then
            local desde
            if e.estado == "cancelando" then
                desde = e.cancelandoEn
            else
                desde = e.posteandoEn
            end
            if not desde or GetTime() - desde >= SEGUNDOS_SIN_RESPUESTA then
                return true
            end
        end
    end
    return false
end

-- Pone `d` a la venta desde `sitio` y devuelve el detalle para la traza.
local function postear(d, sitio)
    local duracion = vigilados().duracion
    -- La entrada sale de la cola cuando el juego crea la subasta
    -- (AUCTION_HOUSE_AUCTION_CREATED), no al pedirlo: un posteo rechazado, o
    -- aceptado desde el aviso de Blizzard, dejaria la cola descuadrada. Se
    -- marca antes de llamar porque ese evento puede llegar enseguida.
    d.estado = "posteando"
    d.posteandoEn = GetTime()
    d.idTope = maxIdVisto
    local pideConfirmar = C_AuctionHouse.PostItem(sitio, duracion, 1, nil, d.precio)
    if pideConfirmar then
        confirmacion = {
            sitio = sitio,
            duracion = duracion,
            precio = d.precio,
            auctionID = d.auctionID,
            itemID = d.itemID,
            ilvl = d.ilvl,
        }
    end
    -- Pasado el margen no llega ningun evento: se refresca a mano para que el
    -- boton deje de decir "Posteando...".
    C_Timer.After(SEGUNDOS_SIN_RESPUESTA + 0.1, function()
        R.refrescarPanel()
    end)
    return formatear(" %s ilvl %s a %s (pide confirmar: %s)",
        d.itemID, d.ilvl, oro(d.precio), tostring(pideConfirmar))
end

-- Lo unico que el reposteo escribe en el chat: que ya no queda nada que hacer
-- en esta ventana, una sola vez, para poder machacar la tecla sin mirar.
local ultimoAviso = nil

-- Si se ha pulsado la tecla en esta visita a la casa. La busqueda sale sola al
-- abrir (ver buscarSolo), y avisar de que no hay nada que hacer cuando no has
-- pedido nada seria ruido: el aviso espera a la primera pulsacion.
local pulsadaEnVisita = false

-- Subastas de la cola canceladas en esta visita a la casa, para el aviso.
local canceladasEnVisita = 0

-- Sale en el chat, sin sonido y no en el centro de la pantalla: el
-- boton del addon ya dice como esta la cosa, y el aviso grande estorbaba.
local function avisarFin()
    if not pulsadaEnVisita then
        return
    end
    local texto = R.Estado()
    if texto == ultimoAviso then
        return
    end
    ultimoAviso = texto
    local mensaje = texto
    if texto == "Recoge lo devuelto en el buzon" and canceladasEnVisita > 0 then
        mensaje = ("Todas canceladas (%s). %s"):format(canceladasEnVisita, texto)
    end
    print("|cff33ccffReposteo:|r " .. mensaje)
end

-- Avisa en cuanto no queda nada que hacer en la casa, sin esperar a otra
-- pulsacion: al llegar la ultima cancelacion, el ultimo posteo o el final de
-- la busqueda.
comprobarFin = function()
    if not casaAbierta() or not buscadoEnEstaVisita or buscando() or confirmacion
        or primeraPorCancelar() or paraPostear()
        or hayReciente("cancelando", "cancelandoEn") or hayReciente("posteando", "posteandoEn") then
        return
    end
    avisarFin()
end

-- Buscar quien te adelanta no es una funcion protegida: puede salir solo, sin
-- tecla. Al abrir la casa se lanza en cuanto la lista de tus subastas esta
-- entera, para que la ventana diga a quien te han adelantado sin tocar nada.
-- Solo hace lo que haria la tecla: si hay algo devuelto listo para postear,
-- eso va antes, y postear si es una funcion protegida y necesita la tecla.
local function buscarSolo()
    if buscadoEnEstaVisita or not casaAbierta() or confirmacion then
        return
    end
    if not subastasListas() or posteoEnCurso() or paraPostear() then
        return
    end
    traza("busco solo: la lista esta entera y no hay nada que postear")
    empezarBusqueda()
    R.refrescarPanel()
end

-- Hace UNA accion y devuelve cual ("buscar", "cancelar", "recoger", "postear",
-- "confirmar"), o nil si no habia nada que hacer. Nunca llama a mas de una
-- funcion protegida.
function R.Siguiente()
    pulsadaEnVisita = true
    local hecho, motivo, detalle = nil, nil, ""
    -- Si no se ha hecho nada porque no queda nada, y no porque haya que esperar.
    local fin = false
    local ocupada = "la casa esta ocupada con otra consulta"
    local b = WowAlertsReposteoBoton
    local decia = (b and b:GetText()) or "?"
    if casaAbierta() then
        if confirmacion then
            if C_AuctionHouse.IsThrottledMessageSystemReady() then
                local c = confirmacion
                confirmacion = nil
                local e = buscarEntrada(c.auctionID)
                if sigueEnSuSitio(c) then
                    if e then
                        e.posteandoEn = GetTime()
                    end
                    C_AuctionHouse.ConfirmPostItem(c.sitio, c.duracion, 1, nil, c.precio)
                    -- Pasado el margen no llega ningun evento: se refresca a mano
                    -- para que el boton deje de decir "Posteando...".
                    C_Timer.After(SEGUNDOS_SIN_RESPUESTA + 0.1, function()
                        R.refrescarPanel()
                    end)
                    hecho = "confirmar"
                    detalle = formatear(" %s a %s", c.itemID, oro(c.precio))
                else
                    -- Si no se confirma, la entrada se queda "posteando": la
                    -- busqueda siguiente decide (la crease el juego aunque se
                    -- perdiera el aviso, o no), en vez de darla por libre aqui.
                    -- No se sabe si llego a crearse (el aviso de Blizzard pudo
                    -- aceptarse).
                    motivo = "el objeto ya no esta en su hueco de la bolsa: no se confirma"
                end
                cerrarAvisoDePrecio()
            else
                motivo = ocupada
            end
        elseif not buscadoEnEstaVisita then
            -- Lo devuelto con precio de hace un momento se postea antes de
            -- buscar, sin esperar a la lista de subastas: al volver del buzon
            -- no hace falta nada mas. La busqueda viene despues, y no empieza
            -- con un posteo sin responder, que aun no estaria en la lista.
            local d, sitio = paraPostear()
            if posteoEnCurso() then
                motivo = "el posteo anterior aun espera respuesta del juego"
            elseif d and not C_AuctionHouse.IsThrottledMessageSystemReady() then
                motivo = ocupada
            elseif d then
                detalle = postear(d, sitio)
                hecho = "postear"
            elseif subastasListas() then
                empezarBusqueda()
                hecho = "buscar"
            else
                motivo = "aun leyendo tus subastas"
            end
        else
            -- Con la casa saturada de consultas, postear podria perderse sin
            -- aviso: mejor no hacer nada y que se vuelva a pulsar. Cancelar no
            -- lo necesita (Auctionator tampoco lo mira): basta con esperar a
            -- que el juego responda a la cancelacion anterior. Por eso lo ya
            -- confirmado se cancela mientras sigue la busqueda de lo demas, y
            -- postear espera a que termine.
            local listo = C_AuctionHouse.IsThrottledMessageSystemReady()
            local e = primeraPorCancelar()
            if e then
                if hayReciente("cancelando", "cancelandoEn") then
                    motivo = "la cancelacion anterior aun espera respuesta del juego"
                else
                    C_AuctionHouse.CancelAuction(e.auctionID)
                    e.estado = "cancelando"
                    e.cancelandoEn = GetTime()
                    hecho = "cancelar"
                    detalle = formatear(" %s (%s ilvl %s, la tuya a %s, rival a %s)",
                        e.auctionID, e.itemID, e.ilvl, oro(e.precioAnterior), oro(e.precio))
                end
            elseif buscando() then
                motivo = formatear("buscando %s/%s", siguienteGrupo, #ordenGrupos)
            elseif not listo then
                motivo = ocupada
            else
                local d, sitio = paraPostear()
                -- Mientras un posteo espera a AUCTION_HOUSE_AUCTION_CREATED,
                -- postear otro dejaria ambiguo a cual de los dos pertenece el
                -- aviso cuando llegue.
                if not d then
                    motivo = "nada que cancelar ni postear. Cola: " .. resumenCola()
                    fin = true
                elseif hayReciente("posteando", "posteandoEn") then
                    motivo = "el posteo anterior aun espera respuesta del juego"
                else
                    detalle = postear(d, sitio)
                    hecho = "postear"
                end
            end
        end
    elseif buzonAbierto() then
        local indice, clave = cartaPorRecoger()
        if C_Mail and C_Mail.IsCommandPending and C_Mail.IsCommandPending() then
            -- La recogida automatica ya tiene una carta en camino.
            motivo = "el buzon esta atendiendo otra carta"
        elseif indice then
            TakeInboxItem(indice, 1)
            tomadas[indice] = { clave = clave, en = GetTime() }
            hecho = "recoger"
            detalle = formatear(" carta %s (%s)", indice, clave)
        else
            motivo = "ninguna carta que recoger. Cola: " .. resumenCola()
            fin = true
        end
    else
        motivo = "ni la casa ni el buzon estan abiertos"
    end
    R.refrescarPanel()
    b = WowAlertsReposteoBoton
    local ahora = (b and b:GetText()) or "?"
    if hecho then
        traza("[%s] -> %s%s. Ahora dice [%s]", decia, hecho, detalle, ahora)
    else
        traza("[%s] -> nada: %s. Ahora dice [%s]", decia, motivo or "?", ahora)
        -- Con una cancelacion, un posteo o una carta aun en camino, lo que
        -- falta llega en un momento: eso no es haber terminado.
        if fin and not hayReciente("cancelando", "cancelandoEn")
            and not hayReciente("posteando", "posteandoEn") and not hayTomasRecientes() then
            avisarFin()
        end
    end
    return hecho
end

-- La subasta tuya con ese id, si el juego la tiene en su lista.
local function subastaPropia(auctionID)
    for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(i)
        if info and info.auctionID == auctionID then
            return info
        end
    end
    return nil
end

-- Cancela una subasta desde el boton de su fila en la ventana. El clic es un
-- evento de raton de verdad, que es lo unico que el juego exige para cancelar:
-- un clic, una cancelacion, igual que la tecla. Devuelve por que no se ha
-- podido, o nil si se ha pedido la cancelacion.
function R.Cancelar(auctionID)
    local e = buscarEntrada(auctionID)
    local motivo = nil
    if not casaAbierta() then
        motivo = "la casa no esta abierta"
    elseif e and e.estado ~= "cancelar" then
        -- Como la tecla, solo se cancela lo que esta por cancelar. La fila de
        -- una recien cancelada sigue en pantalla hasta que llega la lista
        -- nueva, y un segundo clic pedia cancelar una subasta que ya no
        -- existe: el juego no responde a eso, la entrada se quedaba
        -- "cancelando" y bloqueaba todas las X durante SEGUNDOS_SIN_RESPUESTA.
        motivo = "esa ya esta cancelada"
    elseif C_AuctionHouse.CanCancelAuction and not C_AuctionHouse.CanCancelAuction(auctionID) then
        motivo = "el juego no deja cancelar esa subasta"
    elseif hayReciente("cancelando", "cancelandoEn") then
        motivo = "la cancelacion anterior aun espera respuesta del juego"
    end
    if motivo then
        -- Un clic que no hace nada tiene que dejar rastro, o no hay forma de
        -- saber despues por que no se cancelo.
        traza("no cancelo %s desde la ventana: %s", auctionID, motivo)
        return motivo
    end
    if not e then
        -- Entra en la cola para que el ciclo siga: recogerla del buzon y
        -- volver a ponerla. Solo lo vigilado, que es lo unico que el addon
        -- sabe repostear, y solo con precio de compra, que es a partir del
        -- que se calcula el nuevo. Lo demas se cancela y ya.
        local info = subastaPropia(auctionID)
        local itemKey = info and info.itemKey
        if itemKey and vigilados().objetos[itemKey.itemID] and (info.buyoutAmount or 0) > 0 then
            e = {
                auctionID = auctionID,
                itemKey = {
                    itemID = itemKey.itemID,
                    itemLevel = itemKey.itemLevel,
                    itemSuffix = itemKey.itemSuffix,
                },
                itemID = itemKey.itemID,
                ilvl = ilvlDe(info, itemKey),
                precioAnterior = info.buyoutAmount,
                estado = "cancelar",
                desde = time(),
            }
            local entradas = cola()
            entradas[#entradas + 1] = e
        end
    end
    if e then
        e.estado = "cancelando"
        e.cancelandoEn = GetTime()
        -- Cancelar cuesta el deposito, y por eso la tecla solo cancela lo que
        -- la busqueda ha confirmado. Aqui lo confirmas tu con el clic: queda
        -- marcada para que, si el juego descarta la peticion, la tecla pueda
        -- repetirla en vez de dejarla tirada en la cola.
        confirmadas[auctionID] = true
    end
    traza("cancelo %s desde la ventana (en la cola: %s)", auctionID, e ~= nil)
    C_AuctionHouse.CancelAuction(auctionID)
    R.refrescarPanel()
    return nil
end

-- ---------------------------------------------------------------------------
--  El panel
-- ---------------------------------------------------------------------------
--  Un boton debajo de la casa o del buzon que dice que va a hacer la tecla.
--  Pulsarlo es lo mismo que pulsar la tecla asignada.

BINDING_HEADER_WOWALERTS = "WoW Alerts"
BINDING_NAME_WOWALERTS_SIGUIENTE = "Reposteo: siguiente paso"

local function contar(estadoBuscado)
    local n = 0
    for _, e in ipairs(cola()) do
        if e.estado == estadoBuscado then
            n = n + 1
        end
    end
    return n
end

local function devueltaEnBolsa()
    for _, e in ipairs(cola()) do
        if e.estado == "devuelta" and copiasEnBolsa(e.itemID, e.ilvl) > 0 then
            return true
        end
    end
    return false
end

local function contarCancelables()
    local n = 0
    for _, e in ipairs(cola()) do
        if sePuedeCancelar(e) then
            n = n + 1
        end
    end
    return n
end

-- Adelantadas que la busqueda de esta visita no ha podido confirmar.
local function sinConfirmar()
    for _, e in ipairs(cola()) do
        if e.estado == "cancelar" and not confirmadas[e.auctionID] then
            return true
        end
    end
    return false
end

function R.Estado()
    if confirmacion then
        return "Confirmar posteo"
    end
    if casaAbierta() then
        if not buscadoEnEstaVisita then
            if posteoEnCurso() then
                return "Posteando..."
            end
            if paraPostear() then
                return "Postear"
            end
            if subastasListas() then
                return "Buscar undercuts"
            end
            return "Leyendo tus subastas..."
        end
        -- Lo ya confirmado se cancela aunque la busqueda siga.
        if primeraPorCancelar() then
            return ("Cancelar (%s)"):format(contarCancelables())
        end
        if buscando() then
            return ("Buscando %s/%s..."):format(siguienteGrupo, #ordenGrupos)
        end
        if paraPostear() and not hayReciente("posteando", "posteandoEn") then
            return "Postear"
        end
        if hayReciente("cancelando", "cancelandoEn") then
            return "Cancelando..."
        end
        if hayReciente("posteando", "posteandoEn") then
            return "Posteando..."
        end
        if sinConfirmar() or devueltaEnBolsa() or hayAtascada() then
            -- Hay algo cuyo precio no se ha podido repasar en esta visita.
            return "Cierra y abre la casa para repasar precios"
        end
        if contar("devuelta") > 0 then
            return "Recoge lo devuelto en el buzon"
        end
        return "Nada que repostear"
    end
    if buzonAbierto() then
        if cartaPorRecoger() then
            return "Recoger del buzon"
        end
        if contar("devuelta") > 0 then
            return "Vuelve a la casa a postear"
        end
        return "Nada que recoger"
    end
    return "Nada que repostear"
end

-- Cuantas subastas has puesto con la tecla en esta visita.
local function cuentaRepuestas()
    local n = 0
    for _ in pairs(reposteadas) do
        n = n + 1
    end
    return n
end

-- Por donde va lo que el addon esta haciendo ahora, para la barra de la
-- ventana: la fase, cuantas lleva y de cuantas. nil si no hay nada en marcha.
-- Las fases van en el orden del ciclo, y se mira la de mas atras primero: al
-- cancelar aun quedan busquedas por responder, y lo cancelado ya cuenta como
-- pendiente de poner mucho antes de que vayas al buzon.
function R.Progreso()
    if not casaAbierta() then
        return nil
    end
    if buscando() then
        local grupo = grupos[ordenGrupos[siguienteGrupo]]
        return {
            fase = "escaneo",
            hechos = siguienteGrupo - 1,
            total = #ordenGrupos,
            -- Cual esta mirando ahora mismo, para poder decir su nombre.
            itemID = grupo and grupo.itemKey.itemID,
            ilvl = grupo and grupo.itemKey.itemLevel,
        }
    end
    local porCancelar = contarCancelables()
    if porCancelar > 0 or canceladasEnVisita > 0 then
        return {
            fase = "cancelar",
            hechos = canceladasEnVisita,
            total = canceladasEnVisita + porCancelar,
        }
    end
    local puestas = cuentaRepuestas()
    local porPoner = contar("devuelta") + contar("posteando")
    if porPoner > 0 or puestas > 0 then
        return { fase = "postear", hechos = puestas, total = puestas + porPoner }
    end
    -- Nada pendiente, pero el escaneo de esta visita si se hizo: la barra se
    -- queda llena en vez de desaparecer de golpe.
    if buscadoEnEstaVisita and #ordenGrupos > 0 then
        return { fase = "escaneo", hechos = #ordenGrupos, total = #ordenGrupos }
    end
    return nil
end

-- ---------------------------------------------------------------------------
--  La lista para la ventana
-- ---------------------------------------------------------------------------

-- El orden en que se muestran los grupos: primero lo que hay que arreglar.
local ORDEN_GRUPOS = {
    adelantada = 1, reposteada = 2, primera = 3, sinmirar = 4, novigilada = 5,
}

-- Una fila por subasta activa tuya, ya clasificada. Solo lee lo que el
-- reposteo ya sabe: no lanza ninguna busqueda. La ventana saca el nombre, la
-- calidad y el icono del enlace.
function R.Subastas()
    local objetos = vigilados().objetos
    local filas = {}
    local vistas = {}   -- auctionID -> true: ya tiene fila de la lista del juego
    for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
        local info = C_AuctionHouse.GetOwnedAuctionInfo(i)
        local itemKey = info and info.itemKey
        -- status 1 es vendida y pendiente de cobro: esa ya no esta en venta.
        if info and info.status == 0 and itemKey then
            local fila = {
                auctionID = info.auctionID,
                itemID = itemKey.itemID,
                enlace = info.itemLink,
                ilvl = ilvlDe(info, itemKey),
                -- A puja sin precio de compra, `buyoutAmount` puede venir nil
                -- o 0. prepararBusqueda descarta esas, pero aqui SI se
                -- ensenan: el usuario las tiene puestas y quiere verlas.
                precio = info.buyoutAmount,
                -- Lo que le queda de listado. En los clientes que no lo dan en
                -- segundos queda la banda de Blizzard (corto, medio, largo...).
                segundos = info.timeLeftSeconds,
                banda = info.timeLeft,
                grupo = "novigilada",
            }
            vistas[info.auctionID] = true
            -- Ya pedida su cancelacion: la ventana apaga su X hasta que la
            -- lista nueva la quite (ver R.Cancelar).
            local pedida = buscarEntrada(info.auctionID)
            if pedida and pedida.estado ~= "cancelar" then
                fila.cancelada = true
            end
            if reposteadas[info.auctionID] then
                fila.grupo = "reposteada"
            elseif objetos[itemKey.itemID] then
                local e = buscarEntrada(info.auctionID)
                -- Adelantada es lo que la busqueda vio con un rival delante, y eso
                -- siempre deja su precio. Una que cancelas con su X queda
                -- confirmada pero sin rival, y no debe cambiar de grupo mientras
                -- el juego responde: moveria todas las filas bajo el raton.
                if e and (e.estado == "cancelar" or e.estado == "cancelando")
                    and confirmadas[info.auctionID] and e.precio then
                    fila.grupo = "adelantada"
                    fila.precioRival = e.precio
                    fila.igualada = e.precio == info.buyoutAmount
                elseif vistaLimpiaReciente(info.auctionID) then
                    fila.grupo = "primera"
                else
                    fila.grupo = "sinmirar"
                end
            end
            filas[#filas + 1] = fila
        end
    end

    -- Lo que acabas de poner y la lista del juego aun no trae: se pinta con lo
    -- que se apunto al crearla. Pasado un rato ya no, para no dejar colgada la
    -- fila de una que se haya vendido (esas salen de la lista sin avisar).
    for auctionID, d in pairs(reposteadas) do
        if not vistas[auctionID] and GetTime() - d.en < SEGUNDOS_SIN_LISTA then
            filas[#filas + 1] = {
                auctionID = auctionID,
                itemID = d.itemID,
                ilvl = d.ilvl,
                precio = d.precio,
                grupo = "reposteada",
            }
        end
    end

    table.sort(filas, function(a, b)
        if ORDEN_GRUPOS[a.grupo] ~= ORDEN_GRUPOS[b.grupo] then
            return ORDEN_GRUPOS[a.grupo] < ORDEN_GRUPOS[b.grupo]
        end
        if (a.precio or 0) ~= (b.precio or 0) then
            return (a.precio or 0) < (b.precio or 0)
        end
        return a.auctionID < b.auctionID
    end)
    return filas
end

-- ---------------------------------------------------------------------------
--  Las que caducan pronto
-- ---------------------------------------------------------------------------

-- Lo que le tiene que quedar a una subasta para que merezca la pena cancelarla
-- y volver a ponerla entera, en vez de dejar que expire y aparezca en el buzon.
local SEGUNDOS_CADUCA = 8 * 3600

-- Sin los segundos exactos solo valen las bandas que no dejan duda: corto
-- (menos de 30 min) y medio (30 min - 2 h). Largo va de 2 a 12 h y podria
-- tener de sobra, y cancelar cuesta el deposito: en la duda, no se cuenta.
local BANDAS_CADUCA = { [0] = true, [1] = true }

local function caduca(fila)
    if fila.segundos and fila.segundos > 0 then
        return fila.segundos < SEGUNDOS_CADUCA
    end
    return BANDAS_CADUCA[fila.banda] == true
end

-- Las tuyas que caducan pronto, de la mas urgente a la menos. La ventana
-- cuenta esta lista para su boton y cancela la primera con R.Cancelar, igual
-- que si pulsaras su X.
--
-- Solo lo vigilado y con precio de compra: es lo unico que el addon sabe
-- volver a poner, y cancelar lo demas seria dejarlo tirado en el buzon. Lo que
-- el juego no deja cancelar (una subasta con puja) tampoco cuenta, o el boton
-- se atascaria siempre en la misma.
-- Si el objeto se equipa: armadura (4) o arma (2). Las recetas no escalan.
-- No vale mirar el hueco de equipo: lo que no se equipa no lo trae vacio, sino
-- "INVTYPE_NON_EQUIP_IGNORE". GetItemInfoInstant no espera a la cache del
-- cliente.
local function esEquipo(itemID)
    local instantaneo = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    if not instantaneo then
        return false
    end
    local _, _, _, _, _, clase = instantaneo(itemID)
    return clase == 2 or clase == 4
end

-- Los objetos vigilados de equipo de los que no tienes ninguna subasta a
-- R.ILVL_FALTAN, por nombre: { itemID, nombre, icono, precio, pisa }. `precio`
-- es el del mas barato que no es tuyo, false si nadie lo vende y nil si aun no
-- se ha buscado en esta visita. `pisa` es { ilvl, precio } del ilvl mejor que
-- se lleva al comprador, como en la app: el mas barato de los de arriba, si
-- cuesta menos que el tuyo o hasta MARGEN_PISA mas. Sin nadie vendiendo a
-- R.ILVL_FALTAN no hay con que comparar, y no sale.
local function pisa(itemID)
    local mio, mejores = apuntadoDe(itemID)
    if not mio then
        return nil
    end
    local mejor = nil
    for ilvl, precio in pairs(mejores or {}) do
        if not mejor or precio < mejor.precio then
            mejor = { ilvl = ilvl, precio = precio }
        end
    end
    if mejor and mejor.precio <= mio + MARGEN_PISA then
        return mejor
    end
    return nil
end

function R.Faltan()
    -- Solo con los personajes de personajes.yaml: los demas de la cuenta no
    -- necesitan tenerlo puesto, y asi tampoco se buscan sus precios.
    if not misPersonajes()[UnitName("player")] then
        return {}
    end
    local puestos = {}
    for _, fila in ipairs(R.Subastas()) do
        if fila.ilvl == R.ILVL_FALTAN then
            puestos[fila.itemID] = true
        end
    end
    -- Lo que esta en la cola del reposteo (cancelado o caducado y por volver a
    -- poner) ya no sale entre tus subastas, pero va a volver: no falta.
    for _, e in ipairs(cola()) do
        if e.ilvl == R.ILVL_FALTAN and e.itemID then
            puestos[e.itemID] = true
        end
    end
    local lista = {}
    local instantaneo = (C_Item and C_Item.GetItemInfoInstant) or GetItemInfoInstant
    for itemID, nombre in pairs(vigilados().objetos) do
        if not puestos[itemID] and esEquipo(itemID) then
            local _, _, _, _, icono = instantaneo(itemID)
            lista[#lista + 1] = {
                itemID = itemID,
                nombre = nombre,
                icono = icono,
                precio = (apuntadoDe(itemID)),
                pisa = pisa(itemID),
            }
        end
    end
    table.sort(lista, function(a, b) return a.nombre < b.nombre end)
    return lista
end

function R.Caducadas()
    local filas = {}
    for _, fila in ipairs(R.Subastas()) do
        if caduca(fila) and fila.grupo ~= "novigilada" and (fila.precio or 0) > 0
            and not fila.cancelada
            and (not C_AuctionHouse.CanCancelAuction
                or C_AuctionHouse.CanCancelAuction(fila.auctionID)) then
            filas[#filas + 1] = fila
        end
    end
    table.sort(filas, function(a, b)
        if (a.segundos or 0) ~= (b.segundos or 0) then
            return (a.segundos or 0) < (b.segundos or 0)
        end
        return a.auctionID < b.auctionID
    end)
    return filas
end

-- Mientras busca no hay nada que hacer, salvo cancelar lo ya confirmado. Lo
-- usan este boton y el de la ventana, que pulsa lo mismo.
function R.SePuedePulsar()
    return not (buscando() and not primeraPorCancelar())
end

local boton = nil

local function colocarBoton(padre)
    if not padre then
        return
    end
    if not boton then
        boton = CreateFrame("Button", "WowAlertsReposteoBoton", padre, "UIPanelButtonTemplate")
        boton:SetSize(280, 24)
        boton:SetScript("OnClick", function()
            R.Siguiente()
        end)
    end
    boton:SetParent(padre)
    boton:ClearAllPoints()
    boton:SetPoint("TOP", padre, "BOTTOM", 0, -4)
    boton:Show()
end

function R.refrescarPanel()
    -- La interfaz de la casa se carga bajo demanda: si al abrir aun no existia,
    -- el boton se coloca en el siguiente refresco.
    if casaAbierta() and (not boton or boton:GetParent() ~= AuctionHouseFrame) then
        colocarBoton(AuctionHouseFrame)
    elseif buzonAbierto() and (not boton or boton:GetParent() ~= MailFrame) then
        colocarBoton(MailFrame)
    end
    -- La ventana se dibuja sola desde Ventana.lua, si esta cargada. Con pcall
    -- porque un error suyo no debe dejar el boton del reposteo sin
    -- actualizar; se deja rastro en la traza para poder notar que esta rota.
    if WowAlertsVentana and WowAlertsVentana.Refrescar then
        local ok, error_ = pcall(WowAlertsVentana.Refrescar)
        if not ok then
            traza("WowAlertsVentana.Refrescar ha fallado: %s", error_)
        end
    end
    if not casaAbierta() and not buzonAbierto() then
        -- Con las dos ventanas cerradas el boton no se ve: no hace falta
        -- recalcular nada, y BAG_UPDATE_DELAYED llega a menudo.
        return
    end
    if not boton then
        return
    end
    boton:SetText(R.Estado())
    if not R.SePuedePulsar() then
        boton:Disable()
    else
        boton:Enable()
    end
end

-- ---------------------------------------------------------------------------
--  Eventos
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
--  Recoger solo
-- ---------------------------------------------------------------------------
--  Al abrir el buzon se recogen solas las cartas de lo cancelado, una detras
--  de otra, como hace el "abrir todo" de TSM. Recoger correo no necesita una
--  tecla por carta: solo cancelar, postear y confirmar la necesitan.

local SEGUNDOS_ENTRE_CARTAS = 0.3
local recogiendo = false
local recogidaParada = false   -- un error del juego en el buzon la para

-- Cuantas cartas habia al pedir la ultima, y cuando. Hasta que el buzon tenga
-- otro numero de cartas no se pide la siguiente: los indices se reordenan al
-- salir una, y pedir antes daba "No se ha encontrado el objeto" (visto en el
-- juego). Pasado el margen de toma se sigue igual.
local cartaPedida = nil

local function recogerSolo()
    if not buzonAbierto() or recogidaParada then
        recogiendo = false
        return
    end
    local pendiente = (C_Mail and C_Mail.IsCommandPending and C_Mail.IsCommandPending())
        or hayTomasRecientes()
    if cartaPedida then
        if (GetInboxNumItems()) == cartaPedida.cuantas and GetTime() - cartaPedida.en < SEGUNDOS_DE_TOMA then
            pendiente = true
        else
            cartaPedida = nil
        end
    end
    if not pendiente then
        local indice, clave = cartaPorRecoger()
        if not indice then
            recogiendo = false
            traza("buzon: no queda nada que recoger")
            if contar("devuelta") > 0 then
                avisarFin()
            end
            R.refrescarPanel()
            return
        end
        cartaPedida = { cuantas = (GetInboxNumItems()), en = GetTime() }
        TakeInboxItem(indice, 1)
        tomadas[indice] = { clave = clave, en = GetTime() }
        traza("buzon: recojo la carta %s (%s)", indice, clave)
    end
    C_Timer.After(SEGUNDOS_ENTRE_CARTAS, recogerSolo)
end

local function empezarARecoger()
    if recogiendo then
        return
    end
    recogiendo = true
    C_Timer.After(SEGUNDOS_ENTRE_CARTAS, recogerSolo)
end

-- ---------------------------------------------------------------------------
--  La tecla de interaccion
-- ---------------------------------------------------------------------------
--  Con la casa o el buzon abiertos, las teclas de "Interactuar con el
--  objetivo" hacen el siguiente paso del reposteo; al cerrar vuelven a abrir
--  lo que tengas delante. Asi una sola tecla abre la casa, cancela, abre el
--  buzon y repostea. Es lo mismo que hace Auctionator con sus atajos.

local teclado = CreateFrame("Frame")
local soltarAlSalirDeCombate = false

local function tomarTecla()
    if InCombatLockdown() then
        return
    end
    ClearOverrideBindings(teclado)
    local teclas = { GetBindingKey("INTERACTTARGET") }
    for _, tecla in ipairs(teclas) do
        SetOverrideBinding(teclado, false, tecla, "WOWALERTS_SIGUIENTE")
    end
    traza("tomo la tecla de interaccion: %s", table.concat(teclas, ", "))
end

local function soltarTecla()
    if InCombatLockdown() then
        -- En combate no se pueden tocar las teclas: se sueltan al salir.
        soltarAlSalirDeCombate = true
        return
    end
    soltarAlSalirDeCombate = false
    ClearOverrideBindings(teclado)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("ITEM_SEARCH_RESULTS_UPDATED")
frame:RegisterEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED")
frame:RegisterEvent("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
frame:RegisterEvent("OWNED_AUCTIONS_UPDATED")
frame:RegisterEvent("AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED")
frame:RegisterEvent("AUCTION_CANCELED")
frame:RegisterEvent("AUCTION_HOUSE_AUCTION_CREATED")
frame:RegisterEvent("MAIL_SHOW")
frame:RegisterEvent("MAIL_CLOSED")
frame:RegisterEvent("MAIL_INBOX_UPDATE")
frame:RegisterEvent("BAG_UPDATE_DELAYED")
-- Solo para la traza: lo que el juego rechaza o bloquea.
frame:RegisterEvent("UI_ERROR_MESSAGE")
frame:RegisterEvent("ADDON_ACTION_BLOCKED")
frame:RegisterEvent("ADDON_ACTION_FORBIDDEN")
frame:RegisterEvent("PLAYER_REGEN_ENABLED")

frame:SetScript("OnEvent", function(_, evento, arg1, arg2)
    if evento == "AUCTION_HOUSE_SHOW" then
        ultimoAviso = nil
        canceladasEnVisita = 0
        abiertaEn = GetTime()
        cuentaAnterior = nil
        listaRepetida = false
        buscadoEnEstaVisita = false
        pulsadaEnVisita = false
        reposteadas = {}
        repasadas = {}
        confirmadas = {}
        reiniciarBusqueda()
        colocarBoton(AuctionHouseFrame)
        traza("casa abierta (ventana de Blizzard cargada: %s). En %s s digo como esta el boton",
            tostring(AuctionHouseFrame ~= nil), SEGUNDOS_PARA_FIARSE)
        listaPedidaEn = nil
        faltaPedirLista = true
        pedirLista()
        tomarTecla()
        -- Pasada la espera no llega ningun evento: se refresca a mano para que
        -- el boton deje de decir "Leyendo tus subastas...".
        C_Timer.After(SEGUNDOS_PARA_FIARSE, function()
            buscarSolo()
            R.refrescarPanel()
            pcall(function()
                local b = WowAlertsReposteoBoton
                traza("boton creado: %s, visible: %s, escala: %s, borde de abajo a %s px del suelo, dice [%s]. Tecla: %s. Casa visible: %s, escala %s",
                    b ~= nil, b and b:IsVisible(), b and b:GetEffectiveScale(), b and b:GetBottom(),
                    b and b:GetText(), GetBindingKey("WOWALERTS_SIGUIENTE"),
                    AuctionHouseFrame and AuctionHouseFrame:IsVisible(),
                    AuctionHouseFrame and AuctionHouseFrame:GetEffectiveScale())
            end)
        end)
    elseif evento == "AUCTION_HOUSE_CLOSED" then
        abiertaEn = nil
        -- La entrada de una confirmacion pendiente se queda "posteando": la
        -- busqueda siguiente decide, igual que en R.Siguiente (I-2).
        confirmacion = nil
        faltaPedirLista = false
        reiniciarBusqueda()
        if not buzonAbierto() then
            soltarTecla()
        end
    elseif evento == "OWNED_AUCTIONS_UPDATED" then
        recibidasEn = GetTime()
        if abiertaEn then
            local cuenta = C_AuctionHouse.GetNumOwnedAuctions()
            listaRepetida = cuenta > 0 and cuenta == cuentaAnterior
            cuentaAnterior = cuenta
            -- Con la casa cerrada la lista no es de fiar.
            apuntarPrecios()
        end
        if not buscadoEnEstaVisita then
            traza("llega la lista de tus subastas: %s", C_AuctionHouse.GetNumOwnedAuctions())
            -- Pasada la calma no llega ningun evento: se refresca a mano para
            -- que el boton deje de decir "Leyendo tus subastas...".
            C_Timer.After(SEGUNDOS_DE_CALMA + 0.05, function()
                buscarSolo()
                R.refrescarPanel()
            end)
        end
    elseif evento == "ITEM_SEARCH_RESULTS_UPDATED" then
        alResponder(arg1)
    elseif evento == "AUCTION_HOUSE_BROWSE_RESULTS_UPDATED" then
        alNavegar()
    elseif evento == "AUCTION_HOUSE_THROTTLED_SYSTEM_READY" then
        pedirLista()
        lanzarSiguiente()
        buscarSolo()
    elseif evento == "AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED" then
        -- El servidor ha descartado una consulta: se vuelve a pedir la que
        -- estaba en curso, y la lista si aun no ha llegado respuesta.
        traza("la casa descarta una consulta (esperaba %s)", tostring(esperando))
        -- Una cancelacion recien pedida y sin respuesta puede ser lo descartado
        -- (visto en el juego: la tecla se quedaba 10 s esperando). Vuelve a la
        -- fila para que la siguiente pulsacion la repita; si no era ella, el
        -- AUCTION_CANCELED que llegue la da por devuelta igual.
        for _, e in ipairs(cola()) do
            if e.estado == "cancelando" and e.cancelandoEn
                and GetTime() - e.cancelandoEn < SEGUNDOS_DESCARTE then
                traza("  %s vuelve a la fila para cancelarla otra vez", e.auctionID)
                e.estado = "cancelar"
                e.cancelandoEn = nil
            end
        end
        if listaPedidaEn and (recibidasEn == nil or recibidasEn < listaPedidaEn) then
            faltaPedirLista = true
            pedirLista()
        end
        esperando = nil
        lanzarSiguiente()
    elseif evento == "AUCTION_CANCELED" then
        -- arg1 es el id de la subasta. El exportador apunta la cancelacion por
        -- su cuenta, con su propio frame.
        local e = buscarEntrada(arg1)
        reposteadas[arg1] = nil
        traza("el juego cancela la subasta %s (en la cola: %s)", tostring(arg1), e and e.estado or "no")
        if e and (e.estado == "cancelando" or e.estado == "cancelar") then
            e.estado = "devuelta"
            e.canceladaEn = time()
            -- Tus subastas con id mayor que este se crearon despues de la
            -- busqueda que la mando cancelar: si alguna es de este objeto, se
            -- ha vuelto a poner (ver prepararBusqueda).
            e.idTopeCancelada = (maxIdVisto > 0 and maxIdVisto) or e.auctionID
            canceladasEnVisita = canceladasEnVisita + 1
            comprobarFin()
        end
    elseif evento == "AUCTION_HOUSE_AUCTION_CREATED" then
        local entradas = cola()
        local nuestra = false   -- si la subasta creada es un posteo de la tecla
        local vieja = nil       -- la entrada de la cola que acaba de cerrarse
        traza("el juego crea la subasta %s (confirmacion pendiente: %s)", tostring(arg1), tostring(confirmacion ~= nil))
        if confirmacion then
            -- Se acepto desde el aviso de Blizzard: la subasta creada es la que
            -- esperaba confirmacion.
            local e, i = buscarEntrada(confirmacion.auctionID)
            -- La confirmacion guarda los mismos datos que la entrada: si esta
            -- ya no esta en la cola, sirve igual para pintar la fila.
            vieja = e or confirmacion
            if i then
                table.remove(entradas, i)
            end
            confirmacion = nil
            cerrarAvisoDePrecio()
            nuestra = true
        else
            -- La mas reciente de las que se estan posteando, si es de hace un
            -- momento. Una subasta creada mucho despues es otra cosa, como un
            -- posteo a mano: de los posteos viejos se encarga la busqueda.
            local elegida, reciente = nil, nil
            for i, e in ipairs(entradas) do
                if e.estado == "posteando" and e.posteandoEn
                    and GetTime() - e.posteandoEn < SEGUNDOS_SIN_RESPUESTA
                    and (not reciente or e.posteandoEn >= reciente) then
                    elegida, reciente = i, e.posteandoEn
                end
            end
            if elegida then
                vieja = table.remove(entradas, elegida)
                nuestra = true
            end
            traza("  quitada de la cola: %s", tostring(elegida ~= nil))
        end
        if nuestra and type(arg1) == "number" then
            -- Se ha puesto al precio del rival y es la mas nueva: va la primera,
            -- y la busqueda siguiente no necesita mirarla.
            apuntarVistaLimpia(arg1, time())
            -- Y tiene su propio grupo en la ventana el resto de la visita:
            -- machacando la tecla sin mirar, eso es lo que te dice que ya
            -- esta hecho.
            reposteadas[arg1] = {
                itemID = vieja and vieja.itemID,
                ilvl = vieja and vieja.ilvl,
                precio = vieja and vieja.precio,
                en = GetTime(),
            }
            -- Si esta caduca, su carta vuelve sin precio: se apunta ya.
            if vieja and vieja.itemKey and vieja.precio then
                preciosPuestos()[claveObjeto(vieja.itemID, vieja.ilvl)] = {
                    itemKey = vieja.itemKey,
                    precio = vieja.precio,
                }
            end
        end
        comprobarFin()
    elseif evento == "MAIL_SHOW" or evento == "MAIL_CLOSED" or evento == "MAIL_INBOX_UPDATE" then
        if evento == "MAIL_SHOW" then
            -- Una marca de otra visita al buzon no debe saltarse la espera.
            faltan = {}
            ultimoAviso = nil
            buzonPorEventos = true
            recogidaParada = false
            cartaPedida = nil
            tomarTecla()
        elseif evento == "MAIL_CLOSED" then
            buzonPorEventos = false
            if not casaAbierta() then
                soltarTecla()
            end
        end
        if evento ~= "MAIL_CLOSED" then
            apuntarCaducadas()
        end
        -- Justo despues de recoger, la carta ya no esta y el objeto puede no
        -- haber llegado a la bolsa: ese momento no sirve para olvidar nada.
        if evento == "MAIL_INBOX_UPDATE" and not hayTomasRecientes() then
            olvidarSinCarta()
        end
        tomadas = {}
        if evento == "MAIL_SHOW" then
            colocarBoton(MailFrame)
        end
        if evento ~= "MAIL_CLOSED" then
            empezarARecoger()
        end
    elseif evento == "BAG_UPDATE_DELAYED" then
        olvidarSinCarta()
    elseif evento == "UI_ERROR_MESSAGE" then
        if casaAbierta() or buzonAbierto() then
            traza("el juego dice: %s", tostring(arg2))
        end
        if recogiendo then
            -- Con la bolsa llena, por ejemplo: no se insiste. Se reintenta al
            -- volver a abrir el buzon.
            traza("buzon: paro de recoger")
            recogidaParada = true
        end
        return
    elseif evento == "PLAYER_REGEN_ENABLED" then
        if soltarAlSalirDeCombate and not casaAbierta() and not buzonAbierto() then
            soltarTecla()
        end
        return
    elseif evento == "ADDON_ACTION_BLOCKED" or evento == "ADDON_ACTION_FORBIDDEN" then
        if arg1 == "WowAlertsExport" then
            traza("|cffff4040ACCION BLOQUEADA|r (%s): %s", evento, tostring(arg2))
        end
        return
    end
    R.refrescarPanel()
end)
