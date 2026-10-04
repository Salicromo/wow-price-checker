"""Anadir un objeto vigilado desde una issue."""

from pathlib import Path

import pytest
import yaml

from anadir_objeto import (
    CAMPO_OBJETO,
    CAMPO_TIPO,
    CAMPO_TOPE,
    CAMPO_TOPES_ILVL,
    EQUIPO,
    PATRON,
    Peticion,
    comprobar_nuevo,
    id_de,
    parsear,
    resolver,
    verificar,
)
from wowalerts.blizzard import BlizzardAuthError
from wowalerts.config import ItemRule, load_config
from wowalerts.objetos import ObjetoError

RAIZ = Path(__file__).resolve().parent.parent

# Lo que genera el formulario de GitHub, y lo que copia la app.
EQUIPO_NUEVO = """\
### Objeto

https://www.wowhead.com/es/item=123456/venom-rite-mantle

### Tipo

Equipo (tabla por ilvl)

### Topes por ilvl

368: 20000
376: 50000
382: 150000

### Tope, en oro

_No response_
"""

PATRON_NUEVO = """\
### Objeto

Pattern: Lo Que Sea

### Tipo

Patrón o receta (precio unico)

### Topes por ilvl

_No response_

### Tope, en oro

40000
"""


def test_una_pieza_de_equipo():
    assert parsear(EQUIPO_NUEVO) == Peticion(
        objeto="https://www.wowhead.com/es/item=123456/venom-rite-mantle",
        tipo=EQUIPO,
        topes_ilvl={368: 20000, 376: 50000, 382: 150000},
        tope=None,
    )


def test_un_patron():
    assert parsear(PATRON_NUEVO) == Peticion(
        objeto="Pattern: Lo Que Sea",
        tipo=PATRON,
        topes_ilvl=None,
        tope=40000,
    )


def test_el_tipo_se_reconoce_con_y_sin_tilde():
    """El desplegable lo escribe un humano en el YAML; la tilde no debe romperlo."""
    sin_tilde = PATRON_NUEVO.replace("Patrón", "Patron")
    assert parsear(sin_tilde).tipo == PATRON


def test_el_tope_admite_separadores_de_miles():
    assert parsear(PATRON_NUEVO.replace("\n40000\n", "\n40.000 g\n")).tope == 40000


def test_una_pieza_de_equipo_sin_topes():
    cuerpo = EQUIPO_NUEVO.replace("368: 20000\n376: 50000\n382: 150000", "_No response_")
    with pytest.raises(ObjetoError, match="Topes por ilvl"):
        parsear(cuerpo)


def test_un_patron_sin_precio():
    cuerpo = PATRON_NUEVO.replace("\n40000\n", "\n_No response_\n")
    with pytest.raises(ObjetoError, match="Tope, en oro"):
        parsear(cuerpo)


def test_un_tipo_que_no_es_ninguno_de_los_dos():
    cuerpo = PATRON_NUEVO.replace("Patrón o receta (precio unico)", "Mascota")
    with pytest.raises(ObjetoError, match="tipo"):
        parsear(cuerpo)


def test_falta_un_campo():
    with pytest.raises(ObjetoError, match="Tipo"):
        parsear(EQUIPO_NUEVO.split("### Tipo")[0])


def test_el_id_sale_del_enlace_de_wowhead():
    assert id_de("https://www.wowhead.com/item=258126") == 258126
    assert id_de("https://www.wowhead.com/es/item=258126/patron-lo-que-sea") == 258126


def test_el_id_sale_de_un_numero_suelto():
    assert id_de(" 258126 ") == 258126


def test_un_nombre_no_lleva_id_dentro():
    assert id_de("Pattern: Arcanoweave Cord") is None


def test_un_digito_no_ascii_no_cuela():
    """'²'.isdigit() da True, pero int('²') no funciona: no es un id valido."""
    assert id_de("²") is None


def test_el_id_sale_de_un_enlace_con_query_string():
    assert id_de("https://www.wowhead.com/?item=258126") == 258126


