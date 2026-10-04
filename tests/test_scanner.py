from wowalerts.config import COPPER_PER_GOLD, ItemRule
from wowalerts.scanner import find_deals

RULE = ItemRule(name="Botas", max_price_by_ilvl={298: 9000, 311: 90000})
RULES = {5000: RULE}
BONUS_MAP = {12843: 311, 12840: 305, 12838: 298}
REALM = 1305


def auction(auction_id=1, item_id=5000, buyout=None, bonus=(12843,), **extra):
    item = {"id": item_id, "bonus_lists": list(bonus)}
    item.update(extra.pop("item", {}))
    data = {"id": auction_id, "item": item, "quantity": 1, "time_left": "LONG"}
    if buyout is not None:
        data["buyout"] = buyout
    data.update(extra)
    return data


def scan(auctions, **kwargs):
    kwargs.setdefault("alert_on_unconfirmed_ilvl", True)
    return find_deals(auctions, REALM, RULES, BONUS_MAP, **kwargs)


def test_detecta_un_chollo_por_debajo_del_umbral():
    deals = scan([auction(buyout=50_000 * COPPER_PER_GOLD)])

    assert len(deals) == 1
    deal = deals[0]
    assert deal.item_name == "Botas"
    assert deal.ilvl == 311
    assert deal.ilvl_confirmed
    assert deal.price_gold == 50_000
    assert deal.threshold_gold == 90_000
    assert deal.realm_id == REALM
    assert round(deal.discount_pct) == 44


def test_el_precio_exacto_del_umbral_cuenta_como_chollo():
    deals = scan([auction(buyout=90_000 * COPPER_PER_GOLD)])
    assert len(deals) == 1
    assert deals[0].discount_pct == 0


def test_un_cobre_por_encima_del_umbral_no_es_chollo():
    """La comparacion va en cobre; convertir a oro antes redondearia a favor."""
    deals = scan([auction(buyout=90_000 * COPPER_PER_GOLD + 1)])
    assert deals == []


def test_ignora_subastas_sin_compra_directa():
    """Solo puja: el precio 0 haria pasar cualquier filtro (falso chollo)."""
    assert scan([auction(buyout=0, bid=1_000)]) == []
    assert scan([auction(bid=1_000)]) == []
    assert scan([auction(buyout=None, bid=1_000)]) == []


def test_ignora_objetos_que_no_se_vigilan():
    assert scan([auction(item_id=9999, buyout=1)]) == []


def test_ignora_un_ilvl_sin_precio_configurado():
    """El ilvl 305 se identifica bien, pero no esta en la tabla del objeto.

    Aunque el precio sea ridiculo, no se avisa: solo interesan los ilvl que se
    hayan listado en config.yaml.
    """
    deals = scan([auction(buyout=1 * COPPER_PER_GOLD, bonus=(12840,))])
    assert deals == []


def test_ilvl_desconocido_usa_el_umbral_mas_barato():
    barato = auction(auction_id=1, buyout=8_000 * COPPER_PER_GOLD, bonus=(77777,))
    caro = auction(auction_id=2, buyout=50_000 * COPPER_PER_GOLD, bonus=(77777,))

    deals = scan([barato, caro])

    assert [d.auction_id for d in deals] == [1]
    assert deals[0].ilvl is None
    assert deals[0].ilvl_confirmed is False
    assert deals[0].threshold_gold == 9_000


def test_ilvl_desconocido_se_puede_desactivar():
    deals = scan(
        [auction(buyout=8_000 * COPPER_PER_GOLD, bonus=(77777,))],
        alert_on_unconfirmed_ilvl=False,
    )
    assert deals == []


def test_conserva_cantidad_y_tiempo_restante():
    deals = scan([auction(buyout=1 * COPPER_PER_GOLD, quantity=3, time_left="SHORT")])
    assert deals[0].quantity == 3
    assert deals[0].time_left == "SHORT"


def test_subasta_sin_objeto_no_rompe_el_escaneo():
    deals = scan([{"id": 1}, {"id": 2, "item": {}}, auction(buyout=COPPER_PER_GOLD)])
    assert len(deals) == 1


