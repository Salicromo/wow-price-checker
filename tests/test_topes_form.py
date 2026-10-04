from pathlib import Path

import yaml

import topes_form
from aplicar_tope import CAMPO_ILVL, CAMPO_OBJETO, CAMPO_TOPE, parsear
from wowalerts.config import load_config

RAIZ = Path(__file__).resolve().parent.parent


def test_la_plantilla_en_disco_esta_al_dia():
    """El guardian: si anades un objeto y olvidas regenerar, salta aqui.

    Las opciones de un desplegable de GitHub son estaticas, asi que sin esto se
    quedarian atras en silencio y lo descubririas con el formulario delante.
    """
    assert topes_form.main(["--check", "--config", str(RAIZ / "config.yaml"),
                            "--destino", str(RAIZ / topes_form.DESTINO)]) == 0


def test_lista_todos_los_objetos_vigilados():
    config = load_config(RAIZ / "config.yaml")
    plantilla = yaml.safe_load(topes_form.construir(config))

    opciones = _campo(plantilla, "objeto")["attributes"]["options"]
    assert sorted(r.name for r in config.items) == opciones


def test_lista_los_ilvl_de_las_tablas_mas_la_opcion_de_precio_unico():
    config = load_config(RAIZ / "config.yaml")
    plantilla = yaml.safe_load(topes_form.construir(config))

    opciones = _campo(plantilla, "ilvl")["attributes"]["options"]
    esperados = sorted({i for r in config.items for i in r.max_price_by_ilvl})

    assert opciones[:-1] == [str(i) for i in esperados]
    assert opciones[-1] == topes_form.SIN_ILVL


def test_las_etiquetas_son_las_que_espera_el_parser():
    """El contrato entre la plantilla y aplicar_tope.py.

    GitHub titula cada bloque del cuerpo con la ETIQUETA del campo, no con su
    id, asi que si una etiqueta se mueve el parser deja de encontrarla.
    """
    config = load_config(RAIZ / "config.yaml")
    plantilla = yaml.safe_load(topes_form.construir(config))

    etiquetas = {
        c["attributes"]["label"] for c in plantilla["body"] if c["type"] != "markdown"
    }
    assert etiquetas == {CAMPO_OBJETO, CAMPO_ILVL, CAMPO_TOPE}


def test_la_plantilla_de_texto_usa_las_mismas_etiquetas():
    """La otra plantilla, la que prerrellena el aviso, comparte el contrato."""
    ruta = RAIZ / ".github/ISSUE_TEMPLATE/tope-aviso.yml"
    plantilla = yaml.safe_load(ruta.read_text(encoding="utf-8"))

    etiquetas = {
        c["attributes"]["label"] for c in plantilla["body"] if c["type"] != "markdown"
    }
    assert etiquetas == {CAMPO_OBJETO, CAMPO_ILVL, CAMPO_TOPE}

    # Y sus id son los que lleva la URL del aviso: sin esto no se prerrellenan.
    ids = {c.get("id") for c in plantilla["body"] if c["type"] != "markdown"}
    assert {"objeto", "ilvl", "tope"} == ids

    # Los campos de texto son los unicos que GitHub sabe prerrellenar.
    tipos = {c["type"] for c in plantilla["body"] if c["type"] != "markdown"}
    assert tipos == {"input"}


def test_las_dos_plantillas_etiquetan_igual_la_issue():
    """El workflow filtra por esa etiqueta: si falta, no se aplica nada."""
    for nombre in ("tope.yml", "tope-aviso.yml"):
        ruta = RAIZ / ".github/ISSUE_TEMPLATE" / nombre
        plantilla = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        assert plantilla["labels"] == ["tope"], nombre


def test_un_cuerpo_con_las_opciones_generadas_se_parsea():
    """De punta a punta: lo que ofrece el desplegable, el parser lo entiende."""
    config = load_config(RAIZ / "config.yaml")
    plantilla = yaml.safe_load(topes_form.construir(config))

    objeto = _campo(plantilla, "objeto")["attributes"]["options"][0]
    ilvl = _campo(plantilla, "ilvl")["attributes"]["options"][0]

    cuerpo = (
        f"### {CAMPO_OBJETO}\n\n{objeto}\n\n"
        f"### {CAMPO_ILVL}\n\n{ilvl}\n\n"
        f"### {CAMPO_TOPE}\n\n4000\n"
    )
    peticion = parsear(cuerpo)
    assert peticion.objeto == objeto
    assert peticion.ilvl == int(ilvl)
    assert peticion.tope == 4000


def _campo(plantilla, id_campo):
    return next(c for c in plantilla["body"] if c.get("id") == id_campo)


def test_las_plantillas_ponen_el_prefijo_de_titulo_que_espera_el_workflow():
    """El disparo del workflow depende de este prefijo.

    GitHub no aplica una etiqueta de plantilla que no exista ya en el
    repositorio, asi que .github/workflows/tope.yml mira tambien el titulo. Si
    el prefijo se mueve aqui y alli no, deja de dispararse en silencio.
    """
    workflow = (RAIZ / ".github/workflows/tope.yml").read_text(encoding="utf-8")
    assert "startsWith(github.event.issue.title, 'Tope:')" in workflow

    for nombre in ("tope.yml", "tope-aviso.yml"):
        plantilla = yaml.safe_load(
            (RAIZ / ".github/ISSUE_TEMPLATE" / nombre).read_text(encoding="utf-8")
        )
        assert plantilla["title"].startswith("Tope:"), nombre