def test_el_cuerpo_admite_saltos_de_linea_crlf():
    assert parsear(EQUIPO_NUEVO.replace("\n", "\r\n")) == parsear(EQUIPO_NUEVO)


class ClienteFalso:
    """Blizzard sin red: lo que sabe esta en los dos diccionarios."""

    # Un token cualquiera: basta con que acceder a el no explote.
    token = "token-de-prueba"

    def __init__(self, por_id=None, por_nombre=None):
        self.por_id = por_id or {}
        self.por_nombre = por_nombre or {}

    def item_name(self, item_id):
        return self.por_id.get(item_id)

    def search_item_id(self, nombre):
        return self.por_nombre.get(nombre)


class ClienteFalsoSinCredenciales:
    """Simula que Blizzard rechaza las credenciales al pedir el token."""

    @property
    def token(self):
        raise BlizzardAuthError("Blizzard rechaza las credenciales.")


def test_un_enlace_se_resuelve_por_id():
    cliente = ClienteFalso(por_id={123456: "Venom Rite Mantle"})

    assert resolver(cliente, parsear(EQUIPO_NUEVO)) == ("Venom Rite Mantle", 123456)


def test_un_nombre_se_resuelve_por_busqueda():
    cliente = ClienteFalso(por_nombre={"Pattern: Lo Que Sea": 999})

    assert resolver(cliente, parsear(PATRON_NUEVO)) == ("Pattern: Lo Que Sea", 999)


def test_el_nombre_resuelto_es_el_canonico_de_blizzard():
    """Buscado por nombre, se guarda el nombre exacto que devuelve Blizzard."""
    cliente = ClienteFalso(
        por_nombre={"pattern: lo que sea": 999},
        por_id={999: "Pattern: Lo Que Sea"},
    )
    peticion = Peticion(
        objeto="pattern: lo que sea", tipo=PATRON, topes_ilvl=None, tope=40000
    )

    assert resolver(cliente, peticion) == ("Pattern: Lo Que Sea", 999)


def test_un_id_que_blizzard_no_conoce():
    with pytest.raises(ObjetoError, match="123456"):
        resolver(ClienteFalso(), parsear(EQUIPO_NUEVO))


def test_un_nombre_que_blizzard_no_encuentra():
    with pytest.raises(ObjetoError, match="ingles"):
        resolver(ClienteFalso(), parsear(PATRON_NUEVO))


def test_un_objeto_ya_vigilado_por_nombre():
    config = _config_con(ItemRule(name="Venom Rite Mantle", max_price=100))

    with pytest.raises(ObjetoError, match="ya esta vigilado"):
        comprobar_nuevo(config, "Venom Rite Mantle", 123456)


def test_un_objeto_ya_vigilado_por_id():
    config = _config_con(ItemRule(name="Otro nombre", max_price=100, item_id=123456))

    with pytest.raises(ObjetoError, match="ya esta vigilado"):
        comprobar_nuevo(config, "Venom Rite Mantle", 123456)


def test_un_objeto_ya_vigilado_con_otras_mayusculas():
    config = _config_con(ItemRule(name="venom rite mantle", max_price=100))

    with pytest.raises(ObjetoError, match="ya esta vigilado"):
        comprobar_nuevo(config, "Venom Rite Mantle", 999)


def _config_con(*reglas):
    from wowalerts.config import Config, Settings

    return Config(region="eu", items=reglas, bonus_ilvl_map={}, settings=Settings())


CONFIG = """\
region: eu

items:
  - name: "Temple Delver's Mystic Helm"
    max_price_by_ilvl:
      { 295: 9000, 298: 12000, 311: 90000 }

  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000
    avisar_undercut: false
    repostear: true

bonus_ilvl_map:
  12843: 311
"""


def test_verificar_acepta_una_pieza_con_su_tabla():
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.topes_ilvl)

    regla = verificar(CONFIG, nuevo, "Venom Rite Mantle", 123456, peticion)

    assert dict(regla.max_price_by_ilvl) == {368: 20000, 376: 50000, 382: 150000}


