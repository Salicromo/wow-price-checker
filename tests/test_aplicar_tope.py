import pytest

from aplicar_tope import Peticion, parsear, verificar
from wowalerts.topes import TopeError, cambiar_tope

CONFIG = """\
region: eu

items:
  - name: "Temple Delver's Mystic Helm"
    max_price_by_ilvl:
      { 295: 9000, 298: 12000, 311: 90000 }

  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl:
      { 295: 6999, 298: 12000, 311: 90000 }

  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000

bonus_ilvl_map:
  12843: 311
"""

# Lo que GitHub genera desde el formulario de campos de texto, al que apunta el
# enlace del aviso de Discord.
DESDE_AVISO = """\
### Objeto

Temple Delver's Mystic Helm

### ilvl

295

### Tope nuevo, en oro

4000
"""

# Lo que genera el formulario de desplegables, que se abre a mano.
DESDE_DESPLEGABLE = """\
### Objeto

Temple Delver's Mystic Helm

### ilvl

295

### Tope nuevo, en oro

4000
"""

# Lo que construye la app. Mismo contrato, otro emisor.
DESDE_LA_APP = DESDE_AVISO


def test_los_tres_caminos_dan_la_misma_peticion():
    esperada = Peticion("Temple Delver's Mystic Helm", 295, 4000)

    assert parsear(DESDE_AVISO) == esperada
    assert parsear(DESDE_DESPLEGABLE) == esperada
    assert parsear(DESDE_LA_APP) == esperada


def test_la_opcion_del_desplegable_para_precio_unico():
    cuerpo = DESDE_AVISO.replace("\n295\n", "\nsin ilvl (precio unico)\n")
    assert parsear(cuerpo).ilvl is None


def test_la_opcion_con_tilde_tambien():
    """El desplegable lo escribe un humano en el YAML; la tilde no debe romperlo."""
    cuerpo = DESDE_AVISO.replace("\n295\n", "\nsin ilvl (precio único)\n")
    assert parsear(cuerpo).ilvl is None


def test_el_campo_vacio_del_formulario_de_texto():
    """GitHub escribe '_No response_' cuando dejas en blanco un campo opcional."""
    cuerpo = DESDE_AVISO.replace("\n295\n", "\n_No response_\n")
    assert parsear(cuerpo).ilvl is None


def test_falta_un_campo():
    cuerpo = DESDE_AVISO.split("### Tope nuevo")[0]
    with pytest.raises(TopeError, match="Tope nuevo"):
        parsear(cuerpo)


def test_el_tope_no_es_un_numero():
    cuerpo = DESDE_AVISO.replace("\n4000\n", "\ncuatro mil\n")
    with pytest.raises(TopeError, match="numero"):
        parsear(cuerpo)


def test_el_tope_admite_separadores_de_miles():
    """Escribir '4.000' en el movil es lo natural, y no deberia fallar."""
    assert parsear(DESDE_AVISO.replace("\n4000\n", "\n4.000\n")).tope == 4000
    assert parsear(DESDE_AVISO.replace("\n4000\n", "\n4,000\n")).tope == 4000
    assert parsear(DESDE_AVISO.replace("\n4000\n", "\n 4000 g \n")).tope == 4000


def test_el_ilvl_no_es_un_numero():
    cuerpo = DESDE_AVISO.replace("\n295\n", "\ndoscientos\n")
    with pytest.raises(TopeError, match="ilvl"):
        parsear(cuerpo)


def test_verificar_acepta_un_cambio_limpio():
    peticion = Peticion("Temple Delver's Mystic Helm", 295, 4000)
    nuevo, _ = cambiar_tope(CONFIG, peticion.objeto, peticion.ilvl, peticion.tope)

    verificar(CONFIG, nuevo, peticion)


def test_verificar_caza_un_cambio_que_toca_de_mas():
    """La red de seguridad: si la edicion mueve otro tope, no se commitea."""
    peticion = Peticion("Temple Delver's Mystic Helm", 295, 4000)
    # Un reemplazo ingenuo por valor, que es justo lo que no hace topes.py:
    # cambia el 295 de los dos objetos, no solo el pedido.
    corrupto = CONFIG.replace("295: 9000", "295: 4000").replace("295: 6999", "295: 4000")

    with pytest.raises(TopeError, match="otro tope"):
        verificar(CONFIG, corrupto, peticion)


def test_verificar_caza_un_yaml_roto():
    peticion = Peticion("Temple Delver's Mystic Helm", 295, 4000)
    roto = CONFIG.replace("{ 295: 9000, 298: 12000, 311: 90000 }", "{ 295: 4000,")

    with pytest.raises(TopeError):
        verificar(CONFIG, roto, peticion)


