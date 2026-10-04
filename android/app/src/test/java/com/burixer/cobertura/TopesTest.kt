package com.burixer.cobertura

import org.junit.Assert.assertEquals
import org.junit.Test

class TopesTest {

    private fun objeto(en: String) = Objeto(
        id = 1, es = en, en = en, icono = null, escala = true, escalones = emptyList(), tope = null,
    )

    /** Es el contrato con aplicar_tope.py: VARIOS en tests/test_aplicar_tope.py. */
    @Test
    fun laCestaSaleComoLaLeeAplicarTope() {
        val cuerpo = Topes.cuerpoVarios(
            listOf(
                Topes.Cambio(objeto("Temple Delver's Mystic Helm"), 295, 4000),
                Topes.Cambio(objeto("Pattern: Arcanoweave Cord"), null, 45000),
            )
        )

        assertEquals(
            "### Cambios\n\n" +
                "Temple Delver's Mystic Helm | 295 | 4000\n" +
                "Pattern: Arcanoweave Cord | sin ilvl (precio unico) | 45000\n",
            cuerpo,
        )
    }
}
