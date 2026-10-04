# Desplegar la web publica en un VPS

Esto es la otra mitad del proyecto: `web/` es la app que sirve las paginas de
precio, y `publicar_web.py` es lo que la llena cada hora desde la API de
Blizzard. El vigilante (`main.py`, GitHub Actions) es un proceso aparte y no
necesita nada de esto.

Sirve para un VPS Linux con systemd y nginx. Se asume Debian/Ubuntu; en otra
distribucion cambian los nombres de paquete, no la idea.

---

## 0. Que hace falta contratar

Dos cosas, y ninguna cara.

**Un VPS con 2 GB de RAM.** El numero que manda no es la web --uvicorn
sirviendo paginas se queda en decenas de MB-- sino la pasada horaria: se mide
un **pico de 644 MB** al bajar y resumir los 92 reinos de EU, porque tiene que
tener en memoria a la vez las subastas de varios reinos mientras las agrega.
En una maquina de 512 MB o de 1 GB esa pasada muere por falta de memoria (y en
1 GB moriria a veces y no siempre, que es peor). Con 2 GB sobra sitio para el
pico, para uvicorn y para el sistema.

**Disco: 10 GB de sobra.** Lo que ocupa esto de verdad, medido con la region
entera dentro:

| | |
|---|---|
| `web.db` (744.832 precios, 20.138 productos, 149.386 nombres) | 49 MB |
| El entorno virtual (`.venv`) | 92 MB |
| El repositorio | menos de 5 MB |

La base **no crece con el tiempo**: `volcar()` reemplaza la tabla `precio`
entera en cada pasada y no guarda historico, asi que 49 MB es el tamano
estable, no el de partida.

**CPU: uno o dos nucleos bastan.** La pasada pasa casi todo su tiempo
esperando a la API de Blizzard, no calculando.

Con eso, cualquier VPS de los de ~5 euros al mes vale. No hace falta nada
gestionado: esto es un proceso de Python y un SQLite en un fichero.

**Y un dominio.** Da igual cual, pero hace falta uno de verdad por dos
motivos concretos: sin dominio no hay certificado de Let's Encrypt (apartado
6) y por tanto no hay HTTPS, y el `sitemap.xml` tiene que llevar URLs
absolutas con el dominio real o Google no lo acepta. Sirve cualquier registrador;
un `.com` esta en unos 10-15 euros al ano.

Lo que **no** hace falta: base de datos gestionada, CDN, Docker, ni un plan de
copias de seguridad complicado. Si se pierde `web.db` se regenera sola en la
siguiente pasada horaria, porque los datos de verdad estan en Blizzard.

---

## 1. Usuario y clonado

La web no necesita (ni debe) correr como root. Crea un usuario de sistema
dedicado y la carpeta donde va a vivir todo:

```bash
sudo useradd --system --create-home --shell /bin/bash sentinel
sudo mkdir -p /opt/auction-sentinel
sudo chown sentinel:sentinel /opt/auction-sentinel
```

`--shell /bin/bash` y no `/usr/sbin/nologin`: mas abajo hace falta entrar como
este usuario a mano para clonar, instalar y lanzar la primera pasada. El
usuario no tiene sudo ni mas permisos que los de un usuario normal del
sistema, que es lo que importa para un servicio que solo lee.

A partir de aqui, todo como `sentinel`:

```bash
sudo -iu sentinel
git clone https://github.com/Salicromo/wow-price-checker.git /opt/auction-sentinel
cd /opt/auction-sentinel
```

## 2. El entorno virtual

Antes de nada, con permisos de root, los paquetes de sistema que hacen
falta: `python3-venv` para poder crear el entorno virtual, y el cliente
`sqlite3` que se usa mas abajo (apartado 7) para mirar la base a mano.
Muchas imagenes minimas de VPS no traen ninguno de los dos:

```bash
sudo apt update && sudo apt install -y python3-venv sqlite3
```

Ya como `sentinel`, dentro de `/opt/auction-sentinel`:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

**`requirements.txt` y no `requirements-dev.txt`.** El de desarrollo anade
`pytest`, `requests-mock`, `httpx` y `lupa`, que son para los 663 tests y no
hacen falta en el servidor. `fastapi`, `uvicorn[standard]` y `jinja2` —lo que
de verdad sirve la web— ya estan en `requirements.txt`, junto a lo que usa el
vigilante.

## 3. El `.env`

Copia la plantilla del repositorio y edita:

```bash
cp .env.example .env
```

Para la web publica hacen falta **cuatro variables**:

