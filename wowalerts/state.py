"""Memoria entre ejecuciones.

Sin esto, como una subasta dura horas y el escaneo corre cada hora, el mismo
chollo se avisaria una y otra vez. Aqui se guarda que subastas ya se han
notificado y los ids de objeto ya resueltos.

Los ficheros se escriben de forma atomica (fichero temporal + rename) para que
una interrupcion a mitad no deje un JSON corrupto.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ventas import SubastaVigilada, UltimoVolcado

log = logging.getLogger(__name__)

STATE_VERSION = 1


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s ilegible (%s); empiezo de cero.", path, exc)
        return None
    return data if isinstance(data, dict) else None


class NotifiedKeys:
    """Claves ya avisadas, con olvido automatico de las antiguas.

    Cada entrada guarda el numero de ejecucion en que se aviso. Las que llevan
    mas de `retention_runs` pasadas sin volver a verse se descartan, para que
    el fichero no crezca sin limite.
    """

    #: Clave del JSON bajo la que vive esta memoria. Dos memorias con secciones
    #: distintas pueden compartir fichero sin pisarse.
    section = "auctions"

    def __init__(self, path: str | Path, retention_runs: int = 72) -> None:
        self.path = Path(path)
        self.retention_runs = retention_runs
        data = _read_json(self.path) or {}
        raw = data.get(self.section)
        self._seen: dict[str, int] = (
            {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}
            if isinstance(raw, dict)
            else {}
        )
        self.run: int = int(data.get("run", 0)) + 1

    def is_new(self, *key_parts: Any) -> bool:
        return self._as_key(key_parts) not in self._seen

    def mark(self, *key_parts: Any) -> None:
        self._seen[self._as_key(key_parts)] = self.run

    def save(self) -> None:
        cutoff = self.run - self.retention_runs
        kept = {key: run for key, run in self._seen.items() if run > cutoff}
        dropped = len(self._seen) - len(kept)
        if dropped:
            log.debug("Olvidadas %s entradas antiguas del estado.", dropped)
        self._seen = kept
        _write_json_atomic(
            self.path,
            {"version": STATE_VERSION, "run": self.run, self.section: kept},
        )

    def __len__(self) -> int:
        return len(self._seen)

    @staticmethod
    def _as_key(parts: tuple) -> str:
        """Acepta tanto una clave ya montada como sus trozos sueltos."""
        if len(parts) == 1:
            return str(parts[0])
        return ":".join(str(p) for p in parts)


class NotifiedAuctions(NotifiedKeys):
    """Subastas ya avisadas en el escaneo de chollos."""

    section = "auctions"

    @staticmethod
    def key(realm_id: int, auction_id: int) -> str:
        """Los ids de subasta solo son unicos dentro de su reino."""
        return f"{realm_id}:{auction_id}"

    def filter_new(self, deals: Iterable) -> list:
        """Devuelve solo los chollos que no se hayan avisado ya."""
        return [
            deal
            for deal in deals
            if self.is_new(self.key(deal.realm_id, deal.auction_id))
        ]


class NotifiedUndercuts(NotifiedKeys):
    """Parejas 'subasta tuya / subasta rival' ya avisadas.

    La clave lleva las dos subastas a proposito: si reposteas, tu id cambia y
    la pareja es nueva, asi que si ese rival te sigue adelantando te enteras.
    """

    section = "undercuts"

    @staticmethod
    def key(realm_id: int, my_auction_id: int, rival_auction_id: int) -> str:
        return f"{realm_id}:{my_auction_id}:{rival_auction_id}"

    def filter_new(self, undercuts: Iterable) -> list:
        """Devuelve solo los undercuts que no se hayan avisado ya."""
        return [
            u
            for u in undercuts
            if self.is_new(self.key(u.realm_id, u.mine.auction_id, u.rival_auction_id))
        ]


class JsonMapCache:
    """Diccionario sencillo persistido en disco.

    Sirve de red de seguridad: si una consulta a la API falla puntualmente, se
    usa lo que se guardo en la pasada anterior en vez de perder el dato.
    """

    def __init__(self, path: str | Path, section: str = "items") -> None:
        self.path = Path(path)
        self.section = section
        raw = (_read_json(self.path) or {}).get(section)
        self._data: dict[str, Any] = (
            {str(k): v for k, v in raw.items()} if isinstance(raw, dict) else {}
        )

    def get(self, key: Any) -> Any | None:
        return self._data.get(str(key))

    def set(self, key: Any, value: Any) -> None:
        self._data[str(key)] = value

    def update(self, mapping: Mapping[Any, Any]) -> None:
        for key, value in mapping.items():
            self.set(key, value)

    def save(self) -> None:
        _write_json_atomic(
            self.path, {"version": STATE_VERSION, self.section: self._data}
        )

    def __len__(self) -> int:
        return len(self._data)


class ItemIdCache(JsonMapCache):
    """Cache de 'nombre de objeto' -> 'id de objeto'."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "items")


