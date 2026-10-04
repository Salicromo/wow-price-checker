package com.burixer.cobertura

import org.json.JSONObject

/** Un ilvl que vigilas, con el precio maximo que le has puesto en config.yaml. */
data class Escalon(val ilvl: Int, val tope: Long)

/**
 * Un objeto vigilado, tal y como viene del catalogo.
 *
 * El catalogo lo genera el proyecto de Python porque el nombre en espanol y el
 * icono salen de la API de Blizzard, que necesita credenciales: pedirlos desde
 * el movil obligaria a llevar esas credenciales dentro de la app.
 */
data class Objeto(
    val id: Int,
    val es: String,
    val en: String,
    val icono: String?,
    val escala: Boolean,
    val escalones: List<Escalon>,
    val tope: Long?,
)

data class Catalogo(val orden: List<String>, val objetos: List<Objeto>)

/**
 * Una subasta tuya. `id`, `reino` y `nombre` solo hacen falta para saber si se
 * ha vendido: el id la sigue de una descarga a otra, y reino y nombre son como
 * Journalator apunta las ventas.
 */
data class Subasta(
    val itemId: Int,
    val ilvl: Int,
    val personaje: String,
    val buyout: Long,
    val id: Long = 0L,
    val reino: String = "",
    val nombre: String = "",
)

data class Personaje(val nombre: String, val reino: String, val cuenta: Int?)

data class Datos(
    val exportado: Long,
    val subastas: List<Subasta>,
    val personajes: Map<String, Personaje>,
)

/** Lo que tiene puesto un personaje de una variante concreta. */
data class Puesta(val personaje: String, val cuantas: Int, val minOro: Long)

/**
 * Un producto concreto: el objeto a un ilvl determinado.
 *
 * Para el equipo, dos ilvl distintos no son el mismo producto ni compiten entre
 * si, asi que la cobertura se cuenta por variante y no por objeto. Lo que no
 * escala (patrones) tiene una sola variante con `ilvl` a null.
 */
data class Variante(
    val ilvl: Int?,
    val tope: Long?,
    val vigilado: Boolean,
    val tienen: List<Puesta>,
    val faltan: List<String>,
)

data class Cobertura(
    val objeto: Objeto,
    val puestas: Int,
    val conAlgo: Set<String>,
    val variantes: List<Variante>,
) {
    /** La variante por la que conviene abrir: la que mas tienes puesta. */
    val porDefecto: Variante
        get() = variantes.maxByOrNull { it.tienen.size } ?: variantes.first()
}

/**
 * Un objeto visto desde un personaje: lo que tiene puesto de cada ilvl.
 *
 * Tenerlo a un ilvl ya cuenta como puesto. Contar como hueco cada ilvl que le
 * falta llenaria la lista de huecos que no piensas cubrir; los ilvl estan
 * dentro, al desplegar.
 */
data class ObjetoDelPersonaje(val cobertura: Cobertura, val puestas: Map<Int?, Puesta>) {
    val objeto: Objeto get() = cobertura.objeto
    val puesto: Boolean get() = puestas.isNotEmpty()
}

object Parser {

    fun catalogo(texto: String): Catalogo {
        val raiz = JSONObject(texto)
        val orden = raiz.getJSONArray("orden").let { array ->
            (0 until array.length()).map { array.getString(it) }
        }
        val objetos = raiz.getJSONArray("objetos").let { array ->
            (0 until array.length()).map { i ->
                val o = array.getJSONObject(i)
                val escalones = o.optJSONArray("ilvls")?.let { lista ->
                    (0 until lista.length()).map { j ->
                        val e = lista.getJSONObject(j)
                        Escalon(e.getInt("ilvl"), e.getLong("tope"))
                    }
                } ?: emptyList()
                Objeto(
                    id = o.getInt("id"),
                    es = o.getString("es"),
                    en = o.getString("en"),
                    icono = o.optString("icono").ifBlank { null },
                    escala = o.optBoolean("escala"),
                    escalones = escalones,
                    tope = if (o.isNull("tope")) null else o.getLong("tope"),
                )
            }
        }
        return Catalogo(orden, objetos)
    }

