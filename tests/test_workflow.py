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


def test_sin_poder_leer_el_privado_no_se_intenta_subir_a_el():
    """Si el token no vale para leer, tampoco para escribir: el aviso por
    Discord ya lo cuenta y la subida solo dejaria la pasada en rojo."""
    assert paso("Traer lo privado")["id"] == "privado"
    condicion = paso("Subir los datos de la app")["if"]
    assert "steps.privado.outputs.fallo != '1'" in condicion


def test_el_aviso_de_privado_va_antes_de_los_chollos_y_con_la_memoria():
    """Necesita .state para avisar una sola vez por racha, y tiene que llegar
    antes que los chollos que salen con el reino en vez del personaje."""
    flujo = yaml.safe_load(MONITOR.read_text(encoding="utf-8"))
    nombres = [p.get("name") for p in flujo["jobs"]["check-prices"]["steps"]]
    aviso = nombres.index("Avisar si no llega lo privado")
    assert nombres.index("Recuperar memoria de avisos anteriores") < aviso
    assert aviso < nombres.index("Buscar chollos")
    assert "steps.privado.outputs.fallo" in paso("Avisar si no llega lo privado")["env"]["FALLO"]


def test_el_token_del_privado_no_va_en_la_url():
    """Con el token en la URL, git lo pierde al seguir una redireccion de
    GitHub y se queda pidiendo usuario: desde el 2026-10-19 fallaba asi una
    pasada de cada tres."""
    for nombre in ("Traer lo privado", "Subir los datos de la app"):
        assert "${token}@" not in paso(nombre)["run"]
    assert "credential.helper" in paso("Traer lo privado")["run"]
