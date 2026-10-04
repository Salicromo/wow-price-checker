"""Anadir un objeto nuevo al texto de config.yaml."""

import pytest
import yaml

from wowalerts.objetos import ObjetoError, anadir_equipo, anadir_patron

CONFIG = """\
region: eu

items:
  - name: "Temple Delver's Mystic Helm"
    max_price_by_ilvl:
      { 295: 9000, 298: 12000, 311: 90000 }

  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl:
      { 295: 6999, 298: 12000,
        311: 90000 }

  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000
    avisar_undercut: false
    repostear: true

  - name: "Wooly White Rhino"
    item_id: 54068
    max_price: 200000
    avisar_undercut: false

orden_personajes:
  - Adannor

bonus_ilvl_map:
  12843: 311
"""

TOPES = {368: 20000, 376: 50000, 382: 150000}

BLOQUE_NUEVO = (
    '  - name: "Venom Rite Mantle"\n'
    "    item_id: 123456\n"
    "    max_price_by_ilvl:\n"
    "      { 368: 20000, 376: 50000, 382: 150000 }\n"
)


def test_el_equipo_nuevo_va_detras_de_la_ultima_pieza_de_equipo():
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, TOPES)

    assert nuevo == CONFIG.replace(
        '  - name: "Pattern: Arcanoweave Cord"',
        BLOQUE_NUEVO + "\n" + '  - name: "Pattern: Arcanoweave Cord"',
    )


def test_el_resto_del_fichero_no_se_toca():
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, TOPES)

    assert nuevo.replace(BLOQUE_NUEVO + "\n", "", 1) == CONFIG


def test_los_escalones_salen_ordenados_y_en_lineas_de_cinco():
    """Como las tablas que ya hay en config.yaml, y se leen igual con YAML."""
    topes = {382: 7, 368: 1, 370: 2, 372: 3, 374: 4, 376: 5, 379: 6}
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 1, topes)

    assert (
        "    max_price_by_ilvl:\n"
        "      { 368: 1, 370: 2, 372: 3, 374: 4, 376: 5,\n"
        "        379: 6, 382: 7 }\n"
    ) in nuevo
    regla = next(
        item for item in yaml.safe_load(nuevo)["items"]
        if item["name"] == "Venom Rite Mantle"
    )
    assert regla["max_price_by_ilvl"] == topes


def test_una_pieza_sin_escalones_se_rechaza():
    with pytest.raises(ObjetoError, match="ilvl"):
        anadir_equipo(CONFIG, "Venom Rite Mantle", 1, {})


def test_el_equipo_no_se_mete_debajo_del_comentario_de_la_seccion_siguiente():
    texto = CONFIG.replace(
        '  - name: "Pattern: Arcanoweave Cord"',
        "  # --- Patrones\n" + '  - name: "Pattern: Arcanoweave Cord"',
    )
    nuevo = anadir_equipo(texto, "Venom Rite Mantle", 123456, TOPES)

    assert ("        311: 90000 }\n\n" + BLOQUE_NUEVO + "\n  # --- Patrones\n") in nuevo


def test_un_comentario_max_price_by_ilvl_en_un_patron_no_lo_cuenta_como_equipo():
    """Un patron puede llevar un comentario que mencione 'max_price_by_ilvl' en
    su bloque, sin ser la clave de verdad: no debe colarse como la ultima
    pieza de equipo y arrastrar el bloque nuevo por debajo suyo."""
    texto = CONFIG.replace(
        '  - name: "Pattern: Arcanoweave Cord"\n',
        '  - name: "Pattern: Arcanoweave Cord"\n'
        "    # sin max_price_by_ilvl: precio unico\n",
    )
    nuevo = anadir_equipo(texto, "Venom Rite Mantle", 123456, TOPES)

    assert nuevo == texto.replace(
        '  - name: "Pattern: Arcanoweave Cord"',
        BLOQUE_NUEVO + "\n" + '  - name: "Pattern: Arcanoweave Cord"',
    )


def test_sin_ninguna_pieza_de_equipo_va_detras_del_ultimo_objeto():
    sin_equipo = (
        "region: eu\n"
        "\n"
        "items:\n"
        '  - name: "Wooly White Rhino"\n'
        "    item_id: 54068\n"
        "    max_price: 200000\n"
        "\n"
        "orden_personajes:\n"
        "  - Adannor\n"
    )
    nuevo = anadir_equipo(sin_equipo, "Venom Rite Mantle", 123456, TOPES)

    assert nuevo == sin_equipo.replace(
        "\norden_personajes:", "\n" + BLOQUE_NUEVO + "\norden_personajes:"
    )


def test_un_nombre_con_comillas_dobles_se_rechaza():
    """topes.py no sabe buscar un nombre con comillas escapadas, asi que nunca
    se podria cambiar su tope despues. Mejor no dejarlo entrar."""
    with pytest.raises(ObjetoError, match="comillas dobles"):
        anadir_equipo(CONFIG, 'Bolt of "Silk"', 1, TOPES)


def test_un_nombre_con_apostrofo_y_dos_puntos_se_lee_bien_con_yaml():
    """Un nombre normal, con los caracteres que dan problemas sin comillas,
    tiene que salir entrecomillado y el YAML resultante tiene que cargarlo tal
    cual se pidio."""
    nuevo = anadir_equipo(CONFIG, "Pattern: Kael'thas's Cord", 1, TOPES)

    datos = yaml.safe_load(nuevo)
    nombres = [item["name"] for item in datos["items"]]
    assert "Pattern: Kael'thas's Cord" in nombres


