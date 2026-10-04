package com.burixer.cobertura

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.ContentTransform
import androidx.compose.animation.SizeTransform
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.NotificationsOff
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.NumberFormat
import java.util.Locale

// Cortas a proposito: esto se usa con el juego abierto y a medio repartir un
// chollo, no es una app de contemplar. Si apagas las animaciones del sistema,
// Compose las salta solo.
internal const val ENTRADA_MS = 260
internal const val SALIDA_MS = 120

private val Oro = Color(0xFF8A6410)
private val OroOscuro = Color(0xFFDFB349)
private val Falta = Color(0xFFA83E30)
private val FaltaOscuro = Color(0xFFE08678)

private val EsquemaClaro = lightColorScheme(
    primary = Oro,
    onPrimary = Color.White,
    background = Color(0xFFEBEEF2),
    onBackground = Color(0xFF171A21),
    surface = Color.White,
    onSurface = Color(0xFF171A21),
    surfaceVariant = Color(0xFFE2E6EC),
    onSurfaceVariant = Color(0xFF5B6472),
    error = Falta,
    outline = Color(0xFFD5DAE1),
)

private val EsquemaOscuro = darkColorScheme(
    primary = OroOscuro,
    onPrimary = Color(0xFF171A21),
    background = Color(0xFF101317),
    onBackground = Color(0xFFE7EAF0),
    surface = Color(0xFF181C22),
    onSurface = Color(0xFFE7EAF0),
    surfaceVariant = Color(0xFF13161B),
    onSurfaceVariant = Color(0xFF99A2B1),
    error = FaltaOscuro,
    outline = Color(0xFF262C35),
)

/** '18,6k', '1,2M': lo justo para que quepan tres escalones en una fila. */
internal fun oroCorto(valor: Long): String = when {
    valor >= 1_000_000 -> String.format(Locale("es", "ES"), "%.1fM", valor / 1_000_000.0)
    valor >= 1_000 -> String.format(Locale("es", "ES"), "%.1fk", valor / 1_000.0)
    else -> "$valor g"
}

internal fun oro(valor: Long): String =
    NumberFormat.getIntegerInstance(Locale("es", "ES")).format(valor) + " g"

/**
 * El sufijo que comparten todos los personajes de `orden`, si lo hay. No
 * distingue nada, asi que estorba. Se deduce de los datos, y no va escrito
 * aqui, porque este codigo es publico y los nombres no.
 */
internal fun sufijoComun(nombres: List<String>): String {
    if (nombres.size < 2) return ""
    var sufijo = nombres.first()
    for (nombre in nombres.drop(1)) {
        while (!nombre.endsWith(sufijo)) sufijo = sufijo.drop(1)
    }
    // Al menos tres letras, y nunca el nombre entero de ninguno.
    return if (sufijo.length >= 3 && nombres.all { it.length > sufijo.length }) sufijo else ""
}

private var sufijoPersonajes = ""

