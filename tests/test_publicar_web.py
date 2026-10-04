from pathlib import Path

from wowalerts.blizzard import AuctionSnapshot, BlizzardError
from wowalerts.mercado import TIPO_MASCOTA, TIPO_OBJETO, Clave, ResumenReino
from web.consultas import ficha
from web.db import abrir
from web.ingesta import guardar_atributos, guardar_iconos, guardar_nombres

from publicar_web import (
    EXIT_DEMASIADOS_FALLOS,
    EXIT_OK,
    main,
    pedir_datos,
    poblar,
    productos_sin_atributos,
    productos_sin_icono,
    productos_sin_nombre,
)

# Directorio del repositorio: hace falta para que `--config config.yaml` (la
# ruta relativa por defecto de `main()`) encuentre el fichero de verdad, sin
# depender de con que cwd haya arrancado pytest.
RAIZ = Path(__file__).resolve().parent.parent


def resumen(*precios, listados=None):
    return ResumenReino(precios=tuple(sorted(precios)), listados=listados or len(precios))


def test_poblar_deja_precios_estadisticas_nombres_y_reinos(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_OBJETO, 271440, 305): {
            1305: resumen(500_000_000),
            1329: resumen(700_000_000),
        }
    }
    nombres_reino = {1305: "Kazzak", 1329: "Zul'jin / Uldum"}
    nombres_producto = [
        (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None),
        (TIPO_OBJETO, 271440, "es", "Grebas de las profundidades nocivas", None),
    ]

    filas = poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1788451184)

    assert filas == 2
    assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM estadistica").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM nombre").fetchone()[0] == 2
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 1788451184


def test_poblar_dos_veces_no_duplica(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 1, 305): {1305: resumen(100)}}
    nombres_reino = {1305: "Kazzak"}
    nombres_producto = [(TIPO_OBJETO, 1, "en", "Algo", None)]

    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1)
    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=2)

    assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM nombre").fetchone()[0] == 1
    assert con.execute("SELECT generado_en FROM volcado").fetchone()[0] == 2


