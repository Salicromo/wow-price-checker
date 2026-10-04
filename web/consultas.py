"""Lecturas de la web pública. Funciones puras sobre una conexión."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Optional

from wowalerts.config import COPPER_PER_GOLD
from web.ingesta import SIN_VARIANTE

log = logging.getLogger("web.consultas")

# Cuántos reinos ve quien no paga. El corte se aplica aquí, en la consulta, y
# no en la plantilla: lo que no se pregunta no se envía, así que no queda nada
# en el HTML que se pueda descubrir quitando un estilo.
REINOS_GRATIS = 5

# A partir de cuántos reinos una mediana significa "lo que cuesta
# normalmente". Por debajo no es un precio típico: con dos reinos es el más
# caro de los dos, y con uno es el único precio que existe. La ficha no puede
# presentar eso como el precio normal, porque no lo sabe.
#
# No es un caso raro. En una base de dos reinos, 5.034 de 16.239 productos
# tenían datos de un solo reino; en la región entera son menos --269 de
# 20.144-- pero siguen siendo cientos de páginas afirmando lo que no consta.
#
# `productos_de_reino` ya tiene este mismo guardia con su propio umbral (15),
# y por la misma razón: no comparar contra una mediana que no significa nada.
REINOS_PARA_MEDIANA = 5

# Cuántos reinos hacen falta para que "está rebajado respecto a lo normal"
# signifique algo. Es un listón más alto que `REINOS_PARA_MEDIANA` porque aquí
# la mediana no se enseña, se usa para ordenar: una mediana floja no confunde
# a nadie, pero sí llena la portada y la página de reino de productos que solo
# existen en cuatro sitios y cuya "rebaja" es ruido.
#
# El valor es el de producción, con 92 reinos en la región. Se pasa como
# parámetro y no se lee dentro de las consultas para que los tests con una
# región de juguete puedan bajarlo sin tocar el criterio real.
REINOS_PARA_COMPARAR = 15

# El maximo que se puede teclear en la casa de subastas: 9.999.999 de oro.
# Una mediana clavada ahi no es un precio, es un "no quiero venderlo" -- y como
# es enorme, hace que cualquier reino con un precio real parezca una ganga del
# 99%. Medido sobre el volcado de los 92 reinos: 68 variantes de 20.138 tienen
# la mediana en el tope, y se comian 7 de las 12 filas de la portada.
TOPE_CDS = 9_999_999 * COPPER_PER_GOLD

# El descuento mas alto que se considera creible. Por encima de esto, en la
# region entera, no hay gangas: hay medianas rotas por objetos que alguien
# lista a precio de fantasia en medio mundo (4.000.000g por un huevo de
# murloc). En el volcado real son 777 filas al 99% o mas, y ninguna era una
# oferta.
#
# El corte quita basura, no mercancia: por debajo de el siguen quedando 6.798
# filas entre el 95% y el 99%, y 12.265 entre el 90% y el 95%.
DESCUENTO_MAXIMO = 95

# Cuantas filas se piden por cada hueco de la lista para poder quedarse con
# un solo reino por producto. Ver `mejores_rebajas`: con datos reales las 12
# filas se llenan ya con holgura 5, y subir a 20 no costaba tiempo medible
# (385 ms frente a 363 ms), asi que 10 es holgura de sobra sin pagar nada.
HOLGURA_DEDUPE = 10

IDIOMA_POR_DEFECTO = "en"

# Los comodines de LIKE, neutralizados con "!" delante. Un "%" tecleado en
# la caja de busqueda no puede convertirse en "damelo todo".
_ESCAPAR_LIKE = str.maketrans({"!": "!!", "%": "!%", "_": "!_"})


def ficha(
    con: sqlite3.Connection,
    tipo: str,
    producto_id: int,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> Optional[dict[str, Any]]:
    """Cabecera del producto y sus variantes con estadísticas.

    Devuelve None si de ese producto no hay nada en el último volcado, que es
    lo que la ruta convierte en un 404.
    """
    variantes = []
    for fila in con.execute(
        "SELECT variante, mediana, minimo, maximo, reinos "
        "  FROM estadistica "
        " WHERE tipo = ? AND producto_id = ? "
        " ORDER BY variante",
        (tipo, producto_id),
    ):
        variante = dict(fila)
        # La decisión se toma aquí y no en la plantilla para poder probarla:
        # una condición escrita en Jinja no la cubre ningún test.
        variante["mediana_fiable"] = variante["reinos"] >= REINOS_PARA_MEDIANA
        variantes.append(variante)

    if not variantes:
        return None

    fila = con.execute(
        "SELECT nombre, icono FROM nombre "
        " WHERE tipo = ? AND producto_id = ? AND idioma = ?",
        (tipo, producto_id, idioma),
    ).fetchone()

    # Si `volcado` está vacío la base quedó inconsistente (no es el camino
    # normal, porque `volcar` escribe precio y volcado en la misma
    # transacción): mejor una ficha sin fecha que un 500 para quien la ve.
    volcado = con.execute("SELECT generado_en FROM volcado").fetchone()

    # La calidad va aparte de `nombre` porque no es del idioma: sale de
    # `atributo`, que tiene una fila por producto. Puede no estar todavia (un
    # objeto recien visto se clasifica en una pasada posterior), y entonces el
    # titulo va del color del texto normal.
    clasificacion = con.execute(
        "SELECT calidad FROM atributo WHERE tipo = ? AND producto_id = ?",
        (tipo, producto_id),
    ).fetchone()

    return {
        "tipo": tipo,
        "producto_id": producto_id,
        "nombre": fila["nombre"] if fila else f"#{producto_id}",
        "icono": fila["icono"] if fila else None,
        "calidad": clasificacion["calidad"] if clasificacion else None,
        "variantes": variantes,
        "generado_en": volcado[0] if volcado else None,
    }


def reinos_de(
    con: sqlite3.Connection,
    tipo: str,
    producto_id: int,
    variante: Optional[int],
    limite: Optional[int] = REINOS_GRATIS,
) -> list[dict[str, Any]]:
    """Los reinos con existencias, del más barato al más caro.

    Con `limite=None` salen todos, que es lo que verá el plan de pago en v3.
    """
    sql = (
        "SELECT r.nombre, r.slug, p.minimo, p.listados "
        "  FROM precio p JOIN reino r ON r.id = p.reino_id "
        " WHERE p.tipo = ? AND p.producto_id = ? AND p.variante = ? "
        " ORDER BY p.minimo"
    )
    args: list[Any] = [
        tipo,
        producto_id,
        SIN_VARIANTE if variante is None else variante,
    ]
    if limite is not None:
        sql += " LIMIT ?"
        args.append(limite)

    return [dict(fila) for fila in con.execute(sql, args)]


def anotar_peticion(
    con: sqlite3.Connection,
    tipo: str,
    producto_id: int,
    ahora: Optional[int] = None,
) -> None:
    """Deja constancia de que alguien ha pedido esta página.

    De aquí sale qué páginas existen de verdad: en vez de publicar las 20.144
    el primer día --que es el patrón que Google trata como contenido
    generado--, el índice crece con la demanda que ya hay.

    Esto es contabilidad, no contenido: si falla --un bloqueo agotado, el
    disco lleno, la base en solo lectura-- perder esta cuenta no vale nada,
    pero perder la página (que ya tiene todo lo que `ficha` y `reinos_de`
    necesitaban) sí. Por eso el fallo se traga aquí y no sube a quien llama.
    """
    try:
        con.execute(
            "INSERT INTO pagina (tipo, producto_id, primera_peticion) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(tipo, producto_id) DO UPDATE SET "
            "peticiones = peticiones + 1",
            (tipo, producto_id, ahora if ahora is not None else int(time.time())),
        )
    except sqlite3.Error:
        log.warning(
            "No se pudo anotar la petición de %s %s", tipo, producto_id, exc_info=True
        )


def reino_por_slug(con: sqlite3.Connection, slug: str) -> Optional[dict[str, Any]]:
    """El reino de esa URL, o None si el slug no existe (lo convierte en 404)."""
    fila = con.execute("SELECT * FROM reino WHERE slug = ?", (slug,)).fetchone()
    return dict(fila) if fila else None


def productos_de_reino(
    con: sqlite3.Connection,
    reino_id: int,
    limite: int,
    reinos_minimos: int = REINOS_PARA_COMPARAR,
) -> list[dict[str, Any]]:
    """Lo más rebajado del reino: donde más se separa del precio normal.

    Ordenar por precio a secas sacaría la lista de lo más caro, que no le
    interesa a nadie. Lo que se busca es dónde este reino está barato respecto
    a la región.

    Se exige `e.reinos >= reinos_minimos` para no llenar la página de
    productos que solo existen en un puñado de reinos, donde la mediana no
    significa nada: ver `REINOS_PARA_COMPARAR`, que es el mismo listón que
    usa `mejores_rebajas` para la portada.

    Lleva los mismos tres filtros de calidad que `mejores_rebajas`, y por la
    misma razón: con los 92 reinos reales esta página abría con "Honorable
    Combatant's Leather Greaves, normally 9,999,999g, here 959g". Ver
    `TOPE_CDS` y `DESCUENTO_MAXIMO`, y el `JOIN` contra `nombre`, que aquí
    tampoco es `LEFT`: una lista de cien filas no puede llevar "#183942".

    Lo que NO comparte es el deduplicado por producto. Aquí caben cien filas y
    no doce, y el mismo objeto a dos ilvl distintos son dos ofertas distintas
    con dos precios distintos: la plantilla los distingue con su ilvl al lado.

    Coste medido en producción (92 reinos, 20.144 productos, 787.880 filas en
    `precio`): ~27 ms por vista de página de reino, frente a ~0,028 ms de las
    consultas de la página de producto. Se probó un índice en
    precio(reino_id, tipo, producto_id, variante) y se descartó: la lectura
    solo bajaba un 12% (26,8 ms → 23,6 ms) porque el coste está en el JOIN por
    fila contra `estadistica` y `nombre`, no en el acceso a `precio`; a cambio
    la pasada horaria que reescribe la tabla se volvía un 85% más lenta
    (1,37 s → 2,53 s). El arreglo de verdad es precalcular las filas rebajadas
    durante esa misma pasada en una tabla pequeña indexada por reino, pero eso
    queda fuera de v1.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT n.nombre, n.icono, a.calidad, p.producto_id, p.variante, "
            "       p.minimo, e.mediana "
            "  FROM precio p "
            "  JOIN estadistica e ON e.tipo = p.tipo "
            "                    AND e.producto_id = p.producto_id "
            "                    AND e.variante = p.variante "
            "  JOIN nombre n ON n.tipo = p.tipo "
            "                AND n.producto_id = p.producto_id "
            "                AND n.idioma = ? "
            "  LEFT JOIN atributo a ON a.tipo = p.tipo "
            "                     AND a.producto_id = p.producto_id "
            " WHERE p.reino_id = ? AND e.reinos >= ? AND p.minimo < e.mediana "
            "   AND e.mediana < ? "
            "   AND CAST(p.minimo AS REAL) / e.mediana >= ? "
            " ORDER BY CAST(p.minimo AS REAL) / e.mediana "
            " LIMIT ?",
            (
                IDIOMA_POR_DEFECTO,
                reino_id,
                reinos_minimos,
                TOPE_CDS,
                1 - DESCUENTO_MAXIMO / 100,
                limite,
            ),
        )
    ]


