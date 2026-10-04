package com.burixer.cobertura

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * La cobertura al reves: eliges el personaje y ves que objetos tiene puestos y
 * cuales no, con lo que vale cada uno en su reino. Es lo que miras con el
 * personaje ya conectado, para decidir que le subes.
 */
@Composable
internal fun Personajes(
    orden: List<String>,
    datos: Datos,
    precios: Precios,
    cobertura: List<Cobertura>,
    abierto: String?,
    alAbrir: (String) -> Unit,
    encargos: List<Encargo>,
    alApuntar: (Encargo) -> Unit,
) {
    // El ilvl que llevas encima. Vive aqui, fuera de la ficha, para que siga
    // elegido al pasar de un personaje a otro.
    var ilvl by remember { mutableStateOf<Int?>(null) }
    val ilvls = remember(cobertura) {
        cobertura.filter { it.objeto.escala }
            .flatMap { c -> c.objeto.escalones.map { it.ilvl } }
            .distinct().sorted()
    }

    Column {
        if (ilvls.isNotEmpty()) {
            Row(
                Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                FichaIlvl("Todos", ilvl == null) { ilvl = null }
                ilvls.forEach { valor ->
                    FichaIlvl("$valor", ilvl == valor) { ilvl = valor }
                }
            }
        }
        AnimatedContent(
            targetState = abierto,
            transitionSpec = {
                val haciaDentro = targetState != null
                (slideInHorizontally(tween<IntOffset>(ENTRADA_MS, easing = FastOutSlowInEasing)) {
                    if (haciaDentro) it / 5 else -it / 5
                } + fadeIn(tween(ENTRADA_MS))) togetherWith fadeOut(tween(SALIDA_MS))
            },
            label = "personaje",
        ) { nombre ->
            if (nombre == null) {
                ListaPersonajes(orden, datos, cobertura, ilvl, alAbrir)
            } else {
                FichaDelPersonaje(nombre, datos, precios, cobertura, ilvl, encargos, alApuntar)
            }
        }
    }
}

@Composable
internal fun FichaIlvl(texto: String, elegida: Boolean, alPulsar: () -> Unit) {
    FilterChip(
        selected = elegida,
        onClick = alPulsar,
        label = { Text(texto, fontFamily = FontFamily.Monospace, fontSize = 13.sp) },
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
            selectedLabelColor = MaterialTheme.colorScheme.onSurface,
        ),
        border = FilterChipDefaults.filterChipBorder(
            enabled = true,
            selected = elegida,
            borderColor = MaterialTheme.colorScheme.outline,
            selectedBorderColor = MaterialTheme.colorScheme.primary,
        ),
    )
}

internal fun donde(ficha: Personaje?): String = buildString {
    ficha?.reino?.takeIf { it.isNotBlank() }?.let { append(it) }
    ficha?.cuenta?.let { if (isNotEmpty()) append(" · "); append("WoW $it") }
}

