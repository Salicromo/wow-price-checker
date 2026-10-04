"""Carga y validacion de config.yaml.

La configuracion es lo unico que se edita a mano, asi que cualquier error se
detecta aqui y se explica en castellano, antes de gastar una sola peticion a
la API de Blizzard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .silencio import HoraInvalida, zona

VALID_REGIONS = ("eu", "us", "kr", "tw")
COPPER_PER_GOLD = 10_000


class ConfigError(Exception):
    """La configuracion es invalida. El mensaje explica que hay que arreglar."""


@dataclass(frozen=True)
class ItemRule:
    """Un objeto vigilado y su precio maximo.

    Hay dos clases de objeto y cada una lleva su forma de precio:

    - El equipo escala, y la misma pieza vale una fortuna o nada segun el ilvl,
      asi que lleva la tabla `max_price_by_ilvl` y solo interesan los ilvl que
      aparezcan en ella.
    - Lo que no escala --patrones, recetas, monturas-- es siempre el mismo
      objeto, asi que lleva un solo `max_price` y se compara contra el sin
      mirar el ilvl.
    """

    name: str
    max_price_by_ilvl: Mapping[int, int] = field(default_factory=dict)  # ilvl -> oro
    item_id: int | None = None
    # Especie de mascota, cuando la regla vigila una mascota en vez de un objeto.
    # En las subastas todas las mascotas son el objeto 82800 y lo unico que las
    # distingue es este id, asi que sin el no hay forma de pedir una en concreto.
    pet_species_id: int | None = None
    # Precio maximo unico, en oro, para los objetos que no dependen del ilvl.
    max_price: int | None = None
    # Los undercuts se apagan por objeto: de algunas cosas quieres que te avisen
    # de chollos y de ventas, pero te da igual que alguien se ponga por debajo.
    avisar_undercut: bool = True
    # El reposteo con la tecla del addon se enciende y se apaga aparte de los
    # avisos: de las recetas no quieres avisos de undercut en Discord, pero si
    # quieres cancelarlas y volver a ponerlas desde el juego. Sin valor, manda
    # `avisar_undercut`.
    repostear: bool | None = None

    @property
    def sin_ilvl(self) -> bool:
        """Si el objeto lleva precio unico en vez de tabla por ilvl."""
        return self.max_price is not None

    @property
    def es_mascota(self) -> bool:
        return self.pet_species_id is not None

    @property
    def se_repostea(self) -> bool:
        """Si el addon lo repostea con la tecla."""
        if self.repostear is None:
            return self.avisar_undercut
        return self.repostear

    def threshold_gold(self, ilvl: int) -> int | None:
        """Precio maximo para ese ilvl, o None si ese ilvl no interesa."""
        if self.max_price is not None:
            return self.max_price
        return self.max_price_by_ilvl.get(ilvl)

    @property
    def cheapest_threshold_gold(self) -> int:
        """Umbral mas bajo del objeto.

        Se usa cuando no se ha podido determinar el ilvl: solo se avisa si el
        precio esta por debajo incluso del ilvl mas barato, para no inundar de
        falsas alarmas.
        """
        if self.max_price is not None:
            return self.max_price
        return min(self.max_price_by_ilvl.values())


@dataclass(frozen=True)
class Settings:
    alert_on_unconfirmed_ilvl: bool = True
    # Ojo al subirlo: cada reino en vuelo mantiene en memoria su lista de
    # subastas ya parseada, que en un reino grande son cientos de MB.
    max_workers: int = 8
    request_timeout: int = 45
    state_retention_runs: int = 72
    failure_ratio_threshold: float = 0.30
    # A partir de que antiguedad se da por hecho que Blizzard no ha publicado
    # todavia el volcado de esta hora. Como se regenera cada hora, cualquier
    # cosa por encima de 60 delata un retraso.
    max_dump_age_minutes: int = 61
    # Si al escanear resulta que el volcado de esta hora todavia no ha salido,
    # se espera y se vuelve a mirar, en vez de perder la hora entera. A 0 se
    # desactiva y la pasada se conforma con lo que haya.
    stale_retries: int = 2
    stale_retry_wait_seconds: int = 120
    # Cada cuanto se le pregunta a Blizzard si ya ha publicado, mientras se
    # espera. Preguntar cuesta 0,4 s y unos KB, asi que se puede mirar a menudo.
    dump_poll_seconds: int = 15
    # Cuantos minutos se esta dispuesto a esperar a un volcado que esta a punto
    # de salir, en vez de procesar el de la hora anterior. A 0 se desactiva.
    espera_maxima_minutos: int = 12
    # ------------------------------------------------------------------------
    #  Horas en las que no quieres que suene nada
    # ------------------------------------------------------------------------
    # Ventana en hora local (ver zona_horaria). La de inicio entra y la de fin
    # no: con 1 y 9, a las 09:00 ya suena. Iguales = sin silencio.
    #
    # Solo se calla el envio: las pasadas siguen corriendo y el estado sigue
    # actualizandose, porque el seguimiento de ventas necesita ver la subasta
    # hora tras hora.
    silencio_desde: int = 0
    silencio_hasta: int = 0
    # Zona en la que se interpretan esas horas. Las pasadas corren en Actions,
    # cuyo reloj va en UTC, asi que sin esto la ventana se desplazaria sola con
    # el cambio de hora.
    zona_horaria: str = "Europe/Madrid"
    # Interruptor de la app: con los avisos pausados la pasada se comporta como
    # en la ventana de silencio, pero sin hora de fin. Sigue vigilando y no
    # envia nada; al reanudar sale lo que siga vivo.
    avisos_pausados: bool = False
    # ------------------------------------------------------------------------
    #  Ventas de tus propias subastas
    # ------------------------------------------------------------------------
    # Comision que se queda la casa de subastas al vender, en porcentaje. Es lo
    # que separa el precio al que publicas de lo que llega al buzon.
    ah_cut_pct: int = 5
    # Duracion MAS CORTA con la que publicas, en horas. Va la mas corta y no la
    # habitual porque de aqui sale una cota: con una duracion mayor que la real
    # se afirmarian ventas que en realidad son caducaciones.
    listing_hours: int = 12


@dataclass(frozen=True)
class Config:
    region: str
    items: tuple[ItemRule, ...]
    bonus_ilvl_map: Mapping[int, int]
    settings: Settings
    # Orden en el que quieres leer los avisos, por nombre de personaje. Los que
    # no esten aqui salen detras. Vacio = orden por cuenta y reino.
    orden_personajes: tuple[str, ...] = ()

    @property
    def locale(self) -> str:
        return "en_GB" if self.region in ("eu", "kr", "tw") else "en_US"


def load_config(path: str | Path) -> Config:
    """Lee y valida config.yaml. Lanza ConfigError con un mensaje util."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(
            f"No encuentro el fichero de configuracion: {path}\n"
            "Copia el config.yaml de ejemplo del repositorio."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} no es YAML valido:\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} deberia contener un mapa de opciones en la raiz.")

    return Config(
        region=_parse_region(raw.get("region", "eu")),
        items=_parse_items(raw.get("items")),
        bonus_ilvl_map=_parse_bonus_map(raw.get("bonus_ilvl_map") or {}),
        settings=_parse_settings(raw.get("settings") or {}),
        orden_personajes=_parse_orden(_orden_privado(path, raw.get("orden_personajes"))),
    )