class ItemIconCache(JsonMapCache):
    """Cache de 'id de objeto' -> 'url del icono'.

    Los iconos no cambian casi nunca, asi que se piden una sola vez y se
    reutilizan en todas las pasadas siguientes.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "icons")


class RealmIdCache(JsonMapCache):
    """Cache de 'slug de reino' -> 'id de connected realm'.

    Un reino no cambia de connected realm salvo fusion, que es un evento raro
    y anunciado, asi que se pide una vez y se reutiliza siempre.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "realms")


class HistorialDeVolcados:
    """A que minuto ha ido publicando Blizzard en las ultimas pasadas.

    Hace falta memoria de varias pasadas porque una sola observacion no
    distingue "han movido la hora de publicacion" de "hoy han tenido un mal rato
    y han tardado", y mover el disparo del cron detras de un tropiezo suelto lo
    dejaria mal puesto el resto del dia.
    """

    def __init__(self, path: str | Path, recordar: int = 6) -> None:
        self.path = Path(path)
        self.recordar = recordar
        guardado = _read_json(self.path) or {}
        raw = guardado.get("minutos")
        self._minutos: list[int] = (
            [int(m) for m in raw if isinstance(m, int) and 0 <= m < 60]
            if isinstance(raw, list)
            else []
        )
        esperas = guardado.get("esperas")
        self._esperas: int = esperas if isinstance(esperas, int) and esperas >= 0 else 0
        pendiente = guardado.get("aviso_pendiente")
        self._pendiente: tuple[str, str] | None = (
            (str(pendiente[0]), str(pendiente[1]))
            if isinstance(pendiente, list) and len(pendiente) == 2
            else None
        )

    @property
    def aviso_pendiente(self) -> tuple[str, str] | None:
        """Un aviso medido de madrugada, esperando a que acabe el silencio.

        Mover el disparo del cron no molesta a nadie y se hace a cualquier hora,
        pero contarlo por Discord a las cuatro de la manana si. Se guarda y se
        manda en la primera pasada despierta.
        """
        return self._pendiente

    def deja_aviso(self, titulo: str, texto: str) -> None:
        self._pendiente = (titulo, texto)

    def recoge_aviso(self) -> tuple[str, str] | None:
        pendiente = self._pendiente
        self._pendiente = None
        return pendiente

    @property
    def esperas_seguidas(self) -> int:
        """Cuantas pasadas seguidas se han quedado esperando al volcado nuevo.

        Es el freno de mano del gasto. Esperar sale a cuenta mientras es algo
        pasajero, hasta que el disparo se recoloca; si el disparo no se
        recolocase --la clave de cron-job.org caducada, por ejemplo-- se estaria
        esperando cada hora para siempre, y el tiempo de trabajo en Actions se
        paga.
        """
        return self._esperas

    def apunta_espera(self) -> None:
        self._esperas += 1

    def reinicia_esperas(self) -> None:
        self._esperas = 0

    @property
    def minutos(self) -> list[int]:
        """Los minutos observados, el mas reciente al final."""
        return list(self._minutos)

    def apunta(self, minuto: int) -> None:
        self._minutos.append(minuto)
        del self._minutos[: -self.recordar]

    def olvida(self) -> None:
        """Borra el historial, para empezar a medir de cero tras mover el cron.

        Si no, las observaciones de antes del cambio seguirian ahi y la pasada
        siguiente volveria a creer que hay que moverlo.
        """
        self._minutos.clear()

    def save(self) -> None:
        _write_json_atomic(
            self.path,
            {
                "version": STATE_VERSION,
                "minutos": self._minutos,
                "esperas": self._esperas,
                "aviso_pendiente": list(self._pendiente) if self._pendiente else None,
            },
        )


