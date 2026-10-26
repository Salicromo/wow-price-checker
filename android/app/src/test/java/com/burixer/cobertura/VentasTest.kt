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
    fun `lo que cancelo el addon no se da por vendido`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList())

        // El 305 es mas barato, pero lo cancelo el reposteo: el vendido es el 308.
        val (estado, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(grebas305, grebas308), ahora = emptyList(),
            ventas = mapOf(clave to 8), ahoraMs = 0L, canceladas = setOf(grebas305.id),
        )

        assertEquals(listOf(grebas308), vendidas)
        assertTrue(estado.pendientes.isEmpty())
    }

    @Test
    fun `con el oro de Journalator se casa la que cuadra por precio, no la mas barata`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList(), oro = mapOf(clave to 1_000L))

        // Llegan 900.000.000 menos el 5 % de la casa: es el 308.
        val (estado, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(grebas305, grebas308), ahora = emptyList(),
            ventas = mapOf(clave to 8), ahoraMs = 0L,
            oro = mapOf(clave to 1_000L + 855_000_000L),
        )

        assertEquals(listOf(grebas308), vendidas)
        assertEquals(listOf(grebas305), estado.pendientes.map { it.subasta })
        assertEquals(1_000L + 855_000_000L, estado.oro[clave])
    }

    @Test
    fun `varias ventas a la vez, la combinacion que suma el oro que ha entrado`() {
        val barata = subasta(30, 305, 100_000_000)
        val media = subasta(31, 308, 200_000_000)
        val cara = subasta(32, 311, 300_000_000)
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList(), oro = mapOf(clave to 0L))

        val (estado, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(barata, media, cara), ahora = emptyList(),
            ventas = mapOf(clave to 9), ahoraMs = 0L,
            oro = mapOf(clave to 380_000_000L), // (100 + 300) millones menos el 5 %
        )

        assertEquals(setOf(barata, cara), vendidas.toSet())
        assertEquals(listOf(media), estado.pendientes.map { it.subasta })
    }

    @Test
    fun `sin el oro de antes (estado viejo) se dan por vendidas las mas baratas`() {
        val inicio = Ventas.Estado(mapOf(clave to 7), emptyList())

        // Sin saber cuanto habia, todo el oro pareceria de esta venta.
        val (estado, vendidas) = Ventas.avanzar(
            inicio, antes = listOf(grebas305, grebas308), ahora = emptyList(),
            ventas = mapOf(clave to 8), ahoraMs = 0L,
            oro = mapOf(clave to 855_000_000L),
        )

        assertEquals(listOf(grebas305), vendidas)
        assertEquals(855_000_000L, estado.oro[clave])
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
    fun `el oro se lee sumando el de cada maquina`() {
        val pc = """{"reinos":{"Darksorrow":{"Grebas":{"ventas":5,"oro":700}}}}"""
        val deck = """{"reinos":{"Darksorrow":{"Grebas":{"ventas":2,"oro":300}}}}"""

        assertEquals(1_000L, Ventas.oro(listOf(pc, deck))[clave])
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