    fun datos(texto: String): Datos {
        val raiz = JSONObject(texto)

        val subastas = raiz.optJSONArray("auctions")?.let { array ->
            (0 until array.length()).mapNotNull { i ->
                val a = array.getJSONObject(i)
                val personaje = a.optString("character")
                if (personaje.isBlank()) return@mapNotNull null
                Subasta(
                    itemId = a.getInt("itemID"),
                    ilvl = a.optInt("ilvl", 0),
                    personaje = personaje,
                    buyout = a.optLong("buyout", 0L),
                    id = a.optLong("auctionID", 0L),
                    reino = a.optString("realm"),
                    nombre = a.optString("itemName"),
                )
            }
        } ?: emptyList()

        val personajes = raiz.optJSONArray("characters")?.let { array ->
            (0 until array.length()).associate { i ->
                val p = array.getJSONObject(i)
                val nombre = p.getString("name")
                nombre to Personaje(
                    nombre = nombre,
                    reino = p.optString("realm"),
                    cuenta = if (p.isNull("account")) null else p.optInt("account"),
                )
            }
        } ?: emptyMap()

        return Datos(raiz.optLong("exportado", 0L), subastas, personajes)
    }
}

object Calculo {

    /**
     * La cobertura de cada objeto, de lo que mas tienes puesto a lo que menos.
     *
     * Solo cuentan los personajes de `orden`, que son los que de verdad
     * trabajas: el resto de tus personajes tiene subastas sueltas que no dicen
     * nada sobre si te falta cubrir un hueco.
     */
    fun cobertura(catalogo: Catalogo, datos: Datos): List<Cobertura> {
        val orden = catalogo.orden
        val delOrden = orden.toSet()

        // (objeto, ilvl) -> personaje -> subastas suyas
        val porVariante = HashMap<Pair<Int, Int>, HashMap<String, MutableList<Subasta>>>()
        for (subasta in datos.subastas) {
            if (subasta.personaje !in delOrden) continue
            porVariante
                .getOrPut(subasta.itemId to subasta.ilvl) { HashMap() }
                .getOrPut(subasta.personaje) { mutableListOf() }
                .add(subasta)
        }

        return catalogo.objetos.map { objeto ->
            val variantes = if (objeto.escala) {
                // Los ilvl que vigilas, mas los que tengas puestos aunque no
                // esten en tu tabla: esconder un 292 que si tienes puesto seria
                // mentir por omision.
                val delConfig = objeto.escalones.associate { it.ilvl to it.tope }
                val puestos = porVariante.keys.filter { it.first == objeto.id }.map { it.second }
                (delConfig.keys + puestos).distinct().sorted().map { ilvl ->
                    variante(
                        ilvl = ilvl,
                        tope = delConfig[ilvl],
                        vigilado = ilvl in delConfig,
                        duenos = porVariante[objeto.id to ilvl].orEmpty(),
                        orden = orden,
                    )
                }
            } else {
                val duenos = HashMap<String, MutableList<Subasta>>()
                porVariante.forEach { (clave, mapa) ->
                    if (clave.first == objeto.id) {
                        mapa.forEach { (pj, lista) ->
                            duenos.getOrPut(pj) { mutableListOf() }.addAll(lista)
                        }
                    }
                }
                listOf(variante(null, objeto.tope, true, duenos, orden))
            }

            // Cada subasta cae en una sola variante, asi que sumarlas no cuenta
            // nada dos veces.
            val puestas = variantes.sumOf { v -> v.tienen.sumOf { it.cuantas } }
            val conAlgo = variantes.flatMap { v -> v.tienen.map { it.personaje } }.toSet()

            Cobertura(objeto, puestas, conAlgo, variantes)
        }.sortedWith(compareByDescending<Cobertura> { it.puestas }.thenBy { it.objeto.es })
    }

