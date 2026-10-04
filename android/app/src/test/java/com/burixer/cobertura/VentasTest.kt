package com.burixer.cobertura

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VentasTest {

    private val hora = 3_600_000L

    private fun subasta(id: Long, ilvl: Int, buyout: Long, personaje: String = "Sorrow") =
        Subasta(
            itemId = 1, ilvl = ilvl, personaje = personaje, buyout = buyout,
            id = id, reino = "Darksorrow", nombre = "Grebas",
        )

    private val grebas305 = subasta(10, 305, 500_000_000)
    private val grebas308 = subasta(11, 308, 900_000_000)
    private val clave = Ventas.clave("Darksorrow", "Grebas")

    @Test
    fun `la primera vez solo guarda por donde van las ventas`() {
        val (estado, vendidas) = Ventas.avanzar(
            estado = null,
            antes = listOf(grebas305),
            ahora = emptyList(),
            ventas = mapOf(clave to 7),
            ahoraMs = 0L,
        )
        assertTrue(vendidas.isEmpty())
        assertEquals(7, estado.ventas[clave])
    }

    @Test
    fun `desaparece y sube la cuenta de ventas, vendida`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList())

        val (_, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(grebas305, grebas308), ahora = listOf(grebas308),
            ventas = mapOf(clave to 8), ahoraMs = 0L,
        )

        assertEquals(listOf(grebas305), vendidas)
    }

    @Test
    fun `desaparece sin venta, queda pendiente, y la venta que llega luego la confirma`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList())

        val (estado, nada) = Ventas.avanzar(
            inicio, antes = listOf(grebas305), ahora = emptyList(),
            ventas = mapOf(clave to 7), ahoraMs = 0L,
        )
        assertTrue(nada.isEmpty())
        assertEquals(listOf(grebas305), estado.pendientes.map { it.subasta })

        // Recoges el correo mas tarde: la venta llega en otra pasada.
        val (despues, vendidas) = Ventas.avanzar(
            estado, antes = emptyList(), ahora = emptyList(),
            ventas = mapOf(clave to 8), ahoraMs = 2 * hora,
        )
        assertEquals(listOf(grebas305), vendidas)
        assertTrue(despues.pendientes.isEmpty())
    }

    @Test
    fun `mas desaparecidas que ventas, se dan por vendidas las mas baratas`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList())

        val (estado, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(grebas305, grebas308), ahora = emptyList(),
            ventas = mapOf(clave to 8), ahoraMs = 0L,
        )

        assertEquals(listOf(grebas305), vendidas)
        assertEquals(listOf(grebas308), estado.pendientes.map { it.subasta })
    }

    @Test
    fun `lo pendiente caduca a los tres dias, caducada o cancelada`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), listOf(Ventas.Pendiente(grebas305, 0L)))

        val (estado, vendidas) = Ventas.avanzar(
            inicio, antes = emptyList(), ahora = emptyList(),
            ventas = mapOf(clave to 7), ahoraMs = 73 * hora,
        )

        assertTrue(vendidas.isEmpty())
        assertTrue(estado.pendientes.isEmpty())
    }

    @Test
    fun `ventas de otro objeto o reino no confirman nada`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList())

        val (_, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(grebas305), ahora = emptyList(),
            ventas = mapOf(clave to 7, Ventas.clave("Darksorrow", "Yelmo") to 3),
            ahoraMs = 0L,
        )

        assertTrue(vendidas.isEmpty())
    }

    @Test
    fun `ventas se leen sumando las de cada maquina`() {
        val pc = """{"reinos":{"Darksorrow":{"Grebas":{"ventas":5}}}}"""
        val deck = """{"reinos":{"Darksorrow":{"Grebas":{"ventas":2}},"Azuremyst":{"Yelmo":{"ventas":1}}}}"""

        val ventas = Ventas.leer(listOf(pc, deck))

        assertEquals(7, ventas[clave])
        assertEquals(1, ventas[Ventas.clave("Azuremyst", "Yelmo")])
    }

    @Test
    fun `al carrito solo lo vigilado, de tus personajes, y si ya no le queda otro`() {
        val grebas = Objeto(
            id = 1, es = "Grebas", en = "Greaves", icono = null, escala = true,
            escalones = listOf(Escalon(305, 40_000)), tope = null,
        )
        val catalogo = Catalogo(listOf("Sorrow", "Azure"), listOf(grebas))
        val otraDeAzure = subasta(20, 305, 1, personaje = "Azure")
        val cobertura = Calculo.cobertura(
            catalogo,
            Datos(0L, listOf(otraDeAzure), emptyMap()),
        )
        val vendidas = listOf(
            grebas305, // Sorrow ya no tiene Grebas 305: al carrito
            subasta(21, 305, 1, personaje = "Azure"), // Azure aun tiene otra
            subasta(22, 305, 1, personaje = "Fuera"), // no es de tu lista
            grebas305.copy(itemId = 99), // no lo vigilas
        )

        assertEquals(
            listOf(Encargo(1, 305, "Sorrow", porVenta = true)),
            Ventas.encargos(vendidas, catalogo, cobertura),
        )
    }
}
