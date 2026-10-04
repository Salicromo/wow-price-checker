"""Cliente de la API de Blizzard (OAuth + datos de juego).

Todo el trato con la red vive aqui: obtencion del token, reintentos con espera
progresiva y traduccion de errores HTTP a excepciones con mensaje claro. El
resto del programa no sabe que existe `requests`.
"""

from __future__ import annotations

import email.utils
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth.battle.net/token"

# Codigos que merecen reintento: limite de peticiones y caidas temporales.
# El 403 esta aqui a proposito, aunque en general signifique "no tienes permiso"
# y reintentar no arregle nada. Con Blizzard es pasajero: un problema de verdad
# con las credenciales sale como 401 al pedir el token, y eso se trata aparte
# como BlizzardAuthError. El 2026-09-02 a las 07:25 UTC toda la API respondio
# 403 durante un minuto --busquedas, indice de reinos, todo-- y la pasada murio
# en 21 segundos sin reintentar ni una vez, cuando a las 06:25 y a las 07:52 iba
# perfecta. Una hora sin vigilancia por un mal rato de su CDN.
RETRYABLE_STATUS = frozenset({403, 429, 500, 502, 503, 504})


class BlizzardError(Exception):
    """Fallo al hablar con la API de Blizzard."""


class BlizzardAuthError(BlizzardError):
    """Las credenciales no valen. Reintentar no arregla esto."""


@dataclass(frozen=True)
class AuctionSnapshot:
    """Las subastas de un reino, con la hora del volcado que las genero.

    Blizzard regenera los datos de la casa de subastas una vez por hora y pone
    esa hora en la cabecera Last-Modified. Saberla permite comprobar si el cron
    esta bien alineado o si esta leyendo datos de hace casi una hora.
    """

    auctions: list[dict]
    taken_at: datetime | None


