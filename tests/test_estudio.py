from wowalerts.estudio import (
    apuntar,
    comparar,
    construir_estudio,
    filas_del_reino,
    recortar,
)

GREBAS = 271440
CASCO = 271438
MAPA = {12848: 328, 12845: 318, 12838: 308}
HORA = 3600


def subasta(aid, item=GREBAS, bonus=12848, buyout=1_000_000, qty=1, tl="VERY_LONG"):
    return {
        "id": aid,
        "item": {"id": item, "bonus_lists": [bonus]},
        "buyout": buyout,
        "quantity": qty,
        "time_left": tl,
    }


def test_solo_se_guardan_los_ilvl_altos_de_lo_vigilado():
    filas = filas_del_reino(
        [
            subasta(1),
            subasta(2, bonus=12838),  # ilvl 308: fuera
            subasta(3, item=999),  # no vigilado
            subasta(4, buyout=None),  # sin compra directa
            subasta(5, item=CASCO, bonus=12845),
        ],
        {GREBAS, CASCO},
        MAPA,
    )
    assert filas == [
        [1, GREBAS, 328, 1_000_000, 1, "VERY_LONG"],
        [5, CASCO, 318, 1_000_000, 1, "VERY_LONG"],
    ]


def test_desaparecer_antes_de_poder_caducar_es_una_venta():
    antes = [[1, GREBAS, 328, 4_000_000, 1, "LONG"], [2, GREBAS, 328, 5_000_000, 1, "VERY_LONG"]]
    ahora = [[2, GREBAS, 328, 5_000_000, 1, "VERY_LONG"]]
    assert comparar(antes, ahora) == [[GREBAS, 328, 4_000_000, 1]]


def test_lo_que_podia_caducar_no_cuenta():
    antes = [[1, GREBAS, 328, 4_000_000, 1, "SHORT"], [2, GREBAS, 328, 4_000_000, 1, "MEDIUM"]]
    assert comparar(antes, []) == []


def test_un_reposteo_no_es_venta():
    antes = [[1, GREBAS, 328, 4_000_000, 1, "LONG"]]
    ahora = [[900, GREBAS, 328, 3_900_000, 1, "VERY_LONG"]]
    assert comparar(antes, ahora) == []


def test_un_lote_retirado_entero_no_son_ventas():
    antes = [[i, GREBAS, 328, 4_000_000, 1, "LONG"] for i in (10, 11, 12)]
    assert comparar(antes, []) == []


def test_la_primera_foto_no_apunta_nada():
    estado = {}
    apuntar(estado, 1305, [[1, GREBAS, 328, 4_000_000, 1, "LONG"]], 1000)
    assert estado["registro"] == []
    assert estado["fotos"]["1305"]["visto"] == 1000


def test_una_hora_despues_se_apuntan_las_ventas_y_lo_puesto():
    estado = {}
    apuntar(estado, 1305, [[1, GREBAS, 328, 4_000_000, 1, "LONG"], [2, CASCO, 318, 1, 1, "LONG"]], 1000)
    apuntar(estado, 1305, [[2, CASCO, 318, 1, 1, "LONG"]], 1000 + HORA)
    assert estado["registro"] == [
        {
            "reino": 1305,
            "hasta": 1000 + HORA,
            "ventas": [[GREBAS, 328, 4_000_000, 1]],
            "puestas": {"318": 1, "321": 0, "324": 0, "328": 1},
        }
    ]


def test_el_mismo_volcado_no_se_compara_consigo_mismo():
    estado = {}
    apuntar(estado, 1305, [[1, GREBAS, 328, 4_000_000, 1, "LONG"]], 1000)
    apuntar(estado, 1305, [], 1000)
    assert estado["registro"] == []
    assert estado["fotos"]["1305"]["filas"] == [[1, GREBAS, 328, 4_000_000, 1, "LONG"]]


def test_tras_un_hueco_largo_no_se_compara_pero_se_guarda_la_foto():
    estado = {}
    apuntar(estado, 1305, [[1, GREBAS, 328, 4_000_000, 1, "LONG"]], 1000)
    apuntar(estado, 1305, [], 1000 + 5 * HORA)
    assert estado["registro"] == []
    assert estado["fotos"]["1305"]["visto"] == 1000 + 5 * HORA


def test_se_olvida_lo_de_hace_mas_de_14_dias():
    estado = {"registro": [{"hasta": 0}, {"hasta": 10 * 86400}], "fotos": {}}
    recortar(estado, 20 * 86400)
    assert estado["registro"] == [{"hasta": 10 * 86400}]


def test_el_fichero_publicado_lleva_los_nombres_y_no_las_fotos():
    estado = {"registro": [{"reino": 1305}], "fotos": {"1305": {"visto": 1, "filas": []}}}
    fichero = construir_estudio(estado, {1305: "Kazzak"}, 99)
    assert fichero == {
        "generado": 99,
        "ilvls": [318, 321, 324, 328],
        "reinos": {"1305": "Kazzak"},
        "registro": [{"reino": 1305}],
    }
