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
 */
object Ventas {

    /** Lo que espera una desaparecida a que llegue su venta. */
    private const val ESPERA_MS = 72L * 3_600_000L

    private const val FICHERO = "ventas_estado.json"

    data class Pendiente(val subasta: Subasta, val desde: Long)

    /** Por donde iba la cuenta de ventas, y lo desaparecido sin confirmar. */
    data class Estado(val ventas: Map<String, Int>, val pendientes: List<Pendiente>)

    fun clave(reino: String, nombre: String) = "$reino|$nombre"

    /**
     * Un paso: lo que ha desaparecido entre `antes` y `ahora` pasa a pendiente,
     * y por cada venta nueva de un reino y objeto se da por vendida una
     * pendiente de ese reino y objeto, la mas barata primero, que es la que se
     * vende antes.
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
    ): Pair<Estado, List<Subasta>> {
        val siguen = ahora.map { it.id }.toSet()
        val yaPendientes = estado?.pendientes.orEmpty().map { it.subasta.id }.toSet()
        val desaparecidas = antes
            .filter { it.id != 0L && it.id !in siguen && it.id !in yaPendientes }
            .map { Pendiente(it, ahoraMs) }

        // Las que caducaron de verdad o cancelaste nunca veran su venta.
        val pendientes = (estado?.pendientes.orEmpty() + desaparecidas)
            .filter { ahoraMs - it.desde <= ESPERA_MS }
            .toMutableList()

        if (estado == null) return Estado(ventas, pendientes) to emptyList()

        val vendidas = mutableListOf<Subasta>()
        for ((clave, cuantas) in ventas) {
            // Si la cuenta baja (Journalator recorta historial) no hay nada nuevo.
            var nuevas = cuantas - (estado.ventas[clave] ?: 0)
            if (nuevas <= 0) continue
            val candidatas = pendientes
                .filter { clave(it.subasta.reino, it.subasta.nombre) == clave }
                .sortedBy { it.subasta.buyout }
            for (candidata in candidatas) {
                if (nuevas == 0) break
                vendidas.add(candidata.subasta)
                pendientes.remove(candidata)
                nuevas--
            }
        }
        return Estado(ventas, pendientes) to vendidas
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
    fun leer(ficheros: List<String>): Map<String, Int> {
        val total = HashMap<String, Int>()
        for (texto in ficheros) {
            val reinos = runCatching { JSONObject(texto).optJSONObject("reinos") }.getOrNull()
                ?: continue
            for (reino in reinos.keys()) {
                val objetos = reinos.getJSONObject(reino)
                for (nombre in objetos.keys()) {
                    val n = objetos.getJSONObject(nombre).optInt("ventas", 0)
                    total.merge(clave(reino, nombre), n, Int::plus)
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
            Estado(ventas, pendientes)
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
            .put("pendientes", pendientes)
        File(context.filesDir, FICHERO).writeText(raiz.toString())
    }
}
