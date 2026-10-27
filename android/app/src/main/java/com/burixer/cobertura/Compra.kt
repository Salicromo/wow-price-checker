package com.burixer.cobertura

import android.content.Context

/**
 * Algo que tienes que comprar: un objeto a un ilvl, para ponerlo con un personaje.
 *
 * `porVenta` dice si entro solo porque lo vendiste, en vez de apuntarlo tu. No
 * cambia que encargo es: para saber si algo esta apuntado se mira `clave`.
 */
data class Encargo(
    val itemId: Int,
    val ilvl: Int?,
    val personaje: String,
    val porVenta: Boolean = false,
) {
    val clave: Triple<Int, Int?, String> get() = Triple(itemId, ilvl, personaje)
}

/**
 * Lo apuntado de un mismo objeto e ilvl, que se compra junto. `vendidos` son los
 * personajes que entraron por una venta.
 */
data class Pedido(
    val itemId: Int,
    val ilvl: Int?,
    val personajes: List<String>,
    val vendidos: Set<String> = emptySet(),
)

/**
 * La lista de la compra.
 *
 * Vive solo en el movil: es tu lista de trabajo del momento, no configuracion,
 * y asi no depende de GitHub ni de tener conexion.
 */
object Compra {

    private const val PREFS = "compra"
    private const val CLAVE = "encargos"
    private const val CLAVE_DESCARTADOS = "descartados"

    /**
     * Los ilvl de equipo que cada personaje tiene que tener siempre puestos: si
     * le falta uno, al carrito, lo vendiera o lo pasara al banco de hermandad.
     */
    private val ILVLS_FIJOS = setOf(308, 311)

    fun leer(context: Context): List<Encargo> =
        deTexto(prefs(context).getString(CLAVE, "") ?: "")

    fun guardar(context: Context, lista: List<Encargo>) {
        prefs(context).edit().putString(CLAVE, aTexto(lista)).apply()
    }

    /**
     * Lo que quitaste del carrito ("Comprado" o la ✕) y aun no has puesto: no
     * vuelve a entrar por faltar hasta que lo pongas, que ya lo tienes comprado.
     */
    fun leerDescartados(context: Context): List<Encargo> =
        deTexto(prefs(context).getString(CLAVE_DESCARTADOS, "") ?: "")

    fun guardarDescartados(context: Context, lista: List<Encargo>) {
        prefs(context).edit().putString(CLAVE_DESCARTADOS, aTexto(lista)).apply()
    }

    /** Si ese objeto, a ese ilvl y para ese personaje, esta apuntado, venga de donde venga. */
    fun contiene(lista: List<Encargo>, encargo: Encargo): Boolean =
        lista.any { it.clave == encargo.clave }

    fun alternar(lista: List<Encargo>, encargo: Encargo): List<Encargo> =
        if (contiene(lista, encargo)) lista.filterNot { it.clave == encargo.clave }
        else lista + encargo

    /** Los encargos que forman `pedido`, que es lo que quita "Comprado". */
    fun delPedido(lista: List<Encargo>, pedido: Pedido): List<Encargo> =
        lista.filter { it.itemId == pedido.itemId && it.ilvl == pedido.ilvl }

    /** El encargo de un solo personaje del pedido, que es lo que quita la ✕. */
    fun delPersonaje(lista: List<Encargo>, pedido: Pedido, personaje: String): List<Encargo> =
        delPedido(lista, pedido).filter { it.personaje == personaje }

    /**
     * Deshacer: vuelve a poner lo quitado en el sitio que tenia en `antes`, sin
     * repetir nada. Lo apuntado entre medias se queda, al final.
     */
    fun devolver(
        lista: List<Encargo>,
        quitados: List<Encargo>,
        antes: List<Encargo>,
    ): List<Encargo> {
        val vuelven = antes.filter { it in lista || it in quitados }
        return vuelven + lista.filter { it !in vuelven }
    }

    /**
     * Los encargos que ya estan puestos: ese personaje tiene ese objeto a ese
     * ilvl en la casa de subastas. Ya no hay que comprarlos.
     */
    fun yaPuestos(lista: List<Encargo>, cobertura: List<Cobertura>): List<Encargo> =
        lista.filter { encargo ->
            val variante = cobertura.firstOrNull { it.objeto.id == encargo.itemId }
                ?.variantes?.firstOrNull { it.ilvl == encargo.ilvl }
            variante?.tienen?.any { it.personaje == encargo.personaje } == true
        }

    /**
     * Los encargos de personajes que ya no estan en tu lista: no los vas a
     * usar, asi que nunca pondran nada que los saque del carrito. Sin lista
     * (catalogo sin leer) no sale nada, o se vaciaria el carrito entero.
     */
    fun fueraDeLista(lista: List<Encargo>, orden: List<String>): List<Encargo> =
        if (orden.isEmpty()) emptyList() else lista.filter { it.personaje !in orden }

    /** Lo de equipo a los ilvl fijos que algun personaje de tu lista no tiene puesto. */
    fun faltan(cobertura: List<Cobertura>): List<Encargo> =
        cobertura.filter { it.objeto.escala }.flatMap { c ->
            c.variantes
                .filter { it.vigilado && it.ilvl in ILVLS_FIJOS }
                .flatMap { v -> v.faltan.map { Encargo(c.objeto.id, v.ilvl, it) } }
        }

    /** De lo que falta, lo que entra: ni lo ya apuntado ni lo comprado sin poner. */
    fun porReponer(
        lista: List<Encargo>,
        descartados: List<Encargo>,
        faltan: List<Encargo>,
    ): List<Encargo> =
        faltan.filterNot { contiene(lista, it) || contiene(descartados, it) }

    /**
     * Solo los pedidos de esos ilvl; sin ninguno elegido, todos. Lo que no
     * escala no tiene ilvl y solo sale sin filtro.
     */
    fun filtrar(pedidos: List<Pedido>, ilvls: Set<Int>): List<Pedido> =
        if (ilvls.isEmpty()) pedidos else pedidos.filter { it.ilvl in ilvls }

    /** En el orden en que los apuntaste. */
    fun agrupar(lista: List<Encargo>): List<Pedido> =
        lista.groupBy { it.itemId to it.ilvl }
            .map { (clave, encargos) ->
                Pedido(
                    clave.first,
                    clave.second,
                    encargos.map { it.personaje },
                    encargos.filter { it.porVenta }.map { it.personaje }.toSet(),
                )
            }

    // Una linea por encargo, "id|ilvl|personaje", y "|v" al final si entro por
    // una venta. El ilvl va vacio en lo que no escala. Los nombres de personaje
    // no llevan '|' ni saltos de linea.
    fun aTexto(lista: List<Encargo>): String =
        lista.joinToString("\n") {
            "${it.itemId}|${it.ilvl ?: ""}|${it.personaje}" + if (it.porVenta) "|v" else ""
        }

    fun deTexto(texto: String): List<Encargo> =
        texto.lines().mapNotNull { linea ->
            val partes = linea.split("|")
            if (partes.size !in 3..4) return@mapNotNull null
            val id = partes[0].toIntOrNull() ?: return@mapNotNull null
            if (partes[2].isBlank()) return@mapNotNull null
            Encargo(id, partes[1].toIntOrNull(), partes[2], porVenta = partes.getOrNull(3) == "v")
        }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
