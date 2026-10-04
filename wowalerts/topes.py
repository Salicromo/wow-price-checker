"""Cambiar un tope de precio dentro de config.yaml, sin tocar nada mas.

Esto NO pasa por PyYAML a proposito. Cargar y volcar el fichero devolveria un
YAML equivalente pero reformateado y sin un solo comentario, y los comentarios
de config.yaml son la mitad de su valor: explican por que las monturas llevan
tope de 200.000, por que las mascotas van por pet_species_id, y que hacer
cuando Blizzard cambia los bonus ids en un parche.

Asi que se edita el texto: se localiza el bloque del objeto, se sustituye el
numero pedido, y el resto del fichero queda byte a byte identico. El diff de un
cambio es una sola linea.

Editar YAML por texto da miedo, con razon. La red esta fuera, en
aplicar_tope.py: recarga el resultado con load_config() y comprueba que ningun
otro tope se ha movido antes de dejar que se commitee.
"""

from __future__ import annotations

import re

__all__ = ["TopeError", "bloque_de", "cambiar_tope"]


class TopeError(Exception):
    """No se puede aplicar el cambio. El mensaje explica por que."""


# El renglon que abre un objeto: '  - name: "Greaves of the Noxious Depths"'.
# El nombre se ancla hasta el final de la linea para que un objeto cuyo nombre
# es prefijo de otro --'Nightsaber' y 'Nightsaber Cub'-- no se confundan.
def _patron_nombre(objeto: str) -> re.Pattern[str]:
    return re.compile(
        r'^(?P<sangria>[ \t]*)-[ \t]+name:[ \t]*'
        r'(?P<comilla>["\']?)' + re.escape(objeto) + r'(?P=comilla)[ \t]*$',
        re.MULTILINE,
    )


def bloque_de(texto: str, objeto: str) -> tuple[int, int]:
    """Donde empieza y acaba el bloque de ese objeto, en indices del texto.

    Acotar el bloque es lo que impide que un cambio se propague: dos objetos
    con tablas identicas comparten los mismos numeros, y sin esto cambiar el
    escalon de uno cambiaria el del otro.
    """
    apertura = _patron_nombre(objeto).search(texto)
    if apertura is None:
        raise TopeError(
            f"No encuentro {objeto!r} en config.yaml. El nombre tiene que ser "
            "el ingles, igual que en 'name:'."
        )

    inicio = apertura.start()
    sangria = len(apertura.group("sangria"))

    # El bloque acaba en el siguiente objeto de la misma lista, o en la
    # siguiente clave de primer nivel, lo que llegue antes.
    siguiente = re.compile(
        r"^(?:[ \t]{%d}-[ \t]|[^ \t\n#])" % sangria,
        re.MULTILINE,
    )
    cierre = siguiente.search(texto, apertura.end())
    return inicio, cierre.start() if cierre else len(texto)


def _cambiar_max_price(bloque: str, tope: int) -> tuple[str, int]:
    sitio = re.search(r"^([ \t]*max_price:[ \t]*)(\d+)([ \t]*)$", bloque, re.MULTILINE)
    if sitio is None:
        raise TopeError(
            "Ese objeto lleva tabla por ilvl, no un precio unico. Dime que ilvl "
            "quieres cambiar."
        )
    viejo = int(sitio.group(2))
    nuevo = bloque[: sitio.start()] + sitio.group(1) + str(tope) + sitio.group(3) + bloque[sitio.end():]
    return nuevo, viejo


def _cambiar_escalon(bloque: str, ilvl: int, tope: int) -> tuple[str, int]:
    clave = bloque.find("max_price_by_ilvl")
    if clave == -1:
        raise TopeError(
            "Ese objeto no depende del ilvl: lleva un precio unico. Dejalo en "
            "blanco y cambio ese."
        )

    abre = bloque.find("{", clave)
    cierra = bloque.find("}", abre)
    if abre == -1 or cierra == -1:
        raise TopeError(
            "No entiendo la tabla 'max_price_by_ilvl' de ese objeto. Tiene que "
            "ir entre llaves, como { 295: 9000, 311: 90000 }."
        )

    tabla = bloque[abre:cierra]
    sitio = re.search(r"(?<!\d)(%d[ \t]*:[ \t]*)(\d+)" % ilvl, tabla)
    if sitio is None:
        disponibles = re.findall(r"(?<!\d)(\d+)[ \t]*:[ \t]*\d+", tabla)
        raise TopeError(
            f"Ese objeto no vigila el ilvl {ilvl}. Los que tiene son: "
            + ", ".join(disponibles)
            + "."
        )

    viejo = int(sitio.group(2))
    tabla_nueva = tabla[: sitio.start()] + sitio.group(1) + str(tope) + tabla[sitio.end():]
    return bloque[:abre] + tabla_nueva + bloque[cierra:], viejo


def cambiar_tope(
    texto: str,
    objeto: str,
    ilvl: int | None,
    tope: int,
) -> tuple[str, int]:
    """Devuelve (config.yaml nuevo, tope anterior).

    `ilvl` va a None para los objetos de precio unico: patrones, monturas y
    mascotas, que no escalan y llevan un solo `max_price`.
    """
    if not isinstance(tope, int) or isinstance(tope, bool):
        raise TopeError("El tope tiene que ser un numero entero de oro.")
    if tope <= 0:
        raise TopeError("El tope tiene que ser mayor que cero.")

    inicio, fin = bloque_de(texto, objeto)
    bloque = texto[inicio:fin]

    if ilvl is None:
        bloque_nuevo, viejo = _cambiar_max_price(bloque, tope)
    else:
        bloque_nuevo, viejo = _cambiar_escalon(bloque, ilvl, tope)

    return texto[:inicio] + bloque_nuevo + texto[fin:], viejo
