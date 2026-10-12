"""Lo que el workflow de Actions tiene que respetar y ningun otro test ve."""

from pathlib import Path

import yaml

MONITOR = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "monitor.yml"


def paso(nombre):
    flujo = yaml.safe_load(MONITOR.read_text(encoding="utf-8"))
    for trabajo in flujo["jobs"].values():
        for p in trabajo["steps"]:
            if p.get("name") == nombre:
                return p
    raise AssertionError(f"no hay ningun paso llamado {nombre!r}")


def test_sin_catalogo_no_se_suben_los_datos_de_la_app():
    """La subida rehace la rama 'datos' con lo que haya en publicar/. Si
    datos_app.py falla, en publicar/ solo queda adelantadas.json, y subirlo
    borraria de la rama todo lo que lee la app del movil."""
    condicion = paso("Subir los datos de la app")["if"]
    assert "hashFiles('publicar/catalogo.json')" in condicion