def test_verificar_caza_una_edicion_que_toca_otro_objeto():
    """La red de seguridad: si se ha movido algo mas, no se commitea."""
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.topes_ilvl)
    corrupto = nuevo.replace("max_price: 60000", "max_price: 1")

    with pytest.raises(ObjetoError, match="otros objetos"):
        verificar(CONFIG, corrupto, "Venom Rite Mantle", 123456, peticion)


def test_verificar_caza_una_edicion_que_anade_otro_objeto_mas():
    """La red de seguridad: si se ha colado un objeto extra, no se commitea."""
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.topes_ilvl)
    corrupto = nuevo.replace(
        "bonus_ilvl_map:",
        '  - name: "Extra Objeto"\n    max_price: 10\n\nbonus_ilvl_map:',
    )

    with pytest.raises(ObjetoError, match="anadido"):
        verificar(CONFIG, corrupto, "Venom Rite Mantle", 123456, peticion)


def test_verificar_caza_un_yaml_roto():
    peticion = parsear(EQUIPO_NUEVO)
    roto = CONFIG + '  - name: "Venom Rite Mantle"\n    max_price_by_ilvl:\n      { 295:\n'

    with pytest.raises(ObjetoError, match="no es valido"):
        verificar(CONFIG, roto, "Venom Rite Mantle", 123456, peticion)


def test_el_comentario_de_exito(tmp_path, capsys, monkeypatch):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalso(por_id={123456: "Venom Rite Mantle"}),
    )

    assert anadir_objeto.main(["--config", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "Objeto anadido" in salida
    assert "Venom Rite Mantle" in salida
    assert "id 123456" in salida
    # Separador de miles a la espanola.
    assert "ilvl 382: 150.000" in salida
    assert '"Venom Rite Mantle"' in ruta.read_text(encoding="utf-8")


def test_un_fallo_no_escribe_nada_y_sale_con_error(tmp_path, capsys, monkeypatch):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(anadir_objeto, "BlizzardClient", lambda **kw: ClienteFalso())

    assert anadir_objeto.main(["--config", str(ruta)]) == 1

    assert "No he anadido nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


def test_credenciales_invalidas_no_se_confunden_con_un_id_desconocido(
    tmp_path, capsys, monkeypatch
):
    """Si Blizzard rechaza las credenciales, que se note y no que "no conoce el id"."""
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalsoSinCredenciales(),
    )

    assert anadir_objeto.main(["--config", str(ruta)]) == 1

    assert "No he anadido nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


def _explota(*args, **kwargs):
    raise RuntimeError("boom")


def test_un_fallo_inesperado_tampoco_se_queda_sin_comentario(
    tmp_path, capsys, monkeypatch
):
    """El workflow publica el stdout como comentario: uno vacio no sirve."""
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(EQUIPO_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalso(por_id={123456: "Venom Rite Mantle"}),
    )
    monkeypatch.setattr(anadir_objeto, "resolver", _explota)

    assert anadir_objeto.main(["--config", str(ruta)]) == 1

    assert "No he anadido nada" in capsys.readouterr().out
    assert ruta.read_text(encoding="utf-8") == CONFIG


def test_un_patron_sale_con_sus_banderas(tmp_path, capsys, monkeypatch):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PATRON_NUEVO))
    monkeypatch.setattr(
        anadir_objeto, "BlizzardClient",
        lambda **kw: ClienteFalso(por_nombre={"Pattern: Lo Que Sea": 999}),
    )

    assert anadir_objeto.main(["--config", str(ruta)]) == 0

    escrito = load_config(ruta)
    regla = next(r for r in escrito.items if r.name == "Pattern: Lo Que Sea")
    assert regla.max_price == 40000
    assert regla.avisar_undercut is False
    assert regla.se_repostea is True


