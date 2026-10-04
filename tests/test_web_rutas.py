import pytest
from fastapi.testclient import TestClient

from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino
from web.app import crear_app
from web.db import abrir
from web.ingesta import (
    guardar_atributos,
    guardar_nombres,
    guardar_reinos,
    recalcular_estadisticas,
    volcar,
)


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


@pytest.fixture
def ruta_db(tmp_path):
    ruta = tmp_path / "p.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 11)})
    guardar_nombres(
        con, [(TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None)]
    )
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 271440, 305): {
                i: resumen(i * 1_000_000, listados=i) for i in range(1, 11)
            },
            Clave(TIPO_OBJETO, 271440, 318): {1: resumen(90_000_000)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()
    return ruta


@pytest.fixture
def cliente(ruta_db):
    return TestClient(crear_app(ruta_db))


def test_la_ficha_responde_con_el_nombre(cliente):
    r = cliente.get("/item/271440")
    assert r.status_code == 200
    assert "Greaves of the Noxious Depths" in r.text


def test_un_producto_desconocido_da_404(cliente):
    assert cliente.get("/item/999999").status_code == 404


def test_la_ficha_solo_pinta_cinco_reinos(cliente):
    texto = cliente.get("/item/271440").text
    assert "Reino 5" in texto
    # El sexto reino y los siguientes no llegan al HTML: el corte está en la
    # consulta, así que no hay nada que descubrir quitando una regla de CSS.
    assert "Reino 6" not in texto


def test_visitar_la_ficha_la_registra(cliente, ruta_db):
    cliente.get("/item/271440")
    con = abrir(ruta_db)
    assert con.execute("SELECT peticiones FROM pagina").fetchone()[0] == 1


def test_se_puede_pedir_una_variante_concreta(cliente):
    r = cliente.get("/item/271440?ilvl=318")
    assert r.status_code == 200
    assert "318" in r.text


def test_sin_ilvl_abre_por_la_variante_con_mas_mercado(cliente):
    """El 305 está en 10 reinos y el 318 en 1: se abre por el que enseña más."""
    texto = cliente.get("/item/271440").text
    assert "Reino 3" in texto


def test_un_ilvl_que_no_existe_no_revienta(cliente):
    """Una URL manipulada cae en la variante por defecto, no en un 500."""
    assert cliente.get("/item/271440?ilvl=9999").status_code == 200


def test_los_precios_salen_en_oro_y_no_en_cobre(cliente):
    """En la base todo es cobre; el usuario piensa en oro (10.000 cobre)."""
    texto = cliente.get("/item/271440").text
    assert "100" in texto            # 1.000.000 de cobre son 100 de oro
    assert "1000000" not in texto


def test_un_ilvl_que_no_es_un_numero_tampoco_revienta(cliente):
    """El mismo error del usuario no puede dar dos respuestas distintas."""
    r = cliente.get("/item/271440?ilvl=abc")
    assert r.status_code == 200
    assert "Greaves of the Noxious Depths" in r.text


def test_el_nombre_del_objeto_sale_escapado(tmp_path):
    """El nombre viene de la API de Blizzard: es texto de fuera.

    Hoy Jinja2 escapa solo, pero nada en la suite lo sujetaba: un `| safe`
    puesto más adelante para "nombres con formato" reabriría el agujero sin
    que fallara nada.
    """
    ruta = tmp_path / "x.db"
    con = abrir(ruta)
    guardar_reinos(con, {1: "Reino 1"})
    guardar_nombres(con, [(TIPO_OBJETO, 1, "en", "<script>alert(1)</script>", None)])
    volcar(con, {Clave(TIPO_OBJETO, 1, 305): {1: resumen(1_000_000)}}, generado_en=1)
    recalcular_estadisticas(con)
    con.close()

    texto = TestClient(crear_app(ruta)).get("/item/1").text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;" in texto


def test_la_pagina_de_reino_lista_lo_mas_rebajado(cliente):
    r = cliente.get("/realm/reino-1")
    assert r.status_code == 200
    assert "Reino 1" in r.text


def test_un_reino_desconocido_da_404(cliente):
    assert cliente.get("/realm/no-existe").status_code == 404


def test_el_sitemap_solo_lleva_lo_ya_pedido(cliente):
    """Anunciar 20.144 URLs que nadie ha visitado es contenido generado."""
    antes = cliente.get("/sitemap.xml").text
    assert "/item/271440" not in antes

    cliente.get("/item/271440")

    despues = cliente.get("/sitemap.xml").text
    assert despues.startswith("<?xml")
    assert "/item/271440" in despues


def test_el_sitemap_lleva_siempre_los_reinos(cliente):
    """Los reinos son 92 y fijos: esos sí se anuncian desde el primer día."""
    assert "/realm/reino-1" in cliente.get("/sitemap.xml").text


def test_el_sitemap_es_xml_de_verdad(cliente):
    """Si no parsea, Google lo descarta entero y no dice por qué."""
    import xml.etree.ElementTree as ET

    r = cliente.get("/sitemap.xml")
    assert r.headers["content-type"].startswith("application/xml")
    raiz = ET.fromstring(r.text)
    assert raiz.tag.endswith("urlset")


def test_la_ficha_no_promete_un_precio_normal_que_no_sabe(cliente):
    """El ilvl 318 solo esta en un reino: ahi no hay precio "normal".

    Presentar el unico precio que existe como "lo que cuesta normalmente" es
    afirmar algo que la base no sabe.
    """
    texto = cliente.get("/item/271440?ilvl=318").text
    assert "Normally costs" not in texto
    assert "1 realm" in texto


def test_con_reinos_de_sobra_si_sale_el_precio_normal(cliente):
    """El 305 esta en diez reinos: ahi la mediana si significa algo."""
    assert "Normally costs" in cliente.get("/item/271440?ilvl=305").text


def test_la_web_abre_la_base_que_diga_el_entorno(ruta_db, monkeypatch):
    """Sin esto, un uvicorn lanzado desde otra carpeta abre una base vacia,
    la crea con el esquema puesto, y da 404 en todo sin decir por que.
    """
    monkeypatch.setenv("AUCTION_DB", str(ruta_db))
    assert TestClient(crear_app()).get("/item/271440").status_code == 200


def test_sin_variable_de_entorno_usa_la_de_por_defecto(tmp_path, monkeypatch):
    """Y si la de por defecto no tiene nada, la pagina no existe: 404."""
    monkeypatch.delenv("AUCTION_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    assert TestClient(crear_app()).get("/item/271440").status_code == 404


# -- Portada y robots -------------------------------------------------------
#
# `/` daba 404. No es una página que faltara por escribir: es el destino del
# enlace de la marca, que `base.html` pinta en la cabecera de todas las
# páginas, así que cada visita que pulsaba el logotipo se comía un 404. Y el
# sitemap no se anunciaba en ningún sitio, que es lo que hace un robots.txt.


def test_la_portada_responde(cliente):
    r = cliente.get("/")
    assert r.status_code == 200


def test_la_portada_enlaza_los_reinos(cliente):
    texto = cliente.get("/").text
    assert '/realm/reino-1"' in texto
    assert "Reino 1" in texto


def test_la_portada_enlaza_lo_mas_visto(cliente):
    cliente.get("/item/271440")
    texto = cliente.get("/").text
    assert '/item/271440"' in texto
    assert "Greaves of the Noxious Depths" in texto


def test_la_portada_sin_visitas_no_saca_la_lista_vacia(cliente):
    """Recién instalada nadie ha pedido nada: mejor no sacar la sección."""
    texto = cliente.get("/").text
    assert "Greaves of the Noxious Depths" not in texto


def test_visitar_la_portada_no_cuenta_como_pedir_una_ficha(cliente, ruta_db):
    cliente.get("/")
    con = abrir(ruta_db)
    assert con.execute("SELECT count(*) FROM pagina").fetchone()[0] == 0


def test_la_portada_aguanta_una_base_vacia(tmp_path):
    """La primera pasada tarda una hora en llegar y hasta entonces no hay nada."""
    cliente = TestClient(crear_app(tmp_path / "vacia.db"))
    assert cliente.get("/").status_code == 200


def test_el_nombre_del_reino_sale_escapado(tmp_path):
    ruta = tmp_path / "x.db"
    con = abrir(ruta)
    guardar_reinos(con, {1: "<script>alert(1)</script>"})
    con.close()

    texto = TestClient(crear_app(ruta)).get("/").text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;" in texto


def test_hay_robots(cliente):
    r = cliente.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_el_robots_anuncia_el_sitemap(cliente):
    """Es la única pista que tiene un rastreador de que el sitemap existe."""
    assert "Sitemap: https://auctionsentinel.example/sitemap.xml" in (
        cliente.get("/robots.txt").text
    )


def test_el_sitemap_lleva_la_portada(cliente):
    """Es la página con más enlaces internos: dejarla fuera es dejar el mapa
    del sitio sin su raíz."""
    assert "<loc>https://auctionsentinel.example/</loc>" in (
        cliente.get("/sitemap.xml").text
    )


# -- La portada con datos ---------------------------------------------------
#
# El fixture `cliente` tiene diez reinos, por debajo del umbral de produccion
# (15), asi que con el no sale ni una rebaja. Este trae veinte justo para
# ejercitar la portada con el umbral de verdad, sin pasarselo a mano: si el
# dia de manana alguien sube ese numero en `mejores_rebajas`, este test lo
# nota en vez de seguir verde con un valor de juguete.


@pytest.fixture
def ruta_grande(tmp_path):
    ruta = tmp_path / "g.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(
        con,
        [
            (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths",
             "https://cdn/greaves.jpg"),
            (TIPO_OBJETO, 100, "en", "Cosa a su precio", None),
        ],
    )
    guardar_atributos(
        con,
        [
            {"tipo": TIPO_OBJETO, "producto_id": 271440, "clase_id": 4,
             "clase": "Armor", "subclase_id": 3, "subclase": "Mail",
             "calidad": "EPIC", "hueco": "FEET", "nivel": 219,
             "nivel_requerido": 90},
        ],
    )
    volcar(
        con,
        {
            # Mediana 1100 y el reino 1 a 110: un 90% de rebaja.
            Clave(TIPO_OBJETO, 271440, 305): {
                1: resumen(110), **{i: resumen(i * 100) for i in range(2, 21)}
            },
            Clave(TIPO_OBJETO, 100, 305): {i: resumen(500) for i in range(1, 21)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()
    return ruta


@pytest.fixture
def cliente_grande(ruta_grande):
    return TestClient(crear_app(ruta_grande))


def test_la_portada_lista_las_rebajas(cliente_grande):
    texto = cliente_grande.get("/").text
    assert "Greaves of the Noxious Depths" in texto
    assert "90%" in texto


def test_cada_rebaja_enlaza_su_objeto_y_su_reino(cliente_grande):
    texto = cliente_grande.get("/").text
    assert '/item/271440"' in texto
    assert '/realm/reino-1"' in texto


def test_lo_que_esta_a_su_precio_normal_no_sale_como_rebaja(cliente_grande):
    assert "Cosa a su precio" not in cliente_grande.get("/").text


def test_la_portada_dice_cuantos_objetos_y_reinos_cubre(cliente_grande):
    texto = cliente_grande.get("/").text
    assert "Items tracked" in texto and ">2<" in texto
    assert "Realms covered" in texto and ">20<" in texto


def test_la_portada_dice_de_cuando_son_los_datos(cliente_grande):
    """1788451184 es el 2026-09-03 a las 15:59 UTC."""
    texto = cliente_grande.get("/").text
    assert "3 September 2026" in texto
    assert "15:59 UTC" in texto


def test_el_mes_sale_en_ingles_aunque_el_servidor_este_en_espanol(cliente_grande):
    """La pagina esta en ingles y el VPS no tiene por que estarlo.

    `%B` de strftime saca el mes en la locale del sistema: en una maquina en
    espanol pondria "septiembre" en mitad de una frase en ingles.
    """
    assert "September" in cliente_grande.get("/").text


def test_sin_datos_la_portada_no_inventa_una_fecha(cliente):
    """El fixture pequeño no llega al umbral: hay reinos pero no rebajas."""
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Reino 1" in r.text


def test_las_rebajas_no_se_recalculan_en_cada_visita(cliente_grande, monkeypatch):
    """271 ms medidos con 932.000 filas: eso no puede correr por visita.

    Se cachean contra `volcado.generado_en`, que solo cambia cuando la pasada
    horaria escribe un volcado nuevo. No es un TTL a ojo: mientras ese numero
    sea el mismo, el resultado es literalmente el mismo.
    """
    import web.app

    veces = []
    original = web.app.mejores_rebajas

    def contando(*args, **kwargs):
        veces.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(web.app, "mejores_rebajas", contando)

    cliente_grande.get("/")
    cliente_grande.get("/")
    cliente_grande.get("/")

    assert len(veces) == 1


def test_un_volcado_nuevo_invalida_la_cache(cliente_grande, ruta_grande):
    """Si no, la portada se quedaria con las rebajas de la hora pasada."""
    assert "Greaves of the Noxious Depths" in cliente_grande.get("/").text

    con = abrir(ruta_grande)
    volcar(
        con,
        {Clave(TIPO_OBJETO, 100, 305): {i: resumen(500) for i in range(1, 21)}},
        generado_en=1788451184 + 3600,
    )
    recalcular_estadisticas(con)
    con.close()

    assert "Greaves of the Noxious Depths" not in cliente_grande.get("/").text


# -- Ningun enlace interno puede llevar a un 404 ----------------------------
#
# Este test existe porque el fallo se repitio dos veces: la marca de la
# cabecera apuntaba a `/`, que no estaba definida, y el "See all realms" de la
# ficha apuntaba a `/pro`, que era el plan de pago de la v3 y tampoco existia
# --con 92 reinos y 5 visibles, salia en casi todas las fichas. Un enlace
# muerto no lo ve nadie hasta que lo pulsa un usuario.


def test_ningun_enlace_interno_da_404(cliente_grande):
    import re

    paginas = ["/", "/item/271440", "/realm/reino-1"]
    vistos = set()
    for pagina in paginas:
        html = cliente_grande.get(pagina).text
        for href in re.findall(r'href="(/[^"#]*)"', html):
            if href in vistos:
                continue
            vistos.add(href)
            r = cliente_grande.get(href)
            assert r.status_code != 404, f"{pagina} enlaza a {href}, que da 404"

    # Si el regex dejara de encontrar nada, el test pasaria sin comprobar nada.
    assert "/" in vistos and any(h.startswith("/item/") for h in vistos)


# -- Los iconos --------------------------------------------------------------
#
# Una tabla de objetos de WoW sin sus iconos no se lee: son el unico rasgo por
# el que se reconoce un objeto de un vistazo, y los nombres son largos y se
# parecen entre si ("Uncanny Combatant's Satin Belt", "...Satin Pants").


def test_la_portada_pinta_el_icono_del_objeto(cliente_grande):
    assert "https://cdn/greaves.jpg" in cliente_grande.get("/").text


def test_la_ficha_pinta_el_icono_del_objeto(cliente_grande):
    assert "https://cdn/greaves.jpg" in cliente_grande.get("/item/271440").text


def test_la_pagina_de_reino_pinta_el_icono(cliente_grande):
    assert "https://cdn/greaves.jpg" in cliente_grande.get("/realm/reino-1").text


def test_un_objeto_sin_icono_no_deja_una_imagen_rota(tmp_path):
    """Blizzard no tiene icono para todo, y `<img src="">` pide la propia
    pagina otra vez en algunos navegadores. Sin icono, no hay etiqueta.
    """
    ruta = tmp_path / "si.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(con, [(TIPO_OBJETO, 1, "en", "Sin foto", None)])
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 1, 305): {
                1: resumen(50_000), **{i: resumen(100_000) for i in range(2, 21)}
            }
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()

    texto = TestClient(crear_app(ruta)).get("/").text
    assert "Sin foto" in texto
    assert 'src=""' not in texto


def test_en_movil_el_reino_sigue_estando_aunque_su_columna_se_caiga(cliente_grande):
    """A 375px las cuatro columnas no caben y el % de rebaja se salia.

    La columna de reino se cae en pantalla estrecha, pero el dato no puede
    perderse --sin el reino la ganga no sirve de nada-- asi que se repite
    debajo del nombre. El HTML lleva las dos; el CSS ensena una u otra.
    """
    texto = cliente_grande.get("/").text
    assert texto.count("Reino 1") >= 2
    assert "reino-movil" in texto


# -- Categorias y buscador ---------------------------------------------------


@pytest.fixture
def ruta_catalogo(tmp_path):
    ruta = tmp_path / "cat.db"
    con = abrir(ruta)
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 21)})
    piezas = [
        (1, "Mail Boots", "Armor", "Mail", "EPIC"),
        (2, "Mail Helm", "Armor", "Mail", "RARE"),
        (3, "Plate Boots", "Armor", "Plate", "EPIC"),
        (4, "Big Sword", "Weapon", "One-Handed Swords", "EPIC"),
        (5, "Recipe: Soup", "Recipe", "Cooking", "COMMON"),
    ]
    guardar_nombres(
        con, [(TIPO_OBJETO, i, "en", n, f"https://cdn/{i}.jpg") for i, n, *_ in piezas]
    )
    guardar_atributos(
        con,
        [
            {"tipo": TIPO_OBJETO, "producto_id": i, "clase_id": 1, "clase": c,
             "subclase_id": 1, "subclase": s, "calidad": q, "hueco": "FEET",
             "nivel": 200, "nivel_requerido": 70}
            for i, n, c, s, q in piezas
        ],
    )
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, i, 305): {
                1: resumen(10_000 * i),
                **{r: resumen(100_000 * i) for r in range(2, 21)},
            }
            for i, *_ in piezas
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    con.close()
    return ruta


