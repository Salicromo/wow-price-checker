package com.burixer.cobertura

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Cuantos reinos se ensenan por pedido: los mas baratos, que es donde compras. */
private const val REINOS_POR_PEDIDO = 5

/**
 * El boton de apuntar a la lista de la compra, en las filas de lo que le falta
 * a un personaje. Relleno y dorado cuando ya esta apuntado.
 */
@Composable
internal fun BotonCompra(apuntado: Boolean, alPulsar: () -> Unit) {
    IconButton(onClick = alPulsar, modifier = Modifier.size(36.dp)) {
        Icon(
            imageVector = if (apuntado) Icons.Filled.ShoppingCart
            else Icons.Filled.AddShoppingCart,
            contentDescription = if (apuntado) "Quitar de la compra" else "Apuntar a la compra",
            tint = if (apuntado) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
internal fun ListaCompra(
    encargos: List<Encargo>,
    catalogo: Catalogo,
    mercado: Mercado?,
    datos: Datos,
    precios: Precios,
    alComprar: (Pedido) -> Unit,
    alQuitar: (Pedido, String) -> Unit,
) {
    val pedidos = remember(encargos) { Compra.agrupar(encargos) }
    val mios = remember(datos, catalogo) { misReinos(datos, catalogo) }
    // Los ilvl elegidos en el filtro. Se recortan a los que siguen en la lista:
    // al comprar lo ultimo de un ilvl, su ficha desaparece y no puede quedarse
    // filtrando a escondidas.
    var filtro by remember { mutableStateOf(emptySet<Int>()) }
    val ilvls = pedidos.mapNotNull { it.ilvl }.distinct().sorted()
    val activos = filtro intersect ilvls.toSet()
    val visibles = Compra.filtrar(pedidos, activos)

    if (pedidos.isEmpty()) {
        Text(
            text = "No tienes nada apuntado. En «Le falta a» de un objeto, o en «Sin poner» " +
                "de un personaje, toca el carrito de la fila para apuntarlo aquí.",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(16.dp),
        )
        return
    }
    if (mercado == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
        }
        return
    }

    // Una tarjeta que vuelve (deshacer) por encima de lo que estas viendo
    // entraria fuera de la pantalla y pareceria que no ha vuelto: se lleva la
    // lista hasta ella.
    val estado = rememberLazyListState()
    var vistas by remember { mutableStateOf(visibles.map { clave(it) }.toSet()) }
    LaunchedEffect(visibles) {
        val nueva = visibles.indexOfFirst { clave(it) !in vistas }
        vistas = visibles.map { clave(it) }.toSet()
        if (nueva >= 0) estado.animateScrollToItem(nueva)
    }

    Column {
        // Con un solo ilvl no hay nada que filtrar.
        if (ilvls.size > 1) {
            Row(
                Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                FichaIlvl("Todos", activos.isEmpty()) { filtro = emptySet() }
                ilvls.forEach { valor ->
                    FichaIlvl("$valor", valor in activos) {
                        filtro = if (valor in activos) activos - valor else activos + valor
                    }
                }
            }
        }
        LazyColumn(
            state = estado,
            contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(visibles, key = { clave(it) }) { pedido ->
                TarjetaPedido(
                    pedido, catalogo, mercado, mios, datos, precios,
                    alComprar = { alComprar(pedido) },
                    alQuitar = { alQuitar(pedido, it) },
                )
            }
        }
    }
}

@Composable
private fun TarjetaPedido(
    pedido: Pedido,
    catalogo: Catalogo,
    mercado: Mercado,
    mios: Map<String, List<Personaje>>,
    datos: Datos,
    precios: Precios,
    alComprar: () -> Unit,
    alQuitar: (String) -> Unit,
) {
    val objeto = catalogo.objetos.firstOrNull { it.id == pedido.itemId }
    val producto = mercado.productos.firstOrNull { !it.mascota && it.id == pedido.itemId }
    val ofertas = producto?.variantes
        ?.firstOrNull { it.valor == pedido.ilvl }?.ofertas.orEmpty()
        .take(REINOS_POR_PEDIDO)
    val tope = when {
        objeto == null -> null
        objeto.escala -> objeto.escalones.firstOrNull { it.ilvl == pedido.ilvl }?.tope
        else -> objeto.tope
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp, 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icono(objeto?.icono ?: producto?.icono, 40.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        text = objeto?.es ?: producto?.es ?: "Objeto ${pedido.itemId}",
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Medium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (pedido.ilvl != null) {
                        Text(
                            text = "ilvl ${pedido.ilvl}",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                TextButton(onClick = alComprar) { Text("Comprado") }
            }

            // Lo que vale en el reino de cada uno: contra los reinos de abajo
            // es lo que te dice si sale a cuenta comprarlo.
            Spacer(Modifier.height(10.dp))
            Titulo("Para", "${pedido.personajes.size}")
            pedido.personajes.forEach { nombre ->
                FilaPara(
                    nombre, datos.personajes[nombre], objeto, pedido.ilvl, precios,
                    vendido = nombre in pedido.vendidos,
                    alQuitar = { alQuitar(nombre) },
                )
            }

            Spacer(Modifier.height(10.dp))
            Titulo("Dónde comprarlo", "${ofertas.size}")
            if (ofertas.isEmpty()) {
                Text(
                    text = "Nadie lo vende ahora mismo en ningún reino de la región.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            ofertas.forEach { FilaOferta(it, mios, tope) }
        }
    }
}

private fun clave(pedido: Pedido) = "${pedido.itemId}|${pedido.ilvl}"

/**
 * Un personaje del pedido, con lo que vale el objeto en su reino. Al tocarlo se
 * abre la escalera de ilvl de ese reino, como en "Le falta a": con el ilvl que
 * compras marcado, tu tope y en rojo el que te pisa.
 */
@Composable
private fun FilaPara(
    nombre: String,
    ficha: Personaje?,
    objeto: Objeto?,
    ilvl: Int?,
    precios: Precios,
    vendido: Boolean,
    alQuitar: () -> Unit,
) {
    var desplegado by remember(nombre, ilvl) { mutableStateOf(false) }
    val reino = ficha?.reino.orEmpty()

    val conPrecio = objeto?.let { precios.escalera(reino, it.id).toMap() }.orEmpty()
    val topes = objeto?.escalones?.associate { it.ilvl to it.tope }.orEmpty()
    val escalera = if (objeto?.escala == true) {
        (topes.keys + conPrecio.keys + listOfNotNull(ilvl)).distinct().sorted()
    } else {
        emptyList()
    }
    val pisa = if (objeto?.escala == true && ilvl != null) precios.pisa(reino, objeto.id, ilvl)
    else null

    Column(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = escalera.isNotEmpty()) { desplegado = !desplegado }
            .padding(vertical = 6.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(mote(nombre), fontSize = 14.sp, fontWeight = FontWeight.Medium)
                    // Lo que entro solo, por una venta, frente a lo que apuntaste tu.
                    if (vendido) {
                        Spacer(Modifier.width(6.dp))
                        Text(
                            text = "vendido",
                            fontSize = 10.sp,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier
                                .border(1.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(4.dp))
                                .padding(horizontal = 5.dp, vertical = 1.dp),
                        )
                    }
                }
                Text(
                    text = donde(ficha),
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (objeto != null) {
                Column(horizontalAlignment = Alignment.End) {
                    DelReino(objeto, reino, precios, ilvl)
                }
            }
            IconButton(onClick = alQuitar, modifier = Modifier.size(36.dp)) {
                Icon(
                    Icons.Filled.Close,
                    contentDescription = "Quitar a ${mote(nombre)}",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
            }
        }

        if (pisa != null) {
            Text(
                text = "te pisa el ${pisa.first} a ${oro(pisa.second.oro)}",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 3.dp),
            )
        }

        AnimatedVisibility(
            visible = desplegado && escalera.isNotEmpty(),
            enter = expandVertically(tween(ENTRADA_MS, easing = FastOutSlowInEasing)) +
                fadeIn(tween(ENTRADA_MS)),
            exit = shrinkVertically(tween(SALIDA_MS)) + fadeOut(tween(SALIDA_MS)),
        ) {
            Column(Modifier.padding(top = 6.dp)) {
                escalera.chunked(3).forEach { grupo ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        grupo.forEach { escalon ->
                            Escalon(
                                ilvl = escalon,
                                precio = conPrecio[escalon],
                                tuyo = escalon == ilvl,
                                estorba = pisa != null && escalon == pisa.first,
                                tope = topes[escalon],
                            )
                        }
                    }
                    Spacer(Modifier.height(5.dp))
                }
            }
        }
    }
}