internal fun mote(nombre: String): String =
    if (sufijoPersonajes.isNotEmpty() && nombre.length > sufijoPersonajes.length &&
        nombre.endsWith(sufijoPersonajes)
    ) nombre.dropLast(sufijoPersonajes.length) else nombre

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = if (isSystemInDarkTheme()) EsquemaOscuro else EsquemaClaro
            ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    App()
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App() {
    val context = LocalContext.current
    val alcance = rememberCoroutineScope()
    val avisos = remember { SnackbarHostState() }

    var catalogo by remember { mutableStateOf(Repositorio.catalogo(context)) }
    sufijoPersonajes = sufijoComun(catalogo.orden)
    var datos by remember { mutableStateOf(Repositorio.datos(context)) }
    var precios by remember { mutableStateOf(Repositorio.precios(context)) }
    var cargando by remember { mutableStateOf(false) }
    var ajustes by remember { mutableStateOf(false) }
    var anadiendo by remember { mutableStateOf(false) }
    var abierto by remember { mutableStateOf<Int?>(null) }
    var buscando by remember { mutableStateOf(false) }
    // El buscador se lee de disco la primera vez que se abre, y no al arrancar:
    // son miles de productos y la pantalla principal no los necesita.
    var mercado by remember { mutableStateOf<Mercado?>(null) }
    var historial by remember { mutableStateOf(Historial.VACIO) }
    var mercadoLeido by remember { mutableStateOf(false) }
    // La lista de la compra tambien lo usa: es de donde salen los reinos baratos.
    var comprando by remember { mutableStateOf(false) }
    LaunchedEffect(buscando, comprando, mercadoLeido) {
        if ((buscando || comprando) && !mercadoLeido) {
            mercado = withContext(Dispatchers.IO) { Repositorio.mercado(context) }
            historial = withContext(Dispatchers.IO) { Repositorio.historial(context) }
            mercadoLeido = true
        }
    }

    // Topes enviados y todavia no confirmados. Se leen de disco porque la app se
    // muere al salir: en memoria moririan con ella y volverias a ver el numero
    // viejo justo despues de cambiarlo.
    var pendientes by remember { mutableStateOf(Topes.pendientes(context)) }
    var editando by remember { mutableStateOf<Variante?>(null) }
    // Topes apuntados para mandarlos juntos en una sola issue, por clave de
    // Topes.clave. En memoria: es lo que estas montando ahora, no un pendiente.
    val cesta = remember { mutableStateMapOf<String, Topes.Cambio>() }
    var viendoCesta by remember { mutableStateOf(false) }

    // El interruptor de avisos. `pausados` es lo que se ensena: lo pedido si
    // aun va de camino, y si no lo que dice config.yaml.
    var pausados by remember { mutableStateOf(Avisos.pausados(context)) }
    var motivoAvisos by remember { mutableStateOf(Avisos.motivo(context)) }
    var avisosPendiente by remember { mutableStateOf(Avisos.pendiente(context)) }
    var cambiandoAvisos by remember { mutableStateOf(false) }

    val cobertura = remember(datos) { Calculo.cobertura(catalogo, datos) }
    val elegido = cobertura.firstOrNull { it.objeto.id == abierto }

    // La vista por personaje. Atras sale primero del personaje y luego de la
    // lista, como en el buscador.
    var viendoPersonajes by remember { mutableStateOf(false) }
    var personajeAbierto by remember { mutableStateOf<String?>(null) }
    fun atrasEnPersonajes() {
        if (personajeAbierto != null) personajeAbierto = null else viendoPersonajes = false
    }
    BackHandler(enabled = viendoPersonajes) { atrasEnPersonajes() }

    // La lista de la compra. Se guarda en cada cambio: la app muere al salir.
    var encargos by remember { mutableStateOf(Compra.leer(context)) }
    fun cambiarEncargos(nuevos: List<Encargo>) {
        encargos = nuevos
        Compra.guardar(context, nuevos)
    }
    val alApuntar: (Encargo) -> Unit = { cambiarEncargos(Compra.alternar(encargos, it)) }
    // Quitar del carrito (comprado o descartado) con un aviso para deshacerlo:
    // vuelve cada encargo a su sitio, con su marca de vendido.
    fun quitarConDeshacer(quitados: List<Encargo>, mensaje: String) {
        if (quitados.isEmpty()) return
        val antes = encargos
        cambiarEncargos(antes - quitados.toSet())
        alcance.launch {
            avisos.currentSnackbarData?.dismiss()
            val respuesta = avisos.showSnackbar(
                message = mensaje,
                actionLabel = "Deshacer",
                duration = SnackbarDuration.Long,
            )
            if (respuesta == SnackbarResult.ActionPerformed) {
                cambiarEncargos(Compra.devolver(encargos, quitados, antes))
            }
        }
    }
    BackHandler(enabled = comprando) { comprando = false }
    // Lo que ya has puesto sale solo del carrito: cada vez que llegan subastas
    // nuevas (al abrir y al actualizar) se cruza con lo apuntado.
    LaunchedEffect(cobertura) {
        val puestos = Compra.yaPuestos(encargos, cobertura)
        if (puestos.isNotEmpty()) {
            cambiarEncargos(encargos - puestos.toSet())
            avisos.showSnackbar(
                if (puestos.size == 1) "Quitado 1 del carrito: ya lo tienes puesto."
                else "Quitados ${puestos.size} del carrito: ya los tienes puestos."
            )
        }
    }
    var menu by remember { mutableStateOf(false) }

    val enInicio = elegido == null && !buscando && !viendoPersonajes && !comprando

    BackHandler(enabled = elegido != null) { abierto = null }
    // Lo abierto en el buscador vive aqui y no dentro: la flecha de arriba y el
    // atras del sistema tienen que hacer lo mismo, volver primero a la lista
    // de la lupa y solo despues salir del buscador.
    var abiertoEnBuscador by remember { mutableStateOf<Seleccion?>(null) }
    fun atrasEnBuscador() {
        if (abiertoEnBuscador != null) abiertoEnBuscador = null else buscando = false
    }
    BackHandler(enabled = buscando) { atrasEnBuscador() }

    // La descarga de al abrir no dice nada cuando sale bien: no has pedido nada,
    // y un aviso cada vez que entras acaba siendo ruido que se ignora. Los
    // fallos si se cuentan siempre, porque significan que lo que estas viendo no
    // es de ahora.
    fun actualizar(avisar: Boolean = true) {
        if (cargando) return
        cargando = true
        alcance.launch {
            Repositorio.actualizar(context)
                .onSuccess { descarga ->
                    datos = descarga.datos
                    // La misma descarga trae el catalogo y los precios, asi que
                    // se releen: si has tocado config.yaml, aqui aparece.
                    catalogo = Repositorio.catalogo(context)
                    // Lo vendido va solo al carrito, para reponerlo.
                    val porVentas = Ventas.encargos(
                        descarga.vendidas, catalogo, Calculo.cobertura(catalogo, descarga.datos),
                    ).filterNot { Compra.contiene(encargos, it) }
                    if (porVentas.isNotEmpty()) {
                        cambiarEncargos(encargos + porVentas)
                        alcance.launch {
                            avisos.showSnackbar(
                                if (porVentas.size == 1) "Añadido 1 al carrito: lo has vendido."
                                else "Añadidos ${porVentas.size} al carrito: los has vendido."
                            )
                        }
                    }
                    precios = Repositorio.precios(context)
                    mercadoLeido = false
                    // La descarga ya ha borrado los pendientes que el catalogo
                    // nuevo confirma; esto releele lo que queda vivo.
                    pendientes = Topes.pendientes(context)
                    pausados = Avisos.pausados(context)
                    avisosPendiente = Avisos.pendiente(context)
                    motivoAvisos = Avisos.motivo(context)
                    if (avisar) avisos.showSnackbar("Datos actualizados desde GitHub.")
                }
                .onFailure { fallo ->
                    avisos.showSnackbar(fallo.message ?: "No he podido actualizar.")
                }
            cargando = false
        }
    }

    // Al abrir, siempre. La activity muere al salir (ver el manifiesto), asi que
    // esto corre una vez por vez que entras y no en cada recomposicion.
    //
    // Sin token no se intenta: no hay de donde bajar, y saltaria el mismo error
    // cada vez que abres hasta que lo configuras.
    LaunchedEffect(Unit) {
        if (Repositorio.token(context).isNotBlank()) actualizar(avisar = false)
    }

    Scaffold(
        snackbarHost = { SnackbarHost(avisos) },
        bottomBar = {
            if (cesta.isNotEmpty()) {
                Surface(tonalElevation = 3.dp) {
                    Row(
                        Modifier.fillMaxWidth().navigationBarsPadding().padding(16.dp, 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = if (cesta.size == 1) "1 tope en la cesta"
                            else "${cesta.size} topes en la cesta",
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = { viendoCesta = true }) { Text("Revisar y enviar") }
                    }
                }
            }
        },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
                navigationIcon = {
                    if (buscando) {
                        IconButton(onClick = { atrasEnBuscador() }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                        }
                    } else if (comprando) {
                        IconButton(onClick = { comprando = false }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                        }
                    } else if (viendoPersonajes) {
                        IconButton(onClick = { atrasEnPersonajes() }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                        }
                    } else if (elegido != null) {
                        IconButton(onClick = { abierto = null }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                        }
                    }
                },
                title = {
                    Text(
                        text = when {
                            buscando -> "Dónde está más barato"
                            comprando -> "Lista de la compra"
                            viendoPersonajes -> personajeAbierto?.let { mote(it) } ?: "Tus personajes"
                            elegido != null -> elegido.objeto.es
                            else -> "Quién no lo tiene"
                        },
                        fontWeight = FontWeight.Medium,
                        fontSize = if (enInicio) 20.sp else 17.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                actions = {
                    if (cargando) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(22.dp).padding(end = 4.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    } else {
                        IconButton(onClick = { actualizar() }) {
                            Icon(Icons.Filled.Refresh, contentDescription = "Actualizar")
                        }
                    }
                    if (enInicio) {
                        IconButton(onClick = { viendoPersonajes = true }) {
                            Icon(Icons.Filled.Person, contentDescription = "Por personaje")
                        }
                        IconButton(onClick = { buscando = true }) {
                            Icon(Icons.Filled.Search, contentDescription = "Buscar precio")
                        }
                        IconButton(onClick = { comprando = true }) {
                            BadgedBox(badge = {
                                if (encargos.isNotEmpty()) Badge { Text("${encargos.size}") }
                            }) {
                                Icon(Icons.Filled.ShoppingCart, contentDescription = "Lista de la compra")
                            }
                        }
                        // Lo que menos se usa, en el menu: con todo en la barra
                        // el titulo no cabe. Los avisos pausados se siguen viendo
                        // en la franja roja de encima de la lista.
                        Box {
                            IconButton(onClick = { menu = true }) {
                                Icon(Icons.Filled.MoreVert, contentDescription = "Más")
                            }
                            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                                // Sin token no se ofrece: el envio fallaria y el
                                // boton solo serviria para descubrirlo a base de
                                // tocarlo.
                                if (Repositorio.token(context).isNotBlank()) {
                                    DropdownMenuItem(
                                        text = { Text("Añadir objeto") },
                                        leadingIcon = { Icon(Icons.Filled.Add, null) },
                                        onClick = { menu = false; anadiendo = true },
                                    )
                                    DropdownMenuItem(
                                        text = {
                                            Text(if (pausados == true) "Avisos (pausados)" else "Avisos")
                                        },
                                        leadingIcon = {
                                            if (pausados == true) {
                                                Icon(
                                                    Icons.Filled.NotificationsOff,
                                                    null,
                                                    tint = MaterialTheme.colorScheme.error,
                                                )
                                            } else {
                                                Icon(Icons.Filled.Notifications, null)
                                            }
                                        },
                                        onClick = { menu = false; cambiandoAvisos = true },
                                    )
                                }
                                DropdownMenuItem(
                                    text = { Text("Ajustes") },
                                    leadingIcon = { Icon(Icons.Filled.Settings, null) },
                                    onClick = { menu = false; ajustes = true },
                                )
                            }
                        }
                    } else {
                        IconButton(onClick = { ajustes = true }) {
                            Icon(Icons.Filled.Settings, contentDescription = "Ajustes")
                        }
                    }
                },
            )
        },
    ) { relleno ->
        Column(Modifier.padding(relleno)) {
            if (pausados == true && enInicio) {
                AvisoPausa(
                    pendiente = avisosPendiente != null,
                    alPulsar = { cambiandoAvisos = true },
                )
            }
            AnimatedContent(
                targetState = buscando,
                transitionSpec = { lateral(haciaDentro = targetState) },
                label = "buscar",
            ) { enBuscador ->
            if (enBuscador) {
                Buscador(
                    mercado = mercado,
                    cargando = !mercadoLeido,
                    catalogo = catalogo,
                    tusObjetos = cobertura.map { it.objeto },
                    abierto = abiertoEnBuscador,
                    alAbrir = { abiertoEnBuscador = it },
                    datos = datos,
                    historial = historial,
                    pendientes = pendientes,
                    // Mismo dialogo que en la ficha del objeto, con la variante
                    // de la pantalla principal: es la que sabe enviarlo.
                    alTocarTope = if (Repositorio.token(context).isBlank()) null
                    else ({ id, ilvl ->
                        cobertura.firstOrNull { it.objeto.id == id }?.variantes
                            ?.firstOrNull { it.ilvl == ilvl && it.vigilado }
                            ?.let { editando = it }
                    }),
                )
            } else if (comprando) {
                ListaCompra(
                    encargos = encargos,
                    catalogo = catalogo,
                    mercado = if (mercadoLeido) mercado ?: Mercado.VACIO else null,
                    datos = datos,
                    precios = precios,
                    // Se quita al momento, pero se puede deshacer: es facil
                    // tocarlo sin querer y no hay otra forma de recuperarlo.
                    alComprar = { pedido ->
                        quitarConDeshacer(Compra.delPedido(encargos, pedido), "Marcado como comprado.")
                    },
                    alQuitar = { pedido, personaje ->
                        quitarConDeshacer(
                            Compra.delPersonaje(encargos, pedido, personaje),
                            "Quitado ${mote(personaje)} del carrito.",
                        )
                    },
                )
            } else if (viendoPersonajes) {
                Personajes(
                    orden = catalogo.orden,
                    datos = datos,
                    precios = precios,
                    cobertura = cobertura,
                    abierto = personajeAbierto,
                    alAbrir = { personajeAbierto = it },
                    encargos = encargos,
                    alApuntar = alApuntar,
                )
            } else {
            // La pantalla entra por el lado hacia el que vas, como en cualquier
            // app: sin eso, abrir un objeto es un parpadeo y no se sabe si has
            // entrado o si se ha recargado la lista.
            AnimatedContent(
                targetState = abierto,
                transitionSpec = {
                    val entrada = tween<Float>(ENTRADA_MS, easing = FastOutSlowInEasing)
                    val salida = tween<Float>(SALIDA_MS, easing = FastOutSlowInEasing)
                    val haciaDentro = targetState != null
                    val desplazamiento = tween<IntOffset>(
                        ENTRADA_MS, easing = FastOutSlowInEasing
                    )
                    (slideInHorizontally(desplazamiento) { ancho ->
                        if (haciaDentro) ancho / 5 else -ancho / 5
                    } + fadeIn(entrada)) togetherWith
                        fadeOut(salida) using SizeTransform(clip = false)
                },
                label = "pantalla",
            ) { id ->
                val abiertoAhora = cobertura.firstOrNull { it.objeto.id == id }
                if (abiertoAhora == null) {
                    Listado(
                        cobertura = cobertura,
                        orden = catalogo.orden,
                        exportado = datos.exportado,
                        conDescarga = Repositorio.hayDescarga(context),
                        alPulsar = { abierto = it.objeto.id },
                    )
                } else {
                    Detalle(
                        cobertura = abiertoAhora,
                        datos = datos,
                        precios = precios,
                        personajes = catalogo.orden.size,
                        pendientes = pendientes,
                        // Sin token no se ofrece: el envio fallaria y el boton
                        // solo serviria para descubrirlo a base de tocarlo.
                        alTocarTope = if (Repositorio.token(context).isBlank()) null
                        else ({ editando = it }),
                        encargos = encargos,
                        alApuntar = alApuntar,
                    )
                }
            }
            }
            }
        }
    }

    editando?.let { variante ->
        val objeto = cobertura.first { c -> c.variantes.any { it === variante } }.objeto
        val clave = Topes.clave(objeto.id, variante.ilvl)
        DialogoTope(
            objeto = objeto,
            variante = variante,
            pendiente = pendientes[clave],
            enCesta = cesta[clave]?.tope,
            // Con la cesta empezada, enviar uno suelto la dejaria a medias.
            sueltoPermitido = cesta.isEmpty(),
            alCerrar = { editando = null },
            alApuntar = { tope ->
                editando = null
                cesta[clave] = Topes.Cambio(objeto, variante.ilvl, tope)
            },
            alEnviar = { tope ->
                editando = null
                alcance.launch {
                    Topes.enviar(context, objeto, variante.ilvl, tope)
                        .onSuccess {
                            pendientes = Topes.pendientes(context)
                            avisos.showSnackbar(
                                "Tope enviado. Entra en vigor en la pasada siguiente."
                            )
                        }
                        .onFailure { fallo ->
                            avisos.showSnackbar(fallo.message ?: "No he podido enviarlo.")
                        }
                }
            },
        )
    }

    if (viendoCesta) {
        DialogoCesta(
            cambios = cesta.values.toList(),
            alQuitar = { c ->
                cesta.remove(Topes.clave(c.objeto.id, c.ilvl))
                if (cesta.isEmpty()) viendoCesta = false
            },
            alCerrar = { viendoCesta = false },
            alEnviar = {
                viendoCesta = false
                val cambios = cesta.values.toList()
                alcance.launch {
                    val resultado = if (cambios.size == 1) {
                        cambios.single().let { Topes.enviar(context, it.objeto, it.ilvl, it.tope) }
                    } else Topes.enviarVarios(context, cambios)
                    resultado
                        .onSuccess {
                            cambios.forEach { cesta.remove(Topes.clave(it.objeto.id, it.ilvl)) }
                            pendientes = Topes.pendientes(context)
                            avisos.showSnackbar(
                                if (cambios.size == 1) "Tope enviado. Entra en vigor en la pasada siguiente."
                                else "${cambios.size} topes enviados en una issue. Entran en vigor en la pasada siguiente."
                            )
                        }
                        .onFailure { fallo ->
                            avisos.showSnackbar(fallo.message ?: "No he podido enviarlos.")
                        }
                }
            },
        )
    }

    if (anadiendo) {
        DialogoObjeto(
            alCerrar = { anadiendo = false },
            alEnviar = { objeto, tipo, topesIlvl, tope ->
                anadiendo = false
                alcance.launch {
                    Objetos.enviar(context, objeto, tipo, topesIlvl, tope)
                        .onSuccess {
                            avisos.showSnackbar(
                                "Objeto enviado. Si GitHub lo acepta, se vigila desde la " +
                                    "pasada siguiente."
                            )
                        }
                        .onFailure { fallo ->
                            avisos.showSnackbar(fallo.message ?: "No he podido enviarlo.")
                        }
                }
            },
        )
    }

    if (cambiandoAvisos) {
        DialogoAvisos(
            pausados = pausados,
            pendiente = avisosPendiente,
            motivo = motivoAvisos,
            alCerrar = { cambiandoAvisos = false },
            alConfirmar = { pausar ->
                cambiandoAvisos = false
                alcance.launch {
                    Avisos.enviar(context, pausar)
                        .onSuccess {
                            pausados = Avisos.pausados(context)
                            avisosPendiente = Avisos.pendiente(context)
                            motivoAvisos = Avisos.motivo(context)
                            avisos.showSnackbar(
                                if (pausar) "Pausa enviada. En un minuto deja de avisar."
                                else "Enviado. En un minuto vuelve a avisar."
                            )
                        }
                        .onFailure { fallo ->
                            avisos.showSnackbar(fallo.message ?: "No he podido enviarlo.")
                        }
                }
            },
        )
    }

    if (ajustes) {
        DialogoAjustes(
            tokenInicial = Repositorio.token(context),
            repoInicial = Repositorio.repo(context),
            alCerrar = { ajustes = false },
            alGuardar = { token, repo ->
                Repositorio.guardarAjustes(context, token, repo)
                ajustes = false
                actualizar()
            },
        )
    }
}

