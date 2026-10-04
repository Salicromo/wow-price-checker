"""Lee el registro de ventas del addon Journalator.

Journalator apunta cada factura que te llega por correo: que vendiste, en que
reino, por cuanto y cuanto se llevo la casa de subastas. Es el unico sitio donde
esa cifra esta exacta, porque viene del propio juego y no de deducirla mirando
si una subasta desaparecio.

El problema es como lo guarda. Su libreria de archivo (Archivist) comprime cada
bloque de historial en tres pasos: LibSerialize lo convierte en bytes,
LibDeflate lo comprime y una codificacion a 6 bits lo deja en caracteres que
caben en un fichero de texto. Aqui se deshace ese camino al reves, sin Lua de
por medio: asi funciona igual en el PC que en la Steam Deck y no hace falta
entrar en el juego para leerlo.
"""

from __future__ import annotations

import json
import logging
import re
import struct
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .misubastas import cuenta_de_ruta

log = logging.getLogger(__name__)

RESUMEN_VERSION = 1

# El alfabeto de LibDeflate:EncodeForPrint, en el orden en que asigna los
# valores 0..63. No es base64: empieza por las minusculas.
ALFABETO = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()"
_VALOR_DE = {letra: valor for valor, letra in enumerate(ALFABETO)}

# Cada entrada del archivo son cuatro lineas fijas escritas por WoW al guardar
# los SavedVariables. Nos quedamos con la clave y con el bloque codificado.
BLOQUE_RE = re.compile(
    r'\["(?P<clave>[^"]+)"\]\s*=\s*\{\s*'
    r'\["timestamp"\]\s*=\s*(?P<cuando>\d+),\s*'
    r'\["version"\]\s*=\s*\d+,\s*'
    r'\["data"\]\s*=\s*"(?P<datos>[^"]*)"'
)

# Los ficheros del juego pueden tener varias tablas; solo interesa el archivo.
INICIO_ARCHIVO = "JOURNALATOR_ARCHIVE = {"

# Lo que Journalator llama "Invoices" son las facturas del correo, tanto de lo
# que compras como de lo que vendes. Solo cuentan las de vendedor.
TIPO_VENDEDOR = "seller"


class JournalatorError(Exception):
    """El archivo de Journalator no se puede leer."""


@dataclass(frozen=True)
class Venta:
    """Una venta tal y como la apunto el juego."""

    reino: str
    objeto: str
    neto: int
    cuando: datetime
    personaje: str = ""
    # La WoW del selector de cuentas; sale de la carpeta del fichero.
    cuenta: int | None = None

    @property
    def huella(self) -> tuple:
        """Lo que distingue una venta de otra.

        Los bloques del archivo se solapan: el mismo correo aparece en varias
        instantaneas seguidas. Sin esto contariamos cada venta varias veces.
        """
        return (self.personaje, int(self.cuando.timestamp()), self.objeto, self.neto)


# ---------------------------------------------------------------------------
#  Paso 1: de texto imprimible a bytes
# ---------------------------------------------------------------------------


def descodifica_impresion(texto: str) -> bytes:
    """Deshace LibDeflate:EncodeForPrint.

    Cada caracter lleva 6 bits y se van apilando por abajo hasta completar
    bytes. Los bits sueltos del final son relleno y se tiran.
    """
    acumulado = 0
    bits = 0
    salida = bytearray()

    for letra in texto:
        valor = _VALOR_DE.get(letra)
        if valor is None:
            raise JournalatorError(
                f"El bloque trae un caracter que EncodeForPrint no produce: {letra!r}."
            )
        acumulado |= valor << bits
        bits += 6
        while bits >= 8:
            salida.append(acumulado & 0xFF)
            acumulado >>= 8
            bits -= 8

    return bytes(salida)


# ---------------------------------------------------------------------------
#  Paso 2: de bytes a valores (LibSerialize)
# ---------------------------------------------------------------------------

