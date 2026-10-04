from datetime import date

from wowalerts.historial import apuntar, construir_historial, minimos_de_ahora, recortar
from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave

GREBAS_305 = Clave(TIPO_OBJETO, 212000, 305)
MONTURA = Clave(TIPO_OBJETO, 49286)
OTRO = Clave(TIPO_OBJETO, 1, 305)
GATO = Clave(TIPO_MASCOTA, 212000, 3)
HOY = date(2026, 9, 27)


def test_el_minimo_de_ahora_es_el_mas_barato_de_la_region_y_solo_de_lo_vigilado():
    ofertas = {
        GREBAS_305: [(1, 30_000_000, 1), (0, 10_000_000, 4)],
        MONTURA: [(1, 5_000_000, 1)],
        OTRO: [(0, 1, 1)],
        GATO: [(0, 1, 1)],
    }
    minimos = minimos_de_ahora(ofertas, {212000, 49286}, ["Aszune", "Kazzak"])
    assert minimos == {
        (212000, 305): (1000, "Aszune"),
        (49286, None): (500, "Kazzak"),
    }


def test_el_dia_se_queda_con_la_pasada_mas_barata():
    historial = {}
    apuntar(historial, HOY, {(212000, 305): (1000, "Aszune")})
    apuntar(historial, HOY, {(212000, 305): (1500, "Kazzak")})
    apuntar(historial, HOY, {(212000, 305): (800, "Kazzak"), (49286, None): (500, "Aszune")})
    assert historial == {
        "212000": {"305": {"2026-09-27": [800, "Kazzak"]}},
        "49286": {"-": {"2026-09-27": [500, "Aszune"]}},
    }


def test_se_olvida_lo_de_hace_mas_de_30_dias_y_lo_que_ya_no_vigilas():
    historial = {
        "212000": {"305": {"2026-08-28": [1, "A"], "2026-08-29": [2, "B"]}, "311": {"2026-08-01": [3, "C"]}},
        "49286": {"-": {"2026-09-27": [4, "D"]}},
    }
    recortar(historial, HOY, {212000})
    assert historial == {"212000": {"305": {"2026-08-29": [2, "B"]}}}


def test_el_fichero_va_del_dia_mas_viejo_al_de_hoy():
    historial = {"212000": {"305": {"2026-09-27": [800, "Kazzak"], "2026-09-25": [900, "Aszune"]}}}
    fichero = construir_historial(historial, 99)
    assert fichero["generado"] == 99
    assert fichero["objetos"] == {
        "212000": {"305": [["2026-09-25", 900, "Aszune"], ["2026-09-27", 800, "Kazzak"]]}
    }
