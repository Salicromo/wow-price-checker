-- Precio más barato de cada producto en cada reino, tal y como estaba en el
-- último volcado. Se reemplaza entera en cada pasada: no hay histórico.
--
-- `variante` es el ilvl del equipo o la calidad de la mascota, y -1 en lo que
-- no escala. Se usa -1 y no NULL porque en un índice de SQLite dos NULL no
-- comparan iguales, y esto forma parte de la identidad del producto.
CREATE TABLE IF NOT EXISTS precio (
    tipo        TEXT    NOT NULL,
    producto_id INTEGER NOT NULL,
    variante    INTEGER NOT NULL,
    reino_id    INTEGER NOT NULL,
    minimo      INTEGER NOT NULL,
    listados    INTEGER NOT NULL,
    PRIMARY KEY (tipo, producto_id, variante, reino_id)
) WITHOUT ROWID;

-- Resumen por producto de todo lo anterior. Se recalcula en la misma pasada
-- para no tener que sacar medianas en cada visita.
CREATE TABLE IF NOT EXISTS estadistica (
    tipo        TEXT    NOT NULL,
    producto_id INTEGER NOT NULL,
    variante    INTEGER NOT NULL,
    mediana     INTEGER NOT NULL,
    minimo      INTEGER NOT NULL,
    maximo      INTEGER NOT NULL,
    reinos      INTEGER NOT NULL,
    PRIMARY KEY (tipo, producto_id, variante)
) WITHOUT ROWID;

-- `slug` es la URL de /realm/<slug>: `_slugs_unicos` en web/ingesta.py ya
-- garantiza que no se repita, pero el UNIQUE es la red de seguridad -- si
-- algún día ese código tuviera un bug, se ve como un IntegrityError al
-- guardar y no como un reino que calladamente deja de tener manera de
-- llegar a él.
CREATE TABLE IF NOT EXISTS reino (
    id     INTEGER PRIMARY KEY,
    slug   TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL
);

-- Nombre localizado e icono. El icono es del producto, no de la variante, así
-- que aquí no hay columna `variante`.
CREATE TABLE IF NOT EXISTS nombre (
    tipo        TEXT NOT NULL,
    producto_id INTEGER NOT NULL,
    idioma      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    icono       TEXT,
    PRIMARY KEY (tipo, producto_id, idioma)
) WITHOUT ROWID;

-- Qué páginas existen. Una página nace la primera vez que alguien la pide, no
-- el día del despliegue: publicar veinte mil páginas sin tráfico es justo el
-- patrón que Google trata como contenido generado.
CREATE TABLE IF NOT EXISTS pagina (
    tipo             TEXT    NOT NULL,
    producto_id      INTEGER NOT NULL,
    primera_peticion INTEGER NOT NULL,
    peticiones       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (tipo, producto_id)
) WITHOUT ROWID;

-- Cuándo se generó lo que hay ahora mismo en `precio`. Una sola fila.
CREATE TABLE IF NOT EXISTS volcado (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    generado_en INTEGER NOT NULL
);

-- Para "dame todos los reinos de este producto", que es la consulta de la
-- ficha y la única que se hace en caliente.
CREATE INDEX IF NOT EXISTS precio_por_producto
    ON precio (tipo, producto_id, variante, minimo);

-- Lo que la casa de subastas usa para filtrar: categoria, subcategoria,
-- calidad, hueco de equipo y niveles. Una fila por producto, no por variante:
-- las Grebas a ilvl 305 y a 318 son la misma armadura de malla para los pies.
--
-- Todo esto ya venia en la misma respuesta de `/data/wow/item/{id}` de la que
-- se saca el nombre, y se estaba descartando. Guardarlo no cuesta ni una
-- peticion mas por objeto nuevo.
--
-- Los nombres se guardan en ingles y no localizados porque de aqui salen las
-- URLs (`/items/armor/mail`), que no cambian con el idioma del visitante. El
-- `_id` de Blizzard se guarda al lado porque es lo estable: si algun dia
-- renombran una subclase, el id sigue siendo el mismo y el slug se puede
-- recalcular sin perder de vista que es la misma categoria.
CREATE TABLE IF NOT EXISTS atributo (
    tipo            TEXT    NOT NULL,
    producto_id     INTEGER NOT NULL,
    clase_id        INTEGER NOT NULL,
    clase           TEXT    NOT NULL,
    clase_slug      TEXT    NOT NULL,
    subclase_id     INTEGER NOT NULL,
    subclase        TEXT    NOT NULL,
    subclase_slug   TEXT    NOT NULL,
    calidad         TEXT,
    hueco           TEXT,
    nivel           INTEGER,
    nivel_requerido INTEGER,
    PRIMARY KEY (tipo, producto_id)
) WITHOUT ROWID;

-- Para "dame los objetos de esta categoria", que es la consulta de las paginas
-- nuevas de /items.
CREATE INDEX IF NOT EXISTS atributo_por_categoria
    ON atributo (clase_slug, subclase_slug, producto_id);
