from wowalerts.precios import (
    construir_precios,
    minimos_del_reino,
    reinos_a_vigilar,
)

BONUS_MAP = {12840: 305, 12843: 311}
VIGILADOS = {271440, 258126}


def subasta(item_id, buyout, bonus=None, cantidad=1):
    item = {"id": item_id}
    if bonus:
        item["bonus_lists"] = bonus
    return {"item": item, "buyout": buyout, "quantity": cantidad}


def test_se_queda_con_el_mas_barato_de_cada_objeto_e_ilvl():
    minimos = minimos_del_reino(
        [
            subasta(271440, 500_000, [12840]),
            subasta(271440, 300_000, [12840]),
            subasta(271440, 900_000, [12843]),
        ],
        VIGILADOS,
        BONUS_MAP,
    )
    assert minimos[(271440, 305)] == (300_000, 2)
    assert minimos[(271440, 311)] == (900_000, 1)


def test_ignora_los_objetos_que_no_vigilas():
    minimos = minimos_del_reino([subasta(999, 100)], VIGILADOS, BONUS_MAP)
    assert minimos == {}


def test_ignora_las_subastas_sin_compra_directa():
    """Sin buyout no se puede comprar, asi que no marca ningun precio a batir."""
    minimos = minimos_del_reino(
        [subasta(271440, 0, [12840]), subasta(271440, None, [12840])],
        VIGILADOS,
        BONUS_MAP,
    )
    assert minimos == {}


def test_el_ilvl_desconocido_va_a_su_propia_casilla():
    """Lo que no escala no tiene ilvl, y mezclarlo con el equipo mentiria."""
    minimos = minimos_del_reino([subasta(258126, 700_000)], VIGILADOS, BONUS_MAP)
    assert minimos[(258126, None)] == (700_000, 1)


def test_el_precio_es_por_unidad_en_los_lotes():
    """Un lote de 5 a 500.000 compite a 100.000 la unidad, no a 500.000."""
    minimos = minimos_del_reino(
        [subasta(271440, 500_000, [12840], cantidad=5)], VIGILADOS, BONUS_MAP
    )
    assert minimos[(271440, 305)] == (100_000, 1)


def test_solo_se_vigilan_los_reinos_de_los_personajes_del_orden():
    """Bajarse los 92 reinos para mirar 20 seria tirar el tiempo y la cuota."""
    roster = {"Adannor": "Azuremyst", "Obardan": "Ragnaros"}
    assert reinos_a_vigilar(roster, ["Adannor"]) == {"Azuremyst"}


def test_un_personaje_sin_ficha_en_el_roster_no_rompe_nada():
    assert reinos_a_vigilar({}, ["Fbarbar"]) == set()


def test_el_fichero_dice_cuando_se_vio_cada_reino():
    """Sin eso no se distingue 'nadie lo vende' de 'ese reino no se ha mirado'."""
    salida = construir_precios(
        {"garona": ({(271440, 305): (300_000, 2)}, 1788449397)},
        generado=1788450000,
    )
    reino = salida["reinos"]["garona"]
    assert reino["visto"] == 1788449397
    assert reino["precios"]["271440"]["305"] == {"min": 300_000, "n": 2}


def test_un_reino_mirado_y_vacio_sale_igual_pero_sin_precios():
    """Un reino sin ninguna subasta tuya vigilada es justo donde quieres entrar."""
    salida = construir_precios({"garona": ({}, 1788449397)}, generado=1788450000)
    assert salida["reinos"]["garona"]["precios"] == {}


def test_el_ilvl_desconocido_se_escribe_como_plano():
    salida = construir_precios(
        {"garona": ({(258126, None): (700_000, 1)}, 1)}, generado=2
    )
    assert salida["reinos"]["garona"]["precios"]["258126"]["plano"]["min"] == 700_000
