package com.burixer.cobertura

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Que has vendido, para apuntarlo solo en el carrito.
 *
 * Ningun dato lo dice entero. Tus subastas dicen personaje, objeto e ilvl, pero
 * que una desaparezca puede ser venta, caducidad o que la cancelaste. Las
 * ventas de Journalator dicen que vendiste, pero solo cuantas por reino y
 * objeto. Juntas si: una subasta que desaparece en un reino donde la cuenta de
 * ventas de ese objeto sube, se vendio.
 *
 * Journalator apunta la venta al recoger el correo, que puede ser bastante
 * despues de que la subasta desaparezca. Por eso lo desaparecido se guarda como
 * pendiente unos dias, esperando a que llegue su venta.
 *
 * El reposteo cancela muchisimo: el 2026-10-25 Das Konsortium llego a tener 51
 * pendientes del collar, casi todas canceladas, y una venta de un 318 se apunto
 * como un 308 que ya volvia a estar puesto. Por eso lo que el addon dice haber
 * cancelado no espera venta, y la venta se casa por el oro que ha entrado.
 */
object Ventas {

    /** Lo que espera una desaparecida a que llegue su venta. */
    private const val ESPERA_MS = 72L * 3_600_000L

    /** Lo que llega al buzon de cada venta, despues del 5 % de la casa. */
    private const val NETO = 0.95

    /**
     * Hasta cuantas candidatas se prueban todas las combinaciones cuando entran
     * varias ventas a la vez. Sin canceladas suelen ser cinco o seis.
     */
    private const val MAX_COMBINADAS = 16

    private const val FICHERO = "ventas_estado.json"

    data class Pendiente(val subasta: Subasta, val desde: Long)

    /**
     * Por donde iba la cuenta de ventas y el oro de cada reino y objeto, y lo
     * desaparecido sin confirmar.
     */
    data class Estado(
        val ventas: Map<String, Int>,
        val pendientes: List<Pendiente>,
        val oro: Map<String, Long> = emptyMap(),
    )

    fun clave(reino: String, nombre: String) = "$reino|$nombre"

    /**
     * Un paso: lo que ha desaparecido entre `antes` y `ahora` pasa a pendiente,
     * salvo lo que el addon cancelo, y cada venta nueva de un reino y objeto se
     * casa con pendientes de ese reino y objeto: las que mas se acercan al oro
     * que ha entrado, o sin ese dato las mas baratas, que se venden antes.
     *
     * Sin estado (la primera vez) no se confirma nada: no se sabe cuantas
     * ventas habia antes y todas parecerian nuevas.
     */
    fun avanzar(
        estado: Estado?,
        antes: List<Subasta>,
        ahora: List<Subasta>,
        ventas: Map<String, Int>,
        ahoraMs: Long,
        oro: Map<String, Long> = emptyMap(),
        canceladas: Set<Long> = emptySet(),
    ): Pair<Estado, List<Subasta>> {
        val siguen = ahora.map { it.id }.toSet()
        val yaPendientes = estado?.pendientes.orEmpty().map { it.subasta.id }.toSet()
        val desaparecidas = antes
            .filter { it.id != 0L && it.id !in siguen && it.id !in yaPendientes }
            .map { Pendiente(it, ahoraMs) }

        // Las que caducaron de verdad o cancelaste nunca veran su venta.
        val pendientes = (estado?.pendientes.orEmpty() + desaparecidas)
            .filter { ahoraMs - it.desde <= ESPERA_MS && it.subasta.id !in canceladas }
            .toMutableList()

        if (estado == null) return Estado(ventas, pendientes, oro) to emptyList()

        val vendidas = mutableListOf<Subasta>()
        for ((clave, cuantas) in ventas) {
            // Si la cuenta baja (Journalator recorta historial) no hay nada nuevo.
            val nuevas = cuantas - (estado.ventas[clave] ?: 0)
            if (nuevas <= 0) continue
            val candidatas = pendientes.filter { clave(it.subasta.reino, it.subasta.nombre) == clave }
            // Sin el oro de antes (un estado de antes de guardarlo) todo el oro
            // pareceria de esta venta.
            val antesOro = estado.oro[clave]
            val ahoraOro = oro[clave]
            val neto = if (antesOro != null && ahoraOro != null) ahoraOro - antesOro else 0L
            val elegidas = elegir(candidatas, minOf(nuevas, candidatas.size), neto)
            for (elegida in elegidas) {
                vendidas.add(elegida.subasta)
                pendientes.remove(elegida)
            }
        }
        return Estado(ventas, pendientes, oro) to vendidas
    }

