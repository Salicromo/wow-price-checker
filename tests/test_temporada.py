"""Temporada nueva: bonus ids desconocidos e ilvl fuera de tabla."""

import pytest
import yaml

from wowalerts.config import ItemRule
from wowalerts.temporada import (
    MapaError,
    Observado,
    WowheadError,
    anadir_al_mapa,
    ilvl_en_wowhead,
    observar,
    resolver_bonus,
    texto_fuera_de_tabla,
)

GREBAS = ItemRule(name="Greaves", max_price_by_ilvl={298: 9000, 311: 90000})
CASCO = ItemRule(name="Helm", max_price_by_ilvl={311: 50000})
PATRON = ItemRule(name="Pattern", max_price=100, item_id=3)
REGLAS = {1: GREBAS, 2: CASCO, 3: PATRON}
MAPA = {12843: 311, 12830: 298, 12850: 321}


def subasta(item_id, bonus, buyout=1_000_000, **extra):
    return {"id": 9, "item": {"id": item_id, "bonus_lists": list(bonus), **extra},
            "buyout": buyout}


# --- observar ----------------------------------------------------------------


def test_una_lista_sin_bonus_conocido_se_apunta():
    visto = observar([subasta(1, [13001, 6652])], REGLAS, MAPA)

    assert visto.sin_ilvl == {1: {(6652, 13001)}}
    assert visto.nombres == {1: "Greaves"}


def test_un_ilvl_conocido_de_la_tabla_no_se_apunta():
    visto = observar([subasta(1, [12843, 6652])], REGLAS, MAPA)

    assert visto.vacio()


def test_un_ilvl_por_encima_de_la_tabla_se_apunta_con_el_mas_barato():
    visto = observar(
        [subasta(1, [12850], 5_000_000), subasta(1, [12850], 3_000_000)],
        REGLAS, MAPA,
    )

    assert visto.fuera_de_tabla == {(1, 321): 3_000_000}


def test_un_ilvl_por_debajo_de_la_tabla_no_interesa():
    """Los escalones bajos que no vigilas los has dejado fuera a proposito."""
    visto = observar([subasta(2, [12830])], REGLAS, MAPA)

    assert visto.vacio()


def test_patrones_mascotas_y_objetos_no_vigilados_no_cuentan():
    visto = observar(
        [
            subasta(3, [13001]),
            subasta(99, [13001]),
            subasta(1, [13001], pet_species_id=5),
            subasta(1, []),
        ],
        REGLAS, MAPA,
    )

    assert visto.vacio()


def test_observado_ida_y_vuelta_por_json(tmp_path):
    visto = observar(
        [subasta(1, [13001, 6652]), subasta(2, [12850], 7)], REGLAS, MAPA
    )
    ruta = tmp_path / "o.json"
    visto.guardar(ruta)

    assert Observado.leer(ruta) == visto
    assert Observado.leer(tmp_path / "no.json") is None


def test_juntar_se_queda_con_el_precio_mas_bajo():
    a = Observado(fuera_de_tabla={(1, 321): 5}, sin_ilvl={1: {(1,)}})
    a.juntar(Observado(fuera_de_tabla={(1, 321): 3}, sin_ilvl={1: {(2,)}}))

    assert a.fuera_de_tabla == {(1, 321): 3}
    assert a.sin_ilvl == {1: {(1,), (2,)}}


# --- resolver_bonus ----------------------------------------------------------


class Wowhead:
    """Un Wowhead de mentira: ilvl base por objeto y bonus que lo fijan."""

    def __init__(self, fijan, base=None, relativos=None, raros=None):
        self.fijan = fijan
        self.base = base or {}
        self.relativos = relativos or {}
        self.raros = raros or {}
        self.llamadas = []

    def __call__(self, item_id, bonus):
        self.llamadas.append((item_id, tuple(bonus)))
        ilvl = self.base.get(item_id, 227)
        for b in bonus:
            if b in self.fijan:
                ilvl = self.fijan[b]
            elif b in self.relativos:
                ilvl += self.relativos[b] * item_id
            elif b in self.raros:
                ilvl = self.raros[b]
        return ilvl


def test_un_bonus_que_fija_el_ilvl_se_confirma():
    visto = Observado(sin_ilvl={1: {(6652, 13001)}, 2: {(13001,)}})

    r = resolver_bonus(visto, MAPA, Wowhead({13001: 685}))

    assert r.confirmados == {13001: 685}
    assert r.sin_resolver == {}


def test_se_comprueba_con_otro_objeto_aunque_no_lleve_el_bonus():
    visto = Observado(sin_ilvl={1: {(13001,)}, 2: {(13002,)}})

    r = resolver_bonus(visto, MAPA, Wowhead({13001: 685, 13002: 688}))

    assert r.confirmados == {13001: 685, 13002: 688}


def test_con_un_solo_objeto_no_se_confirma():
    visto = Observado(sin_ilvl={1: {(13001,)}})

    r = resolver_bonus(visto, MAPA, Wowhead({13001: 685}))

    assert r.confirmados == {}
    assert r.sin_resolver == {1: {(13001,)}}
    assert "otro" in r.motivos[0]