class BlizzardClient:
    """Acceso de solo lectura a los datos de juego de una region."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        region: str = "eu",
        locale: str = "en_GB",
        timeout: int = 45,
        max_retries: int = 3,
        session: requests.Session | None = None,
        sleep: Any = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region
        self.locale = locale
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self._sleep = sleep if sleep is not None else time.sleep
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- Autenticacion ------------------------------------------------------

    @property
    def token(self) -> str:
        """Token de acceso, pidiendolo solo cuando hace falta."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        if not self.client_id or not self.client_secret:
            raise BlizzardAuthError(
                "Faltan BLIZZARD_CLIENT_ID y/o BLIZZARD_CLIENT_SECRET.\n"
                "Crealos en https://develop.battle.net/access/clients y ponlos "
                "en el fichero .env (en local) o en los secrets del repositorio "
                "(en GitHub Actions)."
            )

        response = self._request(
            "POST",
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            authenticated=False,
        )

        if response.status_code in (400, 401, 403):
            raise BlizzardAuthError(
                f"Blizzard rechaza las credenciales (HTTP {response.status_code}). "
                "Revisa BLIZZARD_CLIENT_ID y BLIZZARD_CLIENT_SECRET."
            )
        if response.status_code != 200:
            raise BlizzardError(
                f"No he podido obtener el token: HTTP {response.status_code}."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise BlizzardError("La respuesta del token no incluye 'access_token'.")

        # Margen de 60 s para no usar un token que caduque a mitad del escaneo.
        expires_in = int(payload.get("expires_in", 3600))
        self._token = token
        self._token_expires_at = time.monotonic() + max(expires_in - 60, 60)
        log.debug("Token obtenido, valido %s s", expires_in)
        return token

    # -- Endpoints ----------------------------------------------------------

    def search_item_id(self, name: str) -> int | None:
        """Busca el id de un objeto por su nombre exacto en ingles.

        Devuelve None si Blizzard no tiene ninguna coincidencia exacta: puede
        que el nombre este mal escrito o que el objeto ya no exista.
        """
        name_field = f"name.{self.locale}"
        response = self._api_get(
            "/data/wow/search/item",
            namespace=f"static-{self.region}",
            params={name_field: name, "_pageSize": 100},
        )
        if response.status_code != 200:
            raise BlizzardError(
                f"Busqueda de {name!r} fallida: HTTP {response.status_code}."
            )

        for result in response.json().get("results", []):
            data = result.get("data", {})
            names = data.get("name", {})
            found = names.get(self.locale) if isinstance(names, dict) else names
            if isinstance(found, str) and found.strip().lower() == name.strip().lower():
                item_id = data.get("id")
                if isinstance(item_id, int):
                    return item_id
        return None

    def item_icon_url(self, item_id: int) -> str | None:
        """URL publica del icono de un objeto, para la miniatura del aviso.

        Devuelve None si no se puede obtener: un aviso sin icono sigue siendo
        util, asi que esto nunca debe tumbar una notificacion.
        """
        try:
            response = self._api_get(
                f"/data/wow/media/item/{item_id}", namespace=f"static-{self.region}"
            )
            if response.status_code != 200:
                return None
            for asset in response.json().get("assets", []):
                if asset.get("key") == "icon" and isinstance(asset.get("value"), str):
                    return asset["value"]
        except BlizzardError as exc:
            log.debug("Sin icono para el objeto %s: %s", item_id, exc)
        return None

    def item_name(self, item_id: int) -> str | None:
        """Nombre de un objeto a partir de su id.

        El camino inverso de `search_item_id`, para cuando el id sale de los
        datos de subastas y lo que falta es como se llama. Devuelve None si no
        se puede saber: quien llama siempre tiene el id para enseñar.
        """
        try:
            response = self._api_get(
                f"/data/wow/item/{item_id}", namespace=f"static-{self.region}"
            )
            if response.status_code != 200:
                return None
            name = response.json().get("name")
            if isinstance(name, dict):
                name = name.get(self.locale)
            return name if isinstance(name, str) and name else None
        except BlizzardError as exc:
            log.debug("Sin nombre para el objeto %s: %s", item_id, exc)
            return None

    def item_datos(self, item_id: int) -> dict | None:
        """Nombre y atributos de un objeto, en una sola peticion.

        La respuesta de `/data/wow/item/{id}` trae, ademas del nombre en ocho
        idiomas, justo lo que la casa de subastas usa para filtrar: categoria,
        subcategoria, calidad, hueco de equipo y niveles. `item_names` pedia
        esta misma respuesta y descartaba todo menos `name`; esto la aprovecha
        entera, asi que los filtros no cuestan ni una peticion mas.

        `item_names` se conserva porque el vigilante (`main.py`) solo quiere el
        nombre y no tiene por que cargar con el resto.

        La categoria se devuelve **en ingles**: de ella salen las URLs
        (`/items/armor/mail`), y esas no cambian con el idioma del visitante.

        Devuelve None si el objeto no responde o si no trae categoria: sin ella
        no se puede colocar en ninguna pagina, y una fila a medias solo
        obligaria a filtrarla en cada consulta.
        """
        try:
            response = self._api_get(
                f"/data/wow/item/{item_id}",
                namespace=f"static-{self.region}",
                localized=False,
            )
            if response.status_code != 200:
                return None
            doc = response.json()
        except BlizzardError as exc:
            log.debug("Sin datos para el objeto %s: %s", item_id, exc)
            return None

        clase = _categoria(doc.get("item_class"))
        subclase = _categoria(doc.get("item_subclass"))
        if clase is None or subclase is None:
            return None

        return {
            "nombres": _nombres(doc.get("name"), self.locale),
            "clase_id": clase[0],
            "clase": clase[1],
            "subclase_id": subclase[0],
            "subclase": subclase[1],
            "calidad": _tipo(doc.get("quality")),
            # NON_EQUIP es como Blizzard dice "esto no se equipa" (una pocion,
            # una receta). Guardarlo seria un hueco de equipo que no existe.
            "hueco": _tipo(doc.get("inventory_type"), descartar="NON_EQUIP"),
            "nivel": doc.get("level"),
            "nivel_requerido": doc.get("required_level"),
        }

    def item_names(self, item_id: int) -> dict[str, str]:
        """Todos los idiomas de golpe, para las páginas de la web pública.

        Es la misma petición que `item_name`: sin locale, Blizzard devuelve el
        nombre ya traducido a todos los idiomas y `item_name` se queda con
        uno. Pedir ocho veces el mismo objeto para sacar ocho idiomas sería
        tirar siete peticiones, y son veinte mil objetos.
        """
        try:
            # Sin locale: con locale Blizzard colapsa la respuesta a un solo
            # idioma, justo lo que este metodo existe para evitar (mismo
            # motivo que `connected_realm_name`).
            response = self._api_get(
                f"/data/wow/item/{item_id}",
                namespace=f"static-{self.region}",
                localized=False,
            )
            if response.status_code != 200:
                return {}
            name = response.json().get("name")
            if isinstance(name, dict):
                return {
                    idioma: texto
                    for idioma, texto in name.items()
                    if isinstance(texto, str) and texto
                }
            if isinstance(name, str) and name:
                return {self.locale: name}
            return {}
        except BlizzardError as exc:
            log.debug("Sin nombres para el objeto %s: %s", item_id, exc)
            return {}

    def pet_species_name(self, species_id: int) -> str | None:
        """Nombre de una especie de mascota.

        En las subastas las mascotas no traen nombre: todas son el objeto
        "jaula" y lo unico que las distingue es este id de especie.
        """
        try:
            response = self._api_get(
                f"/data/wow/pet/{species_id}", namespace=f"static-{self.region}"
            )
            if response.status_code != 200:
                return None
            name = response.json().get("name")
            if isinstance(name, dict):
                name = name.get(self.locale)
            return name if isinstance(name, str) and name else None
        except BlizzardError as exc:
            log.debug("Sin nombre para la especie %s: %s", species_id, exc)
            return None

    def pet_species_names(self, species_id: int) -> dict[str, str]:
        """Todos los idiomas de una especie, como `item_names` con los objetos.

        Hace falta para el panel de ventas: Journalator apunta el nombre que ve
        tu cliente, y comparando contra todos los idiomas da igual en cual
        juegues.
        """
        try:
            response = self._api_get(
                f"/data/wow/pet/{species_id}",
                namespace=f"static-{self.region}",
                localized=False,
            )
            if response.status_code != 200:
                return {}
            name = response.json().get("name")
            if isinstance(name, dict):
                return {
                    idioma: texto
                    for idioma, texto in name.items()
                    if isinstance(texto, str) and texto
                }
            if isinstance(name, str) and name:
                return {self.locale: name}
            return {}
        except BlizzardError as exc:
            log.debug("Sin nombres para la especie %s: %s", species_id, exc)
            return {}

    def item_ids_por_subclase(self, item_class_id: int, item_subclass_id: int) -> list[int]:
        """Todos los ids de objeto de una clase/subclase (p. ej. monturas).

        La busqueda devuelve como mucho 1000 resultados por peticion y no dice
        cuantos hay en total, asi que se avanza por id: cada vuelta pide los
        siguientes al ultimo visto. Cuando una vuelta devuelve menos de 1000,
        se acabaron.
        """
        ids: list[int] = []
        ultimo = 0

        while True:
            response = self._api_get(
                "/data/wow/search/item",
                namespace=f"static-{self.region}",
                params={
                    "item_class.id": item_class_id,
                    "item_subclass.id": item_subclass_id,
                    "id": f"[{ultimo + 1},]",
                    "orderby": "id",
                    "_pageSize": 1000,
                },
            )
            if response.status_code != 200:
                raise BlizzardError(
                    f"Busqueda de la subclase {item_class_id}/{item_subclass_id}: "
                    f"HTTP {response.status_code}."
                )

            pagina = [
                r["data"]["id"]
                for r in response.json().get("results", [])
                if isinstance((r.get("data") or {}).get("id"), int)
            ]
            if not pagina:
                return ids

            ids.extend(pagina)
            ultimo = pagina[-1]
            if len(pagina) < 1000:
                return ids

    def toy_ids(self) -> list[int]:
        """Ids de juguete del indice. No son ids de objeto: ver `toy_item_id`."""
        response = self._api_get(
            "/data/wow/toy/index", namespace=f"static-{self.region}"
        )
        if response.status_code != 200:
            raise BlizzardError(f"Indice de juguetes: HTTP {response.status_code}.")
        return [
            toy["id"]
            for toy in response.json().get("toys", [])
            if isinstance(toy.get("id"), int)
        ]

    def toy_item_id(self, toy_id: int) -> int | None:
        """El objeto al que corresponde un juguete.

        Blizzard numera los juguetes en su propio indice, que no tiene nada que
        ver con los ids de objeto que salen en las subastas. Esta es la unica
        forma de cruzarlos.
        """
        try:
            response = self._api_get(
                f"/data/wow/toy/{toy_id}", namespace=f"static-{self.region}"
            )
            if response.status_code != 200:
                return None
            item_id = (response.json().get("item") or {}).get("id")
            return item_id if isinstance(item_id, int) else None
        except BlizzardError as exc:
            log.debug("Sin objeto para el juguete %s: %s", toy_id, exc)
            return None

    def connected_realm_ids(self) -> list[int]:
        """Ids de todos los connected realms de la region."""
        response = self._api_get(
            "/data/wow/connected-realm/index", namespace=f"dynamic-{self.region}"
        )
        if response.status_code != 200:
            raise BlizzardError(
                f"No he podido listar los reinos: HTTP {response.status_code}."
            )

        realm_ids: list[int] = []
        for entry in response.json().get("connected_realms", []):
            realm_id = _realm_id_from_href(entry.get("href", ""))
            if realm_id is not None:
                realm_ids.append(realm_id)
        return sorted(set(realm_ids))

    def connected_realm_name(self, realm_id: int) -> str:
        """Nombre legible de un connected realm ('Silvermoon / Kazzak').

        Solo se pide para los reinos donde ha aparecido un chollo, para no
        gastar 250 peticiones extra en cada pasada.
        """
        try:
            # Sin locale: asi llega el nombre en todos los idiomas y cada reino
            # puede mostrarse en el suyo.
            response = self._api_get(
                f"/data/wow/connected-realm/{realm_id}",
                namespace=f"dynamic-{self.region}",
                localized=False,
            )
            if response.status_code != 200:
                return f"Reino {realm_id}"

            names: list[str] = []
            for realm in response.json().get("realms", []):
                name = _realm_display_name(realm, self.locale)
                if name:
                    names.append(name)
            if names:
                return " / ".join(dict.fromkeys(names))
        except BlizzardError:
            log.warning("No he podido leer el nombre del reino %s", realm_id)
        return f"Reino {realm_id}"

    def connected_realm_ficha(self, realm_id: int) -> tuple[str, list[str]] | None:
        """Nombre legible y slugs de los reinos de un connected realm.

        Lo mismo que `connected_realm_name`, pero con los slugs, que es lo que
        permite cruzar el grupo con los reinos de tus personajes. None si no se
        ha podido leer, para que quien llame no cachee un nombre de mentira.
        """
        try:
            response = self._api_get(
                f"/data/wow/connected-realm/{realm_id}",
                namespace=f"dynamic-{self.region}",
                localized=False,
            )
        except BlizzardError:
            return None
        if response.status_code != 200:
            return None

        nombres: list[str] = []
        slugs: list[str] = []
        for realm in response.json().get("realms", []):
            nombre = _realm_display_name(realm, self.locale)
            if nombre:
                nombres.append(nombre)
            if isinstance(realm.get("slug"), str) and realm["slug"]:
                slugs.append(realm["slug"])
        if not nombres:
            return None
        return " / ".join(dict.fromkeys(nombres)), sorted(set(slugs))

    def connected_realm_id_for(self, realm_slug: str) -> int | None:
        """Connected realm al que pertenece un reino, por su slug.

        Devuelve None si Blizzard no conoce ese slug, que es lo normal cuando
        el nombre del reino lleva caracteres que no sobreviven al slug.
        """
        response = self._api_get(
            f"/data/wow/realm/{realm_slug}", namespace=f"dynamic-{self.region}"
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise BlizzardError(
                f"Consulta del reino {realm_slug!r}: HTTP {response.status_code}."
            )
        href = (response.json().get("connected_realm") or {}).get("href", "")
        return _realm_id_from_href(href)

    def realm_index(self) -> list[dict]:
        """Todos los reinos de la region, con su slug oficial y todos sus nombres.

        Es la red de seguridad de `connected_realm_id_for`: una sola peticion
        que permite dar con el slug bueno cuando el deducido del nombre no
        acierta. Se pide sin locale para que lleguen los nombres en todos los
        idiomas: un reino ruso se llama 'Ревущий фьорд' en el juego, pero su
        slug es una transliteracion que no hay forma de deducir del nombre. El
        indice no trae el connected realm, asi que despues hay que volver a
        preguntar con el slug correcto.
        """
        response = self._api_get(
            "/data/wow/realm/index",
            namespace=f"dynamic-{self.region}",
            localized=False,
        )
        if response.status_code != 200:
            raise BlizzardError(
                f"No he podido listar los reinos: HTTP {response.status_code}."
            )

        reinos: list[dict] = []
        for realm in response.json().get("realms", []):
            slug = realm.get("slug")
            if not isinstance(slug, str):
                continue
            nombre = realm.get("name")
            if isinstance(nombre, dict):
                nombres = [v for v in nombre.values() if isinstance(v, str) and v]
            elif isinstance(nombre, str) and nombre:
                nombres = [nombre]
            else:
                nombres = []
            reinos.append({"slug": slug, "names": nombres or [slug]})
        return reinos

    def auctions(self, realm_id: int) -> AuctionSnapshot:
        """Todas las subastas de equipo de un connected realm."""
        response = self._api_get(
            f"/data/wow/connected-realm/{realm_id}/auctions",
            namespace=f"dynamic-{self.region}",
        )
        if response.status_code != 200:
            raise BlizzardError(
                f"Subastas del reino {realm_id}: HTTP {response.status_code}."
            )
        auctions = response.json().get("auctions", [])
        if not isinstance(auctions, list):
            raise BlizzardError(
                f"Subastas del reino {realm_id}: respuesta con formato inesperado."
            )
        return AuctionSnapshot(auctions, _parse_http_date(response.headers.get("Last-Modified")))

    def auction_dump_time(self, realm_id: int) -> datetime | None:
        """Cuando publico Blizzard el volcado vigente, SIN bajarselo.

        Es el reloj para saber si ya ha salido el de esta hora. Preguntarlo
        bajando los datos saldria carisimo: un reino grande son 14 MB y la
        region entera casi medio giga. Aqui se abre la respuesta, se lee la
        cabecera y se corta antes de tocar el cuerpo, asi que cuesta unos 0,4 s
        y unos pocos KB.

        Las dos formas ortodoxas de preguntar esto no sirven, comprobado contra
        la API el 2026-09-02: a HEAD responde 404, y `If-Modified-Since` lo
        ignora y manda los 14 MB con un 200 igualmente.

        Devuelve None si no se puede saber, que es lo mismo que decir "no me
        consta que haya salido nada nuevo": quien llama se lo toma como que
        todavia no toca, nunca como que hay datos frescos.
        """
        response = self._api_get(
            f"/data/wow/connected-realm/{realm_id}/auctions",
            namespace=f"dynamic-{self.region}",
            stream=True,
        )
        try:
            if response.status_code != 200:
                return None
            return _parse_http_date(response.headers.get("Last-Modified"))
        finally:
            response.close()

    # -- Fontaneria HTTP ----------------------------------------------------

    def _api_get(
        self,
        path: str,
        *,
        namespace: str,
        params: dict | None = None,
        localized: bool = True,
        stream: bool = False,
    ) -> requests.Response:
        """Peticion a la API de datos.

        Con `localized=False` no se manda el parametro locale y Blizzard
        devuelve los textos en todos los idiomas, que es lo que hace falta para
        elegir el nombre de un reino en su propia lengua.
        """
        url = f"https://{self.region}.api.blizzard.com{path}"
        query = {"namespace": namespace}
        if localized:
            query["locale"] = self.locale
        query.update(params or {})
        return self._request("GET", url, params=query, stream=stream)

    def _request(
        self, method: str, url: str, *, authenticated: bool = True, **kwargs: Any
    ) -> requests.Response:
        """Peticion con reintentos y espera progresiva ante fallos pasajeros."""
        if authenticated:
            headers = dict(kwargs.pop("headers", None) or {})
            headers["Authorization"] = f"Bearer {self.token}"
            kwargs["headers"] = headers

        kwargs.setdefault("timeout", self.timeout)
        last_error: str = "motivo desconocido"

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_error = f"HTTP {response.status_code}"
                if attempt < self.max_retries:
                    self._sleep(_retry_delay(attempt, response))
                    continue
                return response

            if attempt < self.max_retries:
                self._sleep(_retry_delay(attempt, None))

        raise BlizzardError(
            f"{method} {url} ha fallado tras {self.max_retries + 1} intentos: {last_error}"
        )


def _retry_delay(attempt: int, response: requests.Response | None) -> float:
    """Segundos de espera: lo que pida Blizzard, o espera progresiva."""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
    return float(2**attempt)


def _realm_display_name(realm: dict, fallback_locale: str) -> str | None:
    """Nombre de un reino en su propio idioma.

    Los reinos rusos se llaman 'Ревущий фьорд' o 'Гордунни', no por su
    transliteracion inglesa, y asi es como aparecen en el juego a quien juega
    ahi. Blizzard indica el idioma de cada reino en su campo 'locale' (con el
    formato 'ruRU', sin guion bajo), distinto del que usan las claves del
    diccionario de nombres ('ru_RU').
    """
    name = realm.get("name")
    if isinstance(name, str):
        return name or None
    if not isinstance(name, dict):
        return None

    candidatos: list[str] = []
    propio = str(realm.get("locale") or "")
    if len(propio) == 4:
        candidatos.append(f"{propio[:2]}_{propio[2:]}")
    candidatos.append(fallback_locale)

    for clave in candidatos:
        valor = name.get(clave)
        if isinstance(valor, str) and valor:
            return valor

    # Ultimo recurso: cualquier idioma antes que quedarnos sin nombre.
    for valor in name.values():
        if isinstance(valor, str) and valor:
            return valor
    return None


def _parse_http_date(value: str | None) -> datetime | None:
    """Convierte una cabecera de fecha HTTP en datetime, o None si no se puede."""
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _realm_id_from_href(href: str) -> int | None:
    """Extrae el id de una URL '.../connected-realm/1305?namespace=...'."""
    marker = "/connected-realm/"
    if marker not in href:
        return None
    tail = href.split(marker, 1)[1]
    digits = tail.split("?", 1)[0].strip("/")
    return int(digits) if digits.isdigit() else None


def _categoria(campo) -> tuple[int, str] | None:
    """(id, nombre en ingles) de un `item_class` / `item_subclass`.

    El nombre en ingles y no el localizado porque de aqui salen las URLs. Si
    en_GB no viniera se cae a en_US, que es el otro ingles que manda Blizzard.
    """
    if not isinstance(campo, dict):
        return None
    id_ = campo.get("id")
    nombre = campo.get("name")
    if isinstance(nombre, dict):
        nombre = nombre.get("en_GB") or nombre.get("en_US")
    if not isinstance(id_, int) or not isinstance(nombre, str) or not nombre:
        return None
    return id_, nombre


def _tipo(campo, descartar: str | None = None) -> str | None:
    """El `type` de un campo enumerado de Blizzard (EPIC, FEET, ...).

    Es el valor estable: el `name` del mismo campo viene traducido y cambia.
    """
    if not isinstance(campo, dict):
        return None
    valor = campo.get("type")
    if not isinstance(valor, str) or not valor or valor == descartar:
        return None
    return valor


def _nombres(campo, locale: str) -> dict[str, str]:
    """Los nombres por idioma, o el suelto en el locale del cliente.

    Mismo criterio que `item_names`, con el que comparte respuesta.
    """
    if isinstance(campo, dict):
        return {
            idioma: texto
            for idioma, texto in campo.items()
            if isinstance(texto, str) and texto
        }
    if isinstance(campo, str) and campo:
        return {locale: campo}
    return {}
