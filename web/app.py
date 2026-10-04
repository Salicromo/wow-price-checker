"""La web pública. Solo lectura: no hay cuentas ni formularios."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wowalerts.config import COPPER_PER_GOLD
from wowalerts.mercado import TIPO_OBJETO
from web.consultas import (
    REINOS_GRATIS,
    anotar_peticion,
    buscar,
    calidades_de,
    categorias,
    contar_categoria,
    ficha,
    mejores_rebajas,
    paginas_mas_pedidas,
    productos_de_categoria,
    productos_de_reino,
    productos_mas_vistos,
    reino_por_slug,
    reinos_de,
    reinos_publicados,
    resumen_del_catalogo,
    subcategorias,
    sugerencias,
    version_del_volcado,
)
from web.db import VARIABLE_DB, abrir, ruta_de_entorno

log = logging.getLogger("web.app")

AQUI = Path(__file__).parent

# El sitemap necesita URLs absolutas (Google no las acepta relativas), y el
# dominio real solo se conoce en el servidor -- aquí, en desarrollo y en los
# tests, se usa uno de mentira.
BASE_URL = os.environ.get("BASE_URL", "https://auctionsentinel.example")


# El centinela de la caché de la portada. No vale `None`: con la base recién
# creada `generado_en` ES None, y entonces "todavía no lo he calculado" y "lo
# calculé cuando no había volcado" serían el mismo estado.
_SIN_CALCULAR = object()

# Objetos por pagina de categoria. Cien filas es lo que aguanta una pagina
# sin volverse un muro, y con 19.365 objetos salen ~200 paginas: suficientes
# para que quede enlazado el catalogo entero, que es para lo que existen.
POR_PAGINA = 100

# Cuantos resultados devuelve la caja de busqueda. No hay paginacion aqui a
# proposito: quien busca quiere encontrar, no pasear.
RESULTADOS_BUSQUEDA = 50

# Cuantas sugerencias se pintan mientras se teclea. Ocho y no cincuenta: es
# una lista que se lee de un vistazo sin bajar la vista de la caja, y si lo
# que se busca no esta ahi, Enter lleva a los cincuenta de /search.
SUGERENCIAS = 8

# Los meses a mano en vez de `%B`, que saca el nombre en la locale del
# sistema: la página está en inglés y el VPS no tiene por qué estarlo, así que
# un servidor en español pondría "septiembre" en mitad de una frase inglesa.
_MESES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _fecha(epoch: Optional[int]) -> Optional[str]:
    """La hora del volcado, en UTC y legible. None si todavía no hay ninguno.

    UTC y dicho en voz alta: los reinos de EU van en varias zonas horarias y
    la alternativa --la del servidor-- no significa nada para quien lee.
    """
    if not epoch:
        return None
    d = datetime.fromtimestamp(epoch, timezone.utc)
    return f"{d.day} {_MESES[d.month - 1]} {d.year}, {d:%H:%M} UTC"


def _query(pagina: int, cola: str) -> str:
    """El `?p=...&quality=...` de un enlace, con solo lo que haga falta.

    La pagina 1 no lleva `p`: si lo llevara, la misma lista tendria dos URLs
    (`/items/armor` y `/items/armor?p=1`) y volveriamos a tener duplicados,
    que es lo que el canonical acaba de arreglar.
    """
    partes = []
    if pagina > 1:
        partes.append(f"p={pagina}")
    if cola:
        partes.append(cola)
    return "?" + "&".join(partes) if partes else ""


def _ventana(pagina: int, paginas: int, ancho: int = 7) -> list[int]:
    """Los numeros de pagina que se pintan alrededor del actual.

    Con ~200 paginas por categoria, pintarlas todas es una barra ilegible; y
    pintar solo "anterior/siguiente" obliga a un rastreador a dar 200 saltos en
    cadena para llegar al final. Una ventana deja siempre la primera y la
    ultima a un clic.
    """
    if paginas <= ancho:
        return list(range(1, paginas + 1))
    mitad = ancho // 2
    inicio = max(1, min(pagina - mitad, paginas - ancho + 1))
    numeros = list(range(inicio, inicio + ancho))
    if numeros[0] != 1:
        numeros[0] = 1
    if numeros[-1] != paginas:
        numeros[-1] = paginas
    return numeros


def _oro(cobre: int) -> str:
    """Cobre a oro, que es en lo que piensa el jugador.

    La conversión sale de `COPPER_PER_GOLD` y no de un 10000 escrito a mano en
    la plantilla: son el mismo número hoy, pero nada los ataba.
    """
    return f"{cobre // COPPER_PER_GOLD:,}"


def crear_app(ruta_db: Path | str | None = None) -> FastAPI:
    """Fabrica la app. Recibe la ruta para que los tests usen su propia base.

    Sin ruta se usa la que diga `AUCTION_DB`, que es como la nombra el
    servidor: `uvicorn web.app:app` no puede pasar argumentos.
    """
    ruta_db = Path(ruta_db) if ruta_db is not None else ruta_de_entorno()
    app = FastAPI(title="Auction Sentinel")
    plantillas = Jinja2Templates(directory=str(AQUI / "plantillas"))
    plantillas.env.filters["oro"] = _oro
    # Global y no variable de contexto: lo necesita `base.html` en TODAS
    # las paginas para las URLs absolutas de canonical y Open Graph, y
    # pasarlo a mano en cada ruta es una que se olvida.
    plantillas.env.globals["BASE_URL"] = BASE_URL
    app.mount(
        "/estaticos", StaticFiles(directory=str(AQUI / "estaticos")), name="estaticos"
    )

    # Se abre una vez al arrancar para dejar el esquema puesto (las seis
    # CREATE TABLE IF NOT EXISTS más el índice), y de paso para decir en el log
    # QUÉ fichero se ha abierto. Sin esa línea, apuntar a la base equivocada se
    # nota como 404 en todas las páginas y en ningún otro sitio: `abrir()` crea
    # la base que falte, así que no hay ni un error que buscar.
    con = abrir(ruta_db)
    try:
        filas = con.execute("SELECT count(*) FROM precio").fetchone()[0]
    finally:
        con.close()

    log.info("Sirviendo %s (%s filas de precio)", ruta_db.resolve(), f"{filas:,}")
    if not filas:
        # No se aborta: una instalación recién hecha tiene la base vacía hasta
        # que termina la primera pasada, y eso es legítimo.
        log.warning(
            "La base %s está vacía, así que todas las páginas van a dar 404. "
            "Llénala con `publicar_web.py --db %s`, o apunta %s a la base "
            "buena.",
            ruta_db.resolve(),
            ruta_db,
            VARIABLE_DB,
        )

    def conexion() -> sqlite3.Connection:
        # Una conexión por petición: SQLite no deja compartirlas entre hilos, y
        # abrir una cuesta ~0,9 ms (medido contra una base de 800.000 filas).
        # El esquema ya está puesto por `crear_app`, así que aquí se salta:
        # volver a comprobarlo en cada petición costaba ~0,15 ms de las
        # ~1,07 ms totales, más que la propia consulta de la página.
        return abrir(ruta_db, esquema=False)

    # Las rebajas de la portada cuestan 271 ms sobre una base del tamaño de
    # producción (932.000 filas de `precio`), contra los ~23 ms de la página
    # de reino: no hay un `reino_id` que recorte el escaneo y el ORDER BY se
    # resuelve con un b-tree temporal. Eso no puede correr en cada visita, y
    # menos en la página que más se pide y por la que entran los rastreadores.
    #
    # Se guardan contra el `generado_en` del volcado, que solo cambia cuando
    # la pasada horaria escribe precios nuevos: mientras ese número sea el
    # mismo, el resultado es literalmente el mismo. No es un TTL a ojo, no
    # sirve nada caducado y no hay nada que afinar.
    #
    # Vive en el proceso y no en una tabla: con `--workers 2` se calcula dos
    # veces por hora, una por worker, y eso sale más barato que una tabla
    # precalculada que haya que escribir e invalidar en la pasada.
    cache_rebajas: dict[str, Any] = {"generado_en": _SIN_CALCULAR, "filas": []}

    # Las 13 categorias salen en la cabecera de TODAS las paginas: es el menu
    # con el que se elige que objetos ver sin irse a /items, que era abrir otra
    # pagina cuyo unico contenido es elegir.
    #
    # Cuesta 30 ms medidos sobre la base real, y en todas las paginas eso ya no
    # es un detalle. Se cachea igual que las rebajas y por el mismo motivo: son
    # las categorias que hay, y solo cambian cuando la pasada horaria mete
    # objetos de una nueva.
    cache_menu: dict[str, Any] = {"generado_en": _SIN_CALCULAR, "filas": []}

    def menu_categorias(con: sqlite3.Connection) -> list[dict[str, Any]]:
        """Las categorias de la cabecera, cacheadas contra el volcado.

        Recibe la conexion que ya tiene abierta la ruta en vez de abrir otra:
        un `abrir()` cuesta ~0,9 ms, que sobre una pagina cacheada seria casi
        todo el coste.
        """
        version = version_del_volcado(con)
        if cache_menu["generado_en"] != version:
            cache_menu["filas"] = categorias(con)
            cache_menu["generado_en"] = version
        return cache_menu["filas"]

    @app.get("/", response_class=HTMLResponse)
    def portada(request: Request):
        """La entrada al sitio, y el destino del enlace de la marca.

        Ese enlace lo pinta `base.html` en la cabecera de TODAS las páginas, y
        hasta que existió esta ruta cada visita que pulsaba el logotipo se
        comía un 404.

        No se llama a `anotar_peticion`: lo que cuenta esa tabla es qué fichas
        pide la gente, y de ahí sale el sitemap. Contar la portada metería una
        página que no es de producto en el índice de páginas de producto.
        """
        con = conexion()
        try:
            resumen = resumen_del_catalogo(con)
            if cache_rebajas["generado_en"] != resumen["generado_en"]:
                # Doce filas: las que caben sin que la portada se convierta en
                # una lista interminable. Lo demás está en la página de cada
                # reino, que es donde se busca a propósito.
                cache_rebajas["filas"] = mejores_rebajas(con, limite=12)
                cache_rebajas["generado_en"] = resumen["generado_en"]
            reinos = reinos_publicados(con)
            # Veinte y no cincuenta: es una lista para ojear, y las que más se
            # piden son las que de verdad interesan. Las demás llegan por
            # búsqueda, que es para lo que está el sitemap.
            vistos = productos_mas_vistos(con, limite=20)
            menu = menu_categorias(con)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="portada.html",
            context={
                "canonical": "/",
                "resumen": resumen,
                "generado": _fecha(resumen["generado_en"]),
                "rebajas": cache_rebajas["filas"],
                "reinos": reinos,
                "vistos": vistos,
                "menu": menu,
            },
        )

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        """Sin esto el sitemap no se anuncia en ningún sitio.

        Un rastreador que llegue por un enlace no tiene forma de saber que
        `/sitemap.xml` existe: la línea `Sitemap:` de aquí es la única pista
        estándar, y por eso lleva el dominio de `BASE_URL` --absoluto, igual
        que las URLs del propio sitemap.
        """
        return PlainTextResponse(
            f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/item/{producto_id}", response_class=HTMLResponse)
    def pagina_producto(
        request: Request, producto_id: int, ilvl: Optional[str] = None
    ):
        con = conexion()
        try:
            datos = ficha(con, TIPO_OBJETO, producto_id)
            if datos is None:
                raise HTTPException(status_code=404, detail="Item not found")

            actual = _variante_pedida(datos["variantes"], ilvl)
            filas = reinos_de(
                con, TIPO_OBJETO, producto_id, actual["variante"],
                limite=REINOS_GRATIS,
            )
            anotar_peticion(con, TIPO_OBJETO, producto_id)
            menu = menu_categorias(con)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="producto.html",
            context={
                # Sin el `?ilvl=`: las 13 URLs de un objeto con 12 ilvl son
                # una sola pagina, y sin esto competian entre ellas.
                "canonical": f"/item/{producto_id}",
                "og_imagen": datos["icono"],
                "ficha": datos,
                "actual": actual,
                "reinos": filas,
                "menu": menu,
            },
        )

    @app.get("/realm/{slug}", response_class=HTMLResponse)
    def pagina_reino(request: Request, slug: str):
        con = conexion()
        try:
            reino = reino_por_slug(con, slug)
            if reino is None:
                raise HTTPException(status_code=404, detail="Realm not found")
            filas = productos_de_reino(con, reino["id"], limite=100)
            menu = menu_categorias(con)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="reino.html",
            context={
                "canonical": f"/realm/{slug}",
                "reino": reino,
                "productos": filas,
                "menu": menu,
            },
        )

    @app.get("/items", response_class=HTMLResponse)
    def indice_categorias(request: Request):
        """El indice del catalogo entero.

        Es la pieza que le faltaba al sitio: con 19.365 fichas y solo 4.598
        enlazadas desde alguna pagina de reino, tres de cada cuatro no tenian
        forma de ser descubiertas. De aqui cuelgan todas.
        """
        con = conexion()
        try:
            cats = menu_categorias(con)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="categorias.html",
            context={
                "canonical": "/items",
                "categorias": cats,
                "menu": cats,
                "total": sum(c["objetos"] for c in cats),
            },
        )

    @app.get("/items/{clase}", response_class=HTMLResponse)
    @app.get("/items/{clase}/{subclase}", response_class=HTMLResponse)
    def pagina_categoria(
        request: Request,
        clase: str,
        subclase: Optional[str] = None,
        p: int = 1,
        quality: Optional[str] = None,
    ):
        con = conexion()
        try:
            subs = subcategorias(con, clase)
            if not subs:
                raise HTTPException(status_code=404, detail="Category not found")
            if subclase and subclase not in {s["subclase_slug"] for s in subs}:
                raise HTTPException(status_code=404, detail="Subcategory not found")

            cals = calidades_de(con, clase, subclase)
            # Una calidad que no existe aqui es 404 y no una lista vacia: por
            # el mismo motivo que una pagina fuera de rango, y porque
            # `?quality=` es una URL que se puede teclear y compartir.
            if quality and quality not in {c["calidad"] for c in cals}:
                raise HTTPException(status_code=404, detail="Quality not found")

            total = contar_categoria(con, clase, subclase, quality)
            paginas = max(1, -(-total // POR_PAGINA))
            # Una pagina fuera de rango es un 404 y no una tabla vacia: si no,
            # hay infinitas URLs que un rastreador se dedica a pedir.
            if p < 1 or p > paginas:
                raise HTTPException(status_code=404, detail="Page not found")

            productos = productos_de_categoria(
                con, clase, subclase, quality,
                limite=POR_PAGINA, desde=(p - 1) * POR_PAGINA,
            )
            nombre_clase = next(
                (s["subclase"] for s in subs if s["subclase_slug"] == subclase), None
            )
            # Las 13 clases, para que el desplegable de categoria deje saltar
            # a otra sin pasar por /items -- que era irse de la pagina a
            # filtrarla, justo lo que el panel viene a quitar.
            #
            # Cuesta 30 ms medidos sobre la base real, sobre los ~130 ms que
            # ya cuesta la pagina (89 de `productos_de_categoria`, 25 de
            # `subcategorias`, 11 de contar). Se paga: es la misma consulta
            # que /items y no hay ninguna pagina de categoria en el camino
            # caliente --la portada, que si lo es, tiene su propia cache. Si
            # algun dia estorba, la puerta es la de `cache_rebajas`: esto solo
            # cambia cuando cambia el volcado.
            todas = menu_categorias(con)
            # Los tipos que ofrece el menu, ya sin los que no tienen nada de
            # la calidad puesta: sus enlaces se llevan el `?quality=` y serian
            # un 404 salido del propio panel de filtros.
            tipos = subcategorias(con, clase, quality) if quality else subs
        finally:
            con.close()

        base_url = f"/items/{clase}" + (f"/{subclase}" if subclase else "")
        # La calidad viaja en todos los enlaces de paginacion: pasar de pagina
        # no puede perder el filtro que el visitante acaba de poner.
        cola = f"quality={quality}" if quality else ""
        return plantillas.TemplateResponse(
            request=request,
            name="categoria.html",
            context={
                # La pagina 2 es su propia canonical y NO apunta a la 1:
                # son objetos distintos, no duplicados. Si apuntara a la 1,
                # Google descartaria su contenido y el catalogo volveria a
                # quedarse sin enlazar, que es justo lo que esto arregla.
                "canonical": base_url + _query(p, cola),
                # Una funcion y no una lista de URLs ya hechas: la plantilla
                # pinta hasta siete enlaces de pagina y cada uno necesita
                # arrastrar el filtro que haya puesto.
                "enlace": lambda n: _query(n, cola),
                "clase_nombre": clase.replace("-", " ").title(),
                "titulo": nombre_clase or clase.replace("-", " ").title(),
                "clase_slug": clase,
                "subclase": subclase,
                "subcategorias": tipos,
                "menu": todas,
                "productos": productos,
                "total": total,
                "pagina": p,
                "paginas": paginas,
                "ventana": _ventana(p, paginas),
                "base_url": base_url,
                "cola": cola,
                "calidades": cals,
                "calidad": quality,
            },
        )

    @app.get("/search", response_class=HTMLResponse)
    def busqueda(request: Request, q: str = ""):
        """La caja de la cabecera. GET para que cada busqueda sea una URL."""
        con = conexion()
        try:
            productos = buscar(con, q, limite=RESULTADOS_BUSQUEDA) if q else []
            menu = menu_categorias(con)
        finally:
            con.close()

        return plantillas.TemplateResponse(
            request=request,
            name="busqueda.html",
            context={
                # Resultados de busqueda interna: Google los trata como
                # contenido fino y penaliza el sitio entero por ellos.
                # `follow` porque los enlaces a las fichas si valen.
                "noindex": True,
                "q": q,
                "productos": productos,
                "menu": menu,
            },
        )

    @app.get("/suggest")
    def autocompletar(q: str = ""):
        """Lo que la caja pinta debajo mientras se teclea.

        JSON y no HTML porque lo consume `interfaz.js`, que es quien monta la
        lista; devolver el fragmento ya pintado ataria la plantilla al script.

        No dice en que reino esta lo barato, igual que el buscador y las
        paginas de categoria: es lo que vende el Pro (spec v3).
        """
        # Sin texto no se abre conexion: la caja pide en cuanto se teclea, y
        # el primer caracter que se borra no tiene por que costar una consulta.
        if not q.strip():
            filas = []
        else:
            con = conexion()
            try:
                filas = sugerencias(con, q, limite=SUGERENCIAS)
            finally:
                con.close()

        return JSONResponse(
            {
                "q": q,
                "resultados": [
                    {
                        "producto_id": f["producto_id"],
                        "nombre": f["nombre"],
                        "icono": f["icono"],
                        "calidad": f["calidad"],
                        # En oro ya desde aqui: `_oro` es la unica conversion
                        # del sitio y repetirla en JavaScript es la forma de
                        # que un dia digan cosas distintas.
                        "desde": _oro(f["desde"]),
                    }
                    for f in filas
                ],
            },
            headers={
                # Los precios solo cambian con la pasada horaria, y quien
                # teclea borra y vuelve a escribir lo mismo todo el rato.
                "Cache-Control": "public, max-age=300",
                # No es una pagina: es la trastienda de la caja. Sin esto
                # entra en el indice como contenido fino, igual que /search.
                "X-Robots-Tag": "noindex",
            },
        )

    @app.get("/sitemap.xml")
    def sitemap():
        """Solo entra lo que ya se ha pedido, más los reinos.

        Anunciar de golpe las 20.144 páginas posibles de producto es el patrón
        que Google trata como contenido generado; en cambio el índice crece
        con la demanda real, página a página, según la deja `anotar_peticion`.
        Los reinos son distintos: son 92, son fijos, y no dependen de que
        nadie los pida --por eso se anuncian todos desde el primer día.
        """
        con = conexion()
        try:
            paginas = paginas_mas_pedidas(con, limite=50_000)
            reinos = reinos_publicados(con)
            cats = categorias(con)
            subs = {c["clase_slug"]: subcategorias(con, c["clase_slug"]) for c in cats}
        finally:
            con.close()

        # La portada primero: es la que más enlaces internos tiene y la raíz
        # del mapa. Luego lo pedido y, al final, los reinos.
        urls = [f"{BASE_URL}/", f"{BASE_URL}/items"]
        # Las categorias van SIEMPRE, como los reinos: son pocas, son fijas y
        # de ellas cuelga el catalogo entero. Es justo lo contrario que las
        # fichas, que entran segun se piden.
        for c in cats:
            urls.append(f"{BASE_URL}/items/{c['clase_slug']}")
            urls += [
                f"{BASE_URL}/items/{c['clase_slug']}/{s['subclase_slug']}"
                for s in subs[c["clase_slug"]]
            ]
        urls += [f"{BASE_URL}/item/{p['producto_id']}" for p in paginas]
        urls += [f"{BASE_URL}/realm/{r['slug']}" for r in reinos]

        cuerpo = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
            + "</urlset>"
        )
        # Los datos solo cambian con la pasada horaria, así que una hora de
        # caché no cuesta nada y evita reconstruir un megabyte por cada
        # rastreo: la audiencia entera de esta ruta son crawlers que vuelven.
        return Response(
            content=cuerpo,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    return app


def _variante_pedida(variantes: list[dict], ilvl: Optional[str]) -> dict:
    """La variante pedida, o la que más reinos tiene si no se pidió ninguna.

    El ilvl llega como texto y se convierte aquí a propósito. Si se tipara como
    int, un `?ilvl=abc` daría el 422 en JSON de FastAPI en una página que
    Google rastrea, mientras que un `?ilvl=9999` --el mismo error del
    usuario-- cae con elegancia en la variante por defecto. Un solo camino.

    La más extendida y no la primera: en las Grebas, el ilvl 318 solo está en
    12 reinos y el 305 en 85, así que abrir por el 305 enseña más mercado.
    """
    if ilvl is not None:
        try:
            pedido = int(ilvl)
        except (TypeError, ValueError):
            pedido = None
        if pedido is not None:
            for v in variantes:
                if v["variante"] == pedido:
                    return v
    return max(variantes, key=lambda v: v["reinos"])


app = crear_app()