def test_un_bonus_que_no_toca_el_ilvl_no_se_apunta():
    visto = Observado(sin_ilvl={1: {(6652,)}, 2: {(6652,)}})

    r = resolver_bonus(visto, MAPA, Wowhead({}))

    assert r.confirmados == {}
    assert r.sin_resolver == {1: {(6652,)}, 2: {(6652,)}}


def test_un_ilvl_increible_no_se_apunta():
    """6652 solo da ilvl 44 en Wowhead: visto de verdad."""
    visto = Observado(sin_ilvl={1: {(6652,)}, 2: {(6652,)}})

    r = resolver_bonus(visto, MAPA, Wowhead({}, raros={6652: 44}))

    assert r.confirmados == {}


def test_un_bonus_que_suma_segun_el_objeto_no_se_apunta():
    visto = Observado(sin_ilvl={1: {(13001,)}, 2: {(13001,)}})

    r = resolver_bonus(visto, MAPA, Wowhead({}, relativos={13001: 10}))

    assert r.confirmados == {}
    assert "distinto" in r.motivos[0]


def test_si_otro_bonus_de_la_lista_mueve_el_ilvl_no_se_apunta():
    visto = Observado(sin_ilvl={1: {(13001, 13005)}, 2: {(13003,)}})
    wowhead = Wowhead({13001: 685}, relativos={13005: 1})

    r = resolver_bonus(visto, MAPA, wowhead)

    assert 13001 not in r.confirmados


def test_wowhead_caido_no_apunta_nada_y_lo_cuenta():
    def caido(item_id, bonus):
        raise WowheadError("Wowhead no responde: timeout")

    visto = Observado(sin_ilvl={1: {(13001,)}, 2: {(13001,)}})

    r = resolver_bonus(visto, MAPA, caido)

    assert r.confirmados == {}
    assert r.sin_resolver
    assert "no responde" in r.motivos[0]


def test_el_limite_de_consultas_se_respeta():
    visto = Observado(sin_ilvl={1: {(b,) for b in range(13000, 13050)}, 2: {(1,)}})
    wowhead = Wowhead({})

    r = resolver_bonus(visto, MAPA, wowhead, max_consultas=10)

    assert len(wowhead.llamadas) == 10
    assert "siguiente" in r.motivos[-1]


def test_no_se_repite_una_consulta():
    visto = Observado(sin_ilvl={1: {(13001, 6652)}, 2: {(13001,)}})
    wowhead = Wowhead({13001: 685})

    resolver_bonus(visto, MAPA, wowhead)

    assert len(wowhead.llamadas) == len(set(wowhead.llamadas))


# --- Wowhead de verdad, pero sin red ------------------------------------------


URL = "https://nether.wowhead.com/tooltip/item/258946"


def test_ilvl_en_wowhead_lee_la_ficha(requests_mock):
    requests_mock.get(
        URL + "?bonus=12817:6652",
        json={"tooltip": "<span>Item Level <!--ilvl-->266</span>"},
    )

    assert ilvl_en_wowhead(258946, [12817, 6652]) == 266


def test_ilvl_en_wowhead_objeto_desconocido(requests_mock):
    requests_mock.get(URL, status_code=404)

    assert ilvl_en_wowhead(258946) is None


def test_ilvl_en_wowhead_caido(requests_mock):
    requests_mock.get(URL, status_code=503)

    with pytest.raises(WowheadError):
        ilvl_en_wowhead(258946)


# --- anadir_al_mapa ----------------------------------------------------------

CONFIG = """\
items:
  - name: "Greaves"
    max_price_by_ilvl: { 298: 9000 }

bonus_ilvl_map:
  # Adventurer
  12817: 266
  # Myth
  12852: 328

# Ajustes
settings:
  max_workers: 2
"""


def test_los_bonus_nuevos_van_al_final_del_mapa():
    nuevo = anadir_al_mapa(CONFIG, {13002: 688, 13001: 685}, "2026-09-23")

    datos = yaml.safe_load(nuevo)
    assert datos["bonus_ilvl_map"] == {12817: 266, 12852: 328, 13001: 685, 13002: 688}
    assert datos["settings"] == {"max_workers": 2}
    assert "  12852: 328\n  # Anadidos solos el 2026-09-23" in nuevo
    assert nuevo.endswith("\n# Ajustes\nsettings:\n  max_workers: 2\n")


def test_el_mapa_al_final_del_fichero():
    texto = "bonus_ilvl_map:\n  12817: 266"

    nuevo = anadir_al_mapa(texto, {13001: 685}, "2026-09-23")

    assert yaml.safe_load(nuevo)["bonus_ilvl_map"] == {12817: 266, 13001: 685}


def test_sin_mapa_no_se_escribe():
    with pytest.raises(MapaError):
        anadir_al_mapa("items: []\n", {13001: 685}, "2026-09-23")


# --- textos ------------------------------------------------------------------


def test_el_aviso_de_fuera_de_tabla_dice_hasta_donde_llega_la_tabla():
    texto = texto_fuera_de_tabla(
        {(1, 685): 40_000 * 10_000}, {1: "Greaves"}, {1: {298: 1, 328: 2}}
    )

    assert "**Greaves**: ilvl **685**, desde 40.000 de oro (tu tabla llega a 328)" in texto