@Composable
private fun Listado(
    cobertura: List<Cobertura>,
    orden: List<String>,
    exportado: Long,
    conDescarga: Boolean,
    alPulsar: (Cobertura) -> Unit,
) {
    LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Column(Modifier.padding(16.dp, 12.dp, 16.dp, 6.dp)) {
                Text(
                    text = "De lo que más tienes puesto a lo que menos. Elige el objeto y " +
                        "el ilvl que llevas encima.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (!conDescarga) {
                    Spacer(Modifier.height(8.dp))
                    // Sin decir la fecha, un aviso de "datos viejos" no dice
                    // nada: lo que importa es cuanto de viejos.
                    Text(
                        text = "Sin conectar. Estás viendo una copia del " +
                            "${fecha(exportado)} que vino dentro de la app y no cambia " +
                            "sola. Toca el engranaje y pega un token de GitHub para bajar " +
                            "tus subastas de ahora.",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }

        items(cobertura, key = { it.objeto.id }) { fila ->
            Column(
                Modifier
                    .fillMaxWidth()
                    .clickable { alPulsar(fila) }
                    .padding(horizontal = 16.dp, vertical = 10.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icono(fila.objeto.icono, 40.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            text = fila.objeto.es,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium,
                            maxLines = 2,
                        )
                        Spacer(Modifier.height(5.dp))
                        Rejilla(fila, orden)
                    }
                    Spacer(Modifier.width(10.dp))
                    Column(horizontalAlignment = Alignment.End) {
                        Text(
                            text = "${fila.puestas}",
                            fontFamily = FontFamily.Monospace,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium,
                            color = if (fila.puestas == 0) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.primary,
                        )
                        Text(
                            text = "${fila.conAlgo.size}/${orden.size}",
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        }

        item {
            Text(
                text = "${orden.size} personajes vigilados · volcado del addon " +
                    fecha(exportado),
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}

/**
 * Un cuadrito por personaje, en tu orden. Dorado = lo tiene a algun ilvl.
 *
 * La posicion importa: asi el mismo hueco cae siempre en el mismo sitio y se
 * reconoce de un vistazo quien es sin leer nombres.
 */
@Composable
private fun Rejilla(fila: Cobertura, orden: List<String>) {
    Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        orden.forEach { personaje ->
            Box(
                Modifier
                    .size(6.dp)
                    .background(
                        color = if (personaje in fila.conAlgo) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.outline,
                        shape = RoundedCornerShape(1.dp),
                    )
            )
        }
    }
}

@Composable
private fun Detalle(
    cobertura: Cobertura,
    datos: Datos,
    precios: Precios,
    personajes: Int,
    pendientes: Map<String, Long> = emptyMap(),
    alTocarTope: ((Variante) -> Unit)? = null,
    encargos: List<Encargo> = emptyList(),
    alApuntar: ((Encargo) -> Unit)? = null,
) {
    var variante by remember(cobertura.objeto.id) { mutableStateOf(cobertura.porDefecto) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icono(cobertura.objeto.icono, 56.dp)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(cobertura.objeto.es, fontSize = 17.sp, fontWeight = FontWeight.Medium)
                if (cobertura.objeto.en != cobertura.objeto.es) {
                    Text(
                        text = cobertura.objeto.en,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (cobertura.objeto.escala) {
            Spacer(Modifier.height(14.dp))
            Fichas(cobertura, variante) { variante = it }
        }

        Spacer(Modifier.height(14.dp))

        // Al cambiar de ilvl cambia todo lo de abajo. Cruzarlo, en vez de
        // sustituirlo de golpe, es lo que deja claro que sigues en el mismo
        // objeto y solo has movido el nivel.
        AnimatedContent(
            targetState = variante,
            transitionSpec = {
                val sube = (targetState.ilvl ?: 0) > (initialState.ilvl ?: 0)
                (slideInVertically(
                    tween(ENTRADA_MS, easing = FastOutSlowInEasing)
                ) { alto -> if (sube) alto / 12 else -alto / 12 } +
                    fadeIn(tween(ENTRADA_MS, easing = FastOutSlowInEasing))) togetherWith
                    fadeOut(tween(SALIDA_MS)) using SizeTransform(clip = false)
            },
            label = "variante",
        ) { actual ->
            Column {
                // Solo un escalon que ya esta en tu tabla: anadir uno nuevo es
                // otra operacion, y esa sigue siendo trabajo de config.yaml.
                if (actual.vigilado) {
                    TopeAviso(
                        tope = actual.tope,
                        pendiente = pendientes[Topes.clave(cobertura.objeto.id, actual.ilvl)],
                        alTocar = alTocarTope?.let { { it(actual) } },
                    )
                    Spacer(Modifier.height(10.dp))
                }
                Veredicto(variante = actual, total = personajes)

                Spacer(Modifier.height(18.dp))
                if (actual.faltan.isNotEmpty()) {
                    Titulo(
                        if (actual.ilvl != null) "Le falta a — ilvl ${actual.ilvl}"
                        else "Le falta a",
                        "${actual.faltan.size}",
                    )
                    Spacer(Modifier.height(8.dp))
                    actual.faltan.forEach { nombre ->
                        val encargo = Encargo(cobertura.objeto.id, actual.ilvl, nombre)
                        FichaFalta(
                            nombre, datos, precios, cobertura.objeto, actual,
                            apuntado = Compra.contiene(encargos, encargo),
                            alApuntar = alApuntar?.let { { it(encargo) } },
                        )
                    }
                    Spacer(Modifier.height(18.dp))
                }

                Titulo("Ya lo tiene puesto", "${actual.tienen.size}")
                Spacer(Modifier.height(8.dp))
                if (actual.tienen.isEmpty()) {
                    Text(
                        text = if (actual.ilvl != null)
                            "Nadie lo tiene a ilvl ${actual.ilvl} en el mercado."
                        else "Nadie. Este objeto no está en el mercado con ninguno de tus " +
                            "personajes.",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    actual.tienen.forEach { puesta ->
                        FichaPersonaje(puesta.personaje, datos, puesta)
                    }
                }
                Spacer(Modifier.height(32.dp))
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Fichas(
    cobertura: Cobertura,
    elegida: Variante,
    alElegir: (Variante) -> Unit,
) {
    Column {
        cobertura.variantes.chunked(4).forEach { grupo ->
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                grupo.forEach { variante ->
                    FilterChip(
                        selected = variante === elegida,
                        onClick = { alElegir(variante) },
                        label = {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = "${variante.ilvl}",
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 13.sp,
                                )
                                Spacer(Modifier.width(5.dp))
                                Text(
                                    text = "${variante.tienen.size}",
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor =
                                MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
                            selectedLabelColor = MaterialTheme.colorScheme.onSurface,
                        ),
                        border = FilterChipDefaults.filterChipBorder(
                            enabled = true,
                            selected = variante === elegida,
                            borderColor = MaterialTheme.colorScheme.outline,
                            selectedBorderColor = MaterialTheme.colorScheme.primary,
                        ),
                    )
                }
            }
            Spacer(Modifier.height(6.dp))
        }
        if (cobertura.variantes.any { !it.vigilado }) {
            Text(
                text = "Los ilvl que no están en tu tabla de precios salen igual, " +
                    "porque tienes subastas puestas a ese nivel.",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun Veredicto(variante: Variante, total: Int) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (variante.faltan.isEmpty())
                MaterialTheme.colorScheme.surfaceVariant
            else MaterialTheme.colorScheme.error.copy(alpha = 0.12f)
        ),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier.padding(14.dp, 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (variante.faltan.isEmpty()) {
                Text(
                    text = "Lo tienen los $total. No hay hueco donde meterlo.",
                    fontSize = 14.sp,
                )
            } else {
                Text(
                    text = "${variante.faltan.size}",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    text = if (variante.faltan.size == 1) "personaje sin ponerlo, de $total"
                    else "personajes sin ponerlo, de $total",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
internal fun Titulo(texto: String, contador: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(
            text = texto.uppercase(),
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = contador,
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun FichaPersonaje(nombre: String, datos: Datos, puesta: Puesta?) {
    val ficha = datos.personajes[nombre]
    val donde = buildString {
        ficha?.reino?.takeIf { it.isNotBlank() }?.let { append(it) }
        ficha?.cuenta?.let { if (isNotEmpty()) append(" · "); append("WoW $it") }
    }
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .width(3.dp)
                .height(34.dp)
                .background(
                    if (puesta == null) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary
                )
        )
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(mote(nombre), fontSize = 15.sp, fontWeight = FontWeight.Medium)
            Text(
                text = donde,
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (puesta != null) {
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "desde ${oro(puesta.minOro)}",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    text = if (puesta.cuantas == 1) "1 subasta" else "${puesta.cuantas} subastas",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * Un personaje al que le falta el objeto, con lo que cuesta entrar en su reino.
 *
 * Que falte no basta para decidir. Si de tu ilvl no hay nada puesto pero al lado
 * hay uno mejor mas barato, el tuyo no lo compra nadie: eso sale cantado sin
 * tener que desplegar. Y al tocar aparece la escalera entera de ilvl del reino,
 * que es lo que deja poner precio con criterio.
 */
@Composable
private fun FichaFalta(
    nombre: String,
    datos: Datos,
    precios: Precios,
    objeto: Objeto,
    variante: Variante,
    apuntado: Boolean = false,
    alApuntar: (() -> Unit)? = null,
) {
    var desplegado by remember(nombre, variante.ilvl) { mutableStateOf(false) }

    val ficha = datos.personajes[nombre]
    val reino = ficha?.reino.orEmpty()
    val donde = buildString {
        reino.takeIf { it.isNotBlank() }?.let { append(it) }
        ficha?.cuenta?.let { if (isNotEmpty()) append(" · "); append("WoW $it") }
    }

    val consulta = precios.de(reino, objeto.id, variante.ilvl, objeto.escala)
    val pisa = if (objeto.escala) precios.pisa(reino, objeto.id, variante.ilvl) else null

    // Todos los ilvl del objeto, no solo los que tienen algo puesto: que uno
    // este vacio es justo lo que quieres ver, y por ausencia no se ve.
    val conPrecio = precios.escalera(reino, objeto.id).toMap()
    val escalera = if (objeto.escala) {
        (objeto.escalones.map { it.ilvl } + conPrecio.keys).distinct().sorted()
    } else {
        emptyList()
    }

    Column(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = escalera.isNotEmpty()) { desplegado = !desplegado }
            .padding(vertical = 7.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .width(3.dp)
                    .height(34.dp)
                    .background(MaterialTheme.colorScheme.error)
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(mote(nombre), fontSize = 15.sp, fontWeight = FontWeight.Medium)
                Text(
                    text = donde,
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                when (consulta) {
                    is Precios.Consulta.Hay -> {
                        Text(
                            text = "hay a ${oro(consulta.precio.oro)}",
                            fontFamily = FontFamily.Monospace,
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = if (consulta.precio.cuantas == 1) "1 en venta"
                            else "${consulta.precio.cuantas} en venta",
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    is Precios.Consulta.Vacio -> Text(
                        text = "nadie lo vende ahí",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Precios.Consulta.SinDato -> Text(
                        text = "sin precio",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (alApuntar != null) {
                Spacer(Modifier.width(4.dp))
                BotonCompra(apuntado, alApuntar)
            }
        }

        AnimatedVisibility(
            visible = pisa != null,
            enter = expandVertically(tween(ENTRADA_MS, easing = FastOutSlowInEasing)) +
                fadeIn(tween(ENTRADA_MS)),
            exit = shrinkVertically(tween(SALIDA_MS)) + fadeOut(tween(SALIDA_MS)),
        ) {
            Text(
                text = pisa?.let { "te pisa el ${it.first} a ${oro(it.second.oro)}" }.orEmpty(),
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(start = 13.dp, top = 3.dp),
            )
        }

        AnimatedVisibility(
            visible = desplegado && escalera.isNotEmpty(),
            enter = expandVertically(tween(ENTRADA_MS, easing = FastOutSlowInEasing)) +
                fadeIn(tween(ENTRADA_MS)),
            exit = shrinkVertically(tween(SALIDA_MS)) + fadeOut(tween(SALIDA_MS)),
        ) {
            Column(Modifier.padding(start = 13.dp, top = 6.dp)) {
                escalera.chunked(3).forEach { grupo ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        grupo.forEach { ilvl ->
                            Escalon(
                                ilvl = ilvl,
                                precio = conPrecio[ilvl],
                                tuyo = ilvl == variante.ilvl,
                                // Rojo el que te deja sin sitio: mejor que el
                                // tuyo y mas barato.
                                estorba = pisa != null && ilvl == pisa.first,
                            )
                        }
                    }
                    Spacer(Modifier.height(5.dp))
                }
            }
        }
    }
}

@Composable
internal fun Escalon(
    ilvl: Int,
    precio: Precio?,
    tuyo: Boolean,
    estorba: Boolean,
    tope: Long? = null,
) {
    val color = when {
        estorba -> MaterialTheme.colorScheme.error
        tuyo -> MaterialTheme.colorScheme.primary
        precio == null -> MaterialTheme.colorScheme.onSurfaceVariant
        else -> MaterialTheme.colorScheme.onSurface
    }
    Column(
        Modifier
            .width(88.dp)
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 5.dp)
    ) {
        Text(
            text = if (tuyo) "$ilvl ←" else "$ilvl",
            fontFamily = FontFamily.Monospace,
            fontSize = 12.sp,
            fontWeight = if (tuyo) FontWeight.Medium else FontWeight.Normal,
            color = color,
        )
        Text(
            text = if (precio == null) "—" else oroCorto(precio.oro),
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            color = color,
        )
        Text(
            text = if (precio == null) "vacío" else "${precio.cuantas} en venta",
            fontSize = 10.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (tope != null) {
            Text(
                text = "tope ${oroCorto(tope)}",
                fontSize = 10.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
internal fun Icono(url: String?, tamano: androidx.compose.ui.unit.Dp) {
    Box(
        Modifier
            .size(tamano)
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(6.dp))
    ) {
        if (url != null) {
            AsyncImage(
                model = url,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

/**
 * Cambiar el tope de una variante.
 *
 * No escribe config.yaml: abre una issue que un workflow aplica. Por eso el
 * boton dice "Enviar" y no "Guardar", y por eso avisa de que tarda: prometer un
 * cambio inmediato seria mentir, y volverias a tocarlo creyendo que fallo.
 */
@Composable
private fun DialogoTope(
    objeto: Objeto,
    variante: Variante,
    pendiente: Long?,
    enCesta: Long?,
    sueltoPermitido: Boolean,
    alCerrar: () -> Unit,
    alApuntar: (Long) -> Unit,
    alEnviar: (Long) -> Unit,
) {
    val actual = pendiente ?: variante.tope
    var texto by remember { mutableStateOf((enCesta ?: actual)?.toString().orEmpty()) }

    val nuevo = texto.filter { it.isDigit() }.toLongOrNull()
    val valido = nuevo != null && nuevo > 0

    AlertDialog(
        onDismissRequest = alCerrar,
        title = {
            Text(
                if (variante.ilvl != null) "Tope · ilvl ${variante.ilvl}" else "Tope"
            )
        },
        text = {
            Column {
                Text(
                    text = objeto.es,
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = if (actual != null) {
                        "Ahora: ${oro(actual)}" + if (pendiente != null) " (pendiente)" else ""
                    } else "Sin tope puesto.",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                )
                if (enCesta != null) {
                    Text(
                        text = "En la cesta: ${oro(enCesta)}",
                        fontFamily = FontFamily.Monospace,
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = texto,
                    onValueChange = { texto = it },
                    label = { Text("tope nuevo, en oro") },
                    singleLine = true,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = "Se manda como una issue a GitHub. El tope entra en vigor " +
                        "en la pasada siguiente, como mucho dentro de una hora. " +
                        "Con 'A la cesta' juntas varios en una sola issue.",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            Row {
                TextButton(
                    onClick = { nuevo?.let(alApuntar) },
                    enabled = valido && nuevo != actual,
                ) { Text("A la cesta") }
                if (sueltoPermitido) {
                    TextButton(
                        onClick = { nuevo?.let(alEnviar) },
                        enabled = valido && nuevo != actual,
                    ) { Text("Enviar") }
                }
            }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Cancelar") }
        },
    )
}

/**
 * Lo apuntado en la cesta, para repasarlo antes de mandarlo todo junto en una
 * sola issue: un solo commit en vez de una issue por tope.
 */
@Composable
private fun DialogoCesta(
    cambios: List<Topes.Cambio>,
    alQuitar: (Topes.Cambio) -> Unit,
    alCerrar: () -> Unit,
    alEnviar: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = alCerrar,
        title = { Text("Cesta de topes") },
        text = {
            LazyColumn {
                items(cambios.size) { i ->
                    val c = cambios[i]
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(text = c.objeto.es, fontSize = 14.sp)
                            Text(
                                text = (c.ilvl?.let { "ilvl $it · " } ?: "") + oro(c.tope),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 13.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        IconButton(onClick = { alQuitar(c) }) {
                            Icon(Icons.Filled.Close, contentDescription = "Quitar de la cesta")
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = alEnviar) {
                Text(if (cambios.size == 1) "Enviar" else "Enviar ${cambios.size}")
            }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Seguir") }
        },
    )
}

/** Una fila de la tabla del dialogo, tal y como se esta escribiendo. */
private class FilaTope {
    var ilvl by mutableStateOf("")
    var oro by mutableStateOf("")
}

@Composable
private fun DialogoObjeto(
    alCerrar: () -> Unit,
    alEnviar: (String, String, List<Pair<Int, Long>>?, Long?) -> Unit,
) {
    var texto by remember { mutableStateOf("") }
    var tipo by remember { mutableStateOf(Objetos.EQUIPO) }
    var topeTexto by remember { mutableStateOf("") }
    val filas = remember { mutableStateListOf(FilaTope()) }

    // Las filas vacias del todo no cuentan; una a medias impide enviar.
    val escritas = filas.filter { it.ilvl.isNotBlank() || it.oro.isNotBlank() }
    val escalones = escritas.map { it.ilvl.toIntOrNull() to it.oro.toLongOrNull() }
    val completos = escalones.isNotEmpty() && escalones.all { (ilvl, oro) ->
        ilvl != null && ilvl > 0 && ilvl <= Objetos.ILVL_MAXIMO && oro != null && oro > 0
    }
    val repetido = escalones.mapNotNull { it.first }.let { it.toSet().size != it.size }
    val fueraDeRango = escalones.any { (ilvl, _) -> ilvl != null && ilvl > Objetos.ILVL_MAXIMO }
    val topesIlvl = if (completos && !repetido) {
        escalones.map { it.first!! to it.second!! }
    } else {
        null
    }

    val tope = topeTexto.toLongOrNull()
    val valido = texto.isNotBlank() && if (tipo == Objetos.EQUIPO) {
        topesIlvl != null
    } else {
        tope != null && tope > 0
    }

    AlertDialog(
        onDismissRequest = alCerrar,
        title = { Text("Añadir objeto") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(
                    value = texto,
                    onValueChange = { texto = it },
                    label = { Text("enlace de Wowhead o nombre en inglés") },
                    singleLine = true,
                )
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = tipo == Objetos.EQUIPO,
                        onClick = { tipo = Objetos.EQUIPO },
                        label = { Text("Equipo") },
                    )
                    FilterChip(
                        selected = tipo == Objetos.PATRON,
                        onClick = { tipo = Objetos.PATRON },
                        label = { Text("Patrón") },
                    )
                }
                Spacer(Modifier.height(10.dp))
                if (tipo == Objetos.EQUIPO) {
                    filas.forEach { fila ->
                        key(fila) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                OutlinedTextField(
                                    value = fila.ilvl,
                                    onValueChange = { fila.ilvl = it.filter(Char::isDigit).take(4) },
                                    label = { Text("ilvl") },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.weight(0.4f),
                                )
                                Spacer(Modifier.width(8.dp))
                                OutlinedTextField(
                                    value = fila.oro,
                                    onValueChange = { fila.oro = it.filter(Char::isDigit) },
                                    label = { Text("tope, en oro") },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.weight(0.6f),
                                )
                                if (filas.size > 1) {
                                    IconButton(onClick = { filas.remove(fila) }) {
                                        Icon(Icons.Filled.Close, contentDescription = "Quitar ilvl")
                                    }
                                }
                            }
                            Spacer(Modifier.height(6.dp))
                        }
                    }
                    TextButton(onClick = { filas.add(FilaTope()) }) { Text("+ ilvl") }
                    if (repetido) {
                        Text(
                            text = "Hay un ilvl repetido.",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    if (fueraDeRango) {
                        Text(
                            text = "El ilvl máximo es ${Objetos.ILVL_MAXIMO}.",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                } else {
                    OutlinedTextField(
                        value = topeTexto,
                        onValueChange = { topeTexto = it.filter(Char::isDigit) },
                        label = { Text("tope, en oro") },
                        singleLine = true,
                    )
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    text = "Se manda como una issue a GitHub. El objeto empieza a " +
                        "vigilarse en la pasada siguiente, como mucho dentro de una hora.",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    alEnviar(
                        texto,
                        tipo,
                        if (tipo == Objetos.EQUIPO) topesIlvl else null,
                        if (tipo == Objetos.PATRON) tope else null,
                    )
                },
                enabled = valido,
            ) { Text("Enviar") }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Cancelar") }
        },
    )
}

/** La franja que recuerda que los avisos estan parados. */
@Composable
private fun AvisoPausa(pendiente: Boolean, alPulsar: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        modifier = Modifier.fillMaxWidth().clickable(onClick = alPulsar),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Filled.NotificationsOff,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                text = if (pendiente) "Pausando avisos… se aplica en un minuto."
                else "Avisos pausados: no llega nada a Discord.",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
    }
}

/**
 * Pausar o reanudar, con las dos acciones siempre a la vista.
 *
 * No se ofrece solo "la contraria de lo que hay puesto": si la app se equivoca
 * al leer el estado --o no ha podido leerlo-- eso deja sin salida, que es lo
 * que paso leyendo config.yaml del repositorio que no era. La que ya esta
 * puesta sale apagada, y eso mismo es lo que te dice como estan.
 */
@Composable
private fun DialogoAvisos(
    pausados: Boolean?,
    pendiente: Boolean?,
    motivo: String?,
    alCerrar: () -> Unit,
    alConfirmar: (Boolean) -> Unit,
) {
    AlertDialog(
        onDismissRequest = alCerrar,
        title = { Text("Avisos de Discord") },
        text = {
            Column {
                Text(
                    text = when (pausados) {
                        true -> "Ahora mismo están pausados: no llega nada a Discord."
                        false -> "Ahora mismo están activos."
                        null -> "No sé cómo están: no he podido leer config.yaml."
                    },
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Medium,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    text = "En pausa se sigue vigilando cada hora, pero no se envía nada: " +
                        "ni chollos, ni undercuts, ni ventas. Al reanudar te llega lo que " +
                        "siga vigente. Tarda un minuto en aplicarse.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (pendiente != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Hay un cambio enviado que GitHub aún no ha aplicado.",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (motivo != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = motivo,
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            Row {
                TextButton(
                    onClick = { alConfirmar(true) },
                    enabled = pausados != true,
                ) { Text("Pausar") }
                TextButton(
                    onClick = { alConfirmar(false) },
                    enabled = pausados != false,
                ) { Text("Reanudar") }
            }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Cancelar") }
        },
    )
}

@Composable
private fun DialogoAjustes(
    tokenInicial: String,
    repoInicial: String,
    alCerrar: () -> Unit,
    alGuardar: (String, String) -> Unit,
) {
    var token by remember { mutableStateOf(tokenInicial) }
    var repo by remember { mutableStateOf(repoInicial) }

    AlertDialog(
        onDismissRequest = alCerrar,
        title = { Text("Conectar con GitHub") },
        text = {
            Column {
                Text(
                    text = "Un token de acceso personal sobre los dos repositorios, que se " +
                        "queda en este móvil. Necesita Contents: Read-only en el " +
                        "privado (<repo>-privado) para ver los datos, e Issues: Read " +
                        "and write en el público para cambiar topes y añadir objetos.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = repo,
                    onValueChange = { repo = it },
                    label = { Text("usuario/repositorio") },
                    singleLine = true,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("token") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { alGuardar(token, repo) }) { Text("Guardar y actualizar") }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Cancelar") }
        },
    )
}

/** Como se llama una variante: el ilvl, la calidad de la mascota, o nada. */
private fun etiqueta(producto: Producto, valor: Int?): String = when {
    valor == null -> "—"
    producto.mascota -> Mercado.CALIDADES.getOrNull(valor) ?: "$valor"
    else -> "$valor"
}

/**
 * Entrar hacia la derecha y volver hacia la izquierda, como el resto de la app:
 * sin eso, abrir algo es un parpadeo y no se sabe si has entrado o recargado.
 */
private fun lateral(haciaDentro: Boolean): ContentTransform = ContentTransform(
    targetContentEnter = slideInHorizontally(
        tween(ENTRADA_MS, easing = FastOutSlowInEasing)
    ) { ancho -> if (haciaDentro) ancho / 5 else -ancho / 5 } +
        fadeIn(tween(ENTRADA_MS, easing = FastOutSlowInEasing)),
    initialContentExit = fadeOut(tween(SALIDA_MS, easing = FastOutSlowInEasing)),
    sizeTransform = SizeTransform(clip = false),
)

/** Lo que se ha abierto en el buscador, y en que variante empieza. */
private data class Seleccion(val producto: Producto, val valor: Int?)

/**
 * Donde esta mas barato cualquier cosa de la region, como en la casa de subastas.
 *
 * Con la caja vacia salen tus objetos, cada uno con sus ilvl a un toque; al
 * escribir, cualquier cosa que se venda. Al elegir salen los reinos del mas
 * barato al mas caro.
 */
@Composable
private fun Buscador(
    mercado: Mercado?,
    cargando: Boolean,
    catalogo: Catalogo,
    // Tus objetos en el orden de la pantalla principal, que es al que estas hecho.
    tusObjetos: List<Objeto>,
    abierto: Seleccion?,
    alAbrir: (Seleccion) -> Unit,
    datos: Datos,
    historial: Historial,
    pendientes: Map<String, Long>,
    alTocarTope: ((Int, Int?) -> Unit)?,
) {
    var texto by remember { mutableStateOf("") }

    // 0 cargando, 1 sin datos, 2 listo. Un cruce suave entre ellos, para que la
    // lista no aparezca de golpe cuando acaba de leerse.
    val fase = when {
        cargando -> 0
        mercado == null || mercado.productos.isEmpty() -> 1
        else -> 2
    }
    AnimatedContent(
        targetState = fase,
        transitionSpec = {
            fadeIn(tween(ENTRADA_MS)) togetherWith fadeOut(tween(SALIDA_MS))
        },
        label = "buscador",
    ) { f ->
        when {
            f == 0 -> Box(
                Modifier.fillMaxWidth().padding(32.dp),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            }
            f == 1 || mercado == null -> Text(
                text = "Todavía no hay precios de la región. Se publican en la próxima " +
                    "pasada del escaneo; después toca actualizar.",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(16.dp),
            )
            else -> AnimatedContent(
                targetState = abierto,
                // Cambiar de ilvl dentro no es cambiar de pantalla.
                contentKey = { it?.producto },
                transitionSpec = { lateral(haciaDentro = targetState != null) },
                label = "buscador-pantalla",
            ) { seleccion ->
                if (seleccion == null) {
                    ListaBuscador(
                        texto = texto,
                        alEscribir = { texto = it },
                        mercado = mercado,
                        tusObjetos = tusObjetos,
                        alAbrir = { producto, valor -> alAbrir(Seleccion(producto, valor)) },
                    )
                } else {
                    FichaMercado(seleccion, mercado, catalogo, datos, historial, pendientes, alTocarTope)
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ListaBuscador(
    texto: String,
    alEscribir: (String) -> Unit,
    mercado: Mercado,
    tusObjetos: List<Objeto>,
    alAbrir: (Producto, Int?) -> Unit,
) {
    val escribiendo = texto.trim().length >= 2
    val encontrados = remember(texto, mercado) { mercado.buscar(texto) }
    // Tu objeto en el mercado. Si ahora no lo vende nadie se abre igual, vacio:
    // saber que no lo hay en ningun sitio tambien es la respuesta.
    val tuyos = remember(mercado, tusObjetos) {
        val porId = mercado.productos.filter { !it.mascota }.associateBy { it.id }
        tusObjetos.map { o ->
            o to (porId[o.id] ?: Producto(false, o.id, o.es, o.en, o.icono, emptyList()))
        }
    }

    LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
        item(key = "caja") {
            OutlinedTextField(
                value = texto,
                onValueChange = alEscribir,
                placeholder = { Text("Buscar objeto o mascota") },
                singleLine = true,
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (texto.isNotEmpty()) {
                        IconButton(onClick = { alEscribir("") }) {
                            Icon(Icons.Filled.Close, contentDescription = "Borrar")
                        }
                    }
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp, 12.dp, 16.dp, 6.dp),
            )
        }
        if (escribiendo) {
            if (encontrados.isEmpty()) {
                item(key = "nada") {
                    Text(
                        text = "Nada con ese nombre a la venta por encima de 500 g.",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier
                            .animateItem()
                            .padding(horizontal = 16.dp, vertical = 6.dp),
                    )
                }
            }
            items(encontrados, key = { (if (it.mascota) "m" else "o") + it.id }) { p ->
                Column(Modifier.animateItem()) {
                    FilaProducto(p.icono, p.es, p.en, alPulsar = {
                        alAbrir(p, p.variantes.firstOrNull()?.valor)
                    }) {
                        // El precio solo cuando no hay nada que elegir: con varias
                        // variantes, el mas barato seria de un ilvl cualquiera.
                        p.variantes.singleOrNull()?.ofertas?.firstOrNull()?.let {
                            Text(
                                text = "desde ${oroCorto(it.oro)}",
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                }
            }
        } else {
            item(key = "titulo") {
                Column(
                    Modifier
                        .animateItem()
                        .padding(16.dp, 10.dp, 16.dp, 4.dp)
                ) {
                    Titulo("Tus objetos", "${tuyos.size}")
                }
            }
            items(tuyos, key = { "t" + it.first.id }) { (objeto, producto) ->
                val conOferta = producto.variantes.filter { it.ofertas.isNotEmpty() }
                    .map { it.valor }.toSet()
                val ilvls = objeto.escalones.map { it.ilvl }
                Column(Modifier.animateItem()) {
                    FilaProducto(
                        objeto.icono, objeto.es, objeto.en,
                        alPulsar = {
                            alAbrir(producto, ilvls.firstOrNull() ?: producto.variantes.firstOrNull()?.valor)
                        },
                        debajo = if (objeto.escala) {
                            {
                                // Tus ilvl, a un toque. Apagados los que ahora no
                                // vende nadie en la region.
                                FlowRow(
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    verticalArrangement = Arrangement.spacedBy(6.dp),
                                    modifier = Modifier.padding(top = 8.dp),
                                ) {
                                    ilvls.forEach { ilvl ->
                                        FichaIlvl(ilvl, hay = ilvl in conOferta) {
                                            alAbrir(producto, ilvl)
                                        }
                                    }
                                }
                            }
                        } else null,
                    ) {}
                }
            }
            item(key = "pie") {
                Text(
                    text = "Escribe arriba para buscar cualquier otra cosa: " +
                        "${mercado.productos.size} productos en ${mercado.grupos.size} " +
                        "reinos. Materiales y consumibles no salen: cuestan lo mismo " +
                        "en toda la región.",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .animateItem()
                        .padding(16.dp),
                )
            }
        }
    }
}

/** Un ilvl que se puede tocar, en la lista de tus objetos. */
@Composable
private fun FichaIlvl(ilvl: Int, hay: Boolean, alPulsar: () -> Unit) {
    Box(
        Modifier
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(6.dp))
            .clickable(onClick = alPulsar)
            .padding(horizontal = 10.dp, vertical = 5.dp)
    ) {
        Text(
            text = "$ilvl",
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            color = if (hay) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun FilaProducto(
    icono: String?,
    es: String,
    en: String,
    alPulsar: () -> Unit,
    debajo: (@Composable () -> Unit)? = null,
    derecha: @Composable () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = alPulsar)
            .padding(horizontal = 16.dp, vertical = 10.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icono(icono, 36.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(es, fontSize = 15.sp, fontWeight = FontWeight.Medium, maxLines = 2)
                if (en != es) {
                    Text(
                        text = en,
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            derecha()
        }
        debajo?.invoke()
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outline)
}

/**
 * Los reinos mas baratos de un producto.
 *
 * Se marca en que cuenta tienes personaje en cada reino, porque solo ahi puedes
 * comprar sin hacerte uno, y si el objeto es de los que vigilas, el tope, que es
 * tu referencia de si un precio es bueno.
 */
@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun FichaMercado(
    seleccion: Seleccion,
    mercado: Mercado,
    catalogo: Catalogo,
    datos: Datos,
    historial: Historial,
    pendientes: Map<String, Long>,
    alTocarTope: ((Int, Int?) -> Unit)?,
) {
    val producto = seleccion.producto
    // El tope solo existe si el objeto es de los que vigilas.
    val vigilado = if (producto.mascota) null
    else catalogo.objetos.firstOrNull { it.id == producto.id }

    // Si lo vigilas, solo tus ilvl: los demas no los compras. Si no, todo lo
    // que hay a la venta.
    val opciones = if (vigilado != null && vigilado.escala) vigilado.escalones.map { it.ilvl }
    else producto.variantes.map { it.valor }
    var valor by remember(producto) { mutableStateOf(seleccion.valor ?: opciones.firstOrNull()) }

    val mios = remember(datos, catalogo) { misReinos(datos, catalogo) }
    // El historial guarda el nombre del grupo; con esto se le sacan los slugs.
    val slugsDeGrupo = remember(mercado) { mercado.grupos.associate { it.nombre to it.slugs } }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icono(producto.icono, 48.dp)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(producto.es, fontSize = 17.sp, fontWeight = FontWeight.Medium)
                if (producto.en != producto.es) {
                    Text(
                        text = producto.en,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        if (opciones.size > 1) {
            Spacer(Modifier.height(14.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                opciones.forEach { v ->
                    FilterChip(
                        selected = v == valor,
                        onClick = { valor = v },
                        label = {
                            Text(
                                text = etiqueta(producto, v),
                                fontFamily = FontFamily.Monospace,
                                fontSize = 13.sp,
                            )
                        },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor =
                                MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
                            selectedLabelColor = MaterialTheme.colorScheme.onSurface,
                        ),
                        border = FilterChipDefaults.filterChipBorder(
                            enabled = true,
                            selected = v == valor,
                            borderColor = MaterialTheme.colorScheme.outline,
                            selectedBorderColor = MaterialTheme.colorScheme.primary,
                        ),
                    )
                }
            }
        }
        Spacer(Modifier.height(12.dp))

        // Al cambiar de ilvl la lista se cruza, subiendo o bajando segun hacia
        // donde vas, igual que en la ficha de un objeto.
        AnimatedContent(
            targetState = valor,
            transitionSpec = {
                val sube = (targetState ?: 0) > (initialState ?: 0)
                (slideInVertically(
                    tween(ENTRADA_MS, easing = FastOutSlowInEasing)
                ) { alto -> if (sube) alto / 12 else -alto / 12 } +
                    fadeIn(tween(ENTRADA_MS, easing = FastOutSlowInEasing))) togetherWith
                    fadeOut(tween(SALIDA_MS)) using SizeTransform(clip = false)
            },
            label = "variante-mercado",
        ) { actual ->
            val ofertas = producto.variantes.firstOrNull { it.valor == actual }?.ofertas.orEmpty()
            val topeActual = when {
                vigilado == null -> null
                vigilado.escala -> vigilado.escalones.firstOrNull { it.ilvl == actual }?.tope
                else -> vigilado.tope
            }
            Column {
                if (vigilado != null && (topeActual != null || !vigilado.escala)) {
                    TopeAviso(
                        tope = topeActual,
                        pendiente = pendientes[Topes.clave(producto.id, actual)],
                        alTocar = alTocarTope?.let { { it(producto.id, actual) } },
                    )
                    Spacer(Modifier.height(16.dp))
                }
                Titulo(
                    when {
                        actual == null -> "Los reinos más baratos"
                        producto.mascota -> "Los reinos más baratos — ${etiqueta(producto, actual)}"
                        else -> "Los reinos más baratos — ilvl $actual"
                    },
                    "${ofertas.size}",
                )
                Spacer(Modifier.height(8.dp))
                if (ofertas.isEmpty()) {
                    Text(
                        text = "Nadie lo vende ahora mismo en ningún reino de la región.",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                ofertas.forEach { oferta ->
                    FilaOferta(oferta, mios, topeActual)
                }
                if (ofertas.isNotEmpty()) {
                    Text(
                        text = "Solo los ${ofertas.size} reinos más baratos de " +
                            "${mercado.grupos.size} · precios del ${fecha(mercado.generado)}",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 16.dp),
                    )
                }
                // Solo de lo que vigilas: es lo unico de lo que se guarda el mes.
                if (vigilado != null) {
                    Spacer(Modifier.height(24.dp))
                    HistorialDias(historial.de(producto.id, actual), topeActual) { reino ->
                        Entrada.de(reino, slugsDeGrupo[reino].orEmpty(), mios)
                    }
                }
                Spacer(Modifier.height(32.dp))
            }
        }
    }
}

/**
 * El precio por debajo del cual te avisa Discord, junto a los reinos mas
 * baratos: es donde se ve si esta alto o bajo, y por eso se cambia aqui.
 * Mientras el cambio va de camino se ensena el enviado.
 */
@Composable
private fun TopeAviso(tope: Long?, pendiente: Long?, alTocar: (() -> Unit)?) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier
            .fillMaxWidth()
            .then(if (alTocar != null) Modifier.clickable(onClick = alTocar) else Modifier),
    ) {
        Row(Modifier.padding(14.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    text = "Te avisa por debajo de",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = (pendiente ?: tope)?.let { oro(it) } ?: "sin tope",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    color = if (pendiente != null) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface,
                )
                if (pendiente != null) {
                    Text(
                        text = "pendiente: entra en vigor en la pasada siguiente",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (alTocar != null) {
                Icon(
                    Icons.Filled.Edit,
                    contentDescription = "Cambiar tope",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

/**
 * El mas barato de cada dia en la region, de hoy hacia atras, con el minimo
 * del mes destacado: es lo que dice si el precio de hoy es bueno o si toca
 * esperar.
 */
@Composable
private fun HistorialDias(dias: List<DiaHistorial>, tope: Long?, entrada: (String) -> Entrada) {
    Titulo("El más barato, día a día", "${dias.size}")
    Spacer(Modifier.height(8.dp))
    if (dias.isEmpty()) {
        Text(
            text = "Todavía no hay días apuntados. Cada pasada del escaneo guarda el " +
                "más barato del día; se van sumando hasta 30.",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    val minimo = dias.minBy { it.oro }
    val maximo = dias.maxOf { it.oro }
    Text(
        text = (if (dias.size == 1) "Hoy: " else "Mínimo de ${dias.size} días: ") +
            "${oro(minimo.oro)} el " +
            "${diaCorto(minimo.dia)} en ${entrada(minimo.reino).titulo}",
        fontSize = 12.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(bottom = 6.dp),
    )
    dias.asReversed().forEach { d ->
        val esMinimo = d.oro == minimo.oro
        val bajoTope = tope != null && d.oro <= tope
        Row(
            Modifier
                .fillMaxWidth()
                .padding(vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = diaCorto(d.dia),
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                modifier = Modifier.width(72.dp),
            )
            Column(Modifier.weight(1f)) {
                val quien = entrada(d.reino)
                Text(
                    text = quien.titulo,
                    fontSize = 13.sp,
                    color = if (quien.tuyo) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                // La barra da la tendencia de un vistazo, sin leer numeros.
                Box(
                    Modifier
                        .padding(top = 3.dp)
                        .fillMaxWidth(if (maximo > 0) d.oro.toFloat() / maximo else 0f)
                        .height(3.dp)
                        .background(
                            if (esMinimo) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.outline
                        )
                )
            }
            Spacer(Modifier.width(10.dp))
            Text(
                text = oro(d.oro),
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
                fontWeight = if (esMinimo || bajoTope) FontWeight.Medium else FontWeight.Normal,
                color = if (esMinimo || bajoTope) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

/** '2026-09-27' a '27 sep'. */
private fun diaCorto(dia: String): String = runCatching {
    val entrada = java.text.SimpleDateFormat("yyyy-MM-dd", Locale.ROOT)
    java.text.SimpleDateFormat("d MMM", Locale("es", "ES")).format(entrada.parse(dia)!!)
}.getOrDefault(dia)

@Composable
internal fun FilaOferta(oferta: Oferta, mios: Map<String, List<Personaje>>, tope: Long?) {
    val quien = Entrada.de(oferta.grupo.nombre, oferta.grupo.slugs, mios)
    val tuyos = quien.personajes
    val bajoTope = tope != null && oferta.oro <= tope
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .width(3.dp)
                .height(34.dp)
                .background(
                    if (tuyos.isNotEmpty()) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.outline
                )
        )
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                text = quien.titulo,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = quien.detalle,
                fontSize = 12.sp,
                color = if (tuyos.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.primary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = oro(oferta.oro),
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
                fontWeight = if (bajoTope) FontWeight.Medium else FontWeight.Normal,
                color = if (bajoTope) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = (if (oferta.cuantas == 1) "1 en venta" else "${oferta.cuantas} en venta") +
                    if (bajoTope) " · bajo tope" else "",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outline)
}

/**
 * A que entras para comprar en un grupo de reinos.
 *
 * El nombre del grupo ("Kor'gall / Executus / ...") no sirve para nada en el
 * selector de personajes: lo que buscas ahi es tu personaje. Si no tienes
 * ninguno en el grupo, basta el primer reino para saber donde esta.
 */
private data class Entrada(val titulo: String, val detalle: String, val personajes: List<Personaje>) {
    val tuyo get() = personajes.isNotEmpty()

    companion object {
        fun de(grupo: String, slugs: List<String>, mios: Map<String, List<Personaje>>): Entrada {
            // Primero WoW 2 y WoW 3, y WoW 1 solo si no hay otro. Dentro de cada
            // cuenta, tu orden (sortedBy es estable).
            val claves = slugs + grupo.split(" / ").map { "=" + claveDeNombre(it) }
            val tuyos = claves.flatMap { mios[it].orEmpty() }.distinct()
                .sortedBy { prioridadDeCuenta(it.cuenta) }
            if (tuyos.isEmpty()) {
                return Entrada(grupo.substringBefore(" / "), "sin personaje tuyo", tuyos)
            }
            // Con uno basta para entrar: el primero. Debajo, que WoW abres y en que reino sale en el selector.
            val primero = tuyos.first()
            val titulo = mote(primero.nombre)
            val detalle = listOfNotNull(primero.cuenta?.let { "WoW $it" }, primero.reino).joinToString(" · ")
            return Entrada(titulo, detalle, tuyos)
        }
    }
}

private fun claveDeNombre(reino: String): String = normal(reino.trim())

private fun prioridadDeCuenta(cuenta: Int?): Int = when (cuenta) {
    2 -> 0
    3 -> 1
    1 -> 2
    else -> 3
}

private fun fecha(exportado: Long): String {
    if (exportado <= 0L) return "desconocido"
    val formato = java.text.SimpleDateFormat("d MMM HH:mm", Locale("es", "ES"))
    return formato.format(java.util.Date(exportado * 1000))
}

/**
 * Reino -> tus personajes ahi, en el orden de la pantalla principal. Por slug y
 * ademas por nombre: los reinos rusos vienen en cirilico y su slug se queda
 * vacio, pero el nombre si coincide con el del grupo.
 */
internal fun misReinos(datos: Datos, catalogo: Catalogo): Map<String, List<Personaje>> {
    val orden = catalogo.orden
    val ordenados = datos.personajes.values
        .filter { it.reino.isNotBlank() }
        .sortedBy { orden.indexOf(it.nombre).let { i -> if (i < 0) Int.MAX_VALUE else i } }
    val porSlug = ordenados.filter { slugDeReino(it.reino).isNotEmpty() }
        .groupBy { slugDeReino(it.reino) }
    val porNombre = ordenados.groupBy { claveDeNombre(it.reino) }
    return porSlug + porNombre.mapKeys { "=" + it.key }
}
