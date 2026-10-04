package com.burixer.cobertura

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PisaTest {

    private fun oro(valor: Long) = valor * 10_000

    private fun precios(vararg porIlvl: Pair<Int, Long>) = Precios(
        generado = 0L,
        reinos = mapOf(
            "darksorrow" to ReinoPrecios(
                visto = 0L,
                porObjeto = mapOf(1 to porIlvl.associate { (ilvl, o) -> "$ilvl" to Precio(oro(o), 1) }),
            )
        ),
    )

    @Test
    fun `pisa si el mejor es mas barato`() {
        val pisa = precios(295 to 40_000, 298 to 39_999).pisa("Darksorrow", 1, 295)
        assertEquals(298, pisa?.first)
    }

    @Test
    fun `pisa si el mejor cuesta menos de 10k mas`() {
        val pisa = precios(295 to 40_000, 298 to 49_999).pisa("Darksorrow", 1, 295)
        assertEquals(298, pisa?.first)
    }

    @Test
    fun `justo 10k mas tambien pisa`() {
        val pisa = precios(295 to 40_000, 298 to 50_000).pisa("Darksorrow", 1, 295)
        assertEquals(298, pisa?.first)
    }

    @Test
    fun `no pisa si el mejor cuesta mas de 10k mas`() {
        assertNull(precios(295 to 40_000, 298 to 50_001).pisa("Darksorrow", 1, 295))
    }
}