class SeguimientoVentas:
    """Las subastas tuyas que sigo para detectar cuando se venden.

    Guarda dos cosas por reino: la foto del ultimo volcado leido con exito (su
    hora y su id maximo) y una copia de cada subasta tuya viva, con la fecha mas
    temprana en la que podria caducar.

    La copia de los datos del objeto es deliberada: cuando vendes y haces
    /reload, el volcado del addon deja de mencionar la subasta, y sin esta copia
    la venta no se podria anunciar.
    """

    #: Entradas mas viejas que esto se descartan al guardar. Lo normal es que una
    #: entrada salga sola al desaparecer su subasta; esto solo limpia los reinos
    #: que se dejan de escanear porque has dejado de vender alli.
    MAX_DIAS = 7

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        data = _read_json(self.path) or {}
        self._realms = _leer_realms(data.get("realms"))
        self._seguimiento = _leer_seguimiento(data.get("seguimiento"))

    def del_reino(self, realm_id: int) -> dict[int, SubastaVigilada]:
        """Lo que estaba siguiendo en ese reino la pasada anterior."""
        prefijo = f"{realm_id}:"
        return {
            vigilada.auction_id: vigilada
            for clave, vigilada in self._seguimiento.items()
            if clave.startswith(prefijo)
        }

    def anterior(self, realm_id: int) -> UltimoVolcado | None:
        """La foto del ultimo volcado leido con exito de ese reino."""
        return self._realms.get(str(realm_id))

    def reinos_con_seguimiento(self) -> set[int]:
        """Reinos donde queda alguna subasta tuya por resolver.

        Hay que seguir mirandolos aunque el volcado del addon ya no mencione
        ninguna subasta tuya alli: si vendes la ultima de un reino y haces
        /reload, esa venta solo se puede detectar volviendo a ese reino. Como
        las entradas salen del seguimiento en cuanto se resuelven, la lista se
        vacia sola y no se descarga nada de mas.
        """
        reinos: set[int] = set()
        for clave in self._seguimiento:
            realm, _, _ = clave.partition(":")
            if realm.isdigit():
                reinos.add(int(realm))
        return reinos

    def actualizar_reino(
        self,
        realm_id: int,
        seguidas: Mapping[int, SubastaVigilada],
        ultimo: UltimoVolcado,
    ) -> None:
        """Reemplaza lo que sabia de ese reino. No toca los demas."""
        prefijo = f"{realm_id}:"
        self._seguimiento = {
            clave: vigilada
            for clave, vigilada in self._seguimiento.items()
            if not clave.startswith(prefijo)
        }
        for auction_id, vigilada in seguidas.items():
            self._seguimiento[f"{prefijo}{auction_id}"] = vigilada
        self._realms[str(realm_id)] = ultimo

    def save(self, ahora: datetime | None = None) -> None:
        """Vuelca el seguimiento y de paso tira lo mas viejo que MAX_DIAS.

        `ahora` es desde cuando se cuentan esos dias. En produccion es la hora
        de verdad; los tests la pasan para que el corte no dependa del dia en
        que se ejecuten, que es lo que tumbo la suite siete dias despues de
        fijar sus fechas.
        """
        corte = (ahora or datetime.now(timezone.utc)) - timedelta(days=self.MAX_DIAS)
        vivas = {
            clave: vigilada
            for clave, vigilada in self._seguimiento.items()
            if vigilada.visto_at > corte
        }
        olvidadas = len(self._seguimiento) - len(vivas)
        if olvidadas:
            log.debug("Olvidadas %s subastas viejas del seguimiento.", olvidadas)
        self._seguimiento = vivas

        _write_json_atomic(
            self.path,
            {
                "version": STATE_VERSION,
                "realms": {
                    realm: {
                        "dump_at": ultimo.dump_at.isoformat(),
                        "max_auction_id": ultimo.max_auction_id,
                    }
                    for realm, ultimo in self._realms.items()
                },
                "seguimiento": {
                    clave: _vigilada_a_json(vigilada)
                    for clave, vigilada in vivas.items()
                },
            },
        )

    def __len__(self) -> int:
        return len(self._seguimiento)


