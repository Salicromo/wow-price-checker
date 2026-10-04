package com.burixer.cobertura

import org.json.JSONObject

/** El mas barato de un dia en toda la region, en oro, y en que reino estaba. */
data class DiaHistorial(val dia: String, val oro: Long, val reino: String)

/**
 * El precio de tus objetos vigilados en los ultimos 30 dias, dia a dia.
 *
 * Lo genera datos_app.py: cada pasada suma su minimo al del dia, asi que un
 * dia es el mas barato que se vio en cualquiera de sus pasadas.
 */
data class Historial(val objetos: Map<Int, Map<String, List<DiaHistorial>>>) {

    /** Del dia mas viejo al de hoy. `variante` es el ilvl, o null si no escala. */
    fun de(id: Int, variante: Int?): List<DiaHistorial> =
        objetos[id]?.get(variante?.toString() ?: SIN_VARIANTE).orEmpty()

    companion object {
        val VACIO = Historial(emptyMap())
        private const val SIN_VARIANTE = "-"

        fun parsear(texto: String): Historial {
            val objetos = JSONObject(texto).getJSONObject("objetos")
            return Historial(objetos.keys().asSequence().associate { id ->
                val variantes = objetos.getJSONObject(id)
                id.toInt() to variantes.keys().asSequence().associateWith { v ->
                    val dias = variantes.getJSONArray(v)
                    (0 until dias.length()).map { i ->
                        val d = dias.getJSONArray(i)
                        DiaHistorial(d.getString(0), d.getLong(1), d.getString(2))
                    }
                }
            })
        }
    }
}
