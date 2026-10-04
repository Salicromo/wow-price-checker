from wowalerts.buscador import (
    acumular,
    clave_de_nombre,
    construir_indice,
    nombres_que_faltan,
)
from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave, ResumenReino

GREBAS_305 = Clave(TIPO_OBJETO, 212000, 305)
GREBAS_311 = Clave(TIPO_OBJETO, 212000, 311)
MONTURA = Clave(TIPO_OBJETO, 49286)
GATO = Clave(TIPO_MASCOTA, 40, 3)


def resumen(minimo, listados=1):
    return ResumenReino(precios=(minimo,), listados=listados)


def test_se_queda_con_los_reinos_mas_baratos():
    ofertas = {}
    for grupo, precio in enumerate([90, 10, 50, 30]):
        acumular(ofertas, grupo, {GREBAS_305: resumen(precio)}, limite=2)
    assert sorted(ofertas[GREBAS_305], key=lambda o: o[1]) == [(1, 10, 1), (3, 30, 1)]


def test_el_nombre_es_del_producto_y_no_de_la_variante():
    assert clave_de_nombre(GREBAS_305) == clave_de_nombre(GREBAS_311) == "o:212000"
    assert clave_de_nombre(GATO) == "m:40"


def test_faltan_primero_los_que_estan_en_mas_reinos():
    ofertas = {
        MONTURA: [(0, 1, 1)],
        GREBAS_305: [(0, 1, 1), (1, 1, 1), (2, 1, 1)],
        GATO: [(0, 1, 1), (1, 1, 1)],
    }
    assert nombres_que_faltan(ofertas, {}, limite=2) == [GREBAS_305, GATO]
    assert nombres_que_faltan(ofertas, {"o:212000": {}}, limite=5) == [GATO, MONTURA]


def test_el_indice_agrupa_variantes_en_oro_y_ordenadas():
    ofertas = {
        GREBAS_311: [(0, 90_000_000, 2)],
        GREBAS_305: [(1, 30_000_000, 1), (0, 10_000_000, 4)],
        MONTURA: [(1, 5_000_000, 1)],
    }
    nombres = {"o:212000": {"es": "Grebas", "en": "Greaves", "icono": "x.jpg"}}
    indice = construir_indice(
        ofertas, nombres, [("Aszune", ["aszune"], 7), ("Kazzak", ["kazzak"], 8)], 99
    )

    assert indice["grupos"][1] == {"nombre": "Kazzak", "slugs": ["kazzak"], "visto": 8}
    # La montura no tiene nombre todavia: no se puede buscar, asi que no sale.
    assert len(indice["productos"]) == 1
    grebas = indice["productos"][0]
    assert (grebas["t"], grebas["id"], grebas["es"], grebas["en"], grebas["i"]) == (
        "o", 212000, "Grebas", "Greaves", "x.jpg"
    )
    assert grebas["v"] == [
        [305, [[0, 1000, 4], [1, 3000, 1]]],
        [311, [[0, 9000, 2]]],
    ]


def test_sin_nombre_en_espanol_se_usa_el_ingles():
    indice = construir_indice(
        {MONTURA: [(0, 5_000_000, 1)]}, {"o:49286": {"es": None, "en": "Rocket"}}, [], 1
    )
    producto = indice["productos"][0]
    assert producto["es"] == producto["en"] == "Rocket"
    assert producto["v"] == [[None, [[0, 500, 1]]]]
