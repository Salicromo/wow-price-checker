from wowalerts.config import COPPER_PER_GOLD
from wowalerts.mercado import (
    JAULA_DE_MASCOTA,
    TIPO_MASCOTA,
    TIPO_OBJETO,
    Clave,
    ResumenReino,
    agregar,
    arbitrajes,
    flips_locales,
    percentil,
    resumir_reino,
)

BONUS_MAP = {12843: 311, 12838: 308}


def objeto(item_id=5000, variante=311):
    return Clave(TIPO_OBJETO, item_id, variante)


def auction(item_id=5000, buyout=None, bonus=(12843,), quantity=1, **extra):
    item = {"id": item_id, "bonus_lists": list(bonus)}
    item.update(extra.pop("item", {}))
    data = {"id": 1, "item": item, "quantity": quantity}
    if buyout is not None:
        data["buyout"] = buyout
    data.update(extra)
    return data


def oro(cantidad):
    return cantidad * COPPER_PER_GOLD


def resumen(*precios, listados=None):
    return ResumenReino(
        precios=tuple(sorted(precios)), listados=listados or len(precios)
    )


# -- resumir_reino ----------------------------------------------------------


def test_agrupa_por_objeto_e_ilvl():
    """La misma pieza a dos ilvl son dos mercados, no uno."""
    resumido = resumir_reino(
        [
            auction(buyout=oro(10_000), bonus=(12843,)),
            auction(buyout=oro(90_000), bonus=(12838,)),
        ],
        BONUS_MAP,
    )
    assert set(resumido) == {objeto(), objeto(variante=308)}


def test_guarda_los_mas_baratos_en_orden():
    resumido = resumir_reino(
        [auction(buyout=oro(p)) for p in (30_000, 10_000, 20_000)], BONUS_MAP
    )
    datos = resumido[objeto()]
    assert datos.minimo == oro(10_000)
    assert datos.segundo == oro(20_000)
    assert datos.listados == 3


def test_el_precio_es_por_unidad():
    """Un lote de cinco a 50.000 son 10.000 la unidad, no 50.000."""
    resumido = resumir_reino([auction(buyout=oro(50_000), quantity=5)], BONUS_MAP)
    assert resumido[objeto()].minimo == oro(10_000)


def test_ignora_subastas_sin_compra_directa():
    assert resumir_reino([auction(bid=oro(10_000))], BONUS_MAP) == {}
    assert resumir_reino([auction(buyout=0)], BONUS_MAP) == {}


def test_las_mascotas_se_distinguen_por_especie_y_calidad():
    """Todas son el objeto 82800; lo que las separa va en campos aparte."""
    subastas = [
        auction(
            item_id=JAULA_DE_MASCOTA,
            buyout=oro(10_000),
            item={"pet_species_id": 1531, "pet_quality_id": 3},
        ),
        auction(
            item_id=JAULA_DE_MASCOTA,
            buyout=oro(20_000),
            item={"pet_species_id": 1531, "pet_quality_id": 2},
        ),
        auction(
            item_id=JAULA_DE_MASCOTA,
            buyout=oro(30_000),
            item={"pet_species_id": 42, "pet_quality_id": 3},
        ),
    ]
    resumido = resumir_reino(subastas, BONUS_MAP)

    assert set(resumido) == {
        Clave(TIPO_MASCOTA, 1531, 3),
        Clave(TIPO_MASCOTA, 1531, 2),
        Clave(TIPO_MASCOTA, 42, 3),
    }
    assert resumido[Clave(TIPO_MASCOTA, 1531, 3)].minimo == oro(10_000)


def test_una_jaula_sin_especie_se_descarta():
    """Sin especie no se sabe que mascota es, y meterla mezclaria todas."""
    subastas = [auction(item_id=JAULA_DE_MASCOTA, buyout=oro(10_000))]
    assert resumir_reino(subastas, BONUS_MAP) == {}


def test_el_suelo_de_precio_descarta_la_morralla():
    resumido = resumir_reino(
        [auction(buyout=oro(100)), auction(buyout=oro(9_000))],
        BONUS_MAP,
        precio_minimo=oro(5_000),
    )
    assert resumido[objeto()].listados == 1


def test_solo_guarda_las_muestras_pedidas_pero_cuenta_todas():
    resumido = resumir_reino(
        [auction(buyout=oro(p)) for p in range(10_000, 20_000, 1_000)],
        BONUS_MAP,
        muestras=3,
    )
    datos = resumido[objeto()]
    assert datos.precios == (oro(10_000), oro(11_000), oro(12_000))
    assert datos.listados == 10


# -- arbitrajes -------------------------------------------------------------


def agregado_de(por_realm, clave=None):
    clave = clave or objeto()
    return {clave: por_realm}