@pytest.fixture
def cliente_catalogo(ruta_catalogo):
    return TestClient(crear_app(ruta_catalogo))


def test_el_indice_de_categorias_responde(cliente_catalogo):
    r = cliente_catalogo.get("/items")
    assert r.status_code == 200
    for esperado in ("Armor", "Weapon", "Recipe"):
        assert esperado in r.text


def test_el_indice_enlaza_cada_categoria(cliente_catalogo):
    texto = cliente_catalogo.get("/items").text
    assert '/items/armor"' in texto
    assert '/items/weapon"' in texto


def test_una_categoria_lista_sus_objetos_y_sus_subcategorias(cliente_catalogo):
    texto = cliente_catalogo.get("/items/armor").text
    assert "Mail Boots" in texto and "Plate Boots" in texto
    assert '/items/armor/mail"' in texto
    assert "Big Sword" not in texto


def test_una_subcategoria_afina(cliente_catalogo):
    texto = cliente_catalogo.get("/items/armor/mail").text
    assert "Mail Boots" in texto
    assert "Plate Boots" not in texto


def test_una_categoria_que_no_existe_da_404(cliente_catalogo):
    assert cliente_catalogo.get("/items/no-existe").status_code == 404
    assert cliente_catalogo.get("/items/armor/no-existe").status_code == 404