def test_la_plantilla_lleva_las_mismas_etiquetas():
    """Las etiquetas son el contrato: el parser busca por ellas."""
    plantilla = yaml.safe_load(
        (RAIZ / ".github/ISSUE_TEMPLATE/objeto.yml").read_text(encoding="utf-8")
    )
    etiquetas = {
        campo["attributes"]["label"]
        for campo in plantilla["body"]
        if campo["type"] != "markdown"
    }

    assert etiquetas == {CAMPO_OBJETO, CAMPO_TIPO, CAMPO_TOPES_ILVL, CAMPO_TOPE}
    # El prefijo del titulo es lo que mira objeto.yml para reconocer la issue.
    assert plantilla["title"].startswith("Objeto:")


def test_el_parser_entiende_las_opciones_del_desplegable():
    """Las opciones las escribe un humano en el YAML; el parser tiene que leerlas."""
    plantilla = yaml.safe_load(
        (RAIZ / ".github/ISSUE_TEMPLATE/objeto.yml").read_text(encoding="utf-8")
    )
    tipos = next(
        campo for campo in plantilla["body"]
        if campo.get("attributes", {}).get("label") == CAMPO_TIPO
    )["attributes"]["options"]

    # Se usa el cuerpo de equipo, que trae rellenos los dos campos que pueden
    # hacer falta, y se le cambia solo el tipo.
    completo = EQUIPO_NUEVO.replace(
        "### Tope, en oro\n\n_No response_", "### Tope, en oro\n\n40000"
    )
    leidos = {
        parsear(completo.replace("Equipo (tabla por ilvl)", opcion)).tipo
        for opcion in tipos
    }

    assert leidos == {EQUIPO, PATRON}


def _con_tabla(tabla):
    """EQUIPO_NUEVO con otro contenido en 'Topes por ilvl'."""
    return EQUIPO_NUEVO.replace(
        "368: 20000\n376: 50000\n382: 150000", tabla
    )


def test_la_tabla_admite_como_se_escribe_en_un_movil():
    tabla = "\n368 = 20.000 g\n\n  376:50,000\n382: 150000\n"
    assert parsear(_con_tabla(tabla)).topes_ilvl == {
        368: 20000, 376: 50000, 382: 150000,
    }


def test_la_tabla_con_saltos_de_linea_crlf():
    cuerpo = EQUIPO_NUEVO.replace("\n", "\r\n")
    assert parsear(cuerpo).topes_ilvl == {368: 20000, 376: 50000, 382: 150000}


def test_una_linea_de_la_tabla_que_no_se_entiende():
    with pytest.raises(ObjetoError, match="368 veinte mil"):
        parsear(_con_tabla("368 veinte mil"))


def test_un_ilvl_repetido():
    with pytest.raises(ObjetoError, match="368"):
        parsear(_con_tabla("368: 20000\n368: 30000"))


def test_un_tope_a_cero():
    with pytest.raises(ObjetoError, match="mayores que cero"):
        parsear(_con_tabla("368: 0"))


def test_verificar_caza_una_tabla_distinta_de_la_pedida():
    from wowalerts.objetos import anadir_equipo

    peticion = parsear(EQUIPO_NUEVO)
    nuevo = anadir_equipo(CONFIG, "Venom Rite Mantle", 123456, peticion.topes_ilvl)
    corrupto = nuevo.replace("382: 150000", "382: 1")

    with pytest.raises(ObjetoError, match="topes"):
        verificar(CONFIG, corrupto, "Venom Rite Mantle", 123456, peticion)


def test_un_punto_decimal_no_se_confunde_con_un_millar():
    """'20.5' no son veinte mil quinientos: el punto no separa tres cifras."""
    with pytest.raises(ObjetoError, match="20.5"):
        parsear(_con_tabla("368: 20.5"))


def test_una_coma_decimal_tampoco_se_confunde_con_un_millar():
    cuerpo = PATRON_NUEVO.replace("\n40000\n", "\n40,5\n")
    with pytest.raises(ObjetoError, match="40,5"):
        parsear(cuerpo)