    /**
     * Todos los objetos que vigilas, con lo que tiene puesto de cada uno `nombre`.
     *
     * Con `ilvl`, de lo que escala solo cuenta lo puesto a ese ilvl: es el que
     * llevas encima y el que quieres saber donde meter. Lo que no escala no
     * tiene ilvl y sale igual.
     */
    fun delPersonaje(
        cobertura: List<Cobertura>,
        nombre: String,
        ilvl: Int? = null,
    ): List<ObjetoDelPersonaje> =
        cobertura.map { c ->
            val puestas = c.variantes
                .filter { ilvl == null || !c.objeto.escala || it.ilvl == ilvl }
                .mapNotNull { v ->
                    v.tienen.firstOrNull { it.personaje == nombre }?.let { v.ilvl to it }
                }.toMap()
            ObjetoDelPersonaje(c, puestas)
        }

    private fun variante(
        ilvl: Int?,
        tope: Long?,
        vigilado: Boolean,
        duenos: Map<String, List<Subasta>>,
        orden: List<String>,
    ): Variante {
        val tienen = mutableListOf<Puesta>()
        val faltan = mutableListOf<String>()
        for (personaje in orden) {
            val suyas = duenos[personaje]
            if (suyas.isNullOrEmpty()) {
                faltan.add(personaje)
            } else {
                tienen.add(
                    Puesta(
                        personaje = personaje,
                        cuantas = suyas.size,
                        // El buyout viene en cobre; en la app siempre se habla
                        // de oro, como en el juego.
                        minOro = suyas.minOf { it.buyout } / 10_000,
                    )
                )
            }
        }
        return Variante(ilvl, tope, vigilado, tienen, faltan)
    }
}

/** El mas barato de un producto en un reino, y cuantos hay a la venta. */
data class Precio(val minCobre: Long, val cuantas: Int) {
    val oro: Long get() = minCobre / 10_000
}

/**
 * Lo que vale entrar en cada reino.
 *
 * `visto` es lo que separa "ahi no lo vende nadie" --que es justo donde quieres
 * entrar-- de "ese reino no se pudo mirar". Sin esa marca las dos cosas se
 * verian igual: sin precio.
 */
data class ReinoPrecios(val visto: Long, val porObjeto: Map<Int, Map<String, Precio>>)

data class Precios(val generado: Long, val reinos: Map<String, ReinoPrecios>) {

    /** Lo que costaria ser el mas barato de ese reino, o null si no se sabe. */
    fun de(reino: String, itemId: Int, ilvl: Int?, escala: Boolean): Consulta {
        val ficha = reinos[slugDeReino(reino)] ?: return Consulta.SinDato
        val delObjeto = ficha.porObjeto[itemId] ?: return Consulta.Vacio(ficha.visto)

        // Lo que no escala se mira entero: el ilvl de un patron no significa
        // nada y segun el volcado puede venir o no venir.
        val precio = if (escala) {
            delObjeto[ilvl?.toString() ?: SIN_ILVL]
        } else {
            delObjeto.values.minByOrNull { it.minCobre }
        }
        return precio?.let { Consulta.Hay(it, ficha.visto) } ?: Consulta.Vacio(ficha.visto)
    }

    /**
     * Todos los ilvl de ese objeto que hay a la venta en ese reino, en orden.
     *
     * Que falte tu ilvl no basta para decidir: si al lado hay uno mejor mas
     * barato, el tuyo no lo compra nadie. La escalera entera es lo que deja ver
     * eso de un vistazo.
     */
    fun escalera(reino: String, itemId: Int): List<Pair<Int, Precio>> {
        val ficha = reinos[slugDeReino(reino)] ?: return emptyList()
        val delObjeto = ficha.porObjeto[itemId] ?: return emptyList()
        return delObjeto
            .mapNotNull { (clave, precio) -> clave.toIntOrNull()?.let { it to precio } }
            .sortedBy { it.first }
    }

