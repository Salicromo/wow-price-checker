package com.burixer.cobertura

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class FusionTest {

    private fun subasta(id: Long, personaje: String, exportado: Long) = JSONObject()
        .put("auctionID", id)
        .put("character", personaje)
        .put("realm", "Azuremyst")
        .put("exportedAt", exportado)

    private fun ids(subastas: List<JSONObject>) = subastas.map { it.getLong("auctionID") }.toSet()

    @Test
    fun `de cada personaje vale la foto mas reciente, aunque venga de otra maquina`() {
        // El 2026-10-13 la app dio un yelmo como puesto en Azuregoldu: lo decia
        // el volcado de la Steam Deck del 7 de septiembre, y el del PC de ese
        // mismo dia ya no lo tenia.
        val deck = listOf(subasta(1, "Azuregoldu", 100), subasta(2, "Azuregoldu", 100))
        val pc = listOf(subasta(3, "Azuregoldu", 200))

        assertEquals(setOf(3L), ids(Parser.soloLoUltimo(deck + pc)))
    }

    @Test
    fun `un personaje que solo exporta una maquina se queda como esta`() {
        val deck = listOf(subasta(1, "Deckgoldu", 100))
        val pc = listOf(subasta(2, "Azuregoldu", 200))

        assertEquals(setOf(1L, 2L), ids(Parser.soloLoUltimo(deck + pc)))
    }

    @Test
    fun `sin exportedAt no se descarta nada`() {
        val viejas = listOf(
            JSONObject().put("auctionID", 1).put("character", "A").put("realm", "R"),
            JSONObject().put("auctionID", 2).put("character", "A").put("realm", "R"),
        )

        assertEquals(setOf(1L, 2L), ids(Parser.soloLoUltimo(viejas)))
    }
}