def paginas_mas_pedidas(con: sqlite3.Connection, limite: int) -> list[dict[str, Any]]:
    """Para el sitemap: solo entra lo que la gente busca de verdad.

    `limite` es obligatorio a propósito: un valor por defecto que nadie usa es
    una trampa para el próximo llamante que se olvide de pasarlo, y un
    sitemap truncado en silencio no se nota hasta que Google deja de indexar
    páginas que ya nadie le está diciendo que existen.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT tipo, producto_id, peticiones FROM pagina "
            " ORDER BY peticiones DESC, producto_id LIMIT ?",
            (limite,),
        )
    ]


def reinos_publicados(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Los reinos que cubre el sitio, en orden alfabético.

    La usan la portada, para enseñarlos, y el sitemap, para anunciarlos. Es la
    misma lista y sale de un solo sitio: dos SELECT parecidos en dos ficheros
    se separan en cuanto uno de los dos aprenda a filtrar algo.

    Alfabético y no por id porque la portada es una lista para buscar el reino
    propio, no un ranking: el id de reino conectado no significa nada para
    quien lee.
    """
    return [
        dict(fila)
        for fila in con.execute("SELECT nombre, slug FROM reino ORDER BY nombre")
    ]


def productos_mas_vistos(
    con: sqlite3.Connection, limite: int, idioma: str = IDIOMA_POR_DEFECTO
) -> list[dict[str, Any]]:
    """Los productos más pedidos, con su nombre, para enlazar desde la portada.

    Es `paginas_mas_pedidas` con el nombre puesto y con un filtro más: al
    sitemap le basta el id, pero una lista de enlaces necesita algo que leer y,
    sobre todo, no puede llevar a un 404.

    Ese es el `EXISTS`: `pagina` es un histórico y no se poda nunca --es de
    donde sale qué páginas existen de verdad--, mientras que `estadistica` se
    reescribe entera en cada pasada. Un objeto que Blizzard retire, o que
    simplemente deje de tener subastas en toda la región, se queda en `pagina`
    con sus peticiones intactas mientras su ficha ya responde 404. Enlazarlo
    desde la portada sería mandar a los rastreadores justo a donde no hay nada.

    El `EXISTS` y no un JOIN contra `estadistica` porque ahí hay una fila por
    ilvl: las Grebas tienen ocho variantes y saldrían ocho veces en la lista.

    `limite` es obligatorio, igual que en `paginas_mas_pedidas` y por lo mismo.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT g.tipo, g.producto_id, n.nombre, n.icono, g.peticiones "
            "  FROM pagina g "
            "  LEFT JOIN nombre n ON n.tipo = g.tipo "
            "                    AND n.producto_id = g.producto_id "
            "                    AND n.idioma = ? "
            " WHERE EXISTS (SELECT 1 FROM estadistica e "
            "                WHERE e.tipo = g.tipo "
            "                  AND e.producto_id = g.producto_id) "
            " ORDER BY g.peticiones DESC, g.producto_id "
            " LIMIT ?",
            (idioma, limite),
        )
    ]


def mejores_rebajas(
    con: sqlite3.Connection,
    limite: int,
    reinos_minimos: int = REINOS_PARA_COMPARAR,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> list[dict[str, Any]]:
    """Lo más rebajado de toda la región, venga del reino que venga.

    Es la hermana de `productos_de_reino` con la pregunta al revés: allí es
    "qué está barato en MI reino" y aquí "dónde hay una ganga ahora mismo".
    Por eso cada fila trae su reino y su slug: sin eso la cifra no sirve de
    nada, porque no dice adónde ir a comprarlo.

    Tres filtros que no estaban cuando esto se probó con dos reinos y que la
    primera pasada de los 92 hizo obligatorios --la portada salía entera a
    "100% off, normally 9,999,999g"--:

    1. `e.mediana < TOPE_CDS`. Una mediana clavada en el máximo que deja
       teclear la casa de subastas no es un precio.
    2. El descuento no pasa de `DESCUENTO_MAXIMO`. Por encima de eso lo que
       hay roto es la mediana, no el mercado.
    3. Un producto ocupa una fila y no cinco. El mismo objeto rebajado en
       varios reinos daba varias filas seguidas ("Waterlogged Cloth Vest"
       salía tres veces entre las doce primeras).

    Y un `JOIN` --no `LEFT JOIN`-- contra `nombre`: el 6,5% de las variantes
    no tiene nombre en inglés, y la portada no puede enseñar "#183942" como
    si fuera un objeto. En la ficha sí se cae al id, porque allí el usuario ya
    ha pedido ESE producto; aquí se elige qué enseñar.

    El corte de la rebaja es `<` y no `<=`: un reino que clava el precio
    normal no está rebajado, y con noventa y dos reinos los empates en la
    mediana son muchos.

    **El deduplicado se hace aquí y no con un `ROW_NUMBER()`** aunque en SQL
    quedaría más limpio: medido sobre las 744.832 filas del volcado real, la
    función de ventana obliga a ordenar TODAS las filas que pasan el filtro y
    sube la consulta de 363 ms a 696 ms. Con `ORDER BY ... LIMIT` SQLite se
    queda con una cola acotada y no ordena el resto.

    El precio de hacerlo así es que hay que pedir de más y puede quedarse
    corto: se piden `limite * HOLGURA_DEDUPE` filas, y si un puñado de
    productos se repartiera todas, la lista sale con menos de `limite`. Es
    preferible a devolver el mismo objeto cinco veces, y con holgura 10 no ha
    pasado nunca sobre datos reales (las 12 filas se llenan ya con holgura 5).

    **Es cara: ~363 ms sobre el volcado real**, contra los ~23 ms de la página
    de reino, porque aquí no hay un `reino_id` que recorte el escaneo. Quien
    la llame en una ruta tiene que cachearla; la portada lo hace contra
    `volcado.generado_en`.
    """
    vistos: set[int] = set()
    filas: list[dict[str, Any]] = []
    for fila in con.execute(
        "SELECT n.nombre, n.icono, a.calidad, p.producto_id, p.variante, "
        "       p.minimo, e.mediana, r.nombre AS reino, r.slug "
        "  FROM precio p "
        "  JOIN estadistica e ON e.tipo = p.tipo "
        "                    AND e.producto_id = p.producto_id "
        "                    AND e.variante = p.variante "
        "  JOIN reino r ON r.id = p.reino_id "
        "  JOIN nombre n ON n.tipo = p.tipo "
        "                AND n.producto_id = p.producto_id "
        "                AND n.idioma = ? "
        "  LEFT JOIN atributo a ON a.tipo = p.tipo "
        "                     AND a.producto_id = p.producto_id "
        " WHERE e.reinos >= ? "
        "   AND p.minimo < e.mediana "
        "   AND e.mediana < ? "
        "   AND CAST(p.minimo AS REAL) / e.mediana >= ? "
        " ORDER BY CAST(p.minimo AS REAL) / e.mediana "
        " LIMIT ?",
        (
            idioma,
            reinos_minimos,
            TOPE_CDS,
            1 - DESCUENTO_MAXIMO / 100,
            limite * HOLGURA_DEDUPE,
        ),
    ):
        if fila["producto_id"] in vistos:
            continue
        vistos.add(fila["producto_id"])
        rebaja = dict(fila)
        # El porcentaje se calcula aquí y no en la plantilla por lo mismo que
        # `mediana_fiable`: una cuenta escrita en Jinja no la cubre un test.
        rebaja["descuento"] = round((1 - rebaja["minimo"] / rebaja["mediana"]) * 100)
        filas.append(rebaja)
        if len(filas) == limite:
            break
    return filas


def version_del_volcado(con: sqlite3.Connection) -> Optional[int]:
    """Cuando se genero lo que hay ahora mismo en `precio`.

    Es el numero contra el que se cachea todo lo que solo cambia con la pasada
    horaria: mientras no se mueva, el resultado es literalmente el mismo. No
    es un TTL a ojo, no sirve nada caducado y no hay nada que afinar.

    `resumen_del_catalogo` ya lo devuelve, pero de propina con dos cuentas mas
    que no hacen falta para saber si algo caduco. Esto es una fila de una tabla
    de una fila.

    None con la base recien creada, que es el estado normal hasta que termina
    la primera pasada.
    """
    fila = con.execute("SELECT generado_en FROM volcado").fetchone()
    return fila[0] if fila else None


def resumen_del_catalogo(con: sqlite3.Connection) -> dict[str, Any]:
    """Cuánto cubre el sitio y de cuándo son los datos, para la portada.

    `COUNT(DISTINCT producto_id)` y no `COUNT(*)`: en `estadistica` hay una
    fila por ilvl, así que las Grebas con sus ocho variantes contarían como
    ocho objetos. Son uno.

    `generado_en` sale a None con la base recién creada, que es el estado
    normal hasta que termina la primera pasada; la portada lo dibuja como
    "todavía no hay datos" en vez de inventarse una fecha.
    """
    productos = con.execute(
        "SELECT count(DISTINCT producto_id) FROM estadistica"
    ).fetchone()[0]
    reinos = con.execute("SELECT count(*) FROM reino").fetchone()[0]
    volcado = con.execute("SELECT generado_en FROM volcado").fetchone()
    return {
        "productos": productos,
        "reinos": reinos,
        "generado_en": volcado[0] if volcado else None,
    }


# -- Categorias y busqueda ---------------------------------------------------
#
# Estas consultas hacen dos cosas a la vez. Son los filtros de la casa de
# subastas (armas, armadura, recetas...) y, sobre todo, son el camino de
# rastreo que le faltaba al sitio: con 19.365 fichas y solo 4.598 enlazadas
# desde alguna pagina de reino, tres de cada cuatro no tenian forma de ser
# descubiertas por Google ni por nadie.
#
# Ninguna dice en QUE reino esta lo barato. Eso es lo que vende el Pro, y una
# tabla de cien filas con su reino al lado lo regalaria en bloque.


def categorias(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Las clases de objeto con cuantos productos en venta tiene cada una.

    Se cuenta contra `estadistica` y no contra `atributo` a secas porque
    `atributo` no se borra en cada pasada y `precio` si: un objeto que hoy no
    esta en subastas no tiene ficha, y anunciar "Armor (3.412)" cuando 200 de
    esos dan 404 es mentir en el indice.
    """
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT a.clase, a.clase_slug, count(DISTINCT a.producto_id) AS objetos "
            "  FROM atributo a "
            " WHERE EXISTS (SELECT 1 FROM estadistica e "
            "                WHERE e.tipo = a.tipo "
            "                  AND e.producto_id = a.producto_id) "
            " GROUP BY a.clase, a.clase_slug "
            " ORDER BY a.clase"
        )
    ]