def test_la_categoria_no_dice_en_que_reino_esta_lo_barato(cliente_catalogo):
    """Es lo que vende el Pro: una tabla de cien filas lo regalaria en bloque."""
    texto = cliente_catalogo.get("/items/armor").text
    assert "Reino 1" not in texto


def test_las_paginas_de_categoria_se_enlazan_entre_si(cliente_catalogo, monkeypatch):
    """Sin el enlace a la pagina 2, Google solo ve los primeros 100 objetos y
    el catalogo sigue sin estar enlazado, que es todo el motivo de esto."""
    import web.app

    monkeypatch.setattr(web.app, "POR_PAGINA", 2)
    texto = cliente_catalogo.get("/items/armor").text
    assert "?p=2" in texto


def test_la_pagina_dos_ensena_otros_objetos(cliente_catalogo, monkeypatch):
    import web.app

    monkeypatch.setattr(web.app, "POR_PAGINA", 2)
    p1 = cliente_catalogo.get("/items/armor").text
    p2 = cliente_catalogo.get("/items/armor?p=2").text
    assert "Mail Boots" in p1 and "Mail Boots" not in p2
    assert "Plate Boots" in p2


def test_una_pagina_que_no_existe_da_404(cliente_catalogo):
    """Si no, hay infinitas URLs vacias que Google se dedica a rastrear."""
    assert cliente_catalogo.get("/items/armor?p=99").status_code == 404


