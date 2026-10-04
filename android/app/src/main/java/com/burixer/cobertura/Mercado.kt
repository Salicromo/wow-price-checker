package com.burixer.cobertura

import org.json.JSONObject
import java.io.File
import java.util.zip.GZIPInputStream

/** Un connected realm: todos sus reinos comparten casa de subastas. */
data class Grupo(val nombre: String, val slugs: List<String>, val visto: Long)

/** Un reino donde se vende, con el mas barato en oro y cuantos hay. */
data class Oferta(val grupo: Grupo, val oro: Long, val cuantas: Int)

/**
 * Una variante de un producto: el ilvl del equipo, la calidad de una mascota
 * o nada en lo que no escala. Las ofertas vienen ya de la mas barata a la mas
 * cara.
 */
data class VarianteMercado(val valor: Int?, val ofertas: List<Oferta>)

data class Producto(
    val mascota: Boolean,
    val id: Int,
    val es: String,
    val en: String,
    val icono: String?,
    val variantes: List<VarianteMercado>,
) {
    internal val buscable = normal(es) + "\n" + normal(en)
}

/**
 * El buscador de la app: los reinos mas baratos de cualquier cosa de la region.
 *
 * Lo genera datos_app.py en cada pasada. Solo trae los reinos mas baratos de
 * cada producto, que es lo que responde "donde lo compro".
 */
data class Mercado(val generado: Long, val grupos: List<Grupo>, val productos: List<Producto>) {

    /** Como la caja de la casa de subastas: por trozo de nombre, en es o en. */
    fun buscar(texto: String, limite: Int = 60): List<Producto> {
        val filtro = normal(texto.trim())
        if (filtro.length < 2) return emptyList()
        return productos.asSequence()
            .filter { filtro in it.buscable }
            // Primero lo que empieza por lo escrito, y lo corto antes que lo
            // largo: 'grebas' tiene que dar las Grebas antes que 'Grebas de...'.
            .sortedWith(
                compareByDescending<Producto> {
                    normal(it.es).startsWith(filtro) || normal(it.en).startsWith(filtro)
                }.thenBy { it.es.length }
            )
            .take(limite)
            .toList()
    }

    companion object {
        val VACIO = Mercado(0L, emptyList(), emptyList())

        /** Calidades de mascota, tal y como las numera Blizzard. */
        val CALIDADES = listOf("Pobre", "Común", "Poco común", "Rara")

        fun leer(fichero: File): Mercado? {
            if (!fichero.isFile) return null
            return runCatching {
                val texto = GZIPInputStream(fichero.inputStream()).bufferedReader().use { it.readText() }
                parsear(texto)
            }.getOrNull()
        }

        fun parsear(texto: String): Mercado {
            val raiz = JSONObject(texto)
            val grupos = raiz.getJSONArray("grupos").let { array ->
                (0 until array.length()).map { i ->
                    val g = array.getJSONObject(i)
                    Grupo(
                        nombre = g.optString("nombre"),
                        slugs = g.optJSONArray("slugs")?.let { s ->
                            (0 until s.length()).map { s.getString(it) }
                        } ?: emptyList(),
                        visto = g.optLong("visto", 0L),
                    )
                }
            }
            val productos = raiz.getJSONArray("productos").let { array ->
                (0 until array.length()).map { i ->
                    val p = array.getJSONObject(i)
                    val variantes = p.getJSONArray("v").let { vs ->
                        (0 until vs.length()).map { j ->
                            val v = vs.getJSONArray(j)
                            val ofertas = v.getJSONArray(1).let { os ->
                                (0 until os.length()).mapNotNull { k ->
                                    val o = os.getJSONArray(k)
                                    grupos.getOrNull(o.getInt(0))?.let { g ->
                                        Oferta(g, o.getLong(1), o.getInt(2))
                                    }
                                }
                            }
                            VarianteMercado(if (v.isNull(0)) null else v.getInt(0), ofertas)
                        }
                    }
                    Producto(
                        mascota = p.optString("t") == "m",
                        id = p.getInt("id"),
                        es = p.optString("es"),
                        en = p.optString("en"),
                        icono = if (p.isNull("i")) null else p.optString("i").ifBlank { null },
                        variantes = variantes,
                    )
                }
            }
            return Mercado(raiz.optLong("generado", 0L), grupos, productos)
        }
    }
}

private val TILDES = Regex("""\p{Mn}+""")

/** Para buscar sin que importen mayusculas ni tildes: 'almofar' encuentra 'Almófar'. */
internal fun normal(texto: String): String = TILDES.replace(
    java.text.Normalizer.normalize(texto, java.text.Normalizer.Form.NFD), ""
).lowercase()
