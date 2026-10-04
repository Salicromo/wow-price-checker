"""El interruptor de avisos de la app, visto desde este lado.

La app es Kotlin y no corre en estos tests, pero dos cosas suyas se pueden
comprobar aqui y son justo las que fallaron en silencio: de que repositorio
lee el estado, y si su patron reconoce el config.yaml de verdad.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APP = RAIZ / "android/app/src/main/java/com/burixer/cobertura"
REPOSITORIO = APP / "Repositorio.kt"
AVISOS = APP / "Avisos.kt"

# La linea de Repositorio.kt que baja config.yaml para saber si estan pausados.
LECTURA = re.compile(r"leer\((?P<repo>\w+),\s*\"config\.yaml\"")


def fuente(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_el_estado_se_lee_del_repositorio_del_codigo():
    """El bug real: config.yaml se leia del repositorio privado.

    Al repartir los repos, `repo` paso a ser el privado dentro de actualizar(),
    y esta lectura se quedo colgando de ese nombre. Alli config.yaml no existe,
    asi que daba 404: la app se quedaba sin saber como estaban los avisos y el
    interruptor solo ofrecia pausarlos, sin forma de reanudarlos.
    """
    texto = fuente(REPOSITORIO)
    lectura = LECTURA.search(texto)
    assert lectura, "nadie lee config.yaml en Repositorio.kt"

    variable = lectura.group("repo")
    assert re.search(
        rf"^\s*val {variable} = repo\(context\)$", texto, re.MULTILINE
    ), f"config.yaml se lee de {variable!r}, que no es el repositorio del codigo"


def test_no_se_traga_el_fallo_al_leer_el_estado():
    """Sin esto el 404 no se notaba: ni en pantalla ni en ningun sitio."""
    texto = fuente(REPOSITORIO)
    despues = texto[LECTURA.search(texto).end() :]
    # Dentro de la misma cadena de runCatching, antes de la llamada siguiente.
    assert "onFailure" in despues.split("runCatching")[0]


def test_el_patron_de_la_app_reconoce_el_config_de_verdad():
    """El patron vive en Kotlin; se saca de ahi y se prueba contra config.yaml.

    Copiarlo aqui no valdria: probaria la copia, no lo que corre en el movil.
    """
    crudo = re.search(
        r'LINEA = Regex\("""(?P<patron>.+?)"""\)', fuente(AVISOS)
    )
    assert crudo, "no encuentro el patron de Avisos.kt"

    patron = re.compile(crudo.group("patron").replace("(?m)", ""), re.MULTILINE)
    config = fuente(RAIZ / "config.yaml")

    encontrado = patron.search(config)
    assert encontrado, "el patron de la app no ve avisos_pausados en config.yaml"
    assert encontrado.group(1) in ("true", "false")


@pytest.mark.parametrize("valor", ["true", "false"])
def test_el_patron_lee_los_dos_valores(valor):
    crudo = re.search(r'LINEA = Regex\("""(?P<patron>.+?)"""\)', fuente(AVISOS))
    patron = re.compile(crudo.group("patron").replace("(?m)", ""), re.MULTILINE)

    texto = f"settings:\n  # un comentario\n  avisos_pausados: {valor}\n  max_workers: 8\n"

    assert patron.search(texto).group(1) == valor