# Los nombres de tus personajes no van en config.yaml, que es publico: viven en
# este fichero, al lado, que esta en .gitignore. En Actions lo trae el workflow
# del repositorio privado. Si existe, manda sobre lo que diga config.yaml.
PERSONAJES = "personajes.yaml"


def _orden_privado(config_path: Path, por_defecto: Any) -> Any:
    """La lista de personajes.yaml si esta junto a config.yaml; si no, la otra."""
    privado = config_path.with_name(PERSONAJES)
    if not privado.is_file():
        return por_defecto
    try:
        raw = yaml.safe_load(privado.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{privado} no es YAML valido:\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{privado} deberia contener la clave 'orden_personajes'.")
    return raw.get("orden_personajes")


def _parse_orden(value: Any) -> tuple[str, ...]:
    """La lista de nombres de 'orden_personajes'."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(
            "'orden_personajes' debe ser una lista de nombres de personaje."
        )
    nombres = [str(v).strip() for v in value if str(v).strip()]
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    if repetidos:
        raise ConfigError(
            "'orden_personajes' tiene nombres repetidos: "
            + ", ".join(sorted(repetidos))
        )
    return tuple(nombres)


def _parse_region(value: Any) -> str:
    region = str(value).strip().lower()
    if region not in VALID_REGIONS:
        raise ConfigError(
            f"'region' vale {value!r} y solo admite: {', '.join(VALID_REGIONS)}."
        )
    return region


def _parse_items(value: Any) -> tuple[ItemRule, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("'items' debe ser una lista con al menos un objeto.")

    rules: list[ItemRule] = []
    seen: set[str] = set()

    for index, entry in enumerate(value, start=1):
        where = f"items[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(
                f"{where} deberia ser un mapa con 'name' y un precio maximo "
                "('max_price' o 'max_price_by_ilvl')."
            )

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: falta 'name' o esta vacio.")
        name = name.strip()

        if name in seen:
            raise ConfigError(f"{where}: el objeto {name!r} esta repetido en la lista.")
        seen.add(name)

        especie = _parse_optional_id(entry.get("pet_species_id"), name, "pet_species_id")
        if especie is not None and entry.get("item_id") is not None:
            raise ConfigError(
                f"{name!r}: pon 'pet_species_id' o 'item_id', no los dos. Una "
                "mascota no tiene objeto propio: en las subastas todas son el "
                "82800 y lo que las distingue es la especie."
            )

        tabla = entry.get("max_price_by_ilvl")
        unico = entry.get("max_price")
        if especie is not None and tabla is not None:
            raise ConfigError(
                f"{name!r}: las mascotas no tienen ilvl, asi que llevan un "
                "'max_price' unico y no 'max_price_by_ilvl'."
            )
        if (tabla is None) == (unico is None):
            raise ConfigError(
                f"{name!r}: pon 'max_price' o 'max_price_by_ilvl', una de las dos "
                "y solo una. 'max_price' es un precio unico para lo que no "
                "escala (patrones, recetas); 'max_price_by_ilvl' es la tabla "
                "ilvl: precio del equipo."
            )

        rules.append(
            ItemRule(
                name=name,
                max_price_by_ilvl=(
                    {} if tabla is None else _parse_price_table(tabla, name)
                ),
                max_price=None if unico is None else _parse_max_price(unico, name),
                item_id=_parse_optional_id(entry.get("item_id"), name, "item_id"),
                pet_species_id=especie,
                avisar_undercut=_parse_bool(
                    entry.get("avisar_undercut"), name, "avisar_undercut", True
                ),
                repostear=_parse_optional_bool(entry.get("repostear"), name, "repostear"),
            )
        )

    return tuple(rules)


def _parse_max_price(value: Any, item_name: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(
            f"{item_name!r}: 'max_price' es un precio en oro, no un si/no."
        )
    try:
        precio = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"{item_name!r}: 'max_price' debe ser un numero entero de oro "
            f"(he encontrado {value!r})."
        ) from exc
    if precio <= 0:
        raise ConfigError(
            f"{item_name!r}: 'max_price' es {precio}; debe ser mayor que 0 "
            "(se expresa en oro, no en cobre)."
        )
    return precio


def _parse_bool(value: Any, item_name: str, campo: str, por_defecto: bool) -> bool:
    if value is None:
        return por_defecto
    if not isinstance(value, bool):
        raise ConfigError(
            f"{item_name!r}: {campo!r} solo admite true o false "
            f"(he encontrado {value!r})."
        )
    return value


def _parse_optional_bool(value: Any, item_name: str, campo: str) -> bool | None:
    if value is None:
        return None
    return _parse_bool(value, item_name, campo, True)


def _parse_price_table(value: Any, item_name: str) -> Mapping[int, int]:
    if not isinstance(value, dict) or not value:
        raise ConfigError(
            f"{item_name!r}: 'max_price_by_ilvl' debe tener al menos un par "
            "ilvl: precio. Ejemplo -> max_price_by_ilvl: { 311: 90000 }"
        )

    table: dict[int, int] = {}
    for ilvl, price in value.items():
        if isinstance(ilvl, bool) or isinstance(price, bool):
            raise ConfigError(
                f"{item_name!r}: en 'max_price_by_ilvl' hay un valor booleano; "
                "tanto el ilvl como el precio deben ser numeros enteros."
            )
        try:
            ilvl_int = int(ilvl)
            price_int = int(price)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"{item_name!r}: en 'max_price_by_ilvl' tanto el ilvl como el precio "
                f"deben ser numeros enteros (he encontrado {ilvl!r}: {price!r})."
            ) from exc

        if ilvl_int <= 0:
            raise ConfigError(f"{item_name!r}: el ilvl {ilvl_int} no es valido.")
        if price_int <= 0:
            raise ConfigError(
                f"{item_name!r}: el precio para ilvl {ilvl_int} es {price_int}; "
                "debe ser mayor que 0 (se expresa en oro, no en cobre)."
            )
        table[ilvl_int] = price_int

    return table


def _parse_optional_id(value: Any, item_name: str, campo: str) -> int | None:
    if value is None:
        return None
    try:
        numero = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"{item_name!r}: {campo!r} debe ser un numero entero."
        ) from exc
    if numero <= 0:
        raise ConfigError(f"{item_name!r}: {campo!r} debe ser mayor que 0.")
    return numero


def _parse_bonus_map(value: Any) -> Mapping[int, int]:
    if not isinstance(value, dict):
        raise ConfigError("'bonus_ilvl_map' debe ser un mapa de 'bonus id: ilvl'.")

    mapping: dict[int, int] = {}
    for bonus_id, ilvl in value.items():
        try:
            mapping[int(bonus_id)] = int(ilvl)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                "'bonus_ilvl_map': tanto el bonus id como el ilvl deben ser enteros "
                f"(he encontrado {bonus_id!r}: {ilvl!r})."
            ) from exc
    return mapping


def _parse_settings(value: Any) -> Settings:
    if not isinstance(value, dict):
        raise ConfigError("'settings' debe ser un mapa de opciones.")

    defaults = Settings()
    # Aviso a medida para el unico ajuste que ha cambiado de nombre, porque el
    # error generico de abajo diria que no lo reconozco sin decir por que.
    if "dump_minute" in value:
        raise ConfigError(
            "'dump_minute' ya no existe: la deteccion de volcados retrasados ya "
            "no depende del minuto al que publique Blizzard, sino de la "
            "antiguedad del volcado. Quita esa linea y, si quieres tocar el "
            "margen, usa 'max_dump_age_minutes' (por defecto "
            f"{defaults.max_dump_age_minutes})."
        )

    unknown = set(value) - set(defaults.__dataclass_fields__)
    if unknown:
        raise ConfigError(
            f"'settings' tiene opciones que no reconozco: {', '.join(sorted(unknown))}.\n"
            f"Las validas son: {', '.join(sorted(defaults.__dataclass_fields__))}."
        )

    try:
        settings = Settings(
            alert_on_unconfirmed_ilvl=bool(
                value.get(
                    "alert_on_unconfirmed_ilvl", defaults.alert_on_unconfirmed_ilvl
                )
            ),
            max_workers=int(value.get("max_workers", defaults.max_workers)),
            request_timeout=int(value.get("request_timeout", defaults.request_timeout)),
            state_retention_runs=int(
                value.get("state_retention_runs", defaults.state_retention_runs)
            ),
            failure_ratio_threshold=float(
                value.get("failure_ratio_threshold", defaults.failure_ratio_threshold)
            ),
            max_dump_age_minutes=int(
                value.get("max_dump_age_minutes", defaults.max_dump_age_minutes)
            ),
            stale_retries=int(value.get("stale_retries", defaults.stale_retries)),
            dump_poll_seconds=int(
                value.get("dump_poll_seconds", defaults.dump_poll_seconds)
            ),
            espera_maxima_minutos=int(
                value.get("espera_maxima_minutos", defaults.espera_maxima_minutos)
            ),
            stale_retry_wait_seconds=int(
                value.get(
                    "stale_retry_wait_seconds", defaults.stale_retry_wait_seconds
                )
            ),
            silencio_desde=int(
                value.get("silencio_desde", defaults.silencio_desde)
            ),
            silencio_hasta=int(
                value.get("silencio_hasta", defaults.silencio_hasta)
            ),
            zona_horaria=str(value.get("zona_horaria", defaults.zona_horaria)),
            avisos_pausados=value.get("avisos_pausados", defaults.avisos_pausados),
            ah_cut_pct=int(value.get("ah_cut_pct", defaults.ah_cut_pct)),
            listing_hours=int(value.get("listing_hours", defaults.listing_hours)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'settings' tiene un valor con formato incorrecto: {exc}") from exc

    if settings.max_workers < 1:
        raise ConfigError("'max_workers' debe ser al menos 1.")
    if settings.request_timeout < 1:
        raise ConfigError("'request_timeout' debe ser al menos 1 segundo.")
    if settings.state_retention_runs < 1:
        raise ConfigError("'state_retention_runs' debe ser al menos 1.")
    if not 0.0 < settings.failure_ratio_threshold <= 1.0:
        raise ConfigError("'failure_ratio_threshold' debe estar entre 0 (excluido) y 1.")
    # Por debajo de 60 se marcaria como retrasado el volcado bueno: a media hora
    # de la siguiente publicacion, el vigente ya tiene mas de 30 minutos y sigue
    # siendo el ultimo que existe.
    if settings.max_dump_age_minutes <= 60:
        raise ConfigError(
            "'max_dump_age_minutes' tiene que pasar de 60: el volcado se "
            "regenera cada hora, asi que por debajo de eso darias por retrasado "
            "el volcado bueno y cada pasada reescanearia de balde."
        )
    if settings.stale_retries < 0:
        raise ConfigError("'stale_retries' no puede ser negativo (0 lo desactiva).")
    if settings.dump_poll_seconds < 1:
        raise ConfigError("'dump_poll_seconds' debe ser al menos 1 segundo.")
    # Media hora ya no es esperar al siguiente volcado, es hacer la pasada de la
    # hora siguiente antes de tiempo, y en Actions el tiempo de trabajo se paga.
    if not 0 <= settings.espera_maxima_minutos <= 30:
        raise ConfigError(
            "'espera_maxima_minutos' va entre 0 (desactivado) y 30."
        )
    # Sin convertir con bool(): un "false" entre comillas es una cadena no
    # vacia, y bool() lo daria por verdadero, pausando justo al pedir lo
    # contrario.
    if not isinstance(settings.avisos_pausados, bool):
        raise ConfigError(
            "'avisos_pausados' va sin comillas: true o false "
            f"(vale {settings.avisos_pausados!r})."
        )
    for campo in ("silencio_desde", "silencio_hasta"):
        hora = getattr(settings, campo)
        if not 0 <= hora <= 23:
            raise ConfigError(
                f"'{campo}' es una hora del reloj: entre 0 y 23 (vale {hora})."
            )
    try:
        # Se comprueba al cargar y no al enviar: un nombre mal escrito debe
        # fallar aqui, no a las tres de la manana y en silencio.
        zona(settings.zona_horaria)
    except HoraInvalida as exc:
        raise ConfigError(f"'zona_horaria': {exc}") from exc

    if not 0 <= settings.ah_cut_pct < 100:
        raise ConfigError(
            "'ah_cut_pct' es el porcentaje que se queda la casa de subastas: "
            "entre 0 y 99."
        )
    if not 1 <= settings.listing_hours <= 48:
        raise ConfigError(
            "'listing_hours' son las horas de tus publicaciones: entre 1 y 48. "
            "Pon la duracion MAS CORTA que uses, no la habitual."
        )
    if settings.stale_retry_wait_seconds < 1:
        raise ConfigError("'stale_retry_wait_seconds' debe ser al menos 1 segundo.")

    return settings