def subcategorias(
    con: sqlite3.Connection,
    clase_slug: str,
    calidad: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Las subclases de una clase, con su cuenta. Mismo criterio que arriba.

    Con `calidad`, solo las que tienen algo de esa calidad, y la cuenta es la
    de esa calidad. No es un adorno: el menu de tipos arrastra el filtro que
    haya puesto, asi que ofrecer un tipo sin nada de esa calidad es ofrecer un
    404. Salio rastreando la base de verdad --`/items/weapon/thrown` y
    `/items/weapon/miscellaneous` con `?quality=EPIC`-- y la lista sin filtrar
    ademas mentia en la cuenta: prometia los 172 objetos del tipo cuando lo
    que iba a salir eran los de la calidad puesta.
    """
    sql = " WHERE a.clase_slug = ? "
    args: list[Any] = [clase_slug]
    if calidad:
        sql += " AND a.calidad = ? "
        args.append(calidad)
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT a.subclase, a.subclase_slug, "
            "       count(DISTINCT a.producto_id) AS objetos "
            "  FROM atributo a "
            + sql
            + "   AND EXISTS (SELECT 1 FROM estadistica e "
            "                WHERE e.tipo = a.tipo "
            "                  AND e.producto_id = a.producto_id) "
            " GROUP BY a.subclase, a.subclase_slug "
            " ORDER BY a.subclase",
            args,
        )
    ]


def _filtro_categoria(
    clase_slug: str, subclase_slug: Optional[str], calidad: Optional[str]
) -> tuple[str, list[Any]]:
    """El WHERE que comparten `productos_de_categoria` y `contar_categoria`.

    Escrito una vez para que la cuenta y la lista no puedan discrepar: si la
    paginacion se calcula con un criterio y las filas con otro, salen paginas
    vacias al final y Google las ve.
    """
    sql = " WHERE a.clase_slug = ? "
    args: list[Any] = [clase_slug]
    if subclase_slug:
        sql += " AND a.subclase_slug = ? "
        args.append(subclase_slug)
    if calidad:
        sql += " AND a.calidad = ? "
        args.append(calidad)
    return sql, args


def productos_de_categoria(
    con: sqlite3.Connection,
    clase_slug: str,
    subclase_slug: Optional[str] = None,
    calidad: Optional[str] = None,
    limite: int = 100,
    desde: int = 0,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> list[dict[str, Any]]:
    """Los objetos de una categoria, con desde cuanto salen en la region.

    `desde` es el desplazamiento de la paginacion. Una categoria de miles de
    objetos no cabe en una pagina, y hacen falta todas para que quede enlazado
    el catalogo entero.

    `desde` sale mas barato que parece aun siendo OFFSET: el orden es por
    nombre y el filtro va por `atributo_por_categoria`, asi que lo que se
    recorre es el indice y no la tabla de precios.
    """
    where, args = _filtro_categoria(clase_slug, subclase_slug, calidad)
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT a.producto_id, n.nombre, n.icono, a.calidad, a.subclase, "
            "       MIN(e.minimo) AS desde, MIN(e.variante) AS variante "
            "  FROM atributo a "
            "  JOIN nombre n ON n.tipo = a.tipo "
            "               AND n.producto_id = a.producto_id "
            "               AND n.idioma = ? "
            "  JOIN estadistica e ON e.tipo = a.tipo "
            "                    AND e.producto_id = a.producto_id "
            + where
            + " GROUP BY a.producto_id, n.nombre, n.icono, a.calidad, a.subclase "
            " ORDER BY n.nombre "
            " LIMIT ? OFFSET ?",
            [idioma] + args + [limite, desde],
        )
    ]


def contar_categoria(
    con: sqlite3.Connection,
    clase_slug: str,
    subclase_slug: Optional[str] = None,
    calidad: Optional[str] = None,
) -> int:
    """Cuantos objetos hay, para saber cuantas paginas enlazar."""
    where, args = _filtro_categoria(clase_slug, subclase_slug, calidad)
    return con.execute(
        "SELECT count(DISTINCT a.producto_id) "
        "  FROM atributo a "
        "  JOIN estadistica e ON e.tipo = a.tipo "
        "                    AND e.producto_id = a.producto_id "
        + where,
        args,
    ).fetchone()[0]


def buscar(
    con: sqlite3.Connection,
    texto: str,
    limite: int,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> list[dict[str, Any]]:
    """Busca por trozo de nombre. Solo devuelve lo que esta en venta.

    Los comodines de LIKE se escapan: un `%` tecleado por el visitante no puede
    convertirse en "damelo todo", que ademas recorreria la tabla entera.

    Una busqueda vacia devuelve nada y no el catalogo: es lo que llega cuando
    alguien pulsa Enter en la caja sin escribir.

    Sobre `nombre` no hay indice por texto, asi que esto es un recorrido. Con
    149.386 filas sale a unos pocos milisegundos y no merece un FTS5 todavia;
    el dia que la caja se use de verdad, ahi esta la puerta.
    """
    texto = texto.strip()
    if not texto:
        return []

    # El caracter de escape es "!" y no la barra invertida: en SQLite vale
    # cualquiera, y una barra dentro de una cadena de Python dentro de una
    # cadena de SQL se cuela en cuanto alguien reformatea el fichero.
    patron = "%" + texto.translate(_ESCAPAR_LIKE) + "%"
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT n.producto_id, n.nombre, n.icono, a.calidad, "
            "       MIN(e.minimo) AS desde "
            "  FROM nombre n "
            "  JOIN estadistica e ON e.tipo = n.tipo "
            "                    AND e.producto_id = n.producto_id "
            "  LEFT JOIN atributo a ON a.tipo = n.tipo "
            "                     AND a.producto_id = n.producto_id "
            " WHERE n.idioma = ? AND n.nombre LIKE ? ESCAPE '!' "
            " GROUP BY n.producto_id, n.nombre, n.icono, a.calidad "
            " ORDER BY length(n.nombre), n.nombre "
            " LIMIT ?",
            (idioma, patron, limite),
        )
    ]



def sugerencias(
    con: sqlite3.Connection,
    texto: str,
    limite: int,
    idioma: str = IDIOMA_POR_DEFECTO,
) -> list[dict[str, Any]]:
    """Lo que se pinta debajo de la caja mientras se teclea.

    Es `buscar` con otra prioridad, y por eso son dos funciones y no una con
    un parametro. Quien pulsa Enter quiere la lista entera y le sirve el orden
    por nombre corto; quien esta tecleando esta escribiendo el PRINCIPIO de un
    nombre, y espera verlo arriba. Con "sword", ordenar solo por longitud
    cuela "Bloodfang Sword" (15) delante de "Sword of a Thousand Truths" (26).

    El `LIKE` va dos veces a proposito: uno filtra por "lo contiene" y el otro
    --el del ORDER BY, con el comodin solo detras-- decide quien sube. SQLite
    no reusa el resultado de un LIKE entre WHERE y ORDER BY, pero son ocho
    filas de salida y el recorrido de `nombre` ya se paga una vez.

    Cuesta 15-20 ms sobre la base real (149.386 nombres, de los que 18.675 son
    los ingleses), y esto se pide una vez por pausa al teclear. Un indice
    `nombre (idioma, nombre)` parece la cura obvia --recorreria un octavo de la
    tabla-- y esta medido que la EMPEORA a 50 ms: SQLite lo usa como indice
    cubriente y luego tiene que ir a buscar el `icono` de cada coincidencia en
    una tabla WITHOUT ROWID, o sea una busqueda por clave primaria entera por
    fila. El dia que esto se quede corto la puerta es FTS5, no un indice.
    """
    texto = texto.strip()
    if not texto:
        return []

    escapado = texto.translate(_ESCAPAR_LIKE)
    return [
        dict(fila)
        for fila in con.execute(
            "SELECT n.producto_id, n.nombre, n.icono, a.calidad, "
            "       MIN(e.minimo) AS desde "
            "  FROM nombre n "
            "  JOIN estadistica e ON e.tipo = n.tipo "
            "                    AND e.producto_id = n.producto_id "
            "  LEFT JOIN atributo a ON a.tipo = n.tipo "
            "                     AND a.producto_id = n.producto_id "
            " WHERE n.idioma = ? AND n.nombre LIKE ? ESCAPE '!' "
            " GROUP BY n.producto_id, n.nombre, n.icono, a.calidad "
            " ORDER BY (n.nombre LIKE ? ESCAPE '!') DESC, "
            "          length(n.nombre), n.nombre "
            " LIMIT ?",
            (idioma, f"%{escapado}%", f"{escapado}%", limite),
        )
    ]

# El orden del juego: primero lo bueno. Un ORDER BY alfabetico pondria COMMON
# antes que EPIC, que no es como lo lee nadie que juegue.
ORDEN_CALIDAD = ("LEGENDARY", "EPIC", "RARE", "UNCOMMON", "COMMON", "POOR")


def calidades_de(
    con: sqlite3.Connection,
    clase_slug: str,
    subclase_slug: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Que calidades hay en esta categoria y cuantos objetos de cada una.

    Las que HAY y no las seis posibles: un filtro que ofrece "Epic" en una
    categoria sin nada epico lleva a una lista vacia, y eso se siente como un
    fallo de la web y no como un dato del mercado.
    """
    where, args = _filtro_categoria(clase_slug, subclase_slug, None)
    filas = [
        dict(fila)
        for fila in con.execute(
            "SELECT a.calidad, count(DISTINCT a.producto_id) AS objetos "
            "  FROM atributo a "
            "  JOIN estadistica e ON e.tipo = a.tipo "
            "                    AND e.producto_id = a.producto_id "
            + where
            + "   AND a.calidad IS NOT NULL "
            " GROUP BY a.calidad",
            args,
        )
    ]
    orden = {c: i for i, c in enumerate(ORDEN_CALIDAD)}
    return sorted(filas, key=lambda f: orden.get(f["calidad"], 99))