def test_el_buscador_responde(cliente_catalogo):
    r = cliente_catalogo.get("/search?q=mail")
    assert r.status_code == 200
    assert "Mail Boots" in r.text and "Big Sword" not in r.text


def test_el_buscador_sin_texto_no_revienta(cliente_catalogo):
    assert cliente_catalogo.get("/search").status_code == 200


def test_la_caja_de_busqueda_sale_en_todas_las_paginas(cliente_catalogo):
    for ruta in ("/", "/items", "/items/armor", "/item/1", "/realm/reino-1"):
        assert 'action="/search"' in cliente_catalogo.get(ruta).text, ruta


def test_el_sitemap_lleva_las_categorias(cliente_catalogo):
    texto = cliente_catalogo.get("/sitemap.xml").text
    assert "/items</loc>" in texto
    assert "/items/armor</loc>" in texto
    assert "/items/armor/mail</loc>" in texto


def test_ningun_enlace_de_las_categorias_da_404(cliente_catalogo):
    import re

    paginas = (
        "/items", "/items/armor", "/items/armor/mail", "/search?q=mail",
        # Filtrada: con una calidad puesta, los enlaces de tipo se la llevan,
        # y no todos los tipos tienen esa calidad.
        "/items/armor?quality=RARE",
    )
    for pagina in paginas:
        for href in set(re.findall(r'href="(/[^"#]*)"', cliente_catalogo.get(pagina).text)):
            assert cliente_catalogo.get(href).status_code != 404, f"{pagina} -> {href}"