def test_verificar_caza_un_tope_que_no_quedo_puesto():
    peticion = Peticion("Temple Delver's Mystic Helm", 295, 4000)

    with pytest.raises(TopeError, match="no ha quedado"):
        verificar(CONFIG, CONFIG, peticion)


def test_verificar_precio_unico():
    peticion = Peticion("Pattern: Arcanoweave Cord", None, 45000)
    nuevo, _ = cambiar_tope(CONFIG, peticion.objeto, peticion.ilvl, peticion.tope)

    verificar(CONFIG, nuevo, peticion)


def test_el_comentario_de_exito(tmp_path, capsys, monkeypatch):
    import aplicar_tope

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(DESDE_AVISO))

    assert aplicar_tope.main(["--config", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "Tope actualizado" in salida
    # Separador de miles a la espanola, y solo en los numeros.
    assert "9.000 → 4.000 de oro" in salida
    assert "Temple Delver's Mystic Helm · ilvl 295" in salida
    # Y el fichero ha quedado escrito de verdad.
    assert "{ 295: 4000," in ruta.read_text(encoding="utf-8")


def test_un_nombre_con_coma_no_se_estropea(tmp_path, capsys, monkeypatch):
    import aplicar_tope

    texto = CONFIG.replace(
        '"Pattern: Arcanoweave Cord"', '"Bolt of Silk, Fine"'
    )
    ruta = tmp_path / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    cuerpo = DESDE_AVISO.replace(
        "Temple Delver's Mystic Helm", "Bolt of Silk, Fine"
    ).replace("\n295\n", "\n_No response_\n")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(cuerpo))

    assert aplicar_tope.main(["--config", str(ruta)]) == 0
    assert "Bolt of Silk, Fine" in capsys.readouterr().out


def test_un_fallo_no_escribe_nada_y_sale_con_error(tmp_path, capsys, monkeypatch):
    import aplicar_tope

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    cuerpo = DESDE_AVISO.replace("Temple Delver's Mystic Helm", "Molten Helm")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(cuerpo))

    assert aplicar_tope.main(["--config", str(ruta)]) == 1

    assert "No he cambiado nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


# Lo que manda la app cuando envias la cesta: varios topes en una sola issue.
VARIOS = """\
### Cambios

Temple Delver's Mystic Helm | 295 | 4000
Greaves of the Noxious Depths | 311 | 95.000
Pattern: Arcanoweave Cord | sin ilvl (precio unico) | 45000
"""


def test_parsear_varios():
    from aplicar_tope import parsear_varios

    assert parsear_varios(VARIOS) == [
        Peticion("Temple Delver's Mystic Helm", 295, 4000),
        Peticion("Greaves of the Noxious Depths", 311, 95000),
        Peticion("Pattern: Arcanoweave Cord", None, 45000),
    ]


def test_parsear_varios_con_un_solo_cambio_del_formulario():
    from aplicar_tope import parsear_varios

    assert parsear_varios(DESDE_AVISO) == [Peticion("Temple Delver's Mystic Helm", 295, 4000)]


def test_varios_con_una_linea_mal_escrita():
    from aplicar_tope import parsear_varios

    with pytest.raises(TopeError, match="linea"):
        parsear_varios(VARIOS + "Molten Helm 295 4000\n")


def test_varios_con_el_mismo_tope_repetido():
    from aplicar_tope import parsear_varios

    with pytest.raises(TopeError, match="dos veces"):
        parsear_varios(VARIOS + "Temple Delver's Mystic Helm | 295 | 5000\n")


def test_varios_se_aplican_todos_en_un_commit(tmp_path, capsys, monkeypatch):
    import aplicar_tope

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(VARIOS))

    assert aplicar_tope.main(["--config", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "3 topes actualizados" in salida
    assert "Greaves of the Noxious Depths · ilvl 311" in salida
    texto = ruta.read_text(encoding="utf-8")
    assert "{ 295: 4000, 298: 12000, 311: 90000 }" in texto
    assert "{ 295: 6999, 298: 12000, 311: 95000 }" in texto
    assert "max_price: 45000" in texto


def test_varios_si_uno_falla_no_se_aplica_ninguno(tmp_path, capsys, monkeypatch):
    import aplicar_tope

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    cuerpo = VARIOS + "Molten Helm | 295 | 4000\n"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(cuerpo))

    assert aplicar_tope.main(["--config", str(ruta)]) == 1

    salida = capsys.readouterr().out
    assert "No he cambiado nada" in salida
    assert "Molten Helm" in salida
    assert ruta.read_text(encoding="utf-8") == CONFIG
