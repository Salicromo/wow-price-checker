"""Anadir un objeto vigilado a config.yaml, sin tocar nada mas.

No pasa por PyYAML, por lo mismo que topes.py: cargar y volcar devolveria un
YAML equivalente pero reformateado y sin un solo comentario, y los comentarios
de config.yaml son la mitad de su valor.

Asi que se edita el texto: se escribe el bloque nuevo --con la tabla pedida, o
el precio del patron-- detras de los de su clase, y el resto del fichero queda
byte a byte identico.

La red de seguridad esta fuera, en anadir_objeto.py: recarga el resultado con
load_config() y comprueba que no ha cambiado ningun objeto anterior antes de
dejar que se commitee.
"""

from __future__ import annotations

import re
from typing import Mapping

from .topes import TopeError, bloque_de

__all__ = ["ObjetoError", "ampliar_equipo", "anadir_equipo", "anadir_patron"]


class ObjetoError(Exception):
    """No se puede anadir el objeto. El mensaje explica por que."""


def anadir_equipo(
    texto: str, nombre: str, item_id: int, topes: Mapping[int, int]
) -> str:
    """config.yaml con una pieza nueva y su tabla de topes por ilvl.

    Los ilvl los pone quien la anade: una pieza de temporada nueva sale a ilvl
    que no tiene ninguna de las que ya vigilas, asi que copiar una tabla no
    serviria. Va detras de la ultima pieza de equipo, para que el equipo siga
    junto y delante de los patrones.
    """
    _rechazar_comillas(nombre)
    if not topes:
        raise ObjetoError(
            "Una pieza de equipo necesita al menos un ilvl con su tope."
        )
    bloque = (
        f"  - name: {_cita(nombre)}\n"
        f"    item_id: {item_id}\n"
        "    max_price_by_ilvl:\n"
        f"{_tabla_yaml(topes)}"
    )
    return _insertar(texto, _tras_el_ultimo(texto, _CON_TABLA), bloque)


def ampliar_equipo(
    texto: str, nombre: str, topes: Mapping[int, int]
) -> tuple[str, dict[int, int], dict[int, int]]:
    """config.yaml con escalones nuevos en la tabla de una pieza que ya vigilas.

    Es lo que pasa en cada temporada: la pieza sigue siendo la misma, pero sale
    a ilvl que su tabla no tiene. Los escalones que ya estaban no se tocan,
    aunque la peticion traiga otro tope para ellos: para eso esta 'Ajustar un
    tope', y pisarlos en silencio desde aqui seria una sorpresa.

    Devuelve (texto nuevo, escalones anadidos, escalones que ya estaban con el
    tope que conservan).
    """
    try:
        inicio, fin = bloque_de(texto, nombre)
    except TopeError as fallo:
        raise ObjetoError(str(fallo)) from fallo
    bloque = texto[inicio:fin]

    clave = _CON_TABLA.search(bloque)
    if clave is None:
        raise ObjetoError(
            f"{nombre!r} lleva un precio unico, no una tabla por ilvl. Para "
            "cambiarlo usa 'Ajustar un tope'."
        )
    abre = bloque.find("{", clave.end())
    cierra = bloque.find("}", abre)
    if abre == -1 or cierra == -1:
        raise ObjetoError(
            f"No entiendo la tabla de {nombre!r}: tiene que ir entre llaves, "
            "como { 295: 9000, 311: 90000 }. Anade el escalon a mano."
        )

    actuales = {
        int(ilvl): int(tope)
        for ilvl, tope in re.findall(r"(\d+)[ \t]*:[ \t]*(\d+)", bloque[abre:cierra])
    }
    anadidos = {ilvl: tope for ilvl, tope in topes.items() if ilvl not in actuales}
    ya_estaban = {ilvl: actuales[ilvl] for ilvl in topes if ilvl in actuales}
    if not anadidos:
        raise ObjetoError(
            f"{nombre!r} ya vigila todos esos ilvl. Para cambiarles el tope usa "
            "'Ajustar un tope'."
        )

    juntos = {**actuales, **anadidos}
    linea = bloque.rfind("\n", 0, abre) + 1
    if bloque[linea:abre].strip():
        # La tabla va en la misma linea que la clave: se queda en una linea.
        pares = ", ".join(f"{ilvl}: {tope}" for ilvl, tope in sorted(juntos.items()))
        bloque = bloque[:abre] + "{ " + pares + " }" + bloque[cierra + 1:]
    else:
        # En su propia linea: se reescribe como la escribe anadir_equipo.
        resto = cierra + 1
        if bloque.startswith("\n", resto):
            resto += 1
        bloque = bloque[:linea] + _tabla_yaml(juntos) + bloque[resto:]

    return texto[:inicio] + bloque + texto[fin:], anadidos, ya_estaban


def _tabla_yaml(topes: Mapping[int, int]) -> str:
    """{368: 20000, ...} -> '      { 368: 20000, ... }\\n'.

    Ordenada por ilvl y partida en lineas de cinco escalones, que es como estan
    escritas las tablas de config.yaml.
    """
    pares = [f"{ilvl}: {tope}" for ilvl, tope in sorted(topes.items())]
    lineas = [", ".join(pares[i:i + 5]) for i in range(0, len(pares), 5)]
    return "      { " + ",\n        ".join(lineas) + " }\n"