```
BLIZZARD_CLIENT_ID=tu_client_id
BLIZZARD_CLIENT_SECRET=tu_client_secret
AUCTION_DB=/opt/auction-sentinel/web.db
BASE_URL=https://tudominio.example
```

- `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET`: las credenciales de
  <https://develop.battle.net/access/clients>, las mismas que usa el
  vigilante. Las lee `publicar_web.py` (via `os.getenv`, igual que
  `main.py`); la web propiamente dicha (`web/app.py`) no habla nunca con
  Blizzard, solo lee la base que `publicar_web.py` ha llenado.
- `AUCTION_DB`: **ruta absoluta** del fichero SQLite. La leen **las dos
  mitades** —la pasada que lo llena y el servidor que lo sirve—, y ese es el
  motivo de que exista. Sin ella, cada mitad resuelve la ruta relativa
  `web.db` contra su propio directorio de trabajo; en cuanto no coinciden, el
  servidor abre un fichero que no existe, `abrir()` se lo crea con el esquema
  puesto, y **todas las paginas dan 404 sin que nada lo diga**. Con ella, el
  servidor escribe en su primera linea de log que fichero ha abierto y cuantas
  filas tiene.
- `BASE_URL`: el dominio publico, sin barra final. Lo lee `web/app.py` (con
  `os.environ.get`) para construir las URLs absolutas de `sitemap.xml` —
  Google no acepta URLs relativas ahi. Tiene que ser el mismo dominio que
  pongas en `server_name` dentro de `nginx.conf` (apartado 6): si no
  coinciden, el sitemap anuncia un dominio y nginx sirve otro.

**Deja vacias, o borra directamente, las tres lineas de Discord**
(`DISCORD_WEBHOOK_URL`, `DISCORD_UNDERCUT_WEBHOOK_URL`,
`DISCORD_VENTAS_WEBHOOK_URL`). Son del vigilante, no de la web: ni
`web/app.py` ni `publicar_web.py` las leen (compruebalo tu mismo si quieres:
`grep -rn "DISCORD" web/ publicar_web.py` no devuelve nada). Ponerlas aqui no
hace ni bien ni mal, solo confunde a quien lea el `.env` del servidor
pensando que este proceso manda algo a Discord.

## 4. La primera pasada, a mano

Antes de instalar nada automatico, llena la base una vez a mano:

```bash
.venv/bin/python publicar_web.py -v
```

**Esto tarda mucho la primera vez, y es normal.** Medido durante el
desarrollo: dos reinos tardaron **15 minutos y 45 segundos**, casi todo el
tiempo pidiendo el nombre de producto de **14.788 objetos nuevos**, uno por
uno, con Blizzard aplicando rate-limit (HTTP 429) segun se piden. La region
completa —92 reinos conectados en EU— va a tardar mas que eso, no menos: no
lo interrumpas ni lo des por colgado porque no veas movimiento en la
pantalla durante varios minutos, con `-v` cada reino y cada tanda de nombres
va dejando lineas segun avanza.

Las pasadas siguientes son otra cosa: sobre esa misma base, la segunda pasada
completa tardo **4,5 segundos**, porque `publicar_web.py` solo pide el
nombre de un producto la primera vez que aparece (`productos_sin_nombre` en
el propio script). Esa lentitud inicial no se repite cada hora, se paga una
vez.

Si la conexion SSH se puede cortar durante esos minutos, lanzala en segundo
plano y no en primer plano:

```bash
nohup .venv/bin/python publicar_web.py -v \
    > /tmp/primera-pasada.log 2>&1 &
tail -f /tmp/primera-pasada.log
```

Al terminar debe decir algo como `Listo: 92 reinos, 20144 productos, ... filas
de precio, ... productos con nombre nuevo.` y salir con codigo 0:

```bash
echo $?
```

Si en vez de eso ves `2`, mas de un 30% de los reinos han fallado y
`publicar_web.py` **no ha tocado la base a proposito** (ver apartado 7 mas
abajo) — antes de seguir, resuelve por que estan fallando tantos reinos
(credenciales, conectividad con la API de Blizzard) y repite la pasada.

## 5. Instalar y activar los servicios de systemd

```bash
exit   # sales de la sesion de "sentinel", el resto es con sudo
```

```bash
sudo cp /opt/auction-sentinel/despliegue/auction-sentinel.service \
        /opt/auction-sentinel/despliegue/publicar-web.service \
        /opt/auction-sentinel/despliegue/publicar-web.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auction-sentinel.service
sudo systemctl enable --now publicar-web.timer
```

