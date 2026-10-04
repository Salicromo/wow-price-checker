"""El panel de estado que se reescribe cada hora."""

from datetime import datetime, timezone

from wowalerts.misubastas import MyAuction
from wowalerts.panel import COLOR_HAY_TRABAJO, COLOR_TODO_BIEN, build_panel
from wowalerts.undercut import Undercut


def mia(auction_id=1, personaje="Pepe", cuenta=2, objeto="Grebas", oro=9000):
    return MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name=objeto,
        ilvl=311,
        buyout_copper=oro * 10_000,
        quantity=1,
        character=personaje,
        realm="Sanguino",
        realm_slug="sanguino",
        account=cuenta,
    )


def adelantada(subasta, oro_rival=8000):
    return Undercut(
        mine=subasta,
        rival_auction_id=99,
        rival_price_copper=oro_rival * 10_000,
        rivals_ahead=1,
        realm_id=1379,
    )


def texto(panel) -> str:
    return panel["embeds"][0]["description"]


def test_sin_subastas_lo_dice_y_explica_que_hacer():
    panel = build_panel([], [])
    assert "reload" in texto(panel)


def test_cuando_todo_va_bien_el_panel_esta_verde():
    panel = build_panel([mia()], [])
    assert panel["embeds"][0]["color"] == COLOR_TODO_BIEN
    assert "todas primeras" in texto(panel)


def test_cuando_hay_trabajo_el_panel_esta_rojo():
    subasta = mia()
    panel = build_panel([subasta], [adelantada(subasta)])
    assert panel["embeds"][0]["color"] == COLOR_HAY_TRABAJO


def test_cada_personaje_lleva_su_cuenta():
    panel = build_panel([mia(personaje="Pepe", cuenta=2)], [])
    assert "Pepe · WoW 2" in texto(panel)


def test_solo_se_detallan_las_adelantadas():
    """Listar las 300 que van bien seria ilegible: lo que importa es lo que hay
    que atender."""
    subastas = [mia(i, objeto=f"Objeto {i}") for i in range(1, 6)]
    panel = build_panel(subastas, [adelantada(subastas[0])])

    assert "Objeto 1" in texto(panel)
    assert "Objeto 4" not in texto(panel)
    assert "5 vigiladas, 1 adelantada" in texto(panel)


def test_los_personajes_con_trabajo_salen_primero():
    tranquilo = mia(1, personaje="Tranquilo")
    ocupado = mia(2, personaje="Ocupado")
    panel = build_panel([tranquilo, ocupado], [adelantada(ocupado)])

    cuerpo = texto(panel)
    assert cuerpo.index("Ocupado") < cuerpo.index("Tranquilo")


def test_el_resumen_cuenta_lo_que_hay_que_atender():
    subastas = [mia(1), mia(2), mia(3)]
    panel = build_panel(subastas, [adelantada(subastas[0])])
    assert "1 de tus 3 subastas" in texto(panel)


def test_un_empate_se_dice_como_empate():
    subasta = mia(oro=9000)
    panel = build_panel([subasta], [adelantada(subasta, oro_rival=9000)])
    assert "te igualan a 9.000 g" in texto(panel)


def test_un_undercut_de_verdad_muestra_los_dos_precios():
    subasta = mia(oro=50000)
    panel = build_panel([subasta], [adelantada(subasta, oro_rival=30000)])

    assert "50.000" in texto(panel)
    assert "30.000" in texto(panel)


def test_la_hora_va_en_el_embed_para_saber_si_esta_fresco():
    cuando = datetime(2026, 8, 31, 9, 31, tzinfo=timezone.utc)
    panel = build_panel([mia()], [], cuando)
    assert panel["embeds"][0]["timestamp"] == cuando.isoformat()


def test_con_muchisimos_personajes_no_se_pasa_del_limite():
    subastas = [mia(i, personaje=f"Personaje{i}" * 4) for i in range(200)]
    panel = build_panel(subastas, [adelantada(subastas[0])])

    assert len(texto(panel)) <= 4096


def test_lo_que_se_recorta_es_siempre_lo_que_no_tiene_trabajo():
    subastas = [mia(i, personaje=f"Personaje{i}" * 4) for i in range(200)]
    panel = build_panel(subastas, [adelantada(subastas[0])])

    cuerpo = texto(panel)
    assert "Personaje0" in cuerpo
    assert "personaje(s) mas sin novedad" in cuerpo


def test_una_sola_subasta_va_en_singular():
    assert "1 vigilada," in texto(build_panel([mia()], []))


