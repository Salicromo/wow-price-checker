"""Analisis del mercado de la region para decidir que objetos vigilar.

El vigilante de `scanner.py` responde a "esto esta por debajo de X", y la X la
pones tu a mano en el config. Este modulo hace lo de antes: mirar la region
entera y decir QUE objetos merecen una X, y cual deberia ser.

La regla es pura, igual que la de los chollos: recibe subastas ya descargadas
y devuelve resumenes, asi que se puede probar entera sin tocar la red.

Dos vistas, porque responden a preguntas distintas:

- `arbitrajes`: el mismo objeto esta tirado en un reino y caro en otro. Se
  compra alli, se pasa por el banco de hermandad de guerra y se vende aca. Es
  la vista principal.
- `flips_locales`: dentro de un mismo reino, la subasta mas barata esta muy por
  debajo de la siguiente. Se compra y se revende sin moverla de sitio, asi que
  no depende del banco ni de tener personaje en dos reinos.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping, Optional, Sequence

from .ilvl import resolve_ilvl

# Las mascotas enjauladas viajan todas dentro del mismo objeto "jaula": en las
# subastas, un Dragoncito Celestial y una Rata son los dos el item 82800, y lo
# que las distingue va en campos aparte. Por eso no se pueden tratar por
# item_id como todo lo demas.
JAULA_DE_MASCOTA = 82800

# Cuantos precios se guardan de cada objeto en cada reino. Con los cinco mas
# baratos se sabe cuantas copias se pueden comprar por debajo del precio de
# venta, que es lo que separa un chollo suelto de una operacion que merezca el
# viaje al banco.
MUESTRAS_POR_REINO = 5

TIPO_OBJETO = "objeto"
TIPO_MASCOTA = "mascota"


@dataclass(frozen=True, order=True)
class Clave:
    """Que es "el mismo producto" a efectos de comparar precios.

    No basta con el id. Una pieza de equipo a ilvl 295 y la misma a 337 son dos
    mercados distintos, y promediarlos daria un precio que no se cumple en
    ninguno de los dos. Con las mascotas pasa igual entre calidades: la version
    rara de una especie vale un multiplo de la comun.

    Por eso la clave lleva una `variante`, que segun el tipo es una cosa u otra:
    el ilvl en el equipo, la calidad en las mascotas, y nada en lo que no
    escala --monturas, juguetes, recetas--.
    """

    tipo: str  # TIPO_OBJETO o TIPO_MASCOTA
    id: int  # item_id, o pet_species_id si es una mascota
    variante: Optional[int] = None

    @property
    def es_mascota(self) -> bool:
        return self.tipo == TIPO_MASCOTA


@dataclass(frozen=True)
class ResumenReino:
    """Lo que hay que saber de un objeto en un reino, y nada mas.

    Se guardan unos pocos precios y no la lista entera a proposito: con la
    region al completo son millones de subastas, y para decidir una operacion
    solo hacen falta los mas baratos --lo que puedes comprar-- y cuantos hay
    en total --si el precio significa algo o es una subasta suelta--.
    """

    precios: tuple[int, ...]  # cobre por unidad, de menor a mayor
    listados: int

    @property
    def minimo(self) -> int:
        return self.precios[0]

    @property
    def segundo(self) -> int | None:
        return self.precios[1] if len(self.precios) > 1 else None

    def unidades_bajo(self, precio: int) -> int:
        """Cuantas de las subastas mas baratas estan por debajo de `precio`."""
        return sum(1 for p in self.precios if p < precio)


@dataclass(frozen=True)
class Arbitraje:
    """Comprar en un reino y vender en otro, pasando por el banco."""

    clave: Clave
    reino_compra: int
    precio_compra: int  # cobre
    unidades: int  # cuantas copias hay en el reino barato bajo el precio de venta
    reino_venta: int
    precio_venta: int  # cobre, la subasta mas barata del reino caro
    venta_tipica: int  # cobre, mediana de los minimos: lo que vale de verdad
    neto: int  # cobre que quedan tras la comision, vendiendo en el reino caro
    neto_tipico: int  # lo mismo vendiendo a precio de reino normalito
    reinos_con_dato: int
    reinos_rentables: int  # en cuantos reinos se podria colocar con beneficio

    @property
    def ratio(self) -> float:
        return self.precio_venta / self.precio_compra if self.precio_compra else 0.0


@dataclass(frozen=True)
class FlipLocal:
    """Comprar la subasta mas barata de un reino y revenderla en ese reino."""

    clave: Clave
    realm_id: int
    compra: int  # cobre
    referencia: int  # cobre al que se puede revender
    neto: int  # cobre tras la comision de la casa
    listados_reino: int
    reinos_con_dato: int

    @property
    def ratio(self) -> float:
        return self.referencia / self.compra if self.compra else 0.0


def resumir_reino(
    auctions: Sequence[Mapping],
    bonus_ilvl_map: Mapping[int, int],
    precio_minimo: int = 0,
    muestras: int = MUESTRAS_POR_REINO,
) -> dict[Clave, ResumenReino]:
    """Resume las subastas de un reino a unos pocos precios por objeto.

    `precio_minimo` (en cobre, por unidad) descarta la morralla antes de
    agregar. No es cosmetico: sin el, cada reino grande aporta decenas de miles
    de objetos de dos monedas que no vas a comprar jamas, y la region entera no
    cabe en memoria.
    """
    baratos: dict[Clave, list[int]] = {}
    conteo: dict[Clave, int] = {}

    for auction in auctions:
        item_obj = auction.get("item") or {}
        item_id = item_obj.get("id")
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            continue
        # Solo compra directa, por lo mismo que en los chollos: una subasta que
        # solo admite pujas no se puede comprar ya, y tomar la puja por precio
        # inventaria margenes que no existen.
        buyout = auction.get("buyout")
        if not isinstance(buyout, int) or isinstance(buyout, bool) or buyout <= 0:
            continue

        cantidad = auction.get("quantity")
        if not isinstance(cantidad, int) or isinstance(cantidad, bool) or cantidad <= 0:
            cantidad = 1
        unidad = buyout // cantidad
        if unidad < precio_minimo:
            continue

        clave = _clave_de(item_obj, item_id, bonus_ilvl_map)
        if clave is None:
            continue
        conteo[clave] = conteo.get(clave, 0) + 1

        lista = baratos.setdefault(clave, [])
        lista.append(unidad)
        if len(lista) > muestras:
            lista.sort()
            del lista[muestras:]

    return {
        clave: ResumenReino(precios=tuple(sorted(precios)), listados=conteo[clave])
        for clave, precios in baratos.items()
    }


def _clave_de(
    item_obj: Mapping, item_id: int, bonus_ilvl_map: Mapping[int, int]
) -> Clave | None:
    """De que producto es esta subasta.

    Las mascotas son el caso raro: todas son el item 82800, asi que hay que
    mirar `pet_species_id` para saber cual es. Si viene la jaula sin especie no
    hay forma de saberlo, y se descarta: meterla como "item 82800" mezclaria en
    un mismo precio todas las mascotas del juego.
    """
    if item_id == JAULA_DE_MASCOTA:
        especie = item_obj.get("pet_species_id")
        if not isinstance(especie, int) or isinstance(especie, bool):
            return None
        calidad = item_obj.get("pet_quality_id")
        return Clave(
            TIPO_MASCOTA,
            especie,
            calidad if isinstance(calidad, int) and not isinstance(calidad, bool) else None,
        )

    return Clave(TIPO_OBJETO, item_id, resolve_ilvl(item_obj, bonus_ilvl_map).value)


def agregar(
    por_reino: Iterable[tuple[int, Mapping[Clave, ResumenReino]]],
) -> dict[Clave, dict[int, ResumenReino]]:
    """Junta los resumenes de cada reino en {objeto: {reino: resumen}}."""
    agregado: dict[Clave, dict[int, ResumenReino]] = {}
    for realm_id, resumen in por_reino:
        for clave, datos in resumen.items():
            agregado.setdefault(clave, {})[realm_id] = datos
    return agregado


def arbitrajes(
    agregado: Mapping[Clave, Mapping[int, ResumenReino]],
    comision_pct: int = 5,
    beneficio_minimo: int = 0,
    ratio_minimo: float = 2.0,
    reinos_minimos: int = 10,
    listados_minimos_venta: int = 2,
    reinos_rentables_minimos: int = 5,
    valor_minimo: int = 0,
    venta_maxima: int = 0,
) -> list[Arbitraje]:
    """Objetos que se compran barato en un reino y se venden caro en otro.

    El reino de compra es el mas barato de la region. El de venta NO es sin mas
    el mas caro: se exige que ese reino tenga varias subastas del objeto
    (`listados_minimos_venta`), porque un reino con una sola subasta a precio de
    fantasia no es un mercado --nadie la ha comprado, y tu tampoco venderias--.

    Aun asi el reino mas caro es mal numero para decidir, porque en las
    subastas no se ve a que se VENDE algo, solo a que se PIDE, y siempre hay
    quien aparca un objeto a 9.999.999 para que no se lo compren. Por eso se
    ordena por `venta_tipica`, la mediana de los minimos de la region: con 30 o
    40 reinos hace falta que la mitad larga este de acuerdo para moverla, asi
    que un pufio suelto no la despeina.

    `reinos_rentables_minimos` remata la faena: si el objeto solo da beneficio
    en dos reinos de cuarenta, lo que hay no es un mercado caro, son dos
    listados raros.

    `venta_maxima` descarta lo que ni siquiera la mediana salva: objetos cuyo
    precio en media region es 9.999.999, que no es un precio sino un aparcamiento
    --se publica para que NO lo compren, y sale en la mediana igual que uno de
    verdad porque quien aparca lo hace en todos los reinos a la vez--.

    `valor_minimo` corta por abajo: solo productos que valgan de verdad. Sin el,
    la lista se llena de cosas de 20.000 oro con un 10x precioso que no pagan ni
    el rato de ir al banco.
    """
    resultado: list[Arbitraje] = []
    cobro = (100 - comision_pct) / 100

    for clave, por_realm in agregado.items():
        if len(por_realm) < reinos_minimos:
            continue

        minimos = sorted(d.minimo for d in por_realm.values())
        reino_compra = min(por_realm, key=lambda r: por_realm[r].minimo)
        precio_compra = por_realm[reino_compra].minimo
        if precio_compra <= 0:
            continue

        # Vender exige mercado: un reino con una sola subasta no dice a que se
        # vende, solo a que se ha atrevido a pedir alguien.
        vendibles = {
            r: d
            for r, d in por_realm.items()
            if r != reino_compra and d.listados >= listados_minimos_venta
        }
        if not vendibles:
            continue

        reino_venta = max(vendibles, key=lambda r: vendibles[r].minimo)
        precio_venta = vendibles[reino_venta].minimo

        venta_tipica = percentil(minimos, 50)
        if venta_tipica < valor_minimo:
            continue
        if venta_maxima and venta_tipica > venta_maxima:
            continue

        neto = int(precio_venta * cobro) - precio_compra
        neto_tipico = int(venta_tipica * cobro) - precio_compra

        if neto_tipico < beneficio_minimo:
            continue
        if venta_tipica / precio_compra < ratio_minimo:
            continue

        rentables = sum(
            1
            for d in vendibles.values()
            if int(d.minimo * cobro) - precio_compra >= beneficio_minimo
        )
        if rentables < reinos_rentables_minimos:
            continue

        resultado.append(
            Arbitraje(
                clave=clave,
                reino_compra=reino_compra,
                precio_compra=precio_compra,
                unidades=por_realm[reino_compra].unidades_bajo(
                    int(venta_tipica * cobro)
                ),
                reino_venta=reino_venta,
                precio_venta=precio_venta,
                venta_tipica=venta_tipica,
                neto=neto,
                neto_tipico=neto_tipico,
                reinos_con_dato=len(por_realm),
                reinos_rentables=rentables,
            )
        )

    resultado.sort(key=lambda a: a.neto_tipico, reverse=True)
    return resultado


def flips_locales(
    agregado: Mapping[Clave, Mapping[int, ResumenReino]],
    comision_pct: int = 5,
    beneficio_minimo: int = 0,
    ratio_minimo: float = 2.0,
    reinos_minimos: int = 10,
) -> list[FlipLocal]:
    """Subastas muy por debajo de lo que se puede revender en su propio reino.

    El precio de reventa es el mas prudente de dos: la siguiente subasta del
    mismo reino --que es contra quien competirias-- y la mediana de los minimos
    de la region --que es lo que vale el objeto cuando el reino tiene una sola
    subasta y su precio no dice nada--. Quedarse con el menor evita el fallo
    clasico: un reino con un unico listado a precio de fantasia generaria un
    beneficio enorme que no cobrarias nunca.
    """
    resultado: list[FlipLocal] = []
    cobro = (100 - comision_pct) / 100

    for clave, por_realm in agregado.items():
        if len(por_realm) < reinos_minimos:
            continue

        mediana = int(median(sorted(d.minimo for d in por_realm.values())))

        for realm_id, datos in por_realm.items():
            referencia = mediana if datos.segundo is None else min(datos.segundo, mediana)
            neto = int(referencia * cobro) - datos.minimo
            if neto < beneficio_minimo:
                continue
            if datos.minimo <= 0 or referencia / datos.minimo < ratio_minimo:
                continue

            resultado.append(
                FlipLocal(
                    clave=clave,
                    realm_id=realm_id,
                    compra=datos.minimo,
                    referencia=referencia,
                    neto=neto,
                    listados_reino=datos.listados,
                    reinos_con_dato=len(por_realm),
                )
            )

    resultado.sort(key=lambda f: f.neto, reverse=True)
    return resultado


def percentil(ordenados: Sequence[int], pct: int) -> int:
    """Percentil por el metodo del mas cercano, sobre una lista ya ordenada.

    Sin interpolar a proposito: asi el resultado es un precio que existe de
    verdad en algun reino, mas facil de justificar como umbral del config que
    una media entre dos.
    """
    if not ordenados:
        return 0
    indice = max(0, min(len(ordenados) - 1, round(pct / 100 * (len(ordenados) - 1))))
    return ordenados[indice]