# Indices de tipo de LibSerialize v4, tal cual estan en _ReaderIndex.
NIL = 0
NUM_16_POS, NUM_16_NEG = 1, 2
NUM_24_POS, NUM_24_NEG = 3, 4
NUM_32_POS, NUM_32_NEG = 5, 6
NUM_64_POS, NUM_64_NEG = 7, 8
NUM_FLOAT = 9
NUM_FLOATSTR_POS, NUM_FLOATSTR_NEG = 10, 11
BOOL_T, BOOL_F = 12, 13
STR_8, STR_16, STR_24 = 14, 15, 16
TABLE_8, TABLE_16, TABLE_24 = 17, 18, 19
ARRAY_8, ARRAY_16, ARRAY_24 = 20, 21, 22
MIXED_8, MIXED_16, MIXED_24 = 23, 24, 25
STRINGREF_8, STRINGREF_16, STRINGREF_24 = 26, 27, 28
TABLEREF_8, TABLEREF_16, TABLEREF_24 = 29, 30, 31

# Solo las cadenas de mas de dos bytes entran en la tabla de repetidas: para
# una o dos no compensa gastar el indice.
MINIMO_PARA_REPETIR = 2

VERSION_MAXIMA = 1


class _Lector:
    """Recorre los bytes que dejo LibSerialize y reconstruye los valores.

    Las tablas de Lua se devuelven como diccionarios; las que son una lista
    (claves 1..n) se convierten al final, en `_a_python`.
    """

    def __init__(self, datos: bytes) -> None:
        self.datos = datos
        self.pos = 0
        # LibSerialize numera las cadenas y las tablas segun van apareciendo, y
        # luego las referencia por ese numero. Empiezan en 1.
        self.cadenas: list[str] = []
        self.tablas: list[dict] = []

    # -- primitivas ---------------------------------------------------------

    def bytes(self, cuantos: int) -> bytes:
        fin = self.pos + cuantos
        if fin > len(self.datos):
            raise JournalatorError("El bloque se corta antes de tiempo.")
        trozo = self.datos[self.pos : fin]
        self.pos = fin
        return trozo

    def byte(self) -> int:
        return self.bytes(1)[0]

    def entero(self, cuantos: int) -> int:
        # Big-endian. El caso de 7 bytes existe porque Lua no llega a los 64
        # bits enteros sin perder precision.
        return int.from_bytes(self.bytes(cuantos), "big")

    def cadena(self, largo: int) -> str:
        # Los nombres de objeto y de reino vienen en UTF-8 desde el juego.
        texto = self.bytes(largo).decode("utf-8", "replace")
        if largo > MINIMO_PARA_REPETIR:
            self.cadenas.append(texto)
        return texto

    # -- estructuras --------------------------------------------------------

    def tabla(self, parejas: int, sitio: dict | None = None) -> dict:
        if sitio is None:
            sitio = {}
            self.tablas.append(sitio)
        for _ in range(parejas):
            clave = self.objeto()
            valor = self.objeto()
            try:
                sitio[clave] = valor
            except TypeError:
                # En Lua una tabla puede ser clave de otra. Journalator no hace
                # eso, y guardarlo aqui no aportaria nada.
                log.debug("Me salto una clave que no es un valor simple.")
        return sitio

    def lista(self, cuantos: int, sitio: dict | None = None) -> dict:
        if sitio is None:
            sitio = {}
            self.tablas.append(sitio)
        for indice in range(1, cuantos + 1):
            sitio[indice] = self.objeto()
        return sitio

    def mixta(self, de_lista: int, de_tabla: int) -> dict:
        sitio: dict = {}
        self.tablas.append(sitio)
        self.lista(de_lista, sitio)
        self.tabla(de_tabla, sitio)
        return sitio

    # -- el despachador -----------------------------------------------------

    def objeto(self) -> Any:
        cabecera = self.byte()

        # Un entero pequeño y positivo cabe en los siete bits de arriba.
        if cabecera % 2 == 1:
            return cabecera >> 1

        # Tipo con el tamaño metido en la misma cabecera.
        if cabecera % 4 == 2:
            empaquetado = cabecera >> 2
            tipo = empaquetado % 4
            cuantos = empaquetado >> 2
            if tipo == 0:
                return self.cadena(cuantos)
            if tipo == 1:
                return self.tabla(cuantos)
            if tipo == 2:
                return self.lista(cuantos)
            # En la mixta los cuatro bits son dos cuentas de dos, cada una una
            # unidad menos de lo que vale.
            return self.mixta((cuantos % 4) + 1, (cuantos // 4) + 1)

        # Entero de doce bits: cuatro en la cabecera y ocho en el byte de al
        # lado. El bit 4 dice si es negativo.
        if cabecera % 8 == 4:
            empaquetado = self.byte() * 256 + cabecera
            if cabecera % 16 == 12:
                return -((empaquetado - 12) // 16)
            return (empaquetado - 4) // 16

        return self._por_tipo(cabecera >> 3)

    def _por_tipo(self, tipo: int) -> Any:
        if tipo == NIL:
            return None
        if tipo in (BOOL_T, BOOL_F):
            return tipo == BOOL_T

        if tipo in _ENTEROS:
            cuantos, signo = _ENTEROS[tipo]
            return signo * self.entero(cuantos)

        if tipo == NUM_FLOAT:
            return struct.unpack(">d", self.bytes(8))[0]
        if tipo in (NUM_FLOATSTR_POS, NUM_FLOATSTR_NEG):
            # Cuando el numero ocupa menos escrito que en binario, LibSerialize
            # lo guarda como texto.
            texto = self.bytes(self.byte()).decode("ascii", "replace")
            signo = -1 if tipo == NUM_FLOATSTR_NEG else 1
            return signo * float(texto)

        if tipo in _CADENAS:
            return self.cadena(self.entero(_CADENAS[tipo]))
        if tipo in _TABLAS:
            return self.tabla(self.entero(_TABLAS[tipo]))
        if tipo in _LISTAS:
            return self.lista(self.entero(_LISTAS[tipo]))
        if tipo in _MIXTAS:
            ancho = _MIXTAS[tipo]
            return self.mixta(self.entero(ancho), self.entero(ancho))

        if tipo in _REF_CADENA:
            return self._referencia(self.cadenas, self.entero(_REF_CADENA[tipo]))
        if tipo in _REF_TABLA:
            return self._referencia(self.tablas, self.entero(_REF_TABLA[tipo]))

        raise JournalatorError(f"Tipo {tipo} desconocido en el bloque.")

    @staticmethod
    def _referencia(guardadas: Sequence, indice: int) -> Any:
        if not 1 <= indice <= len(guardadas):
            raise JournalatorError(
                f"El bloque apunta a la repetida {indice}, que no existe."
            )
        return guardadas[indice - 1]


_ENTEROS = {
    NUM_16_POS: (2, 1),
    NUM_16_NEG: (2, -1),
    NUM_24_POS: (3, 1),
    NUM_24_NEG: (3, -1),
    NUM_32_POS: (4, 1),
    NUM_32_NEG: (4, -1),
    NUM_64_POS: (7, 1),
    NUM_64_NEG: (7, -1),
}
_CADENAS = {STR_8: 1, STR_16: 2, STR_24: 3}
_TABLAS = {TABLE_8: 1, TABLE_16: 2, TABLE_24: 3}
_LISTAS = {ARRAY_8: 1, ARRAY_16: 2, ARRAY_24: 3}
_MIXTAS = {MIXED_8: 1, MIXED_16: 2, MIXED_24: 3}
_REF_CADENA = {STRINGREF_8: 1, STRINGREF_16: 2, STRINGREF_24: 3}
_REF_TABLA = {TABLEREF_8: 1, TABLEREF_16: 2, TABLEREF_24: 3}


def deserializa(datos: bytes) -> Any:
    """El primer valor que LibSerialize dejo en `datos`."""
    if not datos:
        raise JournalatorError("El bloque esta vacio.")

    lector = _Lector(datos)
    version = lector.byte()
    if version > VERSION_MAXIMA:
        raise JournalatorError(
            f"El bloque usa la version {version} de LibSerialize y aqui solo "
            f"se lee hasta la {VERSION_MAXIMA}. Journalator se habra actualizado."
        )
    return _a_python(lector.objeto())


def _a_python(valor: Any, memoria: dict[int, Any] | None = None) -> Any:
    """Convierte en listas las tablas cuyas claves son 1..n.

    La memoria hace dos cosas: no repetir trabajo cuando una tabla aparece
    varias veces, y no dar vueltas si alguna se referencia a si misma.
    """
    if not isinstance(valor, dict):
        return valor

    memoria = {} if memoria is None else memoria
    if id(valor) in memoria:
        return memoria[id(valor)]

    claves = list(valor.keys())
    es_lista = bool(claves) and _son_1_a_n(claves)

    hueco: Any = [] if es_lista else {}
    memoria[id(valor)] = hueco

    if es_lista:
        hueco.extend(_a_python(valor[i], memoria) for i in range(1, len(claves) + 1))
    else:
        for clave, dentro in valor.items():
            hueco[clave] = _a_python(dentro, memoria)
    return hueco


def _son_1_a_n(claves: Sequence) -> bool:
    return all(isinstance(c, int) and not isinstance(c, bool) for c in claves) and (
        sorted(claves) == list(range(1, len(claves) + 1))
    )


# ---------------------------------------------------------------------------
#  Paso 3: del fichero de WoW a las ventas
# ---------------------------------------------------------------------------


def bloques(texto: str) -> Iterator[tuple[str, str]]:
    """Cada bloque del archivo: su clave y su contenido codificado."""
    inicio = texto.find(INICIO_ARCHIVO)
    if inicio < 0:
        return
    for trozo in BLOQUE_RE.finditer(texto, inicio):
        yield trozo.group("clave"), trozo.group("datos")


def ventas_de_texto(texto: str) -> list[Venta]:
    """Las ventas que hay en un Journalator.lua ya leido.

    Un bloque roto no tumba la lectura: Journalator reescribe el archivo entero
    cada vez que guarda y perder uno solo cuesta unos dias de historial, asi que
    vale mas quedarse con el resto que no devolver nada.
    """
    encontradas: dict[tuple, Venta] = {}

    for clave, codificado in bloques(texto):
        try:
            crudo = zlib.decompress(descodifica_impresion(codificado), -zlib.MAX_WBITS)
            contenido = deserializa(crudo)
        except (JournalatorError, zlib.error, ValueError, IndexError) as fallo:
            log.warning("No he podido leer el bloque %s de Journalator: %s", clave, fallo)
            continue

        if not isinstance(contenido, dict):
            continue

        for factura in contenido.get("Invoices") or ():
            venta = _a_venta(factura)
            if venta is not None:
                encontradas.setdefault(venta.huella, venta)

    return sorted(encontradas.values(), key=lambda v: (v.cuando, v.reino, v.objeto))


def apuntes_de_wow(wow_root: str | Path) -> dict[str, int]:
    """Cuantas anotaciones tiene Journalator de cada clase.

    Sirve para distinguir "el addon no esta" de "esta y funciona, pero todavia
    no se te ha vendido nada": si hay publicaciones o caducidades apuntadas, el
    addon va bien y solo falta la primera venta.
    """
    cuenta: dict[str, int] = {}

    for fichero in encontrar_journalator(wow_root):
        try:
            texto = fichero.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for clave, codificado in bloques(texto):
            try:
                crudo = zlib.decompress(
                    descodifica_impresion(codificado), -zlib.MAX_WBITS
                )
                contenido = deserializa(crudo)
            except (JournalatorError, zlib.error, ValueError, IndexError):
                continue
            if not isinstance(contenido, dict):
                continue
            for seccion, filas in contenido.items():
                if isinstance(filas, list) and filas:
                    # El maximo y no la suma: los bloques del archivo se
                    # solapan, asi que sumarlos inflaria la cifra.
                    cuenta[str(seccion)] = max(cuenta.get(str(seccion), 0), len(filas))

    return cuenta


def _a_venta(factura: Any) -> Venta | None:
    if not isinstance(factura, Mapping):
        return None
    if factura.get("invoiceType") != TIPO_VENDEDOR:
        return None

    objeto = factura.get("itemName")
    cuando = factura.get("time")
    if not isinstance(objeto, str) or not isinstance(cuando, (int, float)):
        return None

    origen = factura.get("source")
    origen = origen if isinstance(origen, Mapping) else {}
    reino = origen.get("realm")
    if not isinstance(reino, str) or not reino:
        return None

    # Lo que acaba en tu bolsillo: lo que pago el comprador, menos la comision
    # de la casa, mas el deposito que te devuelven al vender.
    neto = _entero(factura.get("value")) - _entero(factura.get("consignment"))
    neto += _entero(factura.get("deposit"))

    return Venta(
        reino=reino,
        objeto=objeto,
        neto=neto,
        cuando=datetime.fromtimestamp(int(cuando), timezone.utc),
        personaje=str(origen.get("character") or ""),
    )


def _entero(valor: Any) -> int:
    # LibSerialize devuelve floats cuando el numero venia con decimales; en
    # cobre siempre son enteros disfrazados.
    return int(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else 0


def encontrar_journalator(wow_root: str | Path) -> list[Path]:
    """El fichero de Journalator de cada una de tus cuentas de WoW."""
    patron = "WTF/Account/*/SavedVariables/Journalator.lua"
    return sorted(Path(wow_root).glob(patron))


def ventas_de_wow(wow_root: str | Path) -> list[Venta]:
    """Todas tus ventas apuntadas por Journalator, sin repetir.

    Cada cuenta lleva su propio fichero y sus propios personajes, asi que entre
    cuentas no hay nada que repetir; dentro de una si, porque los bloques del
    archivo se solapan.
    """
    encontradas: dict[tuple, Venta] = {}

    for fichero in encontrar_journalator(wow_root):
        try:
            texto = fichero.read_text(encoding="utf-8", errors="replace")
        except OSError as fallo:
            log.warning("No he podido abrir %s: %s", fichero, fallo)
            continue
        cuenta = cuenta_de_ruta(fichero)
        for venta in ventas_de_texto(texto):
            encontradas.setdefault(venta.huella, replace(venta, cuenta=cuenta))

    return sorted(encontradas.values(), key=lambda v: (v.cuando, v.reino, v.objeto))


# ---------------------------------------------------------------------------
#  Paso 4: el resumen que viaja al repositorio
# ---------------------------------------------------------------------------


def resumir(ventas: Iterable[Venta]) -> dict[str, dict[str, dict]]:
    """Agrupa las ventas por reino y objeto.

    Al repositorio no van las facturas una a una: no hacen falta para el panel
    y arrastrarian el nombre de quien te compro cada cosa.
    """
    resumen: dict[str, dict[str, dict]] = {}

    for venta in ventas:
        por_objeto = resumen.setdefault(venta.reino, {})
        fila = por_objeto.setdefault(
            venta.objeto, {"ventas": 0, "oro": 0, "ultima": "", "cuentas": []}
        )
        fila["ventas"] += 1
        fila["oro"] += venta.neto
        fila["ultima"] = max(fila["ultima"], venta.cuando.date().isoformat())
        if venta.cuenta is not None and venta.cuenta not in fila["cuentas"]:
            fila["cuentas"] = sorted([*fila["cuentas"], venta.cuenta])

    return resumen


def escribir_resumen(path: str | Path, ventas: Iterable[Venta]) -> bool:
    """Escribe el resumen de una maquina. True solo si ha cambiado algo.

    Sin marcas de tiempo, igual que el volcado de subastas: asi dos lecturas
    iguales dan bytes iguales y el sincronizador no genera commits vacios.
    """
    path = Path(path)
    reinos = resumir(ventas)
    contenido = json.dumps(
        {"version": RESUMEN_VERSION, "reinos": reinos},
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )

    if not reinos and _tiene_ventas(path):
        # Journalator desactivado, borrado o a medio instalar: leer cero ventas
        # no significa que no las hubiera. Machacar el fichero se llevaria por
        # delante el historial de esta maquina, y eso no se recupera.
        log.warning(
            "No he leido ninguna venta, pero %s ya tenia historial. Lo dejo "
            "como estaba. Comprueba que Journalator sigue instalado.",
            path.name,
        )
        return False

    if path.is_file() and path.read_text(encoding="utf-8") == contenido:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")
    return True


def _tiene_ventas(path: Path) -> bool:
    """Si el resumen que ya hay en disco dice algo."""
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(isinstance(datos, dict) and datos.get("reinos"))


def ranking(
    resumen: Mapping[str, Mapping[str, Mapping]],
    objetos: Iterable[str] | None = None,
) -> tuple[list[tuple[str, int, int, str, tuple[int, ...]]], tuple[int, int]]:
    """Los reinos de mas a menos oro vendido, y los totales.

    `objetos` deja fuera lo que no vigilas. Journalator apunta todo lo que
    vendes, y mezclar el material de artesania con lo que si rastreas taparia
    justo lo que interesa ver.
    """
    filtro = None if objetos is None else set(objetos)
    filas: list[tuple[str, int, int, str, tuple[int, ...]]] = []

    for reino, por_objeto in resumen.items():
        cuantas = oro = 0
        ultima = ""
        cuentas: set[int] = set()
        for objeto, fila in por_objeto.items():
            if filtro is not None and objeto not in filtro:
                continue
            cuantas += _entero(fila.get("ventas"))
            oro += _entero(fila.get("oro"))
            ultima = max(ultima, str(fila.get("ultima") or ""))
            cuentas.update(_cuentas(fila))
        if cuantas:
            filas.append((str(reino), cuantas, oro, ultima, tuple(sorted(cuentas))))

    # Manda el oro: vender una cosa de 100.000 importa mas que cinco de 500.
    # A igualdad de oro, el reino con mas ventas.
    filas.sort(key=lambda fila: (-fila[2], -fila[1], fila[0]))
    return filas, (sum(f[1] for f in filas), sum(f[2] for f in filas))


def leer_resumenes(origen: str | Path) -> dict[str, dict[str, dict]]:
    """Suma los resumenes de todas las maquinas.

    Una factura se lee del buzon una sola vez, en la maquina donde estabas
    jugando, asi que el PC y la Deck nunca cuentan la misma venta y sumar es
    correcto.
    """
    total: dict[str, dict[str, dict]] = {}

    for fichero in sorted(Path(origen).glob("*.json")):
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as fallo:
            log.warning("No he podido leer %s: %s", fichero, fallo)
            continue

        reinos = datos.get("reinos") if isinstance(datos, dict) else None
        if not isinstance(reinos, dict):
            continue

        for reino, por_objeto in reinos.items():
            if not isinstance(por_objeto, dict):
                continue
            destino = total.setdefault(str(reino), {})
            for objeto, fila in por_objeto.items():
                if not isinstance(fila, dict):
                    continue
                acumulado = destino.setdefault(
                    str(objeto), {"ventas": 0, "oro": 0, "ultima": "", "cuentas": []}
                )
                acumulado["ventas"] += _entero(fila.get("ventas"))
                acumulado["oro"] += _entero(fila.get("oro"))
                acumulado["ultima"] = max(
                    acumulado["ultima"], str(fila.get("ultima") or "")
                )
                acumulado["cuentas"] = sorted(
                    set(acumulado["cuentas"]) | set(_cuentas(fila))
                )

    return total


def _cuentas(fila: Mapping) -> list[int]:
    # Los resumenes de antes de apuntar la cuenta no traen el campo.
    cuentas = fila.get("cuentas")
    if not isinstance(cuentas, list):
        return []
    return [c for c in cuentas if isinstance(c, int) and not isinstance(c, bool)]
