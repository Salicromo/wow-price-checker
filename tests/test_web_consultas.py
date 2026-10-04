import pytest

from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino
from web.db import abrir
from web.consultas import (
    REINOS_GRATIS,
    REINOS_PARA_MEDIANA,
    TOPE_CDS,
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
def con(tmp_path):
    c = abrir(tmp_path / "p.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 11)})
    guardar_nombres(
        c, [(TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", "http://i.jpg")]
    )
    agregado = {
        # 10 reinos, de 100 a 1000, para que se vea el corte de los 5 gratis.
        Clave(TIPO_OBJETO, 271440, 305): {i: resumen(i * 100, listados=i) for i in range(1, 11)},
        Clave(TIPO_OBJETO, 271440, 318): {1: resumen(9000)},
    }
    volcar(c, agregado, generado_en=1788451184)
    recalcular_estadisticas(c)
    return c


def test_la_ficha_trae_el_nombre_y_las_variantes(con):
    f = ficha(con, TIPO_OBJETO, 271440)
    assert f["nombre"] == "Greaves of the Noxious Depths"
    assert [v["variante"] for v in f["variantes"]] == [305, 318]


def test_la_ficha_trae_las_estadisticas_de_cada_variante(con):
    f = ficha(con, TIPO_OBJETO, 271440)
    v305 = f["variantes"][0]
    assert v305["minimo"] == 100
    assert v305["maximo"] == 1000
    assert v305["reinos"] == 10


def test_la_ficha_trae_cuando_se_generaron_los_datos(con):
    assert ficha(con, TIPO_OBJETO, 271440)["generado_en"] == 1788451184


def test_sin_volcado_la_ficha_sale_sin_fecha_en_vez_de_reventar(con):
    """Una base a medias no debe tumbar la página, solo dejarla sin fecha.

    No pasa por el camino normal --`volcar` escribe precio y volcado en la
    misma transacción-- pero sí con una base restaurada a medias o con un
    borrado a mano, y ahí un 500 es peor que una ficha sin sello de hora.
    """
    con.execute("DELETE FROM volcado")

    f = ficha(con, TIPO_OBJETO, 271440)
    assert f is not None
    assert f["nombre"] == "Greaves of the Noxious Depths"
    assert f["generado_en"] is None


def test_un_producto_que_no_existe_no_tiene_ficha(con):
    assert ficha(con, TIPO_OBJETO, 999999) is None


def test_un_producto_sin_nombre_traducido_sale_por_su_id(con):
    """Nunca una ficha en blanco: si falta el nombre, al menos el id."""
    volcar(con, {Clave(TIPO_OBJETO, 555, 305): {1: resumen(100)}}, generado_en=1)
    recalcular_estadisticas(con)

    f = ficha(con, TIPO_OBJETO, 555)
    assert f is not None
    assert "555" in f["nombre"]


def test_los_reinos_salen_de_mas_barato_a_mas_caro(con):
    filas = reinos_de(con, TIPO_OBJETO, 271440, 305, limite=None)
    assert [f["minimo"] for f in filas] == [i * 100 for i in range(1, 11)]
    assert filas[0]["nombre"] == "Reino 1"


def test_los_reinos_traen_cuantas_subastas_hay(con):
    filas = reinos_de(con, TIPO_OBJETO, 271440, 305, limite=None)
    assert filas[0]["listados"] == 1
    assert filas[9]["listados"] == 10


def test_el_plan_gratis_solo_ve_cinco_reinos(con):
    filas = reinos_de(con, TIPO_OBJETO, 271440, 305, limite=REINOS_GRATIS)
    assert len(filas) == REINOS_GRATIS
    # El muro está en la consulta, no en la plantilla: los otros cinco no
    # llegan a salir de la base, así que no hay nada que descubrir mirando el
    # HTML ni quitando una regla de CSS.
    assert [f["minimo"] for f in filas] == [100, 200, 300, 400, 500]


def test_lo_que_no_escala_se_pide_con_variante_none(con):
    """Un patrón o una montura no tienen ilvl; en la base son -1."""
    volcar(con, {Clave(TIPO_OBJETO, 258126, None): {1: resumen(4200)}}, generado_en=1)
    recalcular_estadisticas(con)

    filas = reinos_de(con, TIPO_OBJETO, 258126, None, limite=None)
    assert [f["minimo"] for f in filas] == [4200]


def test_la_primera_peticion_crea_la_pagina(con):
    anotar_peticion(con, TIPO_OBJETO, 271440, ahora=1000)

    fila = con.execute("SELECT * FROM pagina").fetchone()
    assert fila["producto_id"] == 271440
    assert fila["primera_peticion"] == 1000
    assert fila["peticiones"] == 1


def test_las_siguientes_solo_cuentan(con):
    anotar_peticion(con, TIPO_OBJETO, 271440, ahora=1000)
    anotar_peticion(con, TIPO_OBJETO, 271440, ahora=2000)

    fila = con.execute("SELECT * FROM pagina").fetchone()
    assert fila["peticiones"] == 2
    # La fecha es la de la PRIMERA vez: dice desde cuándo existe la página.
    assert fila["primera_peticion"] == 1000


def test_sin_hora_usa_la_de_ahora(con):
    import time

    antes = int(time.time())
    anotar_peticion(con, TIPO_OBJETO, 271440)
    fila = con.execute("SELECT primera_peticion FROM pagina").fetchone()
    assert antes <= fila[0] <= int(time.time())


def test_las_mas_pedidas_salen_primero(con):
    anotar_peticion(con, TIPO_OBJETO, 1, ahora=1)
    for _ in range(3):
        anotar_peticion(con, TIPO_OBJETO, 2, ahora=1)

    assert [p["producto_id"] for p in paginas_mas_pedidas(con, limite=2)] == [2, 1]


def test_sin_paginas_pedidas_la_lista_esta_vacia(con):
    """Un sitio recién desplegado: el sitemap sale vacío, no con 20.144 URLs."""
    assert paginas_mas_pedidas(con, limite=100) == []


def test_un_fallo_al_contar_no_tumba_la_pagina(con, caplog):
    """Contar visitas es contabilidad, no contenido.

    Se tira la tabla para provocar un fallo de verdad de SQLite, en vez de
    simularlo: si `anotar_peticion` dejara subir la excepción, el visitante
    se llevaría un 500 con la ficha ya cargada y lista para pintarse.
    """
    import logging as _logging

    con.execute("DROP TABLE pagina")

    with caplog.at_level(_logging.WARNING):
        anotar_peticion(con, TIPO_OBJETO, 271440)  # no debe lanzar

    assert "271440" in caplog.text


def test_hay_que_decir_cuantas_paginas_se_quieren(con):
    """Sin valor por defecto: un sitemap truncado en silencio no se ve."""
    with pytest.raises(TypeError):
        paginas_mas_pedidas(con)


def test_un_reino_por_su_slug(con):
    r = reino_por_slug(con, "reino-3")
    assert r["id"] == 3
    assert r["nombre"] == "Reino 3"


def test_un_slug_que_no_existe_no_da_reino(con):
    assert reino_por_slug(con, "no-existe") is None


def test_lo_mas_rebajado_de_un_reino_sale_primero(con):
    """Ordenar por precio a secas sacaría lo más caro, que no interesa.

    Lo que se busca es dónde este reino está barato respecto a la región.

    La fixture `con` solo monta 10 reinos (no los 92 de producción), así que
    aquí se baja `reinos_minimos` a 10 -- el valor por defecto de la función
    (15) sigue siendo el de producción y no se toca.
    """
    filas = productos_de_reino(con, 1, limite=10, reinos_minimos=10)
    assert filas, "el reino 1 es el más barato de los diez, algo tiene que salir"
    assert filas[0]["minimo"] < filas[0]["mediana"]


def test_un_reino_caro_no_tiene_rebajas(con):
    """El reino 10 es el más caro de los diez: nada por debajo de la mediana."""
    assert productos_de_reino(con, 10, limite=10, reinos_minimos=10) == []


@pytest.fixture
def con_rebajas(tmp_path):
    """Dos productos con descuentos distintos en el mismo reino.

    Hace falta más de uno para poder ver el orden: con una sola fila, una
    consulta que ordenara por precio bruto en vez de por descuento pasaría
    igual, que es justo lo que este fixture existe para impedir.
    """
    c = abrir(tmp_path / "r.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 11)})
    guardar_nombres(
        c,
        [
            (TIPO_OBJETO, 100, "en", "Barato pero poco rebajado", None),
            (TIPO_OBJETO, 200, "en", "Caro y muy rebajado", None),
        ],
    )
    volcar(
        c,
        {
            # Mediana 100, y en el reino 1 está a 95: solo un 5% de rebaja.
            # Precio bruto BAJO (95) pero descuento pequeño.
            Clave(TIPO_OBJETO, 100, 305): {
                1: resumen(95), **{i: resumen(100) for i in range(2, 11)}
            },
            # Mediana 10000, y en el reino 1 está a 8000: un 20% de rebaja.
            # Precio bruto ALTO (8000) pero descuento grande. Si la consulta
            # ordenara por precio bruto en vez de por descuento, el 100
            # (95 < 8000) saldría primero; ordenando por descuento gana el
            # 200, que es justo lo que comprueba el test de abajo.
            Clave(TIPO_OBJETO, 200, 305): {
                1: resumen(8000), **{i: resumen(10000) for i in range(2, 11)}
            },
        },
        generado_en=1,
    )
    recalcular_estadisticas(c)
    return c


def test_gana_el_mas_rebajado_no_el_mas_barato(con_rebajas):
    filas = productos_de_reino(con_rebajas, 1, limite=10, reinos_minimos=10)
    assert [f["producto_id"] for f in filas] == [200, 100]


def test_el_limite_recorta(con_rebajas):
    assert len(productos_de_reino(con_rebajas, 1, limite=1, reinos_minimos=10)) == 1


def test_solo_sale_lo_que_esta_por_debajo_de_su_mediana(con_rebajas):
    """En el reino 5 los dos están a su precio normal: no hay rebaja."""
    assert productos_de_reino(con_rebajas, 5, limite=10, reinos_minimos=10) == []


def test_con_pocos_reinos_la_mediana_no_es_fiable(con):
    """Con un solo reino la "mediana" es el unico precio que existe.

    El fixture tiene el ilvl 318 en un reino y el 305 en diez, asi que sirven
    los dos casos sin montar nada aparte.
    """
    variantes = {v["variante"]: v for v in ficha(con, TIPO_OBJETO, 271440)["variantes"]}
    assert variantes[318]["reinos"] == 1
    assert variantes[318]["mediana_fiable"] is False


def test_con_reinos_de_sobra_la_mediana_es_fiable(con):
    variantes = {v["variante"]: v for v in ficha(con, TIPO_OBJETO, 271440)["variantes"]}
    assert variantes[305]["reinos"] >= REINOS_PARA_MEDIANA
    assert variantes[305]["mediana_fiable"] is True


def test_el_umbral_es_el_de_la_constante(tmp_path):
    """Justo por debajo no, justo en el umbral si."""
    con = abrir(tmp_path / "u.db")
    guardar_reinos(con, {i: f"Reino {i}" for i in range(1, 21)})
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 1, 305): {
                i: resumen(i * 100) for i in range(1, REINOS_PARA_MEDIANA)
            },
            Clave(TIPO_OBJETO, 2, 305): {
                i: resumen(i * 100) for i in range(1, REINOS_PARA_MEDIANA + 1)
            },
        },
        generado_en=1,
    )
    recalcular_estadisticas(con)

    justo_debajo = ficha(con, TIPO_OBJETO, 1)["variantes"][0]
    justo_encima = ficha(con, TIPO_OBJETO, 2)["variantes"][0]
    assert justo_debajo["reinos"] == REINOS_PARA_MEDIANA - 1
    assert justo_debajo["mediana_fiable"] is False
    assert justo_encima["reinos"] == REINOS_PARA_MEDIANA
    assert justo_encima["mediana_fiable"] is True


# -- La portada -------------------------------------------------------------
#
# `/` daba 404 mientras el enlace de la marca, que sale en TODAS las páginas,
# apuntaba ahí. La portada necesita dos listas: los reinos que se cubren y los
# productos que ya se piden, que es por donde se entra al resto del sitio.


def test_los_reinos_publicados_traen_nombre_y_slug(con):
    reinos = reinos_publicados(con)
    assert len(reinos) == 10
    assert {"nombre": "Reino 1", "slug": "reino-1"} in reinos


def test_los_reinos_publicados_salen_ordenados(con):
    """Alfabético: la portada es una lista para leer, no un ranking."""
    nombres = [r["nombre"] for r in reinos_publicados(con)]
    assert nombres == sorted(nombres)


def test_sin_reinos_la_lista_esta_vacia(tmp_path):
    assert reinos_publicados(abrir(tmp_path / "vacia.db")) == []


def test_los_productos_mas_vistos_salen_por_peticiones(con):
    guardar_nombres(con, [(TIPO_OBJETO, 999, "en", "Otra cosa", None)])
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 271440, 305): {1: resumen(100)},
            Clave(TIPO_OBJETO, 999, 305): {1: resumen(100)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    anotar_peticion(con, TIPO_OBJETO, 999)
    anotar_peticion(con, TIPO_OBJETO, 999)
    anotar_peticion(con, TIPO_OBJETO, 271440)

    vistos = productos_mas_vistos(con, limite=10)
    assert [p["producto_id"] for p in vistos] == [999, 271440]


def test_los_productos_mas_vistos_traen_su_nombre(con):
    anotar_peticion(con, TIPO_OBJETO, 271440)
    assert productos_mas_vistos(con, limite=10)[0]["nombre"] == (
        "Greaves of the Noxious Depths"
    )


def test_el_limite_de_los_mas_vistos_recorta(con):
    guardar_nombres(con, [(TIPO_OBJETO, 999, "en", "Otra cosa", None)])
    volcar(
        con,
        {
            Clave(TIPO_OBJETO, 271440, 305): {1: resumen(100)},
            Clave(TIPO_OBJETO, 999, 305): {1: resumen(100)},
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(con)
    anotar_peticion(con, TIPO_OBJETO, 271440)
    anotar_peticion(con, TIPO_OBJETO, 999)

    assert len(productos_mas_vistos(con, limite=1)) == 1


def test_un_producto_que_ya_no_esta_en_el_volcado_no_sale_en_la_portada(con):
    """Enlazar desde la portada algo que da 404 es peor que no enlazarlo.

    `pagina` es un histórico y no se poda: un objeto que Blizzard retire sigue
    ahí con sus peticiones, pero su ficha ya responde 404 porque `ficha()` la
    busca en `estadistica`, que sí se reescribe en cada pasada.
    """
    anotar_peticion(con, TIPO_OBJETO, 271440)
    anotar_peticion(con, TIPO_OBJETO, 424242)

    assert [p["producto_id"] for p in productos_mas_vistos(con, limite=10)] == [271440]


def test_una_variante_por_producto_aunque_tenga_varios_ilvl(con):
    """El 271440 está a 305 y a 318: la portada lo enseña una vez, no dos."""
    anotar_peticion(con, TIPO_OBJETO, 271440)
    assert len(productos_mas_vistos(con, limite=10)) == 1


# -- Lo más rebajado de toda la región --------------------------------------
#
# Es lo que llena la portada. Misma idea que `productos_de_reino` pero sin
# fijar el reino: ahí la pregunta es "qué está barato AQUÍ" y aquí es "dónde
# hay una ganga ahora mismo", así que cada fila tiene que decir de qué reino
# viene o no sirve de nada.


def test_la_region_saca_el_mas_rebajado_primero(con_rebajas):
    filas = mejores_rebajas(con_rebajas, limite=10, reinos_minimos=10)
    assert [f["producto_id"] for f in filas] == [200, 100]


def test_cada_rebaja_dice_de_que_reino_es(con_rebajas):
    """Sin el reino la fila no sirve: no sabes adónde ir a comprarlo."""
    fila = mejores_rebajas(con_rebajas, limite=1, reinos_minimos=10)[0]
    assert fila["reino"] == "Reino 1"
    assert fila["slug"] == "reino-1"


def test_la_rebaja_viene_en_porcentaje(con_rebajas):
    """8000 sobre una mediana de 10000 es un 20% menos."""
    fila = mejores_rebajas(con_rebajas, limite=1, reinos_minimos=10)[0]
    assert fila["descuento"] == 20


def test_el_limite_de_las_rebajas_recorta(con_rebajas):
    assert len(mejores_rebajas(con_rebajas, limite=1, reinos_minimos=10)) == 1


def test_sin_reinos_de_sobra_no_hay_rebajas_que_ensenar(con_rebajas):
    """Diez reinos no bastan para el umbral de produccion."""
    assert mejores_rebajas(con_rebajas, limite=10, reinos_minimos=15) == []


def test_estar_justo_en_la_mediana_no_es_una_rebaja(tmp_path):
    """El corte es `<` y no `<=` a proposito.

    Un reino que clava el precio normal no tiene nada que ofrecer, y con
    noventa y dos reinos los empates en la mediana son muchos. Hacen falta dos
    productos: con uno solo, una consulta rota que devolviera la lista vacia
    por cualquier otro motivo pasaria igual.
    """
    c = abrir(tmp_path / "e.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(
        c,
        [
            (TIPO_OBJETO, 1, "en", "Todos al mismo precio", None),
            (TIPO_OBJETO, 2, "en", "Rebajado de verdad", None),
        ],
    )
    volcar(
        c,
        {
            Clave(TIPO_OBJETO, 1, 305): {i: resumen(100_000) for i in range(1, 21)},
            Clave(TIPO_OBJETO, 2, 305): {
                1: resumen(50_000), **{i: resumen(100_000) for i in range(2, 21)}
            },
        },
        generado_en=1,
    )
    recalcular_estadisticas(c)

    filas = mejores_rebajas(c, limite=50, reinos_minimos=15)
    assert [f["nombre"] for f in filas] == ["Rebajado de verdad"]


def test_el_resumen_cuenta_productos_distintos_no_variantes(con):
    """El 271440 esta a 305 y a 318: es un producto, no dos."""
    assert resumen_del_catalogo(con)["productos"] == 1


def test_el_resumen_cuenta_los_reinos(con):
    assert resumen_del_catalogo(con)["reinos"] == 10


def test_el_resumen_trae_cuando_se_genero(con):
    assert resumen_del_catalogo(con)["generado_en"] == 1788451184


def test_el_resumen_de_una_base_vacia_no_revienta(tmp_path):
    """Recien instalada, antes de la primera pasada."""
    vacio = resumen_del_catalogo(abrir(tmp_path / "v.db"))
    assert vacio == {"productos": 0, "reinos": 0, "generado_en": None}


# -- Rebajas que no son rebajas ---------------------------------------------
#
# Con los 92 reinos de verdad la portada salia entera a "100% off" y "normally
# 9,999,999g", que es el tope que se puede teclear en la casa de subastas. No
# es un precio: es un "no quiero venderlo". Como esas medianas son enormes,
# cualquier reino con un precio normal parecia la ganga del siglo y esas filas
# copaban las doce.
#
# Medido sobre el volcado real (744.832 filas): 68 variantes tienen la mediana
# clavada en el tope y 777 filas dan un descuento del 99% o mas.


def rebajado(con, producto_id, nombre, mediana, minimo, reinos=20):
    """Un producto que en el reino 1 esta a `minimo` y en los demas a `mediana`."""
    guardar_nombres(con, [(TIPO_OBJETO, producto_id, "en", nombre, None)])
    return {
        Clave(TIPO_OBJETO, producto_id, 305): {
            1: resumen(minimo),
            **{i: resumen(mediana) for i in range(2, reinos + 1)},
        }
    }


@pytest.fixture
def con_region(tmp_path):
    c = abrir(tmp_path / "region.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    agregado = {}
    # Una ganga de verdad: 100.000g que en un reino estan a 20.000g.
    agregado.update(rebajado(c, 1, "Ganga de verdad", 100_000, 20_000))
    # Basura: la mediana es el tope de la casa de subastas.
    agregado.update(rebajado(c, 2, "Puesto al tope", TOPE_CDS, 5_000))
    # Basura sin llegar al tope: 4 millones de oro que nadie paga.
    agregado.update(rebajado(c, 3, "Precio de fantasia", 40_000_000_000, 5_000_000))
    volcar(c, agregado, generado_en=1)
    recalcular_estadisticas(c)
    return c


def test_una_mediana_en_el_tope_de_la_casa_no_es_un_precio(con_region):
    nombres = {f["nombre"] for f in mejores_rebajas(con_region, 10, reinos_minimos=15)}
    assert "Puesto al tope" not in nombres


def test_un_descuento_imposible_no_se_canta(con_region):
    """Un 99,9% no existe en un mercado real: es que la mediana esta mal."""
    nombres = {f["nombre"] for f in mejores_rebajas(con_region, 10, reinos_minimos=15)}
    assert "Precio de fantasia" not in nombres


def test_la_ganga_de_verdad_si_sale(con_region):
    """El filtro tiene que quitar la basura, no la mercancia."""
    filas = mejores_rebajas(con_region, 10, reinos_minimos=15)
    assert [f["nombre"] for f in filas] == ["Ganga de verdad"]
    assert filas[0]["descuento"] == 80


def test_el_tope_es_el_de_la_constante(con_region):
    assert TOPE_CDS == 9_999_999 * 10_000


def test_un_mismo_objeto_no_ocupa_la_lista_entera(tmp_path):
    """El mismo objeto rebajado en cinco reinos son cinco filas identicas.

    Con datos reales "Waterlogged Cloth Vest" salia tres veces entre las doce
    primeras: la lista tiene doce huecos y no puede gastarlos asi.
    """
    c = abrir(tmp_path / "d.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(
        c,
        [
            (TIPO_OBJETO, 1, "en", "Repetido", None),
            (TIPO_OBJETO, 2, "en", "El otro", None),
        ],
    )
    volcar(
        c,
        {
            # Rebajado en cinco reinos a la vez, con descuentos distintos.
            Clave(TIPO_OBJETO, 1, 305): {
                1: resumen(10_000), 2: resumen(11_000), 3: resumen(12_000),
                4: resumen(13_000), 5: resumen(14_000),
                **{i: resumen(100_000) for i in range(6, 21)},
            },
            Clave(TIPO_OBJETO, 2, 305): {
                1: resumen(50_000), **{i: resumen(100_000) for i in range(2, 21)}
            },
        },
        generado_en=1,
    )
    recalcular_estadisticas(c)

    filas = mejores_rebajas(c, 10, reinos_minimos=15)
    assert [f["nombre"] for f in filas] == ["Repetido", "El otro"]
    # Y de las cinco, la mejor: 10.000 sobre 100.000 es un 90%.
    assert filas[0]["descuento"] == 90
    assert filas[0]["reino"] == "Reino 1"


def test_un_producto_sin_nombre_no_sale_en_la_portada(tmp_path):
    """La portada no puede enseñar "#183942" como si fuera un objeto."""
    c = abrir(tmp_path / "sn.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    volcar(
        c,
        {
            Clave(TIPO_OBJETO, 999, 305): {
                1: resumen(10_000), **{i: resumen(100_000) for i in range(2, 21)}
            }
        },
        generado_en=1,
    )
    recalcular_estadisticas(c)
    assert mejores_rebajas(c, 10, reinos_minimos=15) == []


def test_si_la_holgura_no_llega_la_lista_sale_corta_pero_sin_repetidos(
    tmp_path, monkeypatch
):
    """El precio de deduplicar en Python en vez de con ROW_NUMBER().

    Se piden `limite * HOLGURA_DEDUPE` filas y se descartan las repetidas, asi
    que un producto que acapare todas las pedidas deja la lista corta. Es el
    trato aceptado a cambio de la mitad de tiempo (363 ms frente a 696 ms), y
    esta escrito aqui para que se vea que la alternativa nunca es repetir.
    """
    import web.consultas

    monkeypatch.setattr(web.consultas, "HOLGURA_DEDUPE", 1)

    c = abrir(tmp_path / "h.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(
        c,
        [
            (TIPO_OBJETO, 1, "en", "El que acapara", None),
            (TIPO_OBJETO, 2, "en", "El que se queda fuera", None),
        ],
    )
    volcar(
        c,
        {
            # Rebajado en tres reinos: con holgura 1 y limite 2 se piden dos
            # filas, y las dos son de este producto.
            Clave(TIPO_OBJETO, 1, 305): {
                1: resumen(10_000), 2: resumen(11_000), 3: resumen(12_000),
                **{i: resumen(100_000) for i in range(4, 21)},
            },
            Clave(TIPO_OBJETO, 2, 305): {
                1: resumen(90_000), **{i: resumen(100_000) for i in range(2, 21)}
            },
        },
        generado_en=1,
    )
    recalcular_estadisticas(c)

    filas = mejores_rebajas(c, limite=2, reinos_minimos=15)
    assert [f["nombre"] for f in filas] == ["El que acapara"]


# -- La pagina de reino tiene la misma basura -------------------------------
#
# `productos_de_reino` hace la misma comparacion contra la mediana, asi que
# heredaba el mismo problema: con los 92 reinos reales, Argent Dawn abria con
# "Honorable Combatant's Leather Greaves, normally 9,999,999g, here 959g".


def test_un_reino_no_ensena_medianas_del_tope_de_la_casa(con_region):
    nombres = {f["nombre"] for f in productos_de_reino(con_region, 1, 10, 15)}
    assert "Puesto al tope" not in nombres


def test_un_reino_no_ensena_descuentos_imposibles(con_region):
    nombres = {f["nombre"] for f in productos_de_reino(con_region, 1, 10, 15)}
    assert "Precio de fantasia" not in nombres


def test_un_reino_si_ensena_las_rebajas_de_verdad(con_region):
    filas = productos_de_reino(con_region, 1, 10, 15)
    assert [f["nombre"] for f in filas] == ["Ganga de verdad"]


def test_un_reino_no_ensena_productos_sin_nombre(tmp_path):
    c = abrir(tmp_path / "rsn.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    volcar(
        c,
        {
            Clave(TIPO_OBJETO, 999, 305): {
                1: resumen(10_000), **{i: resumen(100_000) for i in range(2, 21)}
            }
        },
        generado_en=1,
    )
    recalcular_estadisticas(c)
    assert productos_de_reino(c, 1, 10, 15) == []


# -- Categorias: /items/armor/mail ------------------------------------------
#
# Son las dos cosas a la vez: los filtros de la casa de subastas que se pidieron
# (armas, armadura, recetas...) y el camino de rastreo que le faltaba al sitio.
# Con 19.365 fichas y solo 4.598 enlazadas desde alguna pagina de reino, tres
# de cada cuatro no tenian forma de ser descubiertas.
#
# NO llevan el reino mas barato: eso es justo lo que vende el Pro, y una tabla
# de cien filas con su reino al lado lo regalaria en bloque.


@pytest.fixture
def con_catalogo(tmp_path):
    c = abrir(tmp_path / "cat.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    piezas = [
        (1, "Mail Boots", "Armor", 4, "Mail", 3, "EPIC"),
        (2, "Mail Helm", "Armor", 4, "Mail", 3, "RARE"),
        (3, "Plate Boots", "Armor", 4, "Plate", 4, "EPIC"),
        (4, "Big Sword", "Weapon", 2, "One-Handed Swords", 7, "EPIC"),
        (5, "Recipe: Soup", "Recipe", 9, "Cooking", 5, "COMMON"),
    ]
    guardar_nombres(
        c, [(TIPO_OBJETO, i, "en", n, f"https://cdn/{i}.jpg") for i, n, *_ in piezas]
    )
    guardar_atributos(
        c,
        [
            {
                "tipo": TIPO_OBJETO, "producto_id": i,
                "clase_id": cid, "clase": clase,
                "subclase_id": sid, "subclase": sub,
                "calidad": cal, "hueco": "FEET", "nivel": 200,
                "nivel_requerido": 70,
            }
            for i, n, clase, cid, sub, sid, cal in piezas
        ],
    )
    volcar(
        c,
        {
            Clave(TIPO_OBJETO, i, 305): {
                1: resumen(10_000 * i), **{r: resumen(100_000 * i) for r in range(2, 21)}
            }
            for i, *_ in piezas
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(c)
    return c


def test_las_categorias_salen_con_cuantos_objetos_tienen(con_catalogo):
    cats = {c["clase_slug"]: c for c in categorias(con_catalogo)}
    assert cats["armor"]["objetos"] == 3
    assert cats["weapon"]["objetos"] == 1
    assert cats["recipe"]["objetos"] == 1


def test_las_categorias_salen_ordenadas_por_nombre(con_catalogo):
    nombres = [c["clase"] for c in categorias(con_catalogo)]
    assert nombres == sorted(nombres)


def test_las_subcategorias_son_las_de_su_clase(con_catalogo):
    subs = [s["subclase"] for s in subcategorias(con_catalogo, "armor")]
    assert subs == ["Mail", "Plate"]


def test_una_clase_que_no_existe_no_tiene_subcategorias(con_catalogo):
    assert subcategorias(con_catalogo, "no-existe") == []


def test_una_categoria_lista_sus_objetos(con_catalogo):
    filas = productos_de_categoria(con_catalogo, "armor", limite=10)
    assert {f["nombre"] for f in filas} == {"Mail Boots", "Mail Helm", "Plate Boots"}


def test_una_subcategoria_afina(con_catalogo):
    filas = productos_de_categoria(con_catalogo, "armor", "mail", limite=10)
    assert {f["nombre"] for f in filas} == {"Mail Boots", "Mail Helm"}


def test_se_puede_filtrar_por_calidad(con_catalogo):
    filas = productos_de_categoria(con_catalogo, "armor", calidad="EPIC", limite=10)
    assert {f["nombre"] for f in filas} == {"Mail Boots", "Plate Boots"}


def test_la_lista_de_categoria_no_dice_en_que_reino(con_catalogo):
    """Es lo que vende el Pro. Una tabla de cien filas con su reino al lado lo
    regalaria en bloque, y el muro de la ficha dejaria de tener sentido.
    """
    fila = productos_de_categoria(con_catalogo, "armor", limite=1)[0]
    assert "reino" not in fila and "slug" not in fila
    # Lo que si lleva: desde cuanto sale y su icono, que es el gancho.
    assert fila["desde"] > 0
    assert fila["icono"].startswith("https://cdn/")


def test_una_categoria_se_puede_paginar(con_catalogo):
    """Con 19.365 objetos, una categoria no cabe en una pagina y Google tiene
    que poder recorrerlas todas."""
    p1 = productos_de_categoria(con_catalogo, "armor", limite=2)
    p2 = productos_de_categoria(con_catalogo, "armor", limite=2, desde=2)
    assert len(p1) == 2 and len(p2) == 1
    assert not ({f["producto_id"] for f in p1} & {f["producto_id"] for f in p2})


def test_cuantos_objetos_tiene_una_categoria(con_catalogo):
    """Hace falta para saber cuantas paginas hay que enlazar."""
    assert contar_categoria(con_catalogo, "armor") == 3
    assert contar_categoria(con_catalogo, "armor", "mail") == 2


def test_un_objeto_sin_precio_no_sale_en_su_categoria(con_catalogo):
    """La categoria viene de `atributo`, que no se borra en cada pasada; los
    precios si. Un objeto que hoy no esta en subastas no tiene ficha que
    ensenar, asi que enlazarlo seria mandar a Google a un 404.
    """
    guardar_nombres(con_catalogo, [(TIPO_OBJETO, 99, "en", "Fantasma", None)])
    guardar_atributos(
        con_catalogo,
        [{"tipo": TIPO_OBJETO, "producto_id": 99, "clase_id": 4, "clase": "Armor",
          "subclase_id": 3, "subclase": "Mail"}],
    )

    assert "Fantasma" not in {
        f["nombre"] for f in productos_de_categoria(con_catalogo, "armor", limite=10)
    }


# -- El buscador -------------------------------------------------------------


def test_el_buscador_encuentra_por_trozo_del_nombre(con_catalogo):
    assert {f["nombre"] for f in buscar(con_catalogo, "mail", limite=10)} == {
        "Mail Boots", "Mail Helm"
    }


def test_el_buscador_no_distingue_mayusculas(con_catalogo):
    assert buscar(con_catalogo, "MAIL BOOTS", limite=10)[0]["nombre"] == "Mail Boots"


def test_el_buscador_ignora_los_comodines_de_sql(con_catalogo):
    """Un `%` escrito por el usuario no puede convertirse en "damelo todo"."""
    assert buscar(con_catalogo, "%", limite=10) == []


def test_una_busqueda_vacia_no_devuelve_el_catalogo(con_catalogo):
    assert buscar(con_catalogo, "   ", limite=10) == []


def test_el_buscador_solo_devuelve_lo_que_esta_en_venta(con_catalogo):
    guardar_nombres(con_catalogo, [(TIPO_OBJETO, 98, "en", "Mail Fantasma", None)])
    assert "Mail Fantasma" not in {
        f["nombre"] for f in buscar(con_catalogo, "mail", limite=10)
    }


# -- La calidad viaja con cada objeto ----------------------------------------
#
# En WoW el nombre de un objeto va SIEMPRE del color de su calidad: gris, blanco,
# verde, azul, morado, naranja. Es el codigo visual mas reconocible del juego y
# sin el una tabla de objetos parece una hoja de calculo. El dato ya estaba en
# `atributo`; lo que faltaba era que llegara a las plantillas.


def test_las_rebajas_traen_la_calidad(con_region):
    fila = mejores_rebajas(con_region, 10, reinos_minimos=15)[0]
    assert "calidad" in fila


def test_lo_rebajado_de_un_reino_trae_la_calidad(con_catalogo):
    fila = productos_de_reino(con_catalogo, 1, 10, 15)[0]
    assert fila["calidad"] in {"EPIC", "RARE", "COMMON"}


def test_un_objeto_sin_clasificar_no_desaparece_por_no_tener_calidad(tmp_path):
    """El JOIN con `atributo` tiene que ser LEFT: un objeto recien visto todavia
    no esta clasificado y aun asi tiene precio que ensenar.
    """
    c = abrir(tmp_path / "sc.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    guardar_nombres(c, [(TIPO_OBJETO, 1, "en", "Sin clasificar", None)])
    volcar(
        c,
        {Clave(TIPO_OBJETO, 1, 305): {
            1: resumen(10_000), **{i: resumen(100_000) for i in range(2, 21)}
        }},
        generado_en=1,
    )
    recalcular_estadisticas(c)

    filas = mejores_rebajas(c, 10, reinos_minimos=15)
    assert [f["nombre"] for f in filas] == ["Sin clasificar"]
    assert filas[0]["calidad"] is None


def test_se_puede_filtrar_una_categoria_por_calidad(con_catalogo):
    filas = productos_de_categoria(con_catalogo, "armor", calidad="RARE", limite=10)
    assert [f["nombre"] for f in filas] == ["Mail Helm"]


def test_las_calidades_de_una_categoria_se_saben(con_catalogo):
    """Para pintar el filtro hace falta saber que calidades HAY, no las seis
    posibles: una categoria sin nada epico no debe ofrecer ese boton."""
    cals = calidades_de(con_catalogo, "armor")
    assert [c["calidad"] for c in cals] == ["EPIC", "RARE"]
    assert cals[0]["objetos"] == 2


def test_las_calidades_salen_de_mejor_a_peor(con_catalogo):
    """Como en el juego: primero lo bueno."""
    cals = [c["calidad"] for c in calidades_de(con_catalogo, "weapon")]
    assert cals == ["EPIC"]


def test_la_ficha_trae_la_calidad(con_catalogo):
    """El titulo de la ficha va del color de su calidad, como en el juego."""
    assert ficha(con_catalogo, TIPO_OBJETO, 1)["calidad"] == "EPIC"


def test_una_ficha_sin_clasificar_no_revienta(con):
    """El fixture `con` no tiene tabla `atributo` poblada."""
    assert ficha(con, TIPO_OBJETO, 271440)["calidad"] is None


# -- Autocompletar -----------------------------------------------------------
#
# La caja de la cabecera no adivinaba nada: habia que teclear el nombre entero
# y pulsar Enter para llegar a una pagina de resultados. Con nombres como
# "Uncanny Combatant's Satin Belt" eso es pedirle al visitante que sepa de
# memoria lo que ha venido a buscar.
#
# `sugerencias` es `buscar` con otra prioridad. El buscador ordena por nombre
# corto porque quien pulsa Enter quiere la lista entera; el autocompletar
# ordena por PREFIJO porque quien teclea "sword" esta escribiendo el principio
# del nombre, no un trozo de en medio.


@pytest.fixture
def con_espadas(tmp_path):
    c = abrir(tmp_path / "esp.db")
    guardar_reinos(c, {i: f"Reino {i}" for i in range(1, 21)})
    espadas = [
        (1, "Bloodfang Sword"),             # contiene, pero no empieza
        (2, "Sword of a Thousand Truths"),  # empieza, y es el mas largo
        (3, "Swordfish"),                   # empieza, y es el mas corto
    ]
    guardar_nombres(
        c, [(TIPO_OBJETO, i, "en", n, f"https://cdn/{i}.jpg") for i, n in espadas]
    )
    volcar(
        c,
        {
            Clave(TIPO_OBJETO, i, 305): {
                1: resumen(10_000 * i),
                **{r: resumen(100_000 * i) for r in range(2, 21)},
            }
            for i, _ in espadas
        },
        generado_en=1788451184,
    )
    recalcular_estadisticas(c)
    return c


def test_el_autocompletar_pone_delante_lo_que_empieza_igual(con_espadas):
    """Quien teclea "sword" esta escribiendo el principio de un nombre.

    Ordenando solo por longitud --que es lo que hace el buscador-- "Bloodfang
    Sword" (15) se colaria delante de "Sword of a Thousand Truths" (26), y la
    segunda sugerencia no empezaria por lo tecleado.
    """
    nombres = [f["nombre"] for f in sugerencias(con_espadas, "sword", limite=10)]
    assert nombres == ["Swordfish", "Sword of a Thousand Truths", "Bloodfang Sword"]


def test_el_autocompletar_no_devuelve_el_catalogo_sin_texto(con_espadas):
    assert sugerencias(con_espadas, "   ", limite=10) == []


def test_el_autocompletar_ignora_los_comodines_de_sql(con_espadas):
    """Un `%` tecleado en la caja no puede convertirse en "damelo todo"."""
    assert sugerencias(con_espadas, "%", limite=10) == []


def test_el_autocompletar_solo_ofrece_lo_que_esta_en_venta(con_espadas):
    """Sugerir algo que no esta en subasta lleva a una ficha sin precios."""
    guardar_nombres(con_espadas, [(TIPO_OBJETO, 98, "en", "Sword Fantasma", None)])
    assert "Sword Fantasma" not in {
        f["nombre"] for f in sugerencias(con_espadas, "sword", limite=10)
    }


def test_el_autocompletar_respeta_el_limite(con_espadas):
    assert len(sugerencias(con_espadas, "sword", limite=2)) == 2


def test_cada_sugerencia_trae_con_que_pintarse(con_catalogo):
    """Icono y calidad: sin ellos la lista desplegable es texto gris."""
    fila = sugerencias(con_catalogo, "mail boots", limite=5)[0]
    assert fila["nombre"] == "Mail Boots"
    assert fila["icono"] == "https://cdn/1.jpg"
    assert fila["calidad"] == "EPIC"
    assert fila["desde"] == 10_000


def test_las_subcategorias_se_pueden_contar_por_calidad(con_catalogo):
    """Con un filtro de calidad puesto, la lista de tipos tiene que hablar de
    ESA calidad: cuantos hay y, sobre todo, cuales existen.

    En `armor` hay Mail y Plate, pero lo unico raro esta en Mail. Ofrecer
    Plate con el filtro Rare puesto lleva a una categoria vacia.
    """
    subs = subcategorias(con_catalogo, "armor", calidad="RARE")
    assert [(s["subclase"], s["objetos"]) for s in subs] == [("Mail", 1)]


def test_sin_calidad_las_subcategorias_son_todas(con_catalogo):
    subs = subcategorias(con_catalogo, "armor")
    assert [(s["subclase"], s["objetos"]) for s in subs] == [("Mail", 2), ("Plate", 1)]


# -- La version del volcado --------------------------------------------------
#
# El numero contra el que se cachea lo que solo cambia con la pasada horaria.
# `resumen_del_catalogo` ya lo devuelve, pero de propina con dos cuentas mas
# que no hacen falta para saber si algo caduco.


def test_la_version_del_volcado_es_cuando_se_genero(con_catalogo):
    assert version_del_volcado(con_catalogo) == 1788451184


def test_una_base_sin_volcado_no_tiene_version(tmp_path):
    """Es el estado normal hasta que termina la primera pasada."""
    assert version_del_volcado(abrir(tmp_path / "v.db")) is None