@Composable
private fun ListaPersonajes(
    orden: List<String>,
    datos: Datos,
    cobertura: List<Cobertura>,
    ilvl: Int?,
    alAbrir: (String) -> Unit,
) {
    val total = cobertura.size
    LazyColumn(contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 24.dp)) {
        item {
            Text(
                text = "Elige el ilvl que llevas y un personaje para ver qué objetos le " +
                    "faltan y cuánto valen en su reino.",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
        }
        items(orden, key = { it }) { nombre ->
            // Mismo criterio que la ficha: a cualquier ilvl, o solo al elegido.
            val puestos = Calculo.delPersonaje(cobertura, nombre, ilvl).count { it.puesto }
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable { alAbrir(nombre) }
                    .padding(vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier
                        .width(3.dp)
                        .height(34.dp)
                        .background(
                            if (puestos < total) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.primary
                        )
                )
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(mote(nombre), fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    Text(
                        text = donde(datos.personajes[nombre]),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = "$puestos de $total",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                    color = if (puestos < total) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun FichaDelPersonaje(
    nombre: String,
    datos: Datos,
    precios: Precios,
    cobertura: List<Cobertura>,
    ilvl: Int?,
    encargos: List<Encargo>,
    alApuntar: (Encargo) -> Unit,
) {
    val reino = datos.personajes[nombre]?.reino.orEmpty()
    val objetos = remember(cobertura, nombre, ilvl) {
        Calculo.delPersonaje(cobertura, nombre, ilvl)
    }
    val (puestos, sinPoner) = objetos.partition { it.puesto }

    // El nombre ya va arriba en la barra; aqui solo el reino y la cuenta.
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp, 4.dp, 16.dp, 16.dp)
    ) {
        Text(
            text = donde(datos.personajes[nombre]),
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        // Primero lo que le falta: es lo que vienes a decidir.
        Spacer(Modifier.height(18.dp))
        Titulo(if (ilvl != null) "Sin poner — ilvl $ilvl" else "Sin poner", "${sinPoner.size}")
        Spacer(Modifier.height(8.dp))
        if (sinPoner.isEmpty()) {
            Text(
                text = "Tiene puestos todos los objetos que vigilas.",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        sinPoner.forEach { fila ->
            // Lo que escala se compra a un ilvl: sin elegir uno no hay que apuntar.
            val encargo = when {
                !fila.objeto.escala -> Encargo(fila.objeto.id, null, nombre)
                ilvl != null -> Encargo(fila.objeto.id, ilvl, nombre)
                else -> null
            }
            FilaObjeto(
                fila, reino, precios, ilvl,
                apuntado = encargo != null && Compra.contiene(encargos, encargo),
                alApuntar = encargo?.let { { alApuntar(it) } },
            )
        }

        Spacer(Modifier.height(18.dp))
        Titulo(if (ilvl != null) "Puestos — ilvl $ilvl" else "Puestos", "${puestos.size}")
        Spacer(Modifier.height(8.dp))
        if (puestos.isEmpty()) {
            Text(
                text = "No tiene ninguno de tus objetos en el mercado.",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        puestos.forEach { FilaObjeto(it, reino, precios, ilvl) }
        Spacer(Modifier.height(32.dp))
    }
}

/**
 * Un objeto en la ficha del personaje. A la derecha, lo mas barato de su reino
 * si no lo tiene, o lo suyo si lo tiene. Al tocar, la escalera de ilvl del
 * reino con tu tope, y marcados los ilvl que ya tiene puestos.
 */
@Composable
private fun FilaObjeto(
    fila: ObjetoDelPersonaje,
    reino: String,
    precios: Precios,
    ilvl: Int?,
    apuntado: Boolean = false,
    alApuntar: (() -> Unit)? = null,
) {
    val objeto = fila.objeto
    var desplegado by remember(objeto.id, reino) { mutableStateOf(false) }

    val conPrecio = precios.escalera(reino, objeto.id).toMap()
    val topes = objeto.escalones.associate { it.ilvl to it.tope }
    val escalera = if (objeto.escala) {
        (topes.keys + conPrecio.keys + fila.puestas.keys.filterNotNull()).distinct().sorted()
    } else {
        emptyList()
    }
    // Solo con un ilvl elegido: sin el no hay "tu ilvl" que pueda quedar pisado.
    val pisa = if (objeto.escala && ilvl != null) precios.pisa(reino, objeto.id, ilvl) else null

    Column(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = escalera.isNotEmpty()) { desplegado = !desplegado }
            .padding(vertical = 7.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icono(objeto.icono, 36.dp)
            Spacer(Modifier.width(10.dp))
            Text(
                text = objeto.es,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            Column(horizontalAlignment = Alignment.End) {
                if (fila.puesto) Suyo(fila) else DelReino(objeto, reino, precios, ilvl)
            }
            if (alApuntar != null) {
                Spacer(Modifier.width(4.dp))
                BotonCompra(apuntado, alApuntar)
            }
        }

        if (pisa != null) {
            Text(
                text = "te pisa el ${pisa.first} a ${oro(pisa.second.oro)}",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(start = 46.dp, top = 3.dp),
            )
        }

        AnimatedVisibility(
            visible = desplegado && escalera.isNotEmpty(),
            enter = expandVertically(tween(ENTRADA_MS, easing = FastOutSlowInEasing)) +
                fadeIn(tween(ENTRADA_MS)),
            exit = shrinkVertically(tween(SALIDA_MS)) + fadeOut(tween(SALIDA_MS)),
        ) {
            Column(Modifier.padding(start = 46.dp, top = 6.dp)) {
                escalera.chunked(3).forEach { grupo ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        grupo.forEach { escalon ->
                            Escalon(
                                ilvl = escalon,
                                precio = conPrecio[escalon],
                                // Con un ilvl elegido se marca ese, el que llevas;
                                // si no, los que ya tiene puestos.
                                tuyo = if (ilvl != null) escalon == ilvl
                                else escalon in fila.puestas,
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

@Composable
private fun Suyo(fila: ObjetoDelPersonaje) {
    val ilvls = fila.puestas.keys.filterNotNull().sorted()
    Text(
        text = "desde ${oro(fila.puestas.values.minOf { it.minOro })}",
        fontFamily = FontFamily.Monospace,
        fontSize = 13.sp,
        color = MaterialTheme.colorScheme.primary,
    )
    val cuantas = fila.puestas.values.sumOf { it.cuantas }
    Text(
        text = buildString {
            if (ilvls.isNotEmpty()) append("ilvl ${ilvls.joinToString(" · ")} — ")
            append(if (cuantas == 1) "1 subasta" else "$cuantas subastas")
        },
        fontSize = 11.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
internal fun DelReino(objeto: Objeto, reino: String, precios: Precios, ilvl: Int?) {
    // Con un ilvl elegido, el precio de ese ilvl. Sin elegir, mirado entero: en
    // lo que escala sale el ilvl mas barato del reino, y el resto de la
    // escalera esta a un toque.
    val alIlvl = objeto.escala && ilvl != null
    val consulta = if (alIlvl) precios.de(reino, objeto.id, ilvl, escala = true)
    else precios.de(reino, objeto.id, null, escala = false)
    when (consulta) {
        is Precios.Consulta.Hay -> {
            val ilvl = when {
                alIlvl -> ilvl
                objeto.escala -> precios.escalera(reino, objeto.id)
                    .firstOrNull { it.second == consulta.precio }?.first
                else -> null
            }
            Text(
                text = "desde ${oro(consulta.precio.oro)}",
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = buildString {
                    if (ilvl != null) append("ilvl $ilvl — ")
                    append("${consulta.precio.cuantas} en venta")
                },
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