def _cita(texto: str) -> str:
    """Un escalar YAML entrecomillado: los nombres llevan apostrofos y dos puntos."""
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rechazar_comillas(nombre: str) -> None:
    """Un nombre con comillas dobles o barras invertidas no se puede admitir.

    _cita lo escribiria escapado, pero topes._patron_nombre busca el nombre
    literal en 'name:' y no sabe de escapes: ese objeto no se podria encontrar
    nunca mas para cambiarle el tope.
    """
    if '"' in nombre or "\\" in nombre:
        raise ObjetoError(
            f"{nombre!r} lleva comillas dobles o una barra invertida, y luego no "
            "se podria volver a encontrar para cambiarle el tope. Anadelo a mano "
            "en config.yaml."
        )


def _fin_del_contenido(texto: str, inicio: int, fin: int) -> int:
    """Donde acaba la ultima linea que es de verdad, dentro de [inicio, fin).

    [inicio, fin) llega hasta el objeto siguiente, y por el camino se lleva las
    lineas en blanco y los comentarios que hay entre medias. Esos comentarios
    suelen abrir la seccion de detras --'Monturas caras'--, asi que lo nuevo
    tiene que ir delante de ellos y no debajo.
    """
    lineas = texto[inicio:fin].splitlines(keepends=True)
    while lineas and (not lineas[-1].strip() or lineas[-1].lstrip().startswith("#")):
        lineas.pop()
    return inicio + sum(len(linea) for linea in lineas)


def _insertar(texto: str, donde: int, bloque: str) -> str:
    """Mete el bloque en `donde`, con una linea en blanco delante.

    Lo que habia detras --la linea en blanco, un comentario, el objeto
    siguiente-- sigue detras tal cual estaba.
    """
    antes = texto[:donde]
    if not antes.endswith("\n"):
        antes += "\n"
    return antes + "\n" + bloque + texto[donde:]


# El renglon que abre cualquier objeto de 'items:'. La lista de personajes no
# casa: sus entradas son nombres sueltos, sin 'name:'.
_APERTURA = re.compile(r"^[ \t]*-[ \t]+name:[ \t]*(.+?)[ \t]*$", re.MULTILINE)

_REPOSTEABLE = re.compile(r"^[ \t]*repostear:[ \t]*true[ \t]*(?:#.*)?$", re.MULTILINE)

# La clave que tiene toda pieza de equipo, anclada al principio de linea para
# que un comentario que la mencione no cuente.
_CON_TABLA = re.compile(r"^[ \t]*max_price_by_ilvl:", re.MULTILINE)

# La siguiente clave de primer nivel del YAML, como 'orden_personajes:'. No
# casa con un comentario ni con una linea sangrada, que es lo que forma el
# resto del bloque de un objeto.
_CLAVE_DE_PRIMER_NIVEL = re.compile(r"^[^ \t\n#]", re.MULTILINE)


def anadir_patron(texto: str, nombre: str, item_id: int, tope: int) -> str:
    """config.yaml con un patron nuevo, con precio unico.

    Lleva las dos banderas que llevan los patrones que ya vigilas: sin avisos de
    undercut --de una receta no quieres saber que alguien se ha puesto debajo--
    pero si reposteable con la tecla del addon.
    """
    _rechazar_comillas(nombre)
    bloque = (
        f"  - name: {_cita(nombre)}\n"
        f"    item_id: {item_id}\n"
        f"    max_price: {tope}\n"
        "    avisar_undercut: false\n"
        "    repostear: true\n"
    )
    return _insertar(texto, _tras_el_ultimo(texto, _REPOSTEABLE), bloque)


def _tras_el_ultimo(texto: str, patron: re.Pattern[str]) -> int:
    """Donde acaba el ultimo objeto cuyo bloque casa con `patron`, o el ultimo
    de la lista.

    Los patrones viven juntos en config.yaml, antes de las monturas y las
    mascotas, que son trampas para el error de otro y no cosas que repostees.
    El equipo vive junto tambien, delante de los patrones.

    Trabaja con posiciones y no con nombres reconstruidos: una linea 'name:'
    con un comentario detras, o un nombre con comillas escapadas, no se puede
    volver a buscar de forma fiable con bloque_de.
    """
    aperturas = list(_APERTURA.finditer(texto))
    if not aperturas:
        raise ObjetoError("No encuentro ningun objeto en 'items:' de config.yaml.")

    ultimo_bloque = None
    ultimo_que_casa = None
    for i, apertura in enumerate(aperturas):
        siguiente_apertura = (
            aperturas[i + 1].start() if i + 1 < len(aperturas) else len(texto)
        )
        clave_siguiente = _CLAVE_DE_PRIMER_NIVEL.search(texto, apertura.end())
        fin = min(
            siguiente_apertura,
            clave_siguiente.start() if clave_siguiente else len(texto),
        )
        ultimo_bloque = (apertura.start(), fin)
        if patron.search(texto[apertura.start():fin]):
            ultimo_que_casa = ultimo_bloque

    inicio, fin = ultimo_que_casa if ultimo_que_casa else ultimo_bloque
    return _fin_del_contenido(texto, inicio, fin)