def test_la_subcategoria_abierta_se_ve_marcada(cliente_catalogo):
    """Sin esto las opciones salen todas iguales y no se sabe cual esta puesta.

    Antes eran pastillas y el modificador `activo` vivia solo en `.ilvl`, la
    pastilla de la ficha. Ahora son opciones dentro del desplegable, pero la
    marca tiene que seguir estando: al abrirlo se ve cual es la de ahora.
    """
    texto = cliente_catalogo.get("/items/armor/mail").text
    assert 'class="op activo"' in texto


# -- Canonical y tarjetas sociales -------------------------------------------
#
# Dos agujeros medidos: 773 URLs `?ilvl=` con titulo y descripcion identicos y
# sin canonical (el 4% del sitio, pero cae justo en las 589 fichas de equipo,
# que son las de busqueda con mas intencion), y cero etiquetas Open Graph, o
# sea que cada enlace pegado en Discord salia como una URL pelada. Para un
# producto cuyo publico vive en Discord, eso es tirar la distribucion gratis.


def test_la_ficha_declara_su_canonical(cliente_grande):
    html = cliente_grande.get("/item/271440").text
    assert '<link rel="canonical" href="https://auctionsentinel.example/item/271440">' in html


def test_las_variantes_de_ilvl_apuntan_a_la_misma_canonical(cliente_grande):
    """Las 13 URLs de un objeto con 12 ilvl son una sola pagina para Google."""
    html = cliente_grande.get("/item/271440?ilvl=305").text
    assert 'href="https://auctionsentinel.example/item/271440">' in html
    assert "?ilvl=" not in html.split("canonical")[1].split(">")[0]