Nota que **`publicar-web.service` no se habilita directamente**: no tiene
seccion `[Install]` porque no hace falta, lo dispara el `.timer`. Habilitar
el `.service` a secas no haria nada malo, pero tampoco haria nada — solo el
`.timer` decide cuando corre.

Comprueba que las tres unidades han quedado bien:

```bash
systemctl status auction-sentinel.service
systemctl list-timers publicar-web.timer
```

La web ya deberia responder en local:

```bash
curl -I http://127.0.0.1:8000/                    # la portada, que no depende de tu base
```

## 6. nginx y certbot

Edita `despliegue/nginx.conf` **antes** de copiarlo: sustituye
`auctionsentinel.example` por tu dominio real (las dos apariciones de
`server_name`), el mismo que pusiste en `BASE_URL` en el `.env`.

```bash
sudo cp /opt/auction-sentinel/despliegue/nginx.conf /etc/nginx/sites-available/auction-sentinel
sudo ln -s /etc/nginx/sites-available/auction-sentinel /etc/nginx/sites-enabled/auction-sentinel
sudo nginx -t
sudo systemctl reload nginx
```

`nginx -t` valida la sintaxis antes de recargar nada; si se queja, corrige
antes de seguir con `reload`.

Con el DNS de tu dominio ya apuntando al VPS, pide el certificado:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tudominio.example
```

Sustituye `tudominio.example` por el mismo dominio de `server_name` y
`BASE_URL`. Certbot reescribe el bloque de nginx para servir en 443 y renueva
solo (systemd trae su propio timer de certbot, `certbot.timer`, que se activa
solo al instalar el paquete).

---

## 7. Como saber si va bien

**Lo primero: ¿que base ha abierto?**

```bash
journalctl -u auction-sentinel.service --no-pager | grep Sirviendo | tail -1
```

Sale una linea asi:

```
Sirviendo /opt/auction-sentinel/web.db (792.403 filas de precio)
```

Esa linea vale por media hora de diagnostico. Si la ruta no es la que pusiste
en `AUCTION_DB`, o si dice `(0 filas de precio)`, ya sabes por que las paginas
dan 404 sin tener que mirar nada mas. Con la base vacia sale ademas un aviso
diciendolo con todas las letras.

**¿Esta viva la web?**

```bash
systemctl status auction-sentinel.service
curl -I https://tudominio.example/sitemap.xml
```

`Active: active (running)` y un `200` quieren decir que uvicorn esta arriba
—`/`, `/robots.txt` y `/sitemap.xml` son las tres rutas que existen siempre,
sin depender de que sepas el slug de un reino o el id de un producto de tu
base. Las dos de los rastreadores (`/robots.txt` y `/sitemap.xml`) deberian
venir ademas con `Cache-Control: public, max-age=3600`, que es la que pone
`web/app.py`; la portada no lleva cabecera de cache, igual que el resto de
paginas HTML.
Si `systemctl status` muestra reinicios recientes, mira por que con
`journalctl -u auction-sentinel.service -n 50 --no-pager`: con `Restart=always`
el servicio se levanta solo, pero un reinicio en bucle es sintoma de algo
roto (por ejemplo, un `web.db` inaccesible).

**¿Que hizo la ultima pasada?**

```bash
systemctl status publicar-web.service
journalctl -u publicar-web.service -n 30 --no-pager
```

Una pasada buena termina con la misma linea que viste a mano en el apartado
4: `Listo: N reinos, N productos, N filas de precio, N productos con nombre
nuevo.` Para ver exactamente cuando fue la ultima:

```bash
systemctl list-timers publicar-web.timer
```

**¿Cuantas filas tiene la base ahora mismo?**

```bash
sqlite3 /opt/auction-sentinel/web.db \
  "SELECT (SELECT COUNT(*) FROM precio)   AS precios, \
          (SELECT COUNT(*) FROM reino)    AS reinos, \
          (SELECT COUNT(*) FROM nombre)   AS nombres, \
          datetime((SELECT generado_en FROM volcado), 'unixepoch') AS generado_en;"
