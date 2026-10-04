from wowalerts.ilvl import MIN_PLAUSIBLE_ILVL, resolve_ilvl

BONUS_MAP = {12843: 311, 12840: 305}


def test_el_bonus_id_manda_sobre_todo_lo_demas():
    item = {
        "id": 1,
        "bonus_lists": [42, 12843],
        "item_level": 200,
        "modifiers": [{"type": 9, "value": 250}],
    }
    result = resolve_ilvl(item, BONUS_MAP)
    assert result.value == 311
    assert result.confirmed
    assert result.source == "bonus_id:12843"


def test_usa_item_level_si_no_hay_bonus_conocido():
    item = {"id": 1, "bonus_lists": [99999], "item_level": 307}
    result = resolve_ilvl(item, BONUS_MAP)
    assert result.value == 307
    assert result.source == "item_level"


def test_usa_el_modificador_9_como_ultimo_recurso():
    item = {"id": 1, "modifiers": [{"type": 3, "value": 1}, {"type": 9, "value": 311}]}
    result = resolve_ilvl(item, BONUS_MAP)
    assert result.value == 311
    assert result.source == "modifier:9"


def test_descarta_un_modificador_9_con_valor_implausible():
    """El tipo 9 a veces trae el nivel del personaje, no el ilvl."""
    item = {"id": 1, "modifiers": [{"type": 9, "value": MIN_PLAUSIBLE_ILVL - 1}]}
    result = resolve_ilvl(item, BONUS_MAP)
    assert result.value is None
    assert not result.confirmed


def test_sin_ninguna_pista_devuelve_desconocido():
    result = resolve_ilvl({"id": 1}, BONUS_MAP)
    assert result.value is None
    assert result.source == "desconocido"


def test_tolera_campos_con_formato_raro():
    item = {
        "id": 1,
        "bonus_lists": "esto no es una lista",
        "item_level": None,
        "modifiers": [None, {"type": 9}, "texto"],
    }
    assert resolve_ilvl(item, BONUS_MAP).value is None


def test_ignora_booleanos_que_python_considera_enteros():
    item = {"id": 1, "item_level": True}
    assert resolve_ilvl(item, BONUS_MAP).value is None


def test_mapa_de_bonus_vacio_no_rompe():
    item = {"id": 1, "bonus_lists": [12843]}
    assert resolve_ilvl(item, {}).value is None