def test_precio_en_oro_se_trunca_hacia_abajo():
    """19.999 cobre son 1 oro largo; mostramos 1, no 2."""
    deals = scan([auction(buyout=19_999)])
    assert deals[0].price_gold == 1
    assert deals[0].price_copper == 19_999


PATRON = ItemRule(name="Pattern: Arcanoweave Cord", max_price=60_000)


def test_un_objeto_de_precio_unico_avisa_sin_mirar_el_ilvl():
    deals = find_deals(
        [auction(buyout=60_000 * COPPER_PER_GOLD, bonus=())],
        REALM,
        {5000: PATRON},
        BONUS_MAP,
    )

    assert len(deals) == 1
    deal = deals[0]
    assert deal.sin_ilvl
    assert deal.ilvl is None
    assert deal.threshold_gold == 60_000


def test_un_objeto_de_precio_unico_no_se_pierde_por_traer_ilvl():
    # Aunque la subasta traiga bonus ids que se traducen a un ilvl, el limite
    # sigue siendo el unico que tiene el objeto.
    deals = find_deals(
        [auction(buyout=59_000 * COPPER_PER_GOLD, bonus=(12843,))],
        REALM,
        {5000: PATRON},
        BONUS_MAP,
    )

    assert len(deals) == 1
    assert deals[0].sin_ilvl


def test_un_objeto_de_precio_unico_por_encima_del_limite_se_ignora():
    deals = find_deals(
        [auction(buyout=60_001 * COPPER_PER_GOLD, bonus=())],
        REALM,
        {5000: PATRON},
        BONUS_MAP,
    )

    assert deals == []


# -- mascotas ---------------------------------------------------------------
#
# Todas las mascotas se subastan dentro del objeto 82800, asi que casarlas por
# item_id daria la misma regla para cualquiera. Van por especie y en su propio
# mapa.

JAULA = 82800
REGLA_MASCOTA = ItemRule(name="Gusting Grimoire", pet_species_id=1174, max_price=100_000)
POR_ESPECIE = {1174: REGLA_MASCOTA}


def jaula(auction_id=1, especie=1174, calidad=3, buyout=None):
    item = {"id": JAULA, "pet_species_id": especie, "pet_quality_id": calidad}
    data = {"id": auction_id, "item": item, "quantity": 1, "time_left": "LONG"}
    if buyout is not None:
        data["buyout"] = buyout
    return data


def escanear_mascotas(auctions):
    return find_deals(
        auctions, REALM, {}, BONUS_MAP, rules_by_species=POR_ESPECIE
    )


def test_detecta_el_chollo_de_una_mascota_vigilada():
    deals = escanear_mascotas([jaula(buyout=60_000 * COPPER_PER_GOLD)])

    assert len(deals) == 1
    assert deals[0].item_name == "Gusting Grimoire"
    assert deals[0].pet_species_id == 1174
    assert deals[0].price_gold == 60_000
    assert deals[0].threshold_gold == 100_000


def test_no_avisa_de_una_mascota_que_no_se_vigila():
    """Lo que rompe el casar por item_id: aqui la especie no coincide."""
    assert escanear_mascotas([jaula(especie=42, buyout=1 * COPPER_PER_GOLD)]) == []


def test_una_mascota_cara_no_es_chollo():
    assert escanear_mascotas([jaula(buyout=100_001 * COPPER_PER_GOLD)]) == []


def test_una_regla_de_objeto_no_pesca_mascotas():
    """Sin esto, una regla con item_id 82800 avisaria de toda mascota de EU."""
    reglas = {JAULA: ItemRule(name="Jaula", max_price=100_000)}
    deals = find_deals(
        [jaula(buyout=1 * COPPER_PER_GOLD)], REALM, reglas, BONUS_MAP
    )
    assert deals == []


def test_los_dos_mapas_conviven_en_la_misma_pasada():
    deals = find_deals(
        [
            auction(auction_id=1, buyout=50_000 * COPPER_PER_GOLD),
            jaula(auction_id=2, buyout=60_000 * COPPER_PER_GOLD),
        ],
        REALM,
        RULES,
        BONUS_MAP,
        rules_by_species=POR_ESPECIE,
    )
    assert {d.item_name for d in deals} == {"Botas", "Gusting Grimoire"}