def test_el_patron_va_detras_del_ultimo_reposteable():
    """Detras del ultimo 'repostear: true', no al final: las monturas van aparte."""
    nuevo = anadir_patron(CONFIG, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo == CONFIG.replace(
        '  - name: "Wooly White Rhino"',
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
        "\n"
        '  - name: "Wooly White Rhino"',
    )


def test_sin_ningun_reposteable_va_detras_del_ultimo_objeto():
    texto = CONFIG.replace("    repostear: true\n", "")
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    esperado = (
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
    )
    # Detras del ultimo objeto, que es la montura, y delante de lo que sigue.
    assert esperado + "\norden_personajes:" in nuevo


def test_el_patron_no_se_mete_debajo_del_comentario_de_las_monturas():
    texto = CONFIG.replace(
        '  - name: "Wooly White Rhino"',
        "  # --- Monturas caras\n"
        '  - name: "Wooly White Rhino"',
    )
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert (
        "    repostear: true\n"
        "\n"
        "  # --- Monturas caras\n"
        '  - name: "Wooly White Rhino"'
    ) in nuevo
    assert nuevo.index("Pattern: Lo Que Sea") < nuevo.index("# --- Monturas caras")


def test_el_patron_se_anade_al_final_cuando_no_hay_nada_detras():
    """El fichero puede acabar en el ultimo objeto, sin linea en blanco.

    Sin reposteables, para que el sitio sea detras de la montura, que es lo
    ultimo del fichero.
    """
    texto = CONFIG.split("orden_personajes:")[0].rstrip() + "\n"
    texto = texto.replace("    repostear: true\n", "")
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo.endswith(
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
    )
    assert nuevo.startswith(texto.rstrip("\n") + "\n\n")


def test_el_patron_se_coloca_bien_si_el_reposteable_anterior_tiene_comentario_en_el_nombre():
    """La linea 'name:' del reposteable lleva un comentario detras. No hay que
    reconstruir el nombre a partir de ahi para volver a buscarlo."""
    texto = CONFIG.replace(
        '  - name: "Pattern: Arcanoweave Cord"',
        '  - name: "Pattern: Arcanoweave Cord"  # nota',
    )
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo == texto.replace(
        '  - name: "Wooly White Rhino"',
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
        "\n"
        '  - name: "Wooly White Rhino"',
    )


def test_repostear_true_con_comentario_detras_cuenta_igual():
    texto = CONFIG.replace(
        "    repostear: true\n",
        "    repostear: true  # nota\n",
    )
    nuevo = anadir_patron(texto, "Pattern: Lo Que Sea", 999, 40000)

    assert nuevo == texto.replace(
        '  - name: "Wooly White Rhino"',
        '  - name: "Pattern: Lo Que Sea"\n'
        "    item_id: 999\n"
        "    max_price: 40000\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
        "\n"
        '  - name: "Wooly White Rhino"',
    )


# --- Ampliar la tabla de una pieza que ya vigilas ----------------------------


def test_ampliar_anade_los_escalones_nuevos_y_ordena_la_tabla():
    from wowalerts.objetos import ampliar_equipo

    nuevo, anadidos, ya_estaban = ampliar_equipo(
        CONFIG, "Greaves of the Noxious Depths", {305: 15000, 328: 500000}
    )

    assert anadidos == {305: 15000, 328: 500000}
    assert ya_estaban == {}
    regla = next(
        r for r in yaml.safe_load(nuevo)["items"]
        if r["name"] == "Greaves of the Noxious Depths"
    )
    assert regla["max_price_by_ilvl"] == {
        295: 6999, 298: 12000, 305: 15000, 311: 90000, 328: 500000,
    }
    assert list(regla["max_price_by_ilvl"]) == sorted(regla["max_price_by_ilvl"])


def test_ampliar_no_toca_los_escalones_que_ya_estaban():
    from wowalerts.objetos import ampliar_equipo

    nuevo, anadidos, ya_estaban = ampliar_equipo(
        CONFIG, "Temple Delver's Mystic Helm", {311: 1, 368: 20000}
    )

    assert anadidos == {368: 20000}
    assert ya_estaban == {311: 90000}
    regla = yaml.safe_load(nuevo)["items"][0]
    assert regla["max_price_by_ilvl"][311] == 90000


def test_ampliar_no_toca_el_resto_del_fichero():
    from wowalerts.objetos import ampliar_equipo

    nuevo, _, _ = ampliar_equipo(CONFIG, "Temple Delver's Mystic Helm", {368: 20000})

    antes = CONFIG.split("\n  - name: \"Greaves")[1]
    despues = nuevo.split("\n  - name: \"Greaves")[1]
    assert antes == despues
    assert nuevo.startswith("region: eu\n\nitems:\n  - name: \"Temple Delver's")


def test_ampliar_una_tabla_escrita_en_la_misma_linea():
    from wowalerts.objetos import ampliar_equipo

    texto = CONFIG.replace(
        "    max_price_by_ilvl:\n      { 295: 9000, 298: 12000, 311: 90000 }",
        "    max_price_by_ilvl: { 295: 9000, 311: 90000 }",
    )

    nuevo, _, _ = ampliar_equipo(texto, "Temple Delver's Mystic Helm", {298: 5})

    regla = yaml.safe_load(nuevo)["items"][0]
    assert regla["max_price_by_ilvl"] == {295: 9000, 298: 5, 311: 90000}


def test_ampliar_sin_nada_nuevo_es_un_error():
    from wowalerts.objetos import ampliar_equipo

    with pytest.raises(ObjetoError, match="Ajustar un tope"):
        ampliar_equipo(CONFIG, "Temple Delver's Mystic Helm", {311: 1})


def test_ampliar_un_patron_es_un_error():
    from wowalerts.objetos import ampliar_equipo

    with pytest.raises(ObjetoError, match="precio unico"):
        ampliar_equipo(CONFIG, "Pattern: Arcanoweave Cord", {311: 1})