    /**
     * Las `cuantas` candidatas que se dan por vendidas: las que mas se acercan a
     * `neto`, o las mas baratas si no hay oro con que comparar o son demasiadas
     * para probar todas las combinaciones.
     */
    private fun elegir(candidatas: List<Pendiente>, cuantas: Int, neto: Long): List<Pendiente> {
        val baratas = candidatas.sortedBy { it.subasta.buyout }.take(cuantas)
        if (neto <= 0 || cuantas == 0) return baratas
        if (cuantas > 1 && candidatas.size > MAX_COMBINADAS) return baratas

        var mejor = baratas
        var error = Double.MAX_VALUE
        fun probar(desde: Int, elegidas: List<Pendiente>) {
            if (elegidas.size == cuantas) {
                val diferencia = Math.abs(elegidas.sumOf { it.subasta.buyout } * NETO - neto)
                if (diferencia < error) {
                    error = diferencia
                    mejor = elegidas
                }
                return
            }
            for (i in desde until candidatas.size) probar(i + 1, elegidas + candidatas[i])
        }
        probar(0, emptyList())
        return mejor
    }

    /**
     * Lo vendido que va al carrito: solo lo que vigilas, de los personajes de tu
     * lista, y solo si a ese personaje ya no le queda otro igual puesto. Si le
     * queda, no le falta nada, y la limpieza del carrito lo quitaria enseguida.
     */
    fun encargos(
        vendidas: List<Subasta>,
        catalogo: Catalogo,
        cobertura: List<Cobertura>,
    ): List<Encargo> = vendidas.mapNotNull { venta ->
        val objeto = catalogo.objetos.firstOrNull { it.id == venta.itemId } ?: return@mapNotNull null
        if (venta.personaje !in catalogo.orden) return@mapNotNull null
        Encargo(venta.itemId, if (objeto.escala) venta.ilvl else null, venta.personaje, porVenta = true)
    }.distinct().let { Compra.yaPuestos(it, cobertura).let { puestos -> it - puestos.toSet() } }

    /** Ventas por reino y objeto, sumando los ficheros de cada maquina. */
    fun leer(ficheros: List<String>): Map<String, Int> =
        sumar(ficheros) { it.optInt("ventas", 0).toLong() }.mapValues { it.value.toInt() }

    /** El oro en cobre que te han dejado esas ventas, ya sin la parte de la casa. */
    fun oro(ficheros: List<String>): Map<String, Long> = sumar(ficheros) { it.optLong("oro", 0L) }

    private fun sumar(ficheros: List<String>, campo: (JSONObject) -> Long): Map<String, Long> {
        val total = HashMap<String, Long>()
        for (texto in ficheros) {
            val reinos = runCatching { JSONObject(texto).optJSONObject("reinos") }.getOrNull()
                ?: continue
            for (reino in reinos.keys()) {
                val objetos = reinos.getJSONObject(reino)
                for (nombre in objetos.keys()) {
                    total.merge(clave(reino, nombre), campo(objetos.getJSONObject(nombre)), Long::plus)
                }
            }
        }
        return total
    }

    fun estado(context: Context): Estado? {
        val fichero = File(context.filesDir, FICHERO)
        if (!fichero.isFile) return null
        return runCatching {
            val raiz = JSONObject(fichero.readText())
            val ventas = HashMap<String, Int>()
            val v = raiz.getJSONObject("ventas")
            for (k in v.keys()) ventas[k] = v.getInt(k)
            // Los estados de antes de casar por oro no lo traen.
            val oro = HashMap<String, Long>()
            raiz.optJSONObject("oro")?.let { o -> for (k in o.keys()) oro[k] = o.getLong(k) }
            val p = raiz.getJSONArray("pendientes")
            val pendientes = (0 until p.length()).map { i ->
                val o = p.getJSONObject(i)
                Pendiente(
                    Subasta(
                        itemId = o.getInt("itemId"),
                        ilvl = o.getInt("ilvl"),
                        personaje = o.getString("personaje"),
                        buyout = o.getLong("buyout"),
                        id = o.getLong("id"),
                        reino = o.getString("reino"),
                        nombre = o.getString("nombre"),
                    ),
                    o.getLong("desde"),
                )
            }
            Estado(ventas, pendientes, oro)
        }.getOrNull()
    }

    fun guardar(context: Context, estado: Estado) {
        val pendientes = JSONArray()
        for (p in estado.pendientes) {
            val s = p.subasta
            pendientes.put(
                JSONObject()
                    .put("itemId", s.itemId).put("ilvl", s.ilvl).put("personaje", s.personaje)
                    .put("buyout", s.buyout).put("id", s.id).put("reino", s.reino)
                    .put("nombre", s.nombre).put("desde", p.desde)
            )
        }
        val raiz = JSONObject()
            .put("ventas", JSONObject(estado.ventas as Map<*, *>))
            .put("oro", JSONObject(estado.oro as Map<*, *>))
            .put("pendientes", pendientes)
        File(context.filesDir, FICHERO).writeText(raiz.toString())
    }
}
