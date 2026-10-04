package com.burixer.cobertura

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CompraTest {

    private val grebas305Sorrow = Encargo(1, 305, "Sorrow")
    private val grebas305Azure = Encargo(1, 305, "Azure")
    private val patronSorrow = Encargo(2, null, "Sorrow")

    @Test
    fun `alternar apunta y vuelve a quitar`() {
        val con = Compra.alternar(emptyList(), grebas305Sorrow)
        assertEquals(listOf(grebas305Sorrow), con)
        assertTrue(Compra.alternar(con, grebas305Sorrow).isEmpty())
    }

    @Test
    fun `sobrevive a guardarse como texto, tambien sin ilvl`() {
        val lista = listOf(grebas305Sorrow, patronSorrow)
        assertEquals(lista, Compra.deTexto(Compra.aTexto(lista)))
    }

    @Test
    fun `lo vendido se guarda como vendido, y lo de antes sigue leyendose`() {
        val vendido = grebas305Sorrow.copy(porVenta = true)
        assertEquals(listOf(vendido), Compra.deTexto(Compra.aTexto(listOf(vendido))))
        // El formato de antes, sin la marca: apuntado a mano.
        assertEquals(listOf(grebas305Sorrow), Compra.deTexto("1|305|Sorrow"))
    }

    @Test
    fun `lo vendido cuenta como apuntado, el carrito lo quita y no lo repite`() {
        val vendido = grebas305Sorrow.copy(porVenta = true)
        assertTrue(Compra.contiene(listOf(vendido), grebas305Sorrow))
        assertTrue(Compra.alternar(listOf(vendido), grebas305Sorrow).isEmpty())
    }

    @Test
    fun `quitar un personaje deja el resto del pedido`() {
        val lista = listOf(grebas305Sorrow, patronSorrow, grebas305Azure)
        assertEquals(
            listOf(grebas305Sorrow),
            Compra.delPersonaje(lista, Compra.agrupar(lista).first(), "Sorrow"),
        )
    }

    @Test
    fun `el pedido sabe que personajes entraron por una venta`() {
        val pedido = Compra.agrupar(
            listOf(grebas305Sorrow.copy(porVenta = true), grebas305Azure)
        ).single()
        assertEquals(setOf("Sorrow"), pedido.vendidos)
    }

    @Test
    fun `texto vacio o roto no da nada`() {
        assertTrue(Compra.deTexto("").isEmpty())
        assertTrue(Compra.deTexto("basura").isEmpty())
    }

    @Test
    fun `comprado quita el pedido entero y deshacer lo devuelve sin duplicar`() {
        val lista = listOf(grebas305Sorrow, patronSorrow, grebas305Azure)
        val pedido = Compra.agrupar(lista).first()

        val quitados = Compra.delPedido(lista, pedido)
        val sin = lista - quitados.toSet()
        assertEquals(listOf(patronSorrow), sin)

        // Vuelve a su sitio, no al final.
        assertEquals(lista, Compra.devolver(sin, quitados, antes = lista))

        // Si entre medias lo has vuelto a apuntar a mano, no sale dos veces; y
        // lo apuntado entre medias se queda.
        val nuevo = Encargo(3, 298, "Bea")
        val vuelto = Compra.devolver(sin + grebas305Sorrow + nuevo, quitados, antes = lista)
        assertEquals(lista + nuevo, vuelto)
    }

    @Test
    fun `ya puestos son los que el personaje tiene a ese ilvl`() {
        val grebas = Objeto(
            id = 1, es = "Grebas", en = "Greaves", icono = null, escala = true,
            escalones = listOf(Escalon(305, 40_000)), tope = null,
        )
        val patron = Objeto(
            id = 2, es = "Patrón", en = "Pattern", icono = null, escala = false,
            escalones = emptyList(), tope = 5_000,
        )
        val catalogo = Catalogo(listOf("Sorrow", "Azure"), listOf(grebas, patron))
        val datos = Datos(
            0L,
            listOf(
                // Sorrow ya puso las Grebas 305 y el patron; Azure las tiene a 308.
                Subasta(1, 305, "Sorrow", 1),
                Subasta(2, 0, "Sorrow", 1),
                Subasta(1, 308, "Azure", 1),
            ),
            emptyMap(),
        )
        val cobertura = Calculo.cobertura(catalogo, datos)

        val puestos = Compra.yaPuestos(
            listOf(grebas305Sorrow, grebas305Azure, patronSorrow),
            cobertura,
        )

        assertEquals(listOf(grebas305Sorrow, patronSorrow), puestos)
    }

    @Test
    fun `filtrar por ilvl deja solo esos, y sin filtro todo`() {
        val pedidos = Compra.agrupar(
            listOf(grebas305Sorrow, patronSorrow, Encargo(1, 308, "Azure"))
        )

        assertEquals(pedidos, Compra.filtrar(pedidos, emptySet()))
        assertEquals(listOf(305), Compra.filtrar(pedidos, setOf(305)).map { it.ilvl })
        assertEquals(
            listOf(305, 308),
            Compra.filtrar(pedidos, setOf(305, 308)).map { it.ilvl },
        )
    }

    @Test
    fun `se agrupa por objeto e ilvl, con sus personajes en orden`() {
        val grupos = Compra.agrupar(listOf(grebas305Sorrow, patronSorrow, grebas305Azure))

        assertEquals(listOf(1 to 305, 2 to null), grupos.map { it.itemId to it.ilvl })
        assertEquals(listOf("Sorrow", "Azure"), grupos[0].personajes)
    }
}