def test_un_tope_con_varios_puntos_de_millar_se_admite():
    assert parsear(PATRON_NUEVO.replace("\n40000\n", "\n1.500.000\n")).tope == 1500000


def test_la_tabla_admite_una_vineta_de_guion():
    assert parsear(_con_tabla("- 368: 20000")).topes_ilvl == {368: 20000}


def test_la_tabla_admite_una_vineta_de_asterisco():
    assert parsear(_con_tabla("* 368: 20000")).topes_ilvl == {368: 20000}


def test_la_tabla_admite_una_vineta_de_punto():
    assert parsear(_con_tabla("• 368: 20000")).topes_ilvl == {368: 20000}


def test_un_ilvl_no_creible_se_rechaza():
    """El ilvl y el tope al reves ('20000: 368') no debe colarse como valido."""
    with pytest.raises(ObjetoError, match="20000"):
        parsear(_con_tabla("20000: 368"))


def test_un_escalon_sin_tope_se_rechaza():
    with pytest.raises(ObjetoError):
        parsear(_con_tabla("368:"))


def test_un_escalon_con_tope_en_blanco_se_rechaza():
    with pytest.raises(ObjetoError):
        parsear(_con_tabla("368: "))


def test_un_ilvl_a_cero_se_rechaza():
    with pytest.raises(ObjetoError, match="mayores que cero"):
        parsear(_con_tabla("0: 20000"))


# --- Un objeto que ya vigilas: se amplia su tabla -----------------------------

AMPLIAR_CASCO = """\
### Objeto

https://www.wowhead.com/item=777/temple-delvers-mystic-helm

### Tipo

Equipo (tabla por ilvl)

### Topes por ilvl

311: 1
368: 20000

### Tope, en oro

_No response_
"""


def _main_con(tmp_path, monkeypatch, cuerpo, cliente):
    import anadir_objeto

    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(cuerpo))
    monkeypatch.setattr(anadir_objeto, "BlizzardClient", lambda **kw: cliente)
    return anadir_objeto.main(["--config", str(ruta)]), ruta


def test_una_pieza_ya_vigilada_amplia_su_tabla(tmp_path, capsys, monkeypatch):
    codigo, ruta = _main_con(
        tmp_path, monkeypatch, AMPLIAR_CASCO,
        ClienteFalso(por_id={777: "Temple Delver's Mystic Helm"}),
    )

    assert codigo == 0
    regla = next(
        r for r in load_config(ruta).items if r.name == "Temple Delver's Mystic Helm"
    )
    # El 311 ya estaba y conserva su tope; el 368 es nuevo.
    assert dict(regla.max_price_by_ilvl) == {
        295: 9000, 298: 12000, 311: 90000, 368: 20000,
    }
    salida = capsys.readouterr().out
    assert "ilvl 368: 20.000" in salida
    assert "311" in salida and "Ajustar un tope" in salida


def test_ampliar_sin_ilvl_nuevos_no_escribe_nada(tmp_path, capsys, monkeypatch):
    cuerpo = AMPLIAR_CASCO.replace("311: 1\n368: 20000", "311: 1")
    codigo, ruta = _main_con(
        tmp_path, monkeypatch, cuerpo,
        ClienteFalso(por_id={777: "Temple Delver's Mystic Helm"}),
    )

    assert codigo == 1
    assert ruta.read_text(encoding="utf-8") == CONFIG
    assert "Ajustar un tope" in capsys.readouterr().out


def test_un_patron_ya_vigilado_sigue_siendo_un_error(tmp_path, capsys, monkeypatch):
    codigo, ruta = _main_con(
        tmp_path, monkeypatch, PATRON_NUEVO,
        ClienteFalso(por_nombre={"Pattern: Lo Que Sea": 258126},
                     por_id={258126: "Pattern: Arcanoweave Cord"}),
    )

    assert codigo == 1
    assert ruta.read_text(encoding="utf-8") == CONFIG
    assert "ya esta vigilado" in capsys.readouterr().out