def test_la_portada_y_los_reinos_tambien_la_declaran(cliente_grande):
    assert 'canonical" href="https://auctionsentinel.example/">' in (
        cliente_grande.get("/").text
    )
    assert 'canonical" href="https://auctionsentinel.example/realm/reino-1">' in (
        cliente_grande.get("/realm/reino-1").text
    )


def test_la_pagina_dos_de_una_categoria_es_su_propia_canonical(
    cliente_catalogo, monkeypatch
):
    """Aqui NO se apunta a la pagina 1: son objetos distintos, no duplicados.

    Si la 2 dijera que su canonical es la 1, Google descartaria el contenido de
    la 2 y volveriamos a tener el catalogo sin enlazar.
    """
    import web.app

    monkeypatch.setattr(web.app, "POR_PAGINA", 2)
    html = cliente_catalogo.get("/items/armor?p=2").text
    assert 'canonical" href="https://auctionsentinel.example/items/armor?p=2">' in html


def test_el_buscador_no_se_indexa(cliente_catalogo):
    """Paginas de resultados internos: Google las trata como contenido fino y
    penaliza el sitio entero por ellas."""
    html = cliente_catalogo.get("/search?q=mail").text
    assert '<meta name="robots" content="noindex,follow">' in html


def test_las_paginas_de_verdad_si_se_indexan(cliente_grande):
    for ruta in ("/", "/item/271440", "/realm/reino-1"):
        assert "noindex" not in cliente_grande.get(ruta).text, ruta


def test_la_tarjeta_social_repite_titulo_y_descripcion(cliente_grande):
    html = cliente_grande.get("/item/271440").text
    assert 'property="og:title" content="Greaves of the Noxious Depths' in html
    assert 'property="og:description"' in html
    assert 'property="og:url" content="https://auctionsentinel.example/item/271440"' in html


def test_la_tarjeta_de_una_ficha_lleva_el_icono_del_objeto(cliente_grande):
    """Es lo que se ve al pegar el enlace en Discord."""
    html = cliente_grande.get("/item/271440").text
    assert 'property="og:image" content="https://cdn/greaves.jpg"' in html


def test_una_ficha_sin_icono_no_deja_una_tarjeta_con_imagen_vacia(cliente_catalogo):
    html = cliente_catalogo.get("/item/5").text
    assert 'og:image" content=""' not in html


def test_hay_tarjeta_de_twitter(cliente_grande):
    assert 'name="twitter:card"' in cliente_grande.get("/item/271440").text


# -- Los filtros, visibles ---------------------------------------------------


def test_una_categoria_se_puede_filtrar_por_calidad(cliente_catalogo):
    texto = cliente_catalogo.get("/items/armor?quality=RARE").text
    assert "Mail Helm" in texto
    assert "Mail Boots" not in texto


def test_el_filtro_de_calidad_se_ofrece_con_lo_que_hay(cliente_catalogo):
    """Ofrecer "Legendary" donde no hay ninguno lleva a una lista vacia, y eso
    se siente como un fallo de la web, no como un dato del mercado."""
    texto = cliente_catalogo.get("/items/armor").text
    assert "Epic" in texto and "Rare" in texto
    assert "Legendary" not in texto


def test_una_calidad_que_no_existe_ahi_da_404(cliente_catalogo):
    assert cliente_catalogo.get("/items/armor?quality=LEGENDARY").status_code == 404
    assert cliente_catalogo.get("/items/armor?quality=INVENTADA").status_code == 404


def test_el_filtro_de_calidad_sobrevive_a_la_paginacion(cliente_catalogo, monkeypatch):
    """Pasar de pagina no puede perder el filtro puesto."""
    import web.app

    monkeypatch.setattr(web.app, "POR_PAGINA", 1)
    texto = cliente_catalogo.get("/items/armor?quality=EPIC").text
    # `&amp;` y no `&`: Jinja escapa el enlace, que es lo correcto en HTML.
    assert "?p=2&amp;quality=EPIC" in texto


def test_filtrar_por_calidad_es_su_propia_canonical(cliente_catalogo):
    html = cliente_catalogo.get("/items/armor?quality=EPIC").text
    assert 'canonical" href="https://auctionsentinel.example/items/armor?quality=EPIC"' in html


def test_se_ve_que_los_filtros_son_filtros(cliente_catalogo):
    """Antes eran pastillas sueltas sin etiqueta: no se leian como un control."""
    texto = cliente_catalogo.get("/items/armor").text
    assert "filtros" in texto or "Type" in texto
    assert "Quality" in texto