    /**
     * El ilvl mejor que el tuyo que te deja sin sitio, si lo hay.
     *
     * Un comprador que ve un 298 mas barato que el 295 que hay puesto se lleva
     * el 298, asi que ese 295 no se vende y meter otro tampoco. Y lo mismo si el
     * 298 cuesta hasta `MARGEN_PISA_ORO` mas: por esa diferencia tambien se
     * lleva el mejor.
     *
     * Solo se avisa cuando de tu ilvl hay algo puesto. Con tu ilvl vacio no hay
     * nada que comparar --el precio lo pones tu-- y el aviso saldria en casi
     * todos los personajes hasta dejar de leerse. Ahi la escalera, que esta a
     * un toque, cuenta el reino entero sin dar nada por hecho.
     */
    fun pisa(reino: String, itemId: Int, ilvl: Int?): Pair<Int, Precio>? {
        if (ilvl == null) return null
        val escalera = escalera(reino, itemId)
        val mio = escalera.firstOrNull { it.first == ilvl }?.second ?: return null
        val mejor = escalera.filter { it.first > ilvl }.minByOrNull { it.second.minCobre }
            ?: return null
        if (mejor.second.minCobre > mio.minCobre + MARGEN_PISA_ORO * 10_000) return null
        return mejor
    }

    sealed interface Consulta {
        /** El reino no se ha podido mirar; no se sabe nada de el. */
        data object SinDato : Consulta

        /** El reino se miro y ahi no lo vende nadie. */
        data class Vacio(val visto: Long) : Consulta

        data class Hay(val precio: Precio, val visto: Long) : Consulta
    }

    companion object {
        val VACIOS = Precios(0L, emptyMap())
        const val SIN_ILVL = "plano"

        /** Lo que un comprador paga de mas sin pensarlo por el ilvl mejor. */
        const val MARGEN_PISA_ORO = 10_000L
    }
}

private val MARCAS = Regex("""\p{Mn}+""")
private val APOSTROFOS = Regex("['\u2018\u2019]")
private val NO_ALFANUMERICO = Regex("[^a-zA-Z0-9]+")

/**
 * 'Area 52' -> 'area-52', igual que lo nombra Blizzard.
 *
 * Los apostrofos se borran en vez de convertirse en guion, porque asi los trata
 * Blizzard: "Kil'jaeden" es "kiljaeden", no "kil-jaeden". Tiene que dar
 * exactamente lo mismo que slugify_realm() en Python, que es quien genera las
 * claves del fichero de precios.
 */
fun slugDeReino(nombre: String): String {
    val sinTildes = MARCAS.replace(
        java.text.Normalizer.normalize(nombre, java.text.Normalizer.Form.NFKD), ""
    )
    return NO_ALFANUMERICO
        .replace(APOSTROFOS.replace(sinTildes, ""), "-")
        .trim('-')
        .lowercase()
}

fun parsearPrecios(texto: String): Precios {
    val raiz = JSONObject(texto)
    val reinos = raiz.optJSONObject("reinos") ?: return Precios.VACIOS
    val salida = HashMap<String, ReinoPrecios>()

    for (slug in reinos.keys()) {
        val reino = reinos.getJSONObject(slug)
        val porObjeto = HashMap<Int, Map<String, Precio>>()
        val objetos = reino.optJSONObject("precios") ?: JSONObject()
        for (idTexto in objetos.keys()) {
            val itemId = idTexto.toIntOrNull() ?: continue
            val porIlvl = objetos.getJSONObject(idTexto)
            val mapa = HashMap<String, Precio>()
            for (clave in porIlvl.keys()) {
                val dato = porIlvl.getJSONObject(clave)
                mapa[clave] = Precio(dato.optLong("min", 0L), dato.optInt("n", 0))
            }
            porObjeto[itemId] = mapa
        }
        salida[slug] = ReinoPrecios(reino.optLong("visto", 0L), porObjeto)
    }
    return Precios(raiz.optLong("generado", 0L), salida)
}