def test_detecta_comprar_barato_y_vender_caro():
    agr = agregado_de(
        {1: resumen(oro(10_000), oro(11_000))}
        | {r: resumen(oro(100_000), oro(110_000)) for r in range(2, 20)}
    )
    resultado = arbitrajes(agr, comision_pct=5, reinos_minimos=15, ratio_minimo=3)

    assert len(resultado) == 1
    arbi = resultado[0]
    assert arbi.reino_compra == 1
    assert arbi.precio_compra == oro(10_000)
    assert arbi.precio_venta == oro(100_000)
    # 100.000 menos el 5% de comision, menos los 10.000 que cuesta comprarlo.
    assert arbi.neto == oro(85_000)
    assert arbi.ratio == 10


def test_un_reino_con_una_sola_subasta_no_sirve_para_vender():
    """Un precio sin competencia detras no es un mercado, es una peticion."""
    agr = agregado_de(
        {1: resumen(oro(10_000), oro(11_000))}
        | {2: resumen(oro(5_000_000), listados=1)}
        | {r: resumen(oro(12_000), oro(13_000)) for r in range(3, 20)}
    )
    resultado = arbitrajes(agr, reinos_minimos=15, ratio_minimo=1, beneficio_minimo=0)

    assert resultado[0].reino_venta != 2


def test_exige_dato_en_bastantes_reinos():
    agr = agregado_de({1: resumen(oro(10_000)), 2: resumen(oro(500_000), oro(510_000))})
    assert arbitrajes(agr, reinos_minimos=15) == []


def test_el_beneficio_minimo_filtra():
    agr = agregado_de(
        {1: resumen(oro(10_000))} | {r: resumen(oro(40_000), oro(41_000)) for r in range(2, 20)}
    )
    assert arbitrajes(agr, reinos_minimos=15, beneficio_minimo=oro(1_000_000)) == []


def test_cuenta_en_cuantos_reinos_se_puede_colocar():
    agr = agregado_de(
        {1: resumen(oro(10_000))}
        | {r: resumen(oro(100_000), oro(110_000)) for r in range(2, 12)}
        | {r: resumen(oro(10_500), oro(10_600)) for r in range(12, 20)}
    )
    arbi = arbitrajes(agr, reinos_minimos=15, ratio_minimo=3)[0]

    assert arbi.reinos_con_dato == 19
    assert arbi.reinos_rentables == 10


# -- flips locales ----------------------------------------------------------


def test_flip_local_usa_la_siguiente_subasta_del_reino():
    agr = agregado_de(
        {1: resumen(oro(10_000), oro(60_000))}
        | {r: resumen(oro(80_000), oro(90_000)) for r in range(2, 20)}
    )
    flip = flips_locales(agr, comision_pct=5, reinos_minimos=15, ratio_minimo=3)[0]

    assert flip.realm_id == 1
    assert flip.referencia == oro(60_000)
    assert flip.neto == oro(47_000)


def test_flip_local_no_se_cree_una_segunda_subasta_de_fantasia():
    """Con un segundo precio absurdo manda la mediana de la region."""
    agr = agregado_de(
        {1: resumen(oro(10_000), oro(9_000_000))}
        | {r: resumen(oro(50_000), oro(60_000)) for r in range(2, 20)}
    )
    flip = flips_locales(agr, reinos_minimos=15, ratio_minimo=3)[0]

    assert flip.referencia == oro(50_000)


# -- percentil --------------------------------------------------------------


def test_percentil_devuelve_un_precio_que_existe():
    valores = [10, 20, 30, 40, 100]
    assert percentil(valores, 25) == 20
    assert percentil(valores, 75) == 40
    assert percentil(valores, 0) == 10
    assert percentil(valores, 100) == 100
    assert percentil([], 50) == 0


# -- agregar ----------------------------------------------------------------


def test_agregar_cruza_los_reinos_por_objeto():
    agr = agregar(
        [
            (1, {objeto(): resumen(oro(10_000))}),
            (
                2,
                {
                    objeto(): resumen(oro(20_000)),
                    Clave(TIPO_OBJETO, 6000): resumen(oro(1_000)),
                },
            ),
        ]
    )
    assert set(agr) == {objeto(), Clave(TIPO_OBJETO, 6000)}
    assert set(agr[objeto()]) == {1, 2}


def test_descarta_los_precios_aparcados():
    """9.999.999 en media region no es un precio, es un aparcamiento."""
    agr = agregado_de(
        {1: resumen(oro(10_000), oro(11_000))}
        | {r: resumen(oro(9_999_999), oro(9_999_999)) for r in range(2, 20)}
    )
    assert arbitrajes(agr, reinos_minimos=15, venta_maxima=oro(5_000_000)) == []
    assert arbitrajes(agr, reinos_minimos=15, venta_maxima=0) != []


def test_el_valor_minimo_descarta_la_calderilla():
    """Un 10x sobre 20.000 oro no paga el viaje al banco."""
    agr = agregado_de(
        {1: resumen(oro(2_000))} | {r: resumen(oro(20_000), oro(21_000)) for r in range(2, 20)}
    )
    assert arbitrajes(agr, reinos_minimos=15, valor_minimo=oro(200_000)) == []
    assert arbitrajes(agr, reinos_minimos=15, valor_minimo=oro(10_000)) != []