def test_hay_como_quitar_los_filtros(cliente_catalogo):
    texto = cliente_catalogo.get("/items/armor/mail?quality=EPIC").text
    assert 'href="/items/armor"' in texto


# -- La calidad se ve en el color -------------------------------------------


def test_el_nombre_va_de_la_clase_de_su_calidad(cliente_catalogo):
    texto = cliente_catalogo.get("/items/armor").text
    assert "q-epic" in texto and "q-rare" in texto


def test_la_portada_tambien_colorea(cliente_grande):
    """Consistencia: el mismo objeto no puede ir de un color en una pagina y
    de otro en la siguiente."""
    assert "q-" in cliente_grande.get("/").text


def test_un_objeto_sin_calidad_no_deja_una_clase_rota(cliente_grande):
    assert 'class="objeto q-None"' not in cliente_grande.get("/").text
    assert 'q-"' not in cliente_grande.get("/").text


def test_la_ficha_colorea_su_titulo(cliente_catalogo):
    assert 'class="titulo q-epic"' in cliente_catalogo.get("/item/1").text


# -- El autocompletar de la caja ---------------------------------------------
#
# Hasta aqui la caja era un formulario a pelo: escribir el nombre entero y
# pulsar Enter para caer en /search. `/suggest` es lo que la convierte en un
# buscador de verdad -- devuelve JSON y la cabecera lo pinta debajo del campo,
# sin cambiar de pagina.
#
# Sigue siendo un anadido: sin JavaScript el formulario funciona igual que
# antes, y por eso el GET a /search no se toca.


def test_el_autocompletar_responde_json(cliente_catalogo):
    r = cliente_catalogo.get("/suggest?q=mail")
    assert r.status_code == 200
    # "Mail Helm" (9) antes que "Mail Boots" (10): los dos empiezan por lo
    # tecleado, asi que desempata el nombre mas corto.
    assert [s["nombre"] for s in r.json()["resultados"]] == ["Mail Helm", "Mail Boots"]


def test_cada_sugerencia_llega_lista_para_pintarse(cliente_catalogo):
    """Icono, calidad y precio: la fila del desplegable se pinta sin volver."""
    fila = cliente_catalogo.get("/suggest?q=mail+boots").json()["resultados"][0]
    assert fila == {
        "producto_id": 1,
        "nombre": "Mail Boots",
        "icono": "https://cdn/1.jpg",
        "calidad": "EPIC",
        # Ya en oro y con sus separadores: el cobre es de la base de datos y
        # formatearlo en JavaScript seria escribir `_oro` dos veces.
        "desde": "1",
    }


def test_el_autocompletar_sin_texto_no_devuelve_el_catalogo(cliente_catalogo):
    r = cliente_catalogo.get("/suggest?q=")
    assert r.status_code == 200 and r.json()["resultados"] == []


def test_el_autocompletar_tampoco_dice_en_que_reino(cliente_catalogo):
    """La misma linea que el buscador y las categorias: donde esta barato es
    justo lo que vende el Pro (spec v3)."""
    assert "Reino" not in cliente_catalogo.get("/suggest?q=mail").text


def test_el_autocompletar_no_se_indexa(cliente_catalogo):
    """No es una pagina; es la trastienda de la caja."""
    r = cliente_catalogo.get("/suggest?q=mail")
    assert "noindex" in r.headers["x-robots-tag"]


def test_la_caja_autocompleta_en_todas_las_paginas(cliente_catalogo):
    for ruta in ("/", "/items", "/items/armor", "/item/1", "/realm/reino-1"):
        texto = cliente_catalogo.get(ruta).text
        assert 'role="combobox"' in texto, ruta
        assert "/estaticos/interfaz.js" in texto, ruta


def test_sin_javascript_la_busqueda_sigue_siendo_un_formulario(cliente_catalogo):
    """El autocompletar es un anadido, no un requisito."""
    assert 'action="/search"' in cliente_catalogo.get("/").text
    assert cliente_catalogo.get("/search?q=mail").status_code == 200


# -- Los filtros, en la propia pagina ----------------------------------------
#
# Eran tres filas de pastillas sueltas: con las 12 subclases de Armor o las 20
# de Weapon, el panel media mas que la tabla que filtraba. Ahora es un
# desplegable por criterio, que se abre encima de la pagina y no lleva a
# ninguna otra.


def test_los_filtros_se_abren_ahi_mismo(cliente_catalogo):
    """`<details>` y no una pagina de filtros: se abre y se cierra en el sitio.

    Nativo del navegador a proposito -- sin JavaScript los filtros siguen
    abriendose, que es lo que ve un rastreador y quien tenga el JS caido.
    """
    texto = cliente_catalogo.get("/items/armor").text
    assert texto.count("<details") >= 2
    assert "<summary" in texto


