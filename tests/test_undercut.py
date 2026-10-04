"""La regla de deteccion de undercuts, sin tocar la red."""

from dataclasses import replace

from wowalerts.misubastas import MyAuction
from wowalerts.undercut import find_undercuts

ITEM = 200000
ORO = 10_000


def mia(auction_id=1, item_id=ITEM, ilvl=311, oro=9000):
    return MyAuction(
        auction_id=auction_id,
        item_id=item_id,
        item_name="Greaves of the Noxious Depths",
        ilvl=ilvl,
        buyout_copper=oro * ORO,
        quantity=1,
        character="Pepe",
        realm="Sanguino",
        realm_slug="sanguino",
    )


def ajena(auction_id=99, item_id=ITEM, ilvl=311, oro=8000, bonus=None):
    item = {"id": item_id}
    if bonus is not None:
        item["bonus_lists"] = bonus
    else:
        item["item_level"] = ilvl
    return {"id": auction_id, "item": item, "buyout": oro * ORO, "quantity": 1}


def test_rival_mas_barato_genera_aviso():
    resultado = find_undercuts([ajena(oro=8000), ajena(auction_id=1)], [mia()], {})
    assert len(resultado) == 1
    assert resultado[0].rival_auction_id == 99
    assert resultado[0].rival_price_gold == 8000


def test_rival_al_mismo_precio_publicado_despues_genera_aviso():
    # Su id (99) es mayor que el tuyo (1): publico despues y te adelanto.
    resultado = find_undercuts([ajena(oro=9000), ajena(auction_id=1)], [mia()], {})
    assert len(resultado) == 1
    assert resultado[0].tied


def test_rival_al_mismo_precio_que_ya_estaba_no_genera_aviso():
    """Si su subasta es anterior a la tuya, no te ha quitado el sitio: llegaste
    tu segundo y empataste a sabiendas."""
    resultado = find_undercuts(
        [ajena(auction_id=5, oro=9000), ajena(auction_id=100)], [mia(100)], {}
    )
    assert resultado == []


def test_un_rival_anterior_pero_mas_barato_si_genera_aviso():
    # Mas barato adelanta siempre, se publicara cuando se publicara.
    resultado = find_undercuts(
        [ajena(auction_id=5, oro=8000), ajena(auction_id=100)], [mia(100)], {}
    )
    assert len(resultado) == 1


def test_rival_mas_caro_no_genera_aviso():
    assert find_undercuts([ajena(oro=9500), ajena(auction_id=1)], [mia()], {}) == []


def test_tu_propia_subasta_no_te_undercutea():
    # Solo esta la tuya en el volcado: nadie te ha adelantado.
    assert find_undercuts([ajena(auction_id=1, oro=9000)], [mia()], {}) == []


def test_dos_subastas_tuyas_solo_avisa_de_la_adelantada():
    subastas = [
        ajena(auction_id=1, oro=9000),
        ajena(auction_id=2, oro=5000),
        ajena(auction_id=99, oro=8000),
    ]
    resultado = find_undercuts(subastas, [mia(1, oro=9000), mia(2, oro=5000)], {})
    assert [u.mine.auction_id for u in resultado] == [1]


def test_ilvl_distinto_no_cuenta():
    subastas = [ajena(auction_id=1, oro=9000), ajena(ilvl=298, oro=100)]
    assert find_undercuts(subastas, [mia()], {}) == []


def test_objeto_distinto_no_cuenta():
    subastas = [ajena(auction_id=1, oro=9000), ajena(item_id=111111, oro=100)]
    assert find_undercuts(subastas, [mia()], {}) == []


def test_subasta_tuya_que_ya_no_existe_se_descarta():
    # La tuya (id 1) no aparece en el volcado: vendida o caducada.
    assert find_undercuts([ajena(oro=1)], [mia()], {}) == []


def test_rival_sin_compra_directa_se_ignora():
    sin_buyout = ajena(oro=1)
    sin_buyout["buyout"] = 0
    assert find_undercuts([sin_buyout, ajena(auction_id=1, oro=9000)], [mia()], {}) == []


def test_rival_con_ilvl_indeterminable_no_avisa():
    """Sobre datos reales, comparar contra rivales de ilvl desconocido daba
    solo falsas alarmas: chatarra de 100 g frente a subastas de 10.000."""
    desconocido = ajena(oro=8000, bonus=[123456])
    assert find_undercuts([desconocido, ajena(auction_id=1, oro=9000)], [mia()], {}) == []


def test_rival_con_los_mismos_bonus_ids_avisa_aunque_no_haya_ilvl():
    igual = ajena(oro=8000, bonus=[12817, 6652])
    mia_con_bonus = replace(mia(), bonus_ids=(12817, 6652))
    resultado = find_undercuts(
        [igual, ajena(auction_id=1, oro=9000)], [mia_con_bonus], {}
    )
    assert len(resultado) == 1
    assert resultado[0].rival_price_gold == 8000


def test_rival_con_otros_bonus_ids_no_cuenta():
    otro = ajena(oro=100, bonus=[13900, 13663])
    mia_con_bonus = replace(mia(), bonus_ids=(12817, 6652))
    assert find_undercuts([otro, ajena(auction_id=1, oro=9000)], [mia_con_bonus], {}) == []


def test_cuenta_cuantos_te_han_adelantado():
    subastas = [
        ajena(auction_id=1, oro=9000),
        ajena(auction_id=97, oro=8500),
        ajena(auction_id=98, oro=8000),
        ajena(auction_id=99, oro=9500),
    ]
    resultado = find_undercuts(subastas, [mia()], {})
    assert resultado[0].rivals_ahead == 2
    assert resultado[0].rival_price_gold == 8000


def test_sin_subastas_propias_no_hay_nada_que_mirar():
    assert find_undercuts([ajena()], [], {}) == []


def test_ordena_por_diferencia_de_precio():
    subastas = [
        ajena(auction_id=1, oro=9000),
        ajena(auction_id=2, item_id=222222, ilvl=311, oro=9000),
        ajena(auction_id=97, oro=8900),
        ajena(auction_id=98, item_id=222222, oro=1000),
    ]
    mias = [mia(1, oro=9000), mia(2, item_id=222222, oro=9000)]
    resultado = find_undercuts(subastas, mias, {})
    assert [u.mine.auction_id for u in resultado] == [2, 1]


def test_lleva_el_reino_para_la_memoria_de_avisos():
    resultado = find_undercuts(
        [ajena(oro=8000), ajena(auction_id=1)], [mia()], {}, realm_id=1379
    )
    assert resultado[0].realm_id == 1379