def _vigilada_a_json(vigilada: SubastaVigilada) -> dict:
    return {
        "auction_id": vigilada.auction_id,
        "item_id": vigilada.item_id,
        "item_name": vigilada.item_name,
        "ilvl": vigilada.ilvl,
        "bonus_ids": list(vigilada.bonus_ids),
        "buyout": vigilada.buyout_copper,
        "quantity": vigilada.quantity,
        "character": vigilada.character,
        "realm": vigilada.realm,
        "account": vigilada.account,
        "no_caduca_antes_de": vigilada.no_caduca_antes_de.isoformat(),
        "visto_at": vigilada.visto_at.isoformat(),
        "adelantada": vigilada.adelantada,
        "desaparecida_at": (
            vigilada.desaparecida_at.isoformat()
            if vigilada.desaparecida_at is not None
            else None
        ),
    }


def _leer_realms(raw: Any) -> dict[str, UltimoVolcado]:
    if not isinstance(raw, dict):
        return {}
    salida: dict[str, UltimoVolcado] = {}
    for realm, entrada in raw.items():
        if not isinstance(entrada, dict):
            continue
        fecha = _fecha(entrada.get("dump_at"))
        max_id = entrada.get("max_auction_id")
        if fecha is None or not isinstance(max_id, int) or isinstance(max_id, bool):
            continue
        salida[str(realm)] = UltimoVolcado(dump_at=fecha, max_auction_id=max_id)
    return salida


def _leer_seguimiento(raw: Any) -> dict[str, SubastaVigilada]:
    """Las entradas ilegibles se descartan; una sola no debe tumbar la pasada."""
    if not isinstance(raw, dict):
        return {}
    salida: dict[str, SubastaVigilada] = {}
    for clave, entrada in raw.items():
        if not isinstance(entrada, dict):
            continue
        caduca = _fecha(entrada.get("no_caduca_antes_de"))
        visto = _fecha(entrada.get("visto_at"))
        if caduca is None or visto is None:
            continue
        try:
            salida[str(clave)] = SubastaVigilada(
                auction_id=int(entrada["auction_id"]),
                item_id=int(entrada["item_id"]),
                item_name=str(entrada["item_name"]),
                ilvl=int(entrada.get("ilvl", 0)),
                buyout_copper=int(entrada["buyout"]),
                quantity=int(entrada.get("quantity", 1)),
                character=str(entrada.get("character", "")),
                realm=str(entrada.get("realm", "")),
                account=entrada.get("account")
                if isinstance(entrada.get("account"), int)
                else None,
                no_caduca_antes_de=caduca,
                visto_at=visto,
                adelantada=bool(entrada.get("adelantada", False)),
                desaparecida_at=_fecha(entrada.get("desaparecida_at")),
                # Las entradas de antes de guardarlos no los tienen: sin bonus,
                # solo se reconoce un reposteo cuyo ilvl se pueda deducir.
                bonus_ids=tuple(
                    b
                    for b in entrada.get("bonus_ids") or ()
                    if isinstance(b, int) and not isinstance(b, bool)
                )
                if isinstance(entrada.get("bonus_ids"), list)
                else (),
            )
        except (KeyError, TypeError, ValueError):
            log.debug("Entrada de seguimiento ilegible, la descarto: %r", entrada)
    return salida


def _fecha(valor: Any) -> datetime | None:
    """Una fecha ISO con zona horaria, o None si no se puede leer."""
    if not isinstance(valor, str):
        return None
    try:
        fecha = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return fecha if fecha.tzinfo is not None else fecha.replace(tzinfo=timezone.utc)