def test_el_desplegable_dice_lo_que_hay_puesto_sin_abrirlo(cliente_catalogo):
    """Un filtro que no dice como esta puesto no es un filtro, es un boton."""
    texto = cliente_catalogo.get("/items/armor/mail?quality=EPIC").text
    assert 'class="puesto">Mail<' in texto
    assert 'class="puesto">Epic<' in texto


def test_sin_filtrar_los_desplegables_dicen_que_estan_todos(cliente_catalogo):
    texto = cliente_catalogo.get("/items/armor").text
    assert texto.count('class="puesto">All<') == 2


def test_se_cambia_de_categoria_sin_pasar_por_el_indice(cliente_catalogo):
    """Ir a /items para elegir otra categoria es salir de la pagina a filtrar,
    que es justo lo que el desplegable evita."""
    texto = cliente_catalogo.get("/items/armor").text
    assert 'href="/items/weapon"' in texto
    assert 'href="/items/recipe"' in texto


def test_el_script_de_la_interfaz_se_sirve(cliente_catalogo):
    """La cabecera lo pide en todas las paginas; una ruta mal escrita es un
    404 que no se ve --la pagina se pinta igual-- y deja la caja muda."""
    r = cliente_catalogo.get("/estaticos/interfaz.js")
    assert r.status_code == 200
    assert "sugerencias" in r.text


def test_el_desplegable_de_tipo_no_ofrece_callejones_sin_salida(cliente_catalogo):
    """Con Rare puesto, cada tipo del menu se lleva el `?quality=RARE`. Plate
    no tiene nada raro, asi que ese enlace es un 404 -- y un filtro no puede
    ofrecer una opcion que rompe la pagina.

    Salio rastreando la base de verdad: `/items/weapon/miscellaneous` y
    `/items/weapon/thrown` con `?quality=EPIC` daban 404 desde el propio panel.
    """
    texto = cliente_catalogo.get("/items/armor?quality=RARE").text
    assert "/items/armor/mail?quality=RARE" in texto
    assert "/items/armor/plate?quality=RARE" not in texto


def test_el_desplegable_de_tipo_cuenta_lo_que_hay_de_esa_calidad(cliente_catalogo):
    """Mail tiene dos objetos, pero raro solo uno: con Rare puesto, decir "2"
    es prometer una lista que no existe."""
    texto = cliente_catalogo.get("/items/armor?quality=RARE").text
    assert "Mail <span class=\"cuenta\">1</span>" in texto


# -- Elegir que objetos ver, desde donde sea ---------------------------------
#
# Los filtros de categoria solo existian dentro de /items/<clase>, y para
# llegar habia que pulsar "Browse", que abre otra pagina cuyo unico contenido
# es elegir. O sea: salir de donde estas para poder filtrar. Ahora el menu vive
# en la cabecera y se despliega encima de la pagina que estes viendo.


def test_se_elige_categoria_desde_cualquier_pagina(cliente_catalogo):
    for ruta in ("/", "/item/1", "/realm/reino-1", "/search?q=mail",
                 "/items", "/items/armor", "/items/armor/mail"):
        texto = cliente_catalogo.get(ruta).text
        assert 'class="desplegable menu-nav"' in texto, ruta
        assert 'href="/items/weapon"' in texto, ruta
        assert 'href="/items/recipe"' in texto, ruta


def test_el_menu_de_la_cabecera_se_abre_ahi_mismo(cliente_catalogo):
    """`<details>`, como los filtros de categoria: se abre encima y no lleva a
    ninguna pagina intermedia."""
    texto = cliente_catalogo.get("/").text
    assert texto.index("<details") < texto.index("</nav>")


def test_el_indice_de_categorias_sigue_existiendo(cliente_catalogo):
    """No se quita /items: de esa pagina cuelga el catalogo entero para
    Googlebot. Lo que se quita es la obligacion de pasar por ella."""
    assert cliente_catalogo.get("/items").status_code == 200
    assert 'href="/items"' in cliente_catalogo.get("/").text


def test_el_menu_de_la_cabecera_no_se_recalcula_en_cada_visita(
    cliente_catalogo, monkeypatch
):
    """Sale en todas las paginas y cuesta 30 ms medidos sobre la base real.

    Se cachea contra `volcado.generado_en`, igual que las rebajas de la
    portada: las categorias solo cambian cuando la pasada horaria mete objetos
    nuevos.
    """
    import web.app

    veces = []
    original = web.app.categorias

    def contando(*args, **kwargs):
        veces.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(web.app, "categorias", contando)

    cliente_catalogo.get("/")
    cliente_catalogo.get("/item/1")
    cliente_catalogo.get("/items/armor")

    assert len(veces) == 1
