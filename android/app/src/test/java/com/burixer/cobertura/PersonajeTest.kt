package com.burixer.cobertura

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PersonajeTest {

    private val grebas = Objeto(
        id = 1, es = "Grebas", en = "Greaves", icono = null, escala = true,
        escalones = listOf(Escalon(305, 40_000), Escalon(308, 60_000)), tope = null,
    )
    private val patron = Objeto(
        id = 2, es = "Patrón", en = "Pattern", icono = null, escala = false,
        escalones = emptyList(), tope = 5_000,
    )
    private val catalogo = Catalogo(listOf("Ana", "Bea"), listOf(grebas, patron))

    private fun datos(vararg subastas: Subasta) = Datos(0L, subastas.toList(), emptyMap())

    @Test
    fun `puesto a un ilvl cuenta como puesto y dice cuales`() {
        val cobertura = Calculo.cobertura(
            catalogo,
            datos(
                Subasta(1, 305, "Ana", 500_000_000),
                Subasta(1, 305, "Ana", 400_000_000),
            ),
        )

        val deAna = Calculo.delPersonaje(cobertura, "Ana").associateBy { it.objeto.id }

        assertTrue(deAna.getValue(1).puesto)
        assertEquals(setOf(305), deAna.getValue(1).puestas.keys)
        assertEquals(2, deAna.getValue(1).puestas.getValue(305).cuantas)
        assertEquals(40_000L, deAna.getValue(1).puestas.getValue(305).minOro)
        assertFalse(deAna.getValue(2).puesto)
    }

    @Test
    fun `con un ilvl elegido solo cuenta lo puesto a ese ilvl`() {
        val cobertura = Calculo.cobertura(
            catalogo,
            datos(Subasta(1, 305, "Ana", 500_000_000), Subasta(2, 0, "Ana", 10_000)),
        )

        val a308 = Calculo.delPersonaje(cobertura, "Ana", ilvl = 308).associateBy { it.objeto.id }
        val a305 = Calculo.delPersonaje(cobertura, "Ana", ilvl = 305).associateBy { it.objeto.id }

        assertFalse(a308.getValue(1).puesto)
        assertTrue(a305.getValue(1).puesto)
        // Lo que no escala no tiene ilvl: el filtro no le afecta.
        assertTrue(a308.getValue(2).puesto)
    }

    @Test
    fun `lo de otro personaje no cuenta`() {
        val cobertura = Calculo.cobertura(catalogo, datos(Subasta(2, 0, "Bea", 10_000)))

        val deAna = Calculo.delPersonaje(cobertura, "Ana")

        assertEquals(2, deAna.size)
        assertTrue(deAna.none { it.puesto })
    }

    @Test
    fun `lo que no escala se guarda sin ilvl`() {
        val cobertura = Calculo.cobertura(catalogo, datos(Subasta(2, 0, "Bea", 10_000)))

        val patronDeBea = Calculo.delPersonaje(cobertura, "Bea").first { it.objeto.id == 2 }

        assertEquals(setOf<Int?>(null), patronDeBea.puestas.keys)
    }
}