```

`generado_en` es la hora del volcado que esta sirviendo la web ahora mismo
(la tabla `volcado` solo guarda esa fila, la pone `publicar_web.py` al
final de cada pasada buena). Si lleva mas de un par de horas sin moverse, el
timer no esta disparando o las pasadas estan fallando — sigue con el punto
siguiente.

**¿Ha rechazado publicar por demasiados reinos caidos?**

`publicar_web.py` sale con codigo **2** cuando fallan mas del **30%** de los
reinos (`failure_ratio_threshold` en `config.yaml`), y en ese caso **deja la
base tal cual estaba** — a proposito: la pasada de la hora anterior es mejor
que una region a medio reemplazar. Se ve asi:

```bash
systemctl is-failed publicar-web.service
```

Si dice `failed` (y no `inactive`/`active`), busca el motivo con:

```bash
journalctl -u publicar-web.service --since "-6 hours" | grep "no toco la base"
```

La linea completa dice algo como `7 de 92 reinos han fallado (8%)...` o, en un
caso de verdad malo, `40 de 92 reinos han fallado (43%), por encima del
limite del 30%: no toco la base. Me quedo a proposito con la pasada
anterior.` La web sigue sirviendo los datos de la ultima pasada buena
mientras tanto —no hay nada roto de cara al usuario—, pero si ese mensaje
sale hora tras hora hay que mirar por que fallan tantos reinos: credenciales
de Blizzard caducadas o mal puestas en el `.env`, o la API de Blizzard con
problemas (compruebalo en <https://status.battle.net>).

---

## 8. Cuando se rompe

**La tabla `precio` esta vacia y todas las paginas dan 404.** Es la ruina
total: sin filas en `precio` no hay ficha de producto ni pagina de reino que
mostrar, y tanto `/item/<id>` como `/realm/<slug>` devuelven 404 (mira
`web/app.py`, ambas rutas lanzan `HTTPException(404)` cuando la consulta
vuelve vacia). La portada sigue dando 200, pero con la lista de reinos
vacia, que es justo la senal de esto. Comprueba:

```bash
sqlite3 /opt/auction-sentinel/web.db "SELECT COUNT(*) FROM precio;"
```

Si da `0`, en orden de lo mas probable a lo menos probable:

1. **La primera pasada (apartado 4) nunca se termino de ejecutar**, o se
   ejecuto contra otra base. Comprueba que el fichero existe y no esta
   vacio: `ls -la /opt/auction-sentinel/web.db*` (deberias ver `web.db`,
   `web.db-wal` y `web.db-shm`, modo WAL). Si no existe ninguno, repite el
   apartado 4.
2. **La ruta de la base no coincide entre los dos servicios.**
   `publicar-web.service` escribe en la ruta que le pasa `--db` (por
   defecto de esta instalacion, `/opt/auction-sentinel/web.db`), y
   `auction-sentinel.service` lee la que resulta de `web.db` **relativo a su
   `WorkingDirectory`** (asi lo abre `web/app.py` con
   `RUTA_POR_DEFECTO = Path("web.db")`, ver `web/db.py`). Si algun dia cambias
   el `WorkingDirectory` de una unidad sin tocar la otra, cada proceso acaba
   mirando un fichero distinto y la web se queda leyendo una base vacia
   aunque las pasadas vayan perfectamente. Los ficheros de este directorio ya
   vienen con las dos rutas alineadas (ambos en `/opt/auction-sentinel`); si
   los tocas, mantenlas iguales.
3. **Las credenciales de Blizzard son invalidas.** Revisa el log de la
   ultima pasada (`journalctl -u publicar-web.service -n 50 --no-pager`) por
   errores de autenticacion, y confirma que `BLIZZARD_CLIENT_ID` y
   `BLIZZARD_CLIENT_SECRET` en `/opt/auction-sentinel/.env` son correctos.
4. **Demasiados reinos han fallado en todas las pasadas recientes** (ver el
   apartado 7 de arriba) y la base nunca ha llegado a escribirse una primera
   vez — esto solo pasa si el apartado 4 nunca se hizo con exito, porque una
   vez que hay una pasada buena, un `2` posterior deja los datos anteriores
   intactos en vez de vaciarlos.

**uvicorn no arranca.** Casi siempre es el `.venv` o la base:

```bash
journalctl -u auction-sentinel.service -n 50 --no-pager
```

Un `ModuleNotFoundError` quiere decir que `pip install -r requirements.txt`
no se completo dentro de `/opt/auction-sentinel/.venv`; un error de SQLite al
abrir la base normalmente es de permisos —recuerda que todo esto corre como
`sentinel`, asi que `/opt/auction-sentinel/web.db` tiene que ser suyo:
`ls -la /opt/auction-sentinel/web.db` deberia mostrar `sentinel sentinel`
como propietario.

**nginx da 502.** uvicorn no esta escuchando en `127.0.0.1:8000`. Comprueba
`systemctl status auction-sentinel.service` primero; si esta activo,
`curl -I http://127.0.0.1:8000/` en el propio VPS para descartar que sea un
problema de nginx y no de la app.