def test_solo_se_piden_los_nombres_que_faltan(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(con, [(TIPO_OBJETO, 111, "en", "Ya tengo nombre", None)])

    agregado = {
        Clave(TIPO_OBJETO, 111, 305): {1305: resumen(100)},
        Clave(TIPO_OBJETO, 222, 305): {1305: resumen(200)},
    }

    assert productos_sin_nombre(con, agregado) == [(TIPO_OBJETO, 222)]


def test_las_mascotas_no_piden_nombre(tmp_path):
    con = abrir(tmp_path / "p.db")
    agregado = {
        Clave(TIPO_MASCOTA, 303, 3): {1305: resumen(100)},
        Clave(TIPO_OBJETO, 111, None): {1305: resumen(200)},
    }

    assert productos_sin_nombre(con, agregado) == [(TIPO_OBJETO, 111)]


def test_el_idioma_guardado_es_el_que_consulta_la_web(tmp_path):
    """Si el codigo de idioma no coincide con lo que consulta la web, la ficha
    cae al `#id` de repuesto en vez de ensenar el nombre de verdad -- esto es
    lo unico que demuestra que ingesta y web estan de acuerdo en el idioma.
    """
    con = abrir(tmp_path / "p.db")
    agregado = {Clave(TIPO_OBJETO, 271440, 305): {1305: resumen(500_000_000)}}
    nombres_reino = {1305: "Kazzak"}
    nombres_producto = [
        (TIPO_OBJETO, 271440, "en", "Greaves of the Noxious Depths", None),
    ]

    poblar(con, agregado, nombres_reino, nombres_producto, generado_en=1)

    resultado = ficha(con, TIPO_OBJETO, 271440)
    assert resultado["nombre"] == "Greaves of the Noxious Depths"
    assert resultado["nombre"] != "#271440"


class ClientePrueba:
    """Cliente falso, sin red: los reinos de `fallan` lanzan `BlizzardError`
    al pedir sus subastas (como haria un reino caido de verdad), y el resto
    responde con una subasta del mismo objeto por encima del suelo de precio.
    """

    def __init__(self, fallan):
        self.fallan = set(fallan)

    def auctions(self, realm_id):
        if realm_id in self.fallan:
            raise BlizzardError("simulado: reino caido")
        return AuctionSnapshot(
            auctions=[{"item": {"id": 271440}, "buyout": 500_000_000, "quantity": 1}],
            taken_at=None,
        )

    def connected_realm_name(self, realm_id):
        return f"Reino {realm_id}"

    def item_datos(self, item_id):
        return {
            "nombres": {"en_GB": f"Objeto {item_id}"},
            "clase_id": 4, "clase": "Armor",
            "subclase_id": 3, "subclase": "Mail",
            "calidad": "EPIC", "hueco": "FEET",
            "nivel": 219, "nivel_requerido": 90,
        }

    def item_icon_url(self, item_id):
        return f"https://cdn/{item_id}.jpg"


def _snapshot(db_path):
    """Contenido de las tablas que `main()` puede tocar, para comparar antes y
    despues de una pasada."""
    con = abrir(db_path)
    try:
        return {
            "precio": con.execute(
                "SELECT * FROM precio ORDER BY tipo, producto_id, variante, reino_id"
            ).fetchall(),
            "reino": con.execute("SELECT * FROM reino ORDER BY id").fetchall(),
            "nombre": con.execute(
                "SELECT * FROM nombre ORDER BY tipo, producto_id, idioma"
            ).fetchall(),
            "volcado": con.execute("SELECT * FROM volcado").fetchall(),
        }
    finally:
        con.close()


def test_si_fallan_demasiados_reinos_no_se_toca_la_base(tmp_path, monkeypatch):
    """Por encima del umbral (30%), `main()` no debe escribir nada: los datos
    de la pasada anterior tienen como mucho una hora, mientras que publicar
    solo lo que ha respondido borraria de la web los reinos que han fallado
    -- eso es peor que no publicar.
    """
    monkeypatch.chdir(RAIZ)
    db_path = tmp_path / "web.db"

    # Pasada buena conocida, para comprobar despues que sobrevive intacta.
    con = abrir(db_path)
    agregado = {Clave(TIPO_OBJETO, 271440, None): {1305: resumen(500_000_000)}}
    poblar(
        con,
        agregado,
        {1305: "Kazzak"},
        [(TIPO_OBJETO, 271440, "en", "Algo", None)],
        generado_en=1000,
    )
    con.close()
    antes = _snapshot(db_path)

    realm_ids = list(range(1, 11))
    fallan = realm_ids[:6]  # 6 de 10 = 60% > 30%: por encima del umbral.
    cliente = ClientePrueba(fallan=fallan)

    codigo = main(
        [
            "--realms", ",".join(map(str, realm_ids)),
            "--db", str(db_path),
            "--config", "config.yaml",
        ],
        client=cliente,
    )

    assert codigo == EXIT_DEMASIADOS_FALLOS
    assert _snapshot(db_path) == antes


def test_si_fallan_pocos_reinos_se_publica_igual(tmp_path, monkeypatch):
    """Por debajo del umbral, un par de reinos caidos no debe frenar la
    publicacion del resto: es el caso normal que el umbral tiene que dejar
    pasar sin tocar el codigo de salida ni saltarse la base.
    """
    monkeypatch.chdir(RAIZ)
    db_path = tmp_path / "web.db"

    realm_ids = list(range(1, 11))
    fallan = realm_ids[:2]  # 2 de 10 = 20% <= 30%: por debajo del umbral.
    cliente = ClientePrueba(fallan=fallan)

    codigo = main(
        [
            "--realms", ",".join(map(str, realm_ids)),
            "--db", str(db_path),
            "--config", "config.yaml",
        ],
        client=cliente,
    )

    assert codigo == EXIT_OK
    con = abrir(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM reino").fetchone()[0] == 8
        assert con.execute("SELECT COUNT(*) FROM precio").fetchone()[0] == 8
    finally:
        con.close()


# -- Iconos ------------------------------------------------------------------
#
# La columna `nombre.icono` existia desde el principio pero nadie la llenaba:
# `pedir_nombres` guardaba None a proposito, con el argumento de que ninguna
# plantilla lo leia. Ahora las tres si, y una tabla de objetos de WoW sin sus
# iconos no se lee bien. Con el volcado real: 18.675 nombres en ingles y cero
# iconos.


class ClienteFalso:
    """Solo lo que usan `pedir_datos` y `pedir_iconos`."""

    def __init__(self, iconos=None, nombres=None):
        self.iconos = iconos if iconos is not None else {}
        self.nombres = nombres if nombres is not None else {}
        self.iconos_pedidos = []

    def item_datos(self, item_id):
        return {
            "nombres": self.nombres.get(item_id, {"en_GB": f"Objeto {item_id}"}),
            "clase_id": 4, "clase": "Armor",
            "subclase_id": 3, "subclase": "Mail",
            "calidad": "EPIC", "hueco": "FEET",
            "nivel": 219, "nivel_requerido": 90,
        }

    def item_icon_url(self, item_id):
        self.iconos_pedidos.append(item_id)
        return self.iconos.get(item_id)


def test_un_objeto_nuevo_trae_su_icono(tmp_path):
    client = ClienteFalso(iconos={222: "https://cdn/222.jpg"})

    filas, _ = pedir_datos(client, [(TIPO_OBJETO, 222)], max_workers=2)

    assert filas, "algo tiene que salir"
    assert {f[4] for f in filas} == {"https://cdn/222.jpg"}


def test_el_icono_va_en_todos_los_idiomas_del_objeto(tmp_path):
    """El icono es del producto, no del idioma, pero la tabla tiene una fila
    por idioma: si solo se pusiera en una, la web en aleman saldria sin foto.
    """
    client = ClienteFalso(
        iconos={222: "https://cdn/222.jpg"},
        nombres={222: {"en_GB": "Boots", "de_DE": "Stiefel"}},
    )

    filas, _ = pedir_datos(client, [(TIPO_OBJETO, 222)], max_workers=2)

    assert len(filas) == 2
    assert all(f[4] == "https://cdn/222.jpg" for f in filas)


def test_un_objeto_sin_icono_no_rompe_la_pasada(tmp_path):
    """`item_icon_url` devuelve None si Blizzard no lo tiene. No es un error."""
    client = ClienteFalso(iconos={})

    filas, _ = pedir_datos(client, [(TIPO_OBJETO, 222)], max_workers=2)

    assert filas and all(f[4] is None for f in filas)


def test_se_rellenan_los_iconos_que_faltan_de_antes(tmp_path):
    """Los 18.675 objetos que ya tenian nombre no vuelven a pasar por
    `productos_sin_nombre`, asi que sin esto no verian un icono jamas.
    """
    con = abrir(tmp_path / "p.db")
    guardar_nombres(
        con,
        [
            (TIPO_OBJETO, 111, "en", "Con icono", "https://cdn/111.jpg"),
            (TIPO_OBJETO, 222, "en", "Sin icono", None),
            (TIPO_OBJETO, 333, "en", "Tambien sin icono", None),
        ],
    )

    assert productos_sin_icono(con, limite=10) == [(TIPO_OBJETO, 222), (TIPO_OBJETO, 333)]


def test_el_relleno_de_iconos_esta_acotado(tmp_path):
    """Una pasada no puede irse a 18.000 peticiones extra a la API."""
    con = abrir(tmp_path / "p.db")
    guardar_nombres(
        con, [(TIPO_OBJETO, i, "en", f"Objeto {i}", None) for i in range(1, 11)]
    )

    assert len(productos_sin_icono(con, limite=3)) == 3


def test_guardar_iconos_no_toca_los_nombres(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(
        con,
        [
            (TIPO_OBJETO, 222, "en", "Boots", None),
            (TIPO_OBJETO, 222, "de", "Stiefel", None),
        ],
    )

    guardar_iconos(con, [(TIPO_OBJETO, 222, "https://cdn/222.jpg")])

    filas = con.execute(
        "SELECT idioma, nombre, icono FROM nombre ORDER BY idioma"
    ).fetchall()
    assert [f["nombre"] for f in filas] == ["Stiefel", "Boots"]
    assert all(f["icono"] == "https://cdn/222.jpg" for f in filas)


def test_un_icono_que_sigue_sin_venir_no_borra_nada(tmp_path):
    """Blizzard puede seguir sin darlo: mejor dejarlo pendiente que escribir
    un None encima y volver a intentarlo eternamente igual."""
    con = abrir(tmp_path / "p.db")
    guardar_nombres(con, [(TIPO_OBJETO, 222, "en", "Boots", "https://cdn/x.jpg")])

    guardar_iconos(con, [(TIPO_OBJETO, 222, None)])

    assert con.execute("SELECT icono FROM nombre").fetchone()[0] == "https://cdn/x.jpg"


def test_solo_iconos_no_toca_los_precios(tmp_path, monkeypatch):
    """El relleno inicial son ~18.000 iconos y no necesita bajar los 92 reinos.

    Y sobre todo NO puede volcar: `volcar()` borra la tabla `precio` entera y
    reinserta lo que se haya bajado, asi que una pasada de iconos que ademas
    publicara dejaria la web con los precios de los reinos que se pidieran.
    """
    monkeypatch.chdir(RAIZ)
    ruta = tmp_path / "p.db"
    con = abrir(ruta)
    guardar_nombres(con, [(TIPO_OBJETO, 271440, "en", "Boots", None)])
    poblar(
        con,
        {Clave(TIPO_OBJETO, 271440, 305): {1305: resumen(500_000_000)}},
        {1305: "Kazzak"},
        [],
        generado_en=1788451184,
    )
    con.close()

    antes = _snapshot(ruta)
    codigo = main(
        ["--db", str(ruta), "--solo-iconos", "--iconos", "50"],
        client=ClientePrueba(fallan=[]),
    )

    assert codigo == EXIT_OK
    despues = _snapshot(ruta)
    assert despues["precio"] == antes["precio"]
    assert despues["volcado"] == antes["volcado"]
    # Y el icono si se ha puesto.
    con = abrir(ruta)
    assert con.execute("SELECT icono FROM nombre").fetchone()[0] == (
        "https://cdn/271440.jpg"
    )


# -- Atributos en la pasada --------------------------------------------------


class ClienteConDatos:
    """Cliente falso que responde `item_datos` como el de verdad."""

    def __init__(self, datos=None):
        self.datos = datos if datos is not None else {}
        self.pedidos = []

    def item_datos(self, item_id):
        self.pedidos.append(item_id)
        if item_id in self.datos:
            return self.datos[item_id]
        return {
            "nombres": {"en_GB": f"Objeto {item_id}"},
            "clase_id": 4, "clase": "Armor",
            "subclase_id": 3, "subclase": "Mail",
            "calidad": "EPIC", "hueco": "FEET",
            "nivel": 219, "nivel_requerido": 90,
        }

    def item_icon_url(self, item_id):
        return f"https://cdn/{item_id}.jpg"


def test_un_objeto_nuevo_trae_nombre_y_atributos_en_una_peticion(tmp_path):
    client = ClienteConDatos()

    nombres, atrib = pedir_datos(client, [(TIPO_OBJETO, 222)], max_workers=2)

    assert client.pedidos == [222], "una sola peticion de datos por objeto"
    assert nombres and nombres[0][3] == "Objeto 222"
    assert atrib and atrib[0]["subclase"] == "Mail"


def test_un_objeto_sin_categoria_conserva_su_nombre(tmp_path):
    """`item_datos` devuelve None cuando no hay categoria. El objeto sigue
    existiendo y su ficha tiene que poder ensenar el nombre; lo que no tiene es
    sitio en /items.
    """
    client = ClienteConDatos(datos={222: None})

    nombres, atrib = pedir_datos(client, [(TIPO_OBJETO, 222)], max_workers=2)

    assert atrib == []
    assert nombres == []


def test_se_rellenan_los_atributos_que_faltan_de_antes(tmp_path):
    """Los 19.365 productos que ya tenian nombre no pasan por
    `productos_sin_nombre`, asi que sin esto no tendrian categoria jamas."""
    con = abrir(tmp_path / "p.db")
    guardar_nombres(
        con,
        [
            (TIPO_OBJETO, 111, "en", "Ya clasificado", None),
            (TIPO_OBJETO, 222, "en", "Sin clasificar", None),
        ],
    )
    guardar_atributos(
        con,
        [
            {
                "tipo": TIPO_OBJETO, "producto_id": 111,
                "clase_id": 4, "clase": "Armor",
                "subclase_id": 3, "subclase": "Mail",
            }
        ],
    )

    assert productos_sin_atributos(con, limite=10) == [(TIPO_OBJETO, 222)]


def test_el_relleno_de_atributos_esta_acotado(tmp_path):
    con = abrir(tmp_path / "p.db")
    guardar_nombres(
        con, [(TIPO_OBJETO, i, "en", f"Objeto {i}", None) for i in range(1, 11)]
    )

    assert len(productos_sin_atributos(con, limite=4)) == 4


def test_solo_atributos_no_toca_los_precios(tmp_path, monkeypatch):
    monkeypatch.chdir(RAIZ)
    ruta = tmp_path / "p.db"
    con = abrir(ruta)
    guardar_nombres(con, [(TIPO_OBJETO, 271440, "en", "Boots", None)])
    poblar(
        con,
        {Clave(TIPO_OBJETO, 271440, 305): {1305: resumen(500_000_000)}},
        {1305: "Kazzak"},
        [],
        generado_en=1788451184,
    )
    con.close()

    antes = _snapshot(ruta)
    codigo = main(
        ["--db", str(ruta), "--solo-atributos", "--atributos", "50"],
        client=ClienteConDatos(),
    )

    assert codigo == EXIT_OK
    despues = _snapshot(ruta)
    assert despues["precio"] == antes["precio"]
    con = abrir(ruta)
    assert con.execute("SELECT clase_slug FROM atributo").fetchone()[0] == "armor"