# -- Personajes con datos caducados -----------------------------------------


def test_el_panel_avisa_de_los_personajes_con_datos_muertos():
    """Si ninguna subasta suya sigue viva, el addon lleva sin visitarlos."""
    panel = build_panel([mia()], [], caducados=["Dbarfel", "Adanlin"])
    texto = panel["embeds"][0]["description"]
    assert "Dbarfel" in texto
    assert "Adanlin" in texto
    assert "/reload" in texto


def test_sin_caducados_el_panel_no_dice_nada():
    panel = build_panel([mia()], [], caducados=[])
    assert "reload" not in panel["embeds"][0]["description"]


# ---------------------------------------------------------------------------
#  Panel de ventas por reino
# ---------------------------------------------------------------------------
#
#  Un aviso suelto dice que has vendido algo; el panel dice DONDE vendes, que es
#  lo que decide adonde merece la pena volver a llevar genero.

from wowalerts.panel import REINOS_EN_EL_PANEL, build_panel_ventas


def fila(reino, ventas, oro, ultima="2026-09-05", cuentas=()):
    """Una fila del ranking, con el oro en cobre como lo guarda el estado."""
    return (reino, ventas, oro * 10_000, ultima, tuple(cuentas))


def descripcion_ventas(ranking, totales=(0, 0)):
    return build_panel_ventas(ranking, totales)["embeds"][0]["description"]


def test_los_reinos_salen_de_mas_a_menos_ventas():
    texto = descripcion_ventas(
        [fila("Sanguino", 12, 450_000), fila("Dun Modr", 9, 810_000)]
    )

    assert texto.index("Sanguino") < texto.index("Dun Modr")


def test_los_tres_primeros_llevan_medalla():
    texto = descripcion_ventas(
        [fila("A", 9, 1), fila("B", 8, 1), fila("C", 7, 1), fila("D", 6, 1)]
    )

    assert "🥇 **A**" in texto and "🥈 **B**" in texto and "🥉 **C**" in texto
    assert "` 4.` **D**" in texto


def test_el_oro_sale_en_oro_y_no_en_cobre():
    """El estado guarda cobre para no perder decimales al sumar."""
    texto = descripcion_ventas([fila("Sanguino", 1, 142_499)])

    assert "142.499 g" in texto


def test_la_cola_larga_se_resume():
    """Con 152 personajes repartidos la lista entera no dice nada."""
    ranking = [fila(f"Reino {i}", 100 - i, 1) for i in range(REINOS_EN_EL_PANEL + 5)]

    texto = descripcion_ventas(ranking)

    assert "y 5 reino(s) mas" in texto


def test_sin_ventas_lo_dice_en_vez_de_salir_vacio():
    assert "Todavia no te he visto vender nada" in descripcion_ventas([])


def test_cada_reino_dice_con_que_cuenta_vendiste():
    texto = descripcion_ventas([fila("Sanguino", 3, 100, cuentas=[2])])

    assert "**Sanguino** · WoW 2 — 3 ventas" in texto


def test_si_vendieron_dos_cuentas_salen_las_dos():
    texto = descripcion_ventas([fila("Sanguino", 3, 100, cuentas=[2, 3])])

    assert "**Sanguino** · WoW 2 y 3 — " in texto


def test_sin_cuenta_conocida_no_se_pone_nada():
    texto = descripcion_ventas([fila("Sanguino", 3, 100)])

    assert "**Sanguino** — 3 ventas" in texto


def test_el_pie_lleva_los_totales():
    panel = build_panel_ventas([fila("Sanguino", 2, 300)], (2, 300 * 10_000))

    assert "2 venta(s) en total" in panel["embeds"][0]["footer"]["text"]
    assert "300 g netos" in panel["embeds"][0]["footer"]["text"]


def test_el_panel_dice_el_ilvl_de_cada_adelantada():
    """Con el mismo objeto a varios ilvl, el nombre solo no dice cual es."""
    subasta = MyAuction(**{**mia().__dict__, "ilvl": 298})
    panel = build_panel([subasta], [adelantada(subasta)])
    assert "Grebas (298)" in texto(panel)


def test_el_panel_no_pone_ilvl_a_las_recetas():
    subasta = MyAuction(**{**mia(objeto="Patrón: cordón").__dict__, "ilvl": 1})
    panel = build_panel([subasta], [adelantada(subasta)])
    assert "Patrón: cordón —" in texto(panel)
