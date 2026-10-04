"""Lectura y analisis de la traza de reposteo que el addon deja en disco.

El addon apunta cada pulsacion y cada respuesta del juego en
`WowAlertsExportDB.trazaReposteo`, con la hora y el reloj del cliente en cada
linea (ver `traza()` en Reposteo.lua). Eso ya es un registro de tiempos: aqui
solo se lee y se cuenta, para poder decir donde se va el tiempo de verdad en
vez de optimizar a ojo.

No se interpreta Lua: la traza es una lista de cadenas, asi que se extraen las
cadenas y se parsean como texto, igual que hace misubastas.py con el payload.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .misubastas import ESCAPES, MisSubastasError

# El principio de la tabla de la traza dentro del fichero de SavedVariables.
TRAZA_RE = re.compile(r'\["trazaReposteo"\]\s*=\s*\{')

# Cada linea es 'HH:MM:SS 12345.6 lo que paso'. La hora es la del reloj de
# pared y el numero es GetTime(), que es el que sirve para medir: la hora solo
# tiene segundos enteros, y aqui casi todo pasa en decimas.
LINEA_RE = re.compile(r"^(\d{2}:\d{2}:\d{2}) (\d+\.\d+) (.*)$", re.DOTALL)

BUSCO_RE = re.compile(r"^busco (\S+) \((\d+)/(\d+)\)$")
RESPUESTA_RE = re.compile(r"^(\S+): (\d+) resultados,")
SIN_RESPUESTA_RE = re.compile(r"^sin respuesta de (\S+) en")
PULSACION_RE = re.compile(r"^\[(.*?)\] -> (.+?)\. Ahora dice \[", re.DOTALL)

CASA_OCUPADA = "casa ocupada: la busqueda"
BUSQUEDA_TERMINADA = "busqueda terminada."
RECOJO_CARTA = "buzon: recojo la carta"

# Dos cartas seguidas mas separadas que esto no son el mismo viaje al buzon:
# midiendo ese hueco saldria el tiempo que tardaste tu en volver, no el addon.
SEGUNDOS_MISMA_TANDA = 10.0


@dataclass(frozen=True)
class Linea:
    """Una linea de la traza, ya partida."""

    hora: str
    reloj: float
    texto: str


@dataclass
class Informe:
    """Lo que se puede medir de una traza."""

    lineas: int = 0
    sesiones: int = 0
    # Segundos entre pedir una busqueda y procesar su respuesta.
    latencias: list[float] = field(default_factory=list)
    sin_respuesta: int = 0
    casa_ocupada: int = 0
    # (objetos, segundos) de cada escaneo que llego hasta el final.
    escaneos: list[tuple[int, float]] = field(default_factory=list)
    utiles: Counter = field(default_factory=Counter)
    vacias: Counter = field(default_factory=Counter)
    # Segundos entre cartas seguidas del mismo viaje al buzon.
    cartas: list[float] = field(default_factory=list)

    @property
    def pulsaciones(self) -> int:
        return sum(self.utiles.values()) + sum(self.vacias.values())


def _decodificar(texto: str, inicio: int) -> tuple[str, int]:
    """La cadena de Lua que empieza en `inicio`, y por donde sigue el fichero.

    `inicio` apunta al primer caracter de dentro de la cadena, es decir, justo
    detras de la comilla de apertura.
    """
    salida: list[str] = []
    i = inicio
    while i < len(texto):
        char = texto[i]
        if char == "\\":
            siguiente = texto[i + 1 : i + 2]
            if siguiente.isdigit():
                # WoW escribe los caracteres no imprimibles como \ddd decimal.
                digitos = ""
                for char_digito in texto[i + 1 : i + 4]:
                    if not char_digito.isdigit():
                        break
                    digitos += char_digito
                salida.append(chr(int(digitos)))
                i += 1 + len(digitos)
                continue
            salida.append(ESCAPES.get(siguiente, siguiente))
            i += 2
            continue
        if char == '"':
            return "".join(salida), i + 1
        salida.append(char)
        i += 1
    raise MisSubastasError("La traza tiene una cadena sin cerrar; esta corrupta.")


def extraer_lineas(texto: str) -> list[str]:
    """Las cadenas de la tabla `trazaReposteo`, sin parsear todavia.

    Devuelve una lista vacia si el fichero no tiene traza. No es un error: el
    addon solo la escribe cuando has usado el reposteo, y con TRAZA apagada no
    la escribe nunca.
    """
    match = TRAZA_RE.search(texto)
    if not match:
        return []

    crudas: list[str] = []
    i = match.end()
    while i < len(texto):
        char = texto[i]
        if char == '"':
            cadena, i = _decodificar(texto, i + 1)
            crudas.append(cadena)
            continue
        if char == "}":
            return crudas
        i += 1
    raise MisSubastasError("La traza no se cierra; el fichero esta corrupto.")


def parsear(crudas: Iterable[str]) -> list[Linea]:
    """Parte cada linea en hora, reloj y texto, saltando las que no encajen."""
    lineas = []
    for cruda in crudas:
        match = LINEA_RE.match(cruda)
        if match:
            lineas.append(Linea(match.group(1), float(match.group(2)), match.group(3)))
    return lineas


def leer_traza(path: str | Path) -> list[Linea]:
    """La traza de un fichero de SavedVariables."""
    path = Path(path)
    try:
        texto = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise MisSubastasError(f"No he podido leer {path}: {exc}") from exc
    return parsear(extraer_lineas(texto))


def partir_sesiones(lineas: Sequence[Linea]) -> list[list[Linea]]:
    """Corta la traza cada vez que el reloj del cliente vuelve atras.

    GetTime() cuenta desde que arrancaste el juego, asi que aguanta un /reload
    pero se reinicia al salir. Medir un hueco a caballo entre dos sesiones
    daria un numero sin ningun sentido.
    """
    sesiones: list[list[Linea]] = []
    actual: list[Linea] = []
    for linea in lineas:
        if actual and linea.reloj < actual[-1].reloj:
            sesiones.append(actual)
            actual = []
        actual.append(linea)
    if actual:
        sesiones.append(actual)
    return sesiones


def _motivo(texto: str) -> str:
    """El motivo de una pulsacion que no hizo nada, sin los datos variables.

    'buscando 3/9' y 'buscando 4/9' son el mismo motivo, y el volcado de la
    cola que algunos arrastran detras haria unico cada uno de ellos.
    """
    motivo = texto[len("nada: ") :]
    motivo = motivo.split(". Cola:")[0]
    return re.sub(r"\d+", "N", motivo).strip()


def _mide_busquedas(sesion: Sequence[Linea], informe: Informe) -> None:
    """Latencia de cada busqueda y duracion de los escaneos completos."""
    pedida: dict[str, float] = {}
    empezo: float | None = None
    objetos = 0

    for linea in sesion:
        busco = BUSCO_RE.match(linea.texto)
        if busco:
            pedida[busco.group(1)] = linea.reloj
            if busco.group(2) == "1":
                empezo, objetos = linea.reloj, int(busco.group(3))
            continue

        respuesta = RESPUESTA_RE.match(linea.texto)
        if respuesta:
            desde = pedida.pop(respuesta.group(1), None)
            if desde is not None:
                informe.latencias.append(linea.reloj - desde)
            continue

        perdida = SIN_RESPUESTA_RE.match(linea.texto)
        if perdida:
            pedida.pop(perdida.group(1), None)
            informe.sin_respuesta += 1
            continue

        if linea.texto.startswith(BUSQUEDA_TERMINADA):
            if empezo is not None:
                informe.escaneos.append((objetos, linea.reloj - empezo))
            empezo = None
            continue

        if linea.texto.startswith(CASA_OCUPADA):
            informe.casa_ocupada += 1


def _mide_pulsaciones(sesion: Sequence[Linea], informe: Informe) -> None:
    for linea in sesion:
        match = PULSACION_RE.match(linea.texto)
        if not match:
            continue
        resultado = match.group(2)
        if resultado.startswith("nada: "):
            informe.vacias[_motivo(resultado)] += 1
        else:
            informe.utiles[resultado.split()[0]] += 1


def _mide_buzon(sesion: Sequence[Linea], informe: Informe) -> None:
    anterior: float | None = None
    for linea in sesion:
        if not linea.texto.startswith(RECOJO_CARTA):
            continue
        if anterior is not None and linea.reloj - anterior <= SEGUNDOS_MISMA_TANDA:
            informe.cartas.append(linea.reloj - anterior)
        anterior = linea.reloj


def analizar(lineas: Sequence[Linea]) -> Informe:
    """Cuenta todo lo medible de una traza ya parseada."""
    sesiones = partir_sesiones(lineas)
    informe = Informe(lineas=len(lineas), sesiones=len(sesiones))
    for sesion in sesiones:
        _mide_busquedas(sesion, informe)
        _mide_pulsaciones(sesion, informe)
        _mide_buzon(sesion, informe)
    return informe


def _percentil(valores: Sequence[float], fraccion: float) -> float:
    """El valor por debajo del cual queda esa fraccion de la muestra.

    Sin interpolar y sin numpy: con muestras de unas decenas de busquedas, el
    elemento que toca ya dice lo que hay que saber.
    """
    ordenados = sorted(valores)
    indice = min(int(len(ordenados) * fraccion), len(ordenados) - 1)
    return ordenados[indice]


def formatear(informe: Informe, titulo: str) -> str:
    """El informe legible de una traza."""
    fuera: list[str] = [f"📄 {titulo} — {informe.lineas} lineas, {informe.sesiones} sesion(es)"]

    if not informe.lineas:
        fuera.append("   Sin traza. Usa el reposteo en el juego y haz /reload.")
        return "\n".join(fuera)

    fuera.append("")
    if informe.latencias:
        fuera.append(
            f"🔍 Busquedas: {len(informe.latencias)} respondidas, "
            f"{informe.sin_respuesta} sin respuesta"
        )
        fuera.append(
            "   tarda   mediana {:.2f} s   media {:.2f} s   p90 {:.2f} s   peor {:.2f} s".format(
                statistics.median(informe.latencias),
                statistics.fmean(informe.latencias),
                _percentil(informe.latencias, 0.9),
                max(informe.latencias),
            )
        )
        if informe.escaneos:
            objetos = sum(n for n, _ in informe.escaneos)
            segundos = sum(s for _, s in informe.escaneos)
            fuera.append(
                "   {} escaneo(s) completo(s): {} objetos en {:.1f} s ({:.2f} s por objeto)".format(
                    len(informe.escaneos), objetos, segundos, segundos / max(objetos, 1)
                )
            )
        if informe.casa_ocupada:
            fuera.append(
                f"   {informe.casa_ocupada} vez/veces la casa estaba ocupada y la busqueda espero"
            )
    else:
        fuera.append("🔍 Busquedas: ninguna en esta traza.")

    fuera.append("")
    total = informe.pulsaciones
    hechas = sum(informe.utiles.values())
    if total:
        fuera.append(
            "⌨️  Pulsaciones: {} en total, {} hicieron algo ({:.0f} %)".format(
                total, hechas, 100 * hechas / total
            )
        )
        if informe.utiles:
            detalle = ", ".join(f"{que} {n}" for que, n in informe.utiles.most_common())
            fuera.append(f"   lo que hicieron: {detalle}")
        if informe.vacias:
            fuera.append(f"   las {sum(informe.vacias.values())} vacias, por que:")
            for motivo, n in informe.vacias.most_common():
                fuera.append(f"      {n:4}  {motivo}")
    else:
        fuera.append("⌨️  Pulsaciones: ninguna en esta traza.")

    fuera.append("")
    if informe.cartas:
        fuera.append(
            "📬 Buzon: {} carta(s) seguida(s), {:.2f} s entre cartas de media (peor {:.2f} s)".format(
                len(informe.cartas) + 1,
                statistics.fmean(informe.cartas),
                max(informe.cartas),
            )
        )
    else:
        fuera.append("📬 Buzon: ninguna tanda de cartas en esta traza.")

    return "\n".join(fuera)
