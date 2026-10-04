"""Lectura de las subastas propias exportadas por el addon.

El addon guarda un JSON dentro de una cadena de Lua, asi que aqui no se
interpreta Lua: se extrae la cadena, se deshacen sus escapes y se parsea como
JSON. Es lo que hace que un cambio de formato de SavedVariables no rompa nada.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

PAYLOAD_RE = re.compile(r'\["payload"\]\s*=\s*"')

# El sufijo de la carpeta de cuenta, con barra de cualquier tipo detras o nada:
# '403840080#2/', '403840080#2\' o '403840080#2' al final de la ruta.
CUENTA_RE = re.compile(r"#(\d+)(?=[\\/]|$)")

# WoW escapa asi los caracteres especiales dentro de una cadena guardada.
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


class MisSubastasError(Exception):
    """No se ha podido leer el volcado del addon."""


@dataclass(frozen=True)
class MyAuction:
    """Una subasta tuya, tal y como la vio el addon dentro del juego."""

    auction_id: int
    item_id: int
    item_name: str
    ilvl: int
    buyout_copper: int
    quantity: int
    character: str
    realm: str
    realm_slug: str
    # Numero de cuenta de WoW (la "WoW 2" del selector), deducido de la carpeta
    # de WTF de la que salio el volcado. None si no se ha podido saber.
    account: int | None = None
    # Los bonus ids identifican la version exacta del objeto (ilvl, calidad,
    # afijos). Dos subastas del mismo objeto con los mismos bonus ids son el
    # mismo producto; con distintos, no compiten entre si.
    bonus_ids: tuple[int, ...] = ()
    # Cuando el addon exporto estos datos, en segundos unix. Sirve para no
    # fiarse de un volcado que se ha quedado atras: sin esto, una maquina que
    # deja de sincronizar sigue diciendo que unas subastas son tuyas mucho
    # despues de que dejaran de existir, y al desaparecer de los datos de
    # Blizzard se cantan como vendidas. Paso el 2026-09-02.
    exported_at: int = 0


def slugify_realm(name: str) -> str:
    """'Area 52' -> 'area-52', que es como los nombra la API de Blizzard.

    Los apostrofos se borran en vez de convertirse en guion, porque asi es como
    los trata Blizzard: "Zul'jin" es "zuljin", no "zul-jin".
    """
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(c)
    )
    sin_apostrofos = re.sub(r"['‘’]", "", sin_tildes)
    return re.sub(r"[^a-zA-Z0-9]+", "-", sin_apostrofos).strip("-").lower()


def cuenta_de_ruta(path: str | Path) -> int | None:
    """Numero de cuenta a partir de la ruta del volcado.

    WoW guarda cada cuenta del juego en su propia carpeta bajo WTF/Account, con
    el numero al final: '403840080#2' es la WoW 2 del selector de cuentas. Es un
    dato mas fiable que cualquier tabla escrita a mano, y se mantiene solo.

    Se busca sobre el texto de la ruta y no con Path.parts porque este ultimo
    depende del sistema: en Linux, una ruta de Windows entera es un solo
    componente y no encontraria nada.
    """
    numeros = CUENTA_RE.findall(str(path))
    return int(numeros[-1]) if numeros else None


def extraer_payload(texto: str) -> str:
    """Saca la cadena JSON del fichero de SavedVariables."""
    match = PAYLOAD_RE.search(texto)
    if not match:
        raise MisSubastasError(
            "El volcado no contiene ningun campo 'payload'. Comprueba que el "
            "addon WowAlertsExport esta activado y que has abierto la Casa de "
            "Subastas al menos una vez."
        )

    return leer_cadena_lua(texto, match.end())


def leer_cadena_lua(texto: str, i: int) -> str:
    """La cadena de Lua que empieza en `i`, justo despues de las comillas."""
    salida: list[str] = []
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
            return "".join(salida)
        salida.append(char)
        i += 1

    raise MisSubastasError("El volcado tiene una cadena sin cerrar; esta corrupto.")


def leer_payload(path: str | Path) -> dict:
    """Lee un fichero de SavedVariables y devuelve su payload ya parseado."""
    path = Path(path)
    try:
        texto = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise MisSubastasError(f"No he podido leer {path}: {exc}") from exc

    try:
        datos = json.loads(extraer_payload(texto))
    except json.JSONDecodeError as exc:
        raise MisSubastasError(f"El payload de {path} no es JSON valido: {exc}") from exc

    if not isinstance(datos, dict):
        raise MisSubastasError(f"El payload de {path} no es un objeto JSON.")
    return datos


def fusionar_payloads(payloads: Iterable[Mapping]) -> dict[str, dict]:
    """Une varios volcados quedandose con el mas reciente de cada personaje.

    Hace falta porque puedes tener varias cuentas de WoW, cada una con su
    carpeta en WTF, y porque un mismo personaje aparece en todas las que hayan
    tenido su sesion abierta.
    """
    fusion: dict[str, dict] = {}
    for payload in payloads:
        personajes = payload.get("personajes")
        if not isinstance(personajes, dict):
            continue
        for clave, entrada in personajes.items():
            if not isinstance(entrada, dict):
                continue
            previo = fusion.get(clave)
            if previo is None or _exported_at(entrada) >= _exported_at(previo):
                fusion[clave] = entrada
    return fusion


def subastas_de_payloads(personajes: Mapping[str, Mapping]) -> list[MyAuction]:
    """Aplana los volcados fusionados en una lista de subastas."""
    subastas: list[MyAuction] = []
    for entrada in personajes.values():
        character = str(entrada.get("character") or "")
        realm = str(entrada.get("realm") or "")
        cuenta = entrada.get("account")
        for cruda in entrada.get("auctions") or []:
            subasta = _to_auction(
                cruda, character, realm, cuenta, _exported_at(entrada)
            )
            if subasta is not None:
                subastas.append(subasta)
    subastas.sort(key=lambda s: (s.realm, s.character, s.auction_id))
    return subastas


def encontrar_savedvariables(wow_root: str | Path) -> list[Path]:
    """Todos los ficheros del addon, de todas tus cuentas de WoW."""
    patron = "WTF/Account/*/SavedVariables/WowAlertsExport.lua"
    return sorted(Path(wow_root).glob(patron))


def leer_de_wow(wow_root: str | Path) -> list[MyAuction] | None:
    """Lee y fusiona todo lo que haya exportado el addon.

    Devuelve None cuando el addon no ha volcado nada todavia. No es un error:
    en una maquina recien montada es lo normal hasta que juegas alli con el
    addon puesto, y tratarlo como fallo haria que la sincronizacion programada
    diera error cada cuarto de hora sin motivo.
    """
    ficheros = encontrar_savedvariables(wow_root)
    if not ficheros:
        log.warning(
            "Todavia no hay ningun WowAlertsExport.lua bajo %s. Entra al juego "
            "en esta maquina con el addon activado y abre la Casa de Subastas.",
            wow_root,
        )
        return None
    log.info("Leyendo %s volcado(s) del addon.", len(ficheros))

    payloads = []
    for fichero in ficheros:
        payload = leer_payload(fichero)
        cuenta = cuenta_de_ruta(fichero)
        # Cada personaje se queda con la cuenta de la carpeta donde vivia.
        for entrada in (payload.get("personajes") or {}).values():
            if isinstance(entrada, dict):
                entrada["account"] = cuenta
        payloads.append(payload)

    return subastas_de_payloads(fusionar_payloads(payloads))


def canceladas_de_payload(payload: Mapping) -> set[int]:
    """Los ids de subasta que el addon ha visto que cancelaste tu.

    El addon las guarda como un mapa 'id -> cuando', pero su codificador escribe
    una lista vacia cuando no hay ninguna, asi que aqui se aceptan las dos
    formas. Solo interesan los ids: el cuando es para que el addon pode.
    """
    crudas = payload.get("canceladas")
    if isinstance(crudas, dict):
        claves = crudas.keys()
    elif isinstance(crudas, list):
        claves = crudas
    else:
        return set()

    ids: set[int] = set()
    for clave in claves:
        try:
            ids.add(int(clave))
        except (TypeError, ValueError):
            log.debug("Cancelacion con id ilegible, la ignoro: %r", clave)
    return ids


def apunta_cancelaciones(payload: Mapping) -> bool:
    """Si ese volcado lo escribio un addon que ya apunta las cancelaciones.

    La clave la escribe siempre el addon nuevo, tenga o no cancelaciones dentro,
    asi que su ausencia significa que esa cuenta sigue con el addon viejo. Y eso
    importa: /reload solo recarga la sesion en la que lo haces, asi que con
    varias cuentas de WoW abiertas es facil dejarse una atras y que sus
    reposteos sigan saliendo como ventas.
    """
    return "canceladas" in payload


EXPORTED_AT_RE = re.compile(r'\["exportedAt"\]\s*=\s*(\d+)')


def volcado_atrasado(fichero: str | Path) -> tuple[int, int] | None:
    """(tabla, volcado) si el volcado del addon se ha quedado atras.

    El addon guarda dos cosas: su tabla de personajes y una copia en JSON, que
    es la unica que se lee desde fuera. El 2026-09-01 esa copia se quedo con los
    datos del dia anterior mientras la tabla iba al dia, y treinta personajes se
    pasaron un dia entero sin vigilar sin que nada lo cantara.
    """
    fichero = Path(fichero)
    crudo = fichero.read_text(encoding="utf-8", errors="replace")

    en_tabla = [int(v) for v in EXPORTED_AT_RE.findall(crudo)]
    if not en_tabla:
        return None

    try:
        payload = json.loads(extraer_payload(crudo))
    except (MisSubastasError, json.JSONDecodeError):
        return None

    en_volcado = [
        _exported_at(v)
        for v in (payload.get("personajes") or {}).values()
        if isinstance(v, Mapping)
    ]
    if max(en_tabla) <= max(en_volcado or [0]):
        return None
    return max(en_tabla), max(en_volcado or [0])


def cuentas_con_addon_viejo(wow_root: str | Path) -> list[str]:
    """Las cuentas de WoW cuyo volcado aun no apunta cancelaciones."""
    viejas: list[str] = []
    for fichero in encontrar_savedvariables(wow_root):
        if not apunta_cancelaciones(leer_payload(fichero)):
            # .../WTF/Account/<cuenta>/SavedVariables/WowAlertsExport.lua
            viejas.append(fichero.parts[-3])
    return viejas


def leer_canceladas_de_wow(wow_root: str | Path) -> set[int]:
    """Las cancelaciones apuntadas por el addon en todas tus cuentas."""
    ids: set[int] = set()
    for fichero in encontrar_savedvariables(wow_root):
        ids |= canceladas_de_payload(leer_payload(fichero))
    return ids


def leer_canceladas(origen: str | Path) -> set[int]:
    """Las cancelaciones del volcado de todas tus maquinas.

    Se unen sin mirar cual es mas reciente: una cancelacion es un hecho que no
    caduca, y el addon ya se encarga de podar las viejas.
    """
    origen = Path(origen)
    ficheros = [origen] if origen.is_file() else sorted(origen.glob("*.json"))

    ids: set[int] = set()
    for fichero in ficheros:
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(datos, dict):
            ids |= canceladas_de_payload(datos)
    return ids


def escribir_snapshot(
    path: str | Path,
    subastas: Sequence[MyAuction],
    canceladas: Iterable[int] = (),
) -> bool:
    """Escribe mis_subastas.json. Devuelve True solo si el contenido ha cambiado.

    No lleva marcas de tiempo a proposito: asi dos volcados con las mismas
    subastas producen bytes identicos y el sincronizador no genera commits
    vacios cada cuarto de hora.
    """
    path = Path(path)
    contenido = json.dumps(
        {
            "version": SNAPSHOT_VERSION,
            "auctions": [_to_json(s) for s in subastas],
            # Ordenadas para que dos volcados iguales den bytes iguales y el
            # sincronizador no genere commits vacios.
            "canceladas": sorted(set(canceladas)),
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )

    anterior = path.read_text(encoding="utf-8") if path.is_file() else None
    if anterior == contenido:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")
    return True


def leer_snapshots(origen: str | Path) -> list[MyAuction]:
    """Lee el volcado de todas tus maquinas y los une.

    Cada maquina escribe su propio fichero (el PC uno, la Steam Deck otro),
    porque compartir uno haria que cada una borrase los personajes de la otra
    al subir. Aqui se unen por id de subasta, sin mirar cual es mas reciente:
    una subasta que aparezca en un fichero viejo y ya no exista se descarta
    sola mas adelante, al no estar en el volcado de Blizzard.

    Acepta tambien un fichero suelto, que es como estaba antes de haber dos
    maquinas.
    """
    origen = Path(origen)
    if origen.is_file():
        return leer_snapshot(origen)
    if not origen.is_dir():
        log.warning(
            "No existe %s: no se de ninguna subasta tuya. Ejecuta "
            "sync_subastas.py en tu PC para generarlo.",
            origen,
        )
        return []

    por_id: dict[int, MyAuction] = {}
    ficheros = sorted(origen.glob("*.json"))
    for fichero in ficheros:
        for subasta in leer_snapshot(fichero):
            por_id.setdefault(subasta.auction_id, subasta)

    log.info(
        "%s subasta(s) tuyas, de %s maquina(s).", len(por_id), len(ficheros)
    )
    return sorted(
        por_id.values(), key=lambda s: (s.realm, s.character, s.auction_id)
    )


def actividad_por_maquina(origen: str | Path) -> dict[str, datetime]:
    """Cuando exporto por ultima vez cada maquina, por el nombre de su fichero.

    Es la ultima senal de vida que tengo de ella. La deteccion de ventas la usa
    para saber si estabas jugando cuando una subasta desaparecio: solo se puede
    cancelar una subasta jugando, y solo se puede saber si la cancelaste cuando
    esa maquina vuelve a exportar.

    Las subastas sin `exportedAt` no cuentan: son de volcados anteriores a que
    existiera el campo, y una hora inventada es peor que no tenerla.
    """
    origen = Path(origen)
    ficheros = [origen] if origen.is_file() else sorted(origen.glob("*.json"))

    actividad: dict[str, datetime] = {}
    for fichero in ficheros:
        marcas = [s.exported_at for s in leer_snapshot(fichero) if s.exported_at]
        if marcas:
            actividad[fichero.stem] = datetime.fromtimestamp(
                max(marcas), tz=timezone.utc
            )
    return actividad


def separar_por_frescura(
    subastas: Sequence[MyAuction], ahora: datetime, max_horas: int
) -> tuple[list[MyAuction], list[MyAuction]]:
    """Parte tus subastas en (las de fiar, las de un volcado que se quedo atras).

    El volcado del addon dice que subastas son tuyas, pero no cuando dejan de
    serlo: si una maquina deja de exportar, sigue afirmando lo mismo dia tras
    dia. Y esa afirmacion caduca. El 2026-09-02 la Steam Deck se quedo 16 horas
    sin exportar, sus subastas de ayer se relistaron con ids nuevos, y al no
    encontrar los ids viejos en los datos de Blizzard se cantaron como vendidas.

    Sin `exportedAt` no se puede juzgar, y eso pasa con los volcados escritos
    antes de que esto existiera. Se dan por buenos: estrenar la comprobacion
    tirando de golpe todo lo que hay seria peor que el problema que arregla.
    """
    if max_horas <= 0:
        return list(subastas), []

    limite = ahora - timedelta(hours=max_horas)
    frescas: list[MyAuction] = []
    viejas: list[MyAuction] = []
    for subasta in subastas:
        if not subasta.exported_at:
            frescas.append(subasta)
            continue
        exportada = datetime.fromtimestamp(subasta.exported_at, tz=timezone.utc)
        (frescas if exportada >= limite else viejas).append(subasta)
    return frescas, viejas


def leer_snapshot(path: str | Path) -> list[MyAuction]:
    """Lee mis_subastas.json. Un fichero que no existe son cero subastas."""
    path = Path(path)
    if not path.is_file():
        log.warning(
            "No existe %s: no se de ninguna subasta tuya. Ejecuta "
            "sync_subastas.py en tu PC para generarlo.",
            path,
        )
        return []

    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MisSubastasError(f"{path} no se puede leer: {exc}") from exc

    subastas: list[MyAuction] = []
    for cruda in datos.get("auctions") or []:
        subasta = _to_auction(
            cruda, cruda.get("character", ""), cruda.get("realm", "")
        )
        if subasta is not None:
            subastas.append(subasta)
    return subastas


def _exported_at(entrada: Mapping) -> int:
    valor = entrada.get("exportedAt")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else 0


def _to_auction(
    cruda: Any,
    character: str,
    realm: str,
    cuenta: Any = None,
    exportado: int = 0,
) -> MyAuction | None:
    """Convierte una entrada cruda, o None si le falta algo imprescindible."""
    if not isinstance(cruda, Mapping):
        return None

    campos = {}
    for clave in ("auctionID", "itemID", "ilvl", "buyout"):
        valor = cruda.get(clave)
        if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
            log.debug("Subasta propia descartada, falta %s: %r", clave, cruda)
            return None
        campos[clave] = valor

    cantidad = cruda.get("quantity")
    bonus = cruda.get("bonusIDs")
    return MyAuction(
        bonus_ids=tuple(
            b for b in bonus if isinstance(b, int) and not isinstance(b, bool)
        )
        if isinstance(bonus, list)
        else (),
        auction_id=campos["auctionID"],
        item_id=campos["itemID"],
        item_name=str(cruda.get("itemName") or f"Objeto {campos['itemID']}"),
        ilvl=campos["ilvl"],
        buyout_copper=campos["buyout"],
        quantity=cantidad if isinstance(cantidad, int) and cantidad > 0 else 1,
        character=str(cruda.get("character") or character),
        realm=str(cruda.get("realm") or realm),
        realm_slug=slugify_realm(str(cruda.get("realm") or realm)),
        account=_cuenta_valida(cruda.get("account", cuenta)),
        exported_at=_exported_at(cruda) or exportado,
    )


def _cuenta_valida(valor: Any) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _to_json(subasta: MyAuction) -> dict:
    return {
        "auctionID": subasta.auction_id,
        "itemID": subasta.item_id,
        "itemName": subasta.item_name,
        "ilvl": subasta.ilvl,
        "bonusIDs": list(subasta.bonus_ids),
        "buyout": subasta.buyout_copper,
        "quantity": subasta.quantity,
        "character": subasta.character,
        "realm": subasta.realm,
        "account": subasta.account,
        "exportedAt": subasta.exported_at,
    }
