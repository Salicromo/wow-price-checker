# WoW Price Checker

Vigila la Casa de Subastas de World of Warcraft y avisa por Discord cuando
alguno de tus objetos esta en **compra directa** por debajo del precio que hayas
fijado.

- Escanea todos los reinos conectados de una region (por defecto EU).
- Precio maximo **por objeto y por ilvl**, configurable en `config.yaml`.
- No repite avisos: recuerda que subastas ya te ha notificado.
- Avisos con embed, enlace a Wowhead y cuanto esta por debajo de tu limite.
- Si el escaneo va mal (muchos reinos caidos) te lo dice, en vez de callarse.

---

## 1. Puesta en marcha (en local)

### 1.1 Credenciales

Necesitas dos cosas:

**API de Blizzard** — entra en <https://develop.battle.net/access/clients>, crea
un cliente (cualquier nombre; como URL de redireccion vale
`https://localhost`) y apunta el *Client ID* y el *Client Secret*.

**Webhook de Discord** — en el canal donde quieras los avisos: `Editar canal >
Integraciones > Webhooks > Nuevo webhook > Copiar URL del webhook`.

### 1.2 Instalacion

Desde la carpeta del proyecto, en PowerShell:

```bash
py -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copia `.env.example` a `.env` y rellena los tres valores. Ese fichero no se sube
a git nunca.

### 1.3 Comprobar que todo esta bien

Primero, que el webhook funcione:

```bash
.venv\Scripts\python.exe main.py --test-discord
```

Deberia aparecerte un mensaje de prueba en el canal de Discord.

Despues, una pasada de prueba sobre un par de reinos, sin enviar nada:

```bash
.venv\Scripts\python.exe main.py --dry-run --realms 1305,1378
```

Y por ultimo, el escaneo completo de verdad:

```bash
.venv\Scripts\python.exe main.py
```

Tarda unos segundos: son los 92 connected realms de EU y unos 2,8 millones de
subastas, pero solo se mira lo que interesa.

---

## 2. Configurar que vigilar

Todo se edita en `config.yaml`; no hay que tocar codigo.

```yaml
items:
  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl: { 298: 9000, 311: 90000 }
```

Puntos importantes:

- El **nombre debe ser exacto y en ingles**, tal cual aparece en el juego.
- Los precios van **en oro**.
- **Solo se avisa de los ilvl que aparezcan en la tabla.** En el ejemplo, una
  subasta de ilvl 305 se ignora aunque este tirada de precio.
- Si un nombre da problemas, puedes fijar el id a mano:
  `item_id: 213456`. Lo ves en la URL de Wowhead del objeto.

### Objetos que no dependen del ilvl

Un patron, una receta o una montura no escalan: siempre son el mismo objeto, y
una tabla por ilvl no significa nada ahi. Esos llevan un precio unico:

```yaml
items:
  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000
    avisar_undercut: false
```

- `max_price` es el limite en oro, y se avisa de cualquier subasta a ese precio
  o por debajo, venga con el ilvl que venga.
- Cada objeto lleva `max_price` **o** `max_price_by_ilvl`, nunca los dos.
- `avisar_undercut: false` apaga los avisos de undercut de ese objeto y solo de
  ese. Los chollos y los avisos de venta siguen funcionando igual: el undercut
  se sigue calculando por dentro, porque el seguimiento de ventas lo necesita
  para no confundir un reposteo tuyo con una venta; lo unico que no pasa es que
  te lo envie.

Si cambias algo mal, el script te lo dice al arrancar y no llega a escanear.

### Cuando no se puede saber el ilvl

Blizzard no publica el ilvl de una subasta: lo codifica en unos "bonus ids" que
el fichero traduce en `bonus_ilvl_map`. Si Blizzard los cambia en un parche, el
script no se queda mudo: avisa igualmente cuando el precio este por debajo de tu
umbral **mas barato** para ese objeto, marcando el aviso como *ilvl sin
confirmar*. Comprueba el ilvl en el juego antes de comprar.

Para actualizar el mapa, ejecuta con `-v` y mira los bonus ids que salen:

```bash
.venv\Scripts\python.exe main.py --dry-run --realms 1305 -v
```

---

## 3. Ponerlo en GitHub Actions

Cuando funcione en local:

1. En el repositorio: `Settings > Secrets and variables > Actions > New
   repository secret`, y crea `DISCORD_WEBHOOK_URL`, `BLIZZARD_CLIENT_ID` y
   `BLIZZARD_CLIENT_SECRET`. Si vigilas tus propias subastas, crea tambien
   `PRIVADO_TOKEN` (apartado 3.0).
2. Sube los cambios. El workflow `.github/workflows/monitor.yml` ya se ejecuta
   solo: su `schedule` corre cada 3 horas como red de seguridad, y la pasada de
   cada hora la dispara el cron externo del apartado 3.1, que es puntual.

   Blizzard regenera los datos de la casa de subastas una vez por hora y para
   toda la region a la vez (comprobado: 30 reinos de EU compartian el volcado de
   las 11:31 UTC). Escanear mas a menudo devuelve datos identicos. Cada pasada
   escribe en el log la antiguedad del volcado; si ves que se acerca a los 60
   minutos, Blizzard ha movido su horario y conviene retrasar el minuto.
3. Para probarlo a mano: pestana `Actions > WoW Price Monitor > Run workflow`
   (tiene una casilla para hacer una pasada en seco).

La memoria de avisos se guarda entre ejecuciones con la cache de Actions, asi
que no ensucia el repositorio con commits.

---

## 3.0 El repositorio privado

Este repositorio es publico. Lo que dice quien eres en el juego no puede estar
en el, y vive en otro, privado, que se llama igual con `-privado` detras (por
ejemplo `usuario/wow-price-checker-privado`):

| Donde | Que | Quien lo escribe |
|---|---|---|
| `main` | `personajes.yaml`: el orden de tus personajes (5.7) | Tu, a mano |
| rama `subastas` | Tus subastas, personajes y ventas | `sync_subastas.py` (5.3) |
| rama `datos` | Catalogo y precios de la app | El workflow, cada pasada |

El workflow lo lee y escribe con un token *fine-grained* guardado como secret
`PRIVADO_TOKEN`, con acceso solo al repositorio privado y el permiso
`Contents: Read and write`. Sin el secret, la pasada sigue avisando de chollos,
pero no vigila tus subastas.

Como los logs de Actions de un repositorio publico los lee cualquiera, el
workflow registra cada nombre de personaje como valor enmascarado nada mas
traerse los ficheros: en los logs salen como `***`.

Y como cualquiera puede abrir un PR, en `Settings > Actions > General` conviene
pedir aprobacion para los workflows de *todos* los colaboradores externos: un PR
podria restaurar la cache de `.state` y sacarla por el log.

## 3.1 Disparo puntual desde un cron externo

Los eventos `schedule` de Actions entran en una cola compartida y se retrasan
entre 20 y 40 minutos, cuando no se descartan. Un `workflow_dispatch`, en
cambio, arranca en segundos (medido en este repositorio: 12 s). Por eso la
ejecucion de cada hora la dispara un cron externo llamando a la API de GitHub,
y el `schedule` del workflow se queda como red de seguridad cada 3 horas.

Hace falta un token, asi que conviene que sea lo mas limitado posible.

### El token

En <https://github.com/settings/personal-access-tokens/new> crea un token
**fine-grained** (no uno clasico):

- **Repository access**: *Only select repositories* -> `wow-price-checker`.
- **Permissions** -> *Repository permissions* -> **Actions: Read and write**.
  Nada mas. (Si la llamada devolviera 403, anade *Contents: Read*.)
- **Expiration**: pon una fecha y apuntala; habra que renovarlo.

Asi acotado, el token solo puede lanzar workflows en ese repositorio. No puede
leer tu codigo ni tocar ningun otro repo.

### El cron externo

En un servicio de cron por HTTP (cron-job.org o equivalente), crea un trabajo
con exactamente esto:

| Campo | Valor |
|---|---|
| URL | `https://api.github.com/repos/Salicromo/wow-price-checker/actions/workflows/monitor.yml/dispatches` |
| Metodo | `POST` |
| Horario | cada hora, minuto **24** |
| Cuerpo | `{"ref":"main"}` |

Cabeceras:

```
Accept: application/vnd.github+json
Authorization: Bearer TU_TOKEN_AQUI
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

La respuesta correcta es **HTTP 204 sin cuerpo**. Un 404 suele significar que
el token no tiene acceso al repositorio; un 422, que la rama `main` o el nombre
del workflow no coinciden.

El minuto sale de cuando Blizzard regenera los datos, mas **un** minuto de
margen. **Ese momento se mueve**: el 2026-08-31 el volcado salia a las
`:31:22` y el 2026-09-02 ya salia a las `:23:30`.

El margen es de un minuto y no de dos porque es lo que mas pesa en lo que tarda
un aviso en llegarte. Medido en la pasada de las 18:25 UTC del 2026-09-02:

| Tramo | Tiempo |
|---|---|
| Blizzard publica | `18:23:30` |
| El cron dispara | `18:25:00` (90 s de colchon) |
| GitHub arranca la maquina | `18:25:18` |
| Preparar Python | `18:25:26` |
| Escanear los 92 reinos y avisar | `18:25:43` |

Dos tercios del retraso eran colchon. Con un minuto el aviso sale a los ~75 s de
publicarse, en vez de a los ~135.

No se baja a cero. Disparar en el minuto exacto de la publicacion obliga a
esperar medio minuto casi siempre, y **GitHub redondea cada trabajo al minuto
entero**: se pasaria de 1 a 2 minutos facturados por pasada --el doble de
cuota-- para ganar 40 segundos.

No hace falta que lo vigiles ni que lo pongas tu: cada pasada apunta a que
minuto ha publicado Blizzard, y cuando **tres pasadas seguidas** coinciden en
que el disparo se ha descolgado mas de **un** minuto, lo mueve.

Ese margen de un minuto es a proposito. Fue de seis, y eso toleraba hasta seis
minutos de latencia regalada: el aviso salia mas tarde de lo necesario y nada lo
corregia, porque el sistema lo daba por bueno. Un reajuste de uno o dos minutos
se hace igual pero sin avisar por Discord: es afinar, no arreglar una averia. Tres y no una: si Blizzard tiene un mal rato
y publica tarde una hora suelta, mover el cron detras de ese tropiezo lo dejaria
mal puesto el resto del dia.

Funciona en los dos sentidos. Que el disparo se quede corto es incluso peor que
llegar tarde: la vigilancia esta acotada a unos minutos, asi que si publican mas
tarde de esa ventana la pasada se va de vacio y pierdes la hora entera.

### Que lo mueva solo (recomendado)

Con estos dos secretos puestos en el repositorio, la pasada lo cambia sola en
cron-job.org y te lo cuenta por Discord:

| Secreto | De donde sale |
|---|---|
| `CRONJOB_API_KEY` | cron-job.org -> Settings -> API, boton *Create API key* |
| `CRONJOB_JOB_ID` | el numero que sale en la URL del trabajo, `.../jobs/<ID>` |

Se ponen en *Settings -> Secrets and variables -> Actions* del repositorio, igual
que los de Blizzard y Discord. Usa la API documentada en
<https://docs.cron-job.org/rest-api.html> y lo unico que toca es el minuto del
horario.

### Si prefieres cambiarlo tu

Sin esos secretos no se toca nada y el aviso llega igual por Discord, con el
minuto exacto:

```
⚠️ El disparo se ha desalineado
Blizzard lleva 3 pasadas publicando a y 23 y el disparo esta en y 33.
Entra en cron-job.org y pon el disparo en el minuto 25: tendras los avisos antes.
```

Ese aviso no se repite cada hora: tras mandarlo se olvida lo medido y vuelve a
contar, asi que si no le haces caso reincide cada tres pasadas, no cada una.

### De madrugada tambien

Durante la ventana de silencio se mide y se mueve igual, porque cambiar el
minuto del cron no despierta a nadie. Lo unico que se aplaza es contarlo: el
aviso se guarda y sale en la primera pasada despierta.

Importa mas de lo que parece. Si Blizzard cambia la hora a las 02:00 y no se
midiera hasta las 09:25, con las tres pasadas que hacen falta no quedaria
arreglado hasta las 11:25: toda la manana con los avisos llegando tarde, justo
cuando empiezas a usarlos.

### Si Blizzard llega tarde

Si al escanear resulta que el volcado de esta hora todavia no ha salido, la
pasada **se queda vigilando** en vez de perder la hora entera: le pregunta la
hora de publicacion a un reino cada 15 segundos y reescanea en cuanto aparece.

Preguntarla es barato porque no baja el cuerpo de la respuesta, solo la
cabecera: unas decimas de segundo y unos KB, frente a los casi 500 MB que pesa
un escaneo de la region entera. (Las dos formas ortodoxas de preguntarlo no
sirven, comprobado el 2026-09-02: a `HEAD` responde 404 y `If-Modified-Since`
lo ignora y manda el cuerpo igual.)

```
⏳ Blizzard va tarde: el volcado mas nuevo es el de las 13:23 UTC y ya tiene 70
   min, asi que el de esta hora no ha salido. Vigilo hasta 120 s a ver si
   aparece (quedan 2 intento(s)).
✅ Ya esta: Blizzard ha publicado el volcado de las 14:23 UTC. Reescaneo.
```

Cada intento envia sus propios avisos, asi que un chollo que solo aparezca en
el primero se manda igual: reintentar nunca se traga una alerta.

Se decide por **antiguedad**, no contra un minuto configurado. Como el volcado
se regenera cada hora, uno de mas de 61 minutos delata que el de esta hora no ha
salido, publiquen a la hora que publiquen. Por eso una pasada lanzada a mano a y
58 no reintenta: su volcado de y 23 tiene 35 minutos, pero es el ultimo que
existe.

### Si el disparo se queda por delante de la publicacion

Es el caso feo, y pasa solo en cuanto Blizzard mueve la publicacion mas tarde:
disparando a y 25 con publicacion a y 31, cada pasada se encontraria el volcado
de la hora anterior. No se pierde ninguno --la pasada de las 10:25 leeria el de
las 09:31, la de las 11:25 el de las 10:31-- pero se leerian con **54 minutos de
retraso**, y un chollo de hace 54 minutos ya se lo ha llevado alguien.

Para eso no se espera al arreglo del disparo, que tarda tres pasadas: si al
escanear resulta que el siguiente volcado sale dentro de poco, la pasada espera
a ese en vez de avisar de uno casi caduco.

```
⏳ El volcado de las 09:31 UTC ya tiene 54 min y el siguiente sale en unos 6
   min: no merece la pena avisar de chollos tan viejos. Espero al nuevo.
```

En marcha normal no espera nunca, porque el volcado recien salido tiene 2
minutos y el siguiente esta a 58.

Y tiene freno de mano: esperar sale a cuenta mientras el disparo acabe
recolocandose, pero si no lo hiciera --la clave de cron-job.org caducada, por
ejemplo-- esperar 12 minutos cada hora son 288 al dia, y en un repositorio
privado el tiempo de Actions se paga. Tras 4 pasadas seguidas esperando, tira la
toalla y lo dice:

```
⚠️ Llevo 4 pasadas esperando al volcado y el disparo sigue sin recolocarse.
   Dejo de esperar para no gastar horas de Actions.
```

Se ajusta en `config.yaml` con `max_dump_age_minutes`, `stale_retries`,
`stale_retry_wait_seconds`, `dump_poll_seconds` y `espera_maxima_minutos`. Con
`stale_retries: 0` se desactiva.

## 3.2 Saber si esta corriendo de verdad

Cuando no llega ningun aviso a Discord hay dos explicaciones muy distintas: que
no haya chollos, o que la pasada no se haya ejecutado. Para distinguirlas:

```bash
.venv\Scripts\python.exe estado.py
```

Lista las ejecuciones programadas de las ultimas 24 horas, marca las que
faltan, y dice cuanto se retraso cada una respecto al minuto del cron. Con
`--detalle` descarga ademas el log de cada pasada y resume que encontro (mas
lento). Necesita el cliente `gh` autenticado.

Para revisar una sola ejecucion a fondo, la pestana Actions del repositorio, o:

```bash
gh run list --workflow="WoW Price Monitor" --limit 10
```

## 4. Opciones de la linea de comandos

| Opcion | Para que sirve |
|---|---|
| `--dry-run` | Escanea y muestra los chollos, pero no envia nada ni guarda estado. |
| `--realms 1305,1378` | Escanea solo esos reinos. Ideal para probar rapido. |
| `--test-discord` | Manda un mensaje de prueba al webhook y termina. |
| `--ignore-state` | Avisa tambien de chollos ya notificados antes. |
| `--ventas` | Avisa de tus subastas vendidas, en su propio canal. |
| `--mis-ventas ruta` | Carpeta con el resumen de lo vendido (por defecto `mis_ventas/`). |
| `--config otro.yaml` | Usa otro fichero de configuracion. |
| `--state-dir ruta` | Cambia donde se guarda la memoria (por defecto `.state/`). |
| `-v` | Muestra cada subasta vista, con sus bonus ids. |

Codigos de salida: `0` todo bien · `1` error de configuracion o credenciales ·
`2` demasiados reinos han fallado y el resultado esta incompleto.

---

## 5. Estructura del proyecto

```
config.yaml            Lo unico que editas normalmente
main.py                Linea de comandos y orquestacion
estado.py              Comprueba si Actions esta ejecutando el cron
datos_app.py           Genera lo que lee la app del movil
android/               La app: que personajes no tienen puesto cada objeto
wowalerts/
  config.py            Carga y validacion del config
  blizzard.py          API de Blizzard: OAuth, reintentos, endpoints
  items.py             Nombres de objeto -> ids
  ilvl.py              Deduccion del ilvl de una subasta
  scanner.py           Que cuenta como chollo (logica pura)
  state.py             Memoria entre ejecuciones
  notifier.py          Embeds y envio a Discord
  ventas.py            Que cuenta como venta y que como caducidad
  journalator.py       Lee el historial de ventas del addon Journalator
  snapshot.py          Si el volcado leido es el de esta hora
  precios.py           El precio a batir en cada reino, para la app
tests/                 741 tests, sin tocar la red
```

Para pasar los tests:

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python.exe -m pytest -q
```

---

## 5. Avisos de undercut en tus propias subastas

Ademas de buscar chollos ajenos, el proyecto puede avisarte cuando **alguien
publica el mismo objeto que tu, a tu precio o por debajo**, para que vayas a
repostear. Solo mira los objetos que ya vigila `config.yaml`: el resto de lo que
tengas puesto (monturas, mochilas, decoracion) se ignora.

La API de Blizzard no dice quien publica cada subasta, asi que hace falta un
addon que exporte las tuyas desde dentro del juego.

### 5.1 Instalar el addon

Copia la carpeta `addon/WowAlertsExport` a tu carpeta de addons:

```bash
Copy-Item -Recurse -Force addon/WowAlertsExport "D:/Juegos/World of Warcraft/_retail_/Interface/AddOns/"
```

En la Steam Deck no hace falta saberse la ruta: hay un script que se la
pregunta a `sync_subastas.py`, que ya sabe buscarla.

```bash
bash instalar_addon_deck.sh
```

Vuelve a ejecutarlo **cada vez que cambie el addon**. Para saber que version
tienes cargada, dentro del juego: `/wa`.

Entra al juego y **abre la Casa de Subastas**: en el chat general te dira
cuantas subastas tuyas ha registrado. Si tienes personajes vendiendo en varios
reinos, repitelo con cada uno; el addon los va acumulando.

Para comprobarlo en cualquier momento: `/wowalerts`.

**Dos cosas que conviene saber:**

- El juego solo conoce tus subastas **mientras la Casa de Subastas esta
  abierta**. Con ella cerrada, el addon no puede leer nada y no toca lo que ya
  tenia guardado.
- WoW solo escribe los datos del addon a disco al salir del juego, al volver al
  selector de personajes o al hacer `/reload`. Si posteas y sigues jugando, el
  vigilante todavia no lo sabe. El addon te lo recuerda en pantalla.

### 5.2 Canal propio para los undercuts

Los avisos de undercut son de otra naturaleza que los chollos, asi que van a su
propio canal. Crea un webhook en el canal que quieras (`Editar canal >
Integraciones > Webhooks > Nuevo webhook`) y ponlo en `.env`:

```
DISCORD_UNDERCUT_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Si lo dejas vacio, los undercuts van al mismo canal que los chollos.

Para comprobar que ese canal funciona:

```bash
.venv\Scripts\python.exe main.py --undercut --test-discord
```

En GitHub Actions hace falta el mismo valor como secret del repositorio, con
ese mismo nombre.

### 5.3 Instalar la sincronizacion

```bash
powershell -ExecutionPolicy Bypass -File instalar_tarea_sync.ps1
```

Crea una tarea de Windows que cada 15 minutos mira si el volcado ha cambiado y,
si si, lo sube a GitHub. A partir de ahi el vigilante funciona **aunque apagues
el PC**.

Lo sube al repositorio privado (apartado 3.0), que en cada maquina se da de alta
una vez como remoto `privado`:

```bash
git remote add privado https://github.com/<usuario>/wow-price-checker-privado.git
```

Sin ese remoto no sube nada: caer en `origin`, que es publico, publicaria justo
lo que no debe.

Lo sube a la rama **`subastas`**, no a `main`. Son cuatro carpetas de JSON que
se reescriben enteras cada vez que sales al selector de personajes --unas veinte
veces por tarde de juego-- y en `main` tapaban el historial de verdad: de los
primeros 954 commits del proyecto, 765 eran volcados. Ademas GitHub solo cuenta
como contribucion lo que cae en la rama por defecto, asi que ahi tampoco salen
como trabajo del dia.

Esa rama **no guarda historial**: cada publicacion es un commit sin padre que
reemplaza al anterior, y siempre tiene exactamente uno. Con 100 KB reescritos
veinte veces al dia, guardarlo habria engordado el repositorio un par de MB
diarios para siempre, y de esa rama solo interesa como esta ahora.

Antes de publicar se trae lo que haya en ella, porque el PC y la Steam Deck
comparten rama y cada uno escribe solo su fichero. Si no se puede consultar
--sin red, credenciales caducadas-- no sube nada: rehacer la rama a ciegas
borraria el volcado de la otra maquina.

**No te va a saltar ninguna ventana.** La tarea corre con `pythonw.exe`, que no
tiene consola, y las llamadas a `git` van con `CREATE_NO_WINDOW`. Sin eso se
abrian cuatro consolas de un parpadeo cada quince minutos, en mitad de la
partida: un proceso de consola lanzado desde un padre sin consola se abre la
suya.

Para forzarlo a mano:

```bash
.venv\Scripts\python.exe sync_subastas.py
```

Para quitar la tarea:

```bash
schtasks /delete /tn "WoW subastas sync" /f
```

### 5.4 Probarlo

```bash
.venv\Scripts\python.exe main.py --undercut --dry-run
```

Te lista quien te ha adelantado y en que personaje tienes que ir a cambiarlo,
sin enviar nada a Discord.

### 5.5 Como decide que dos subastas compiten

Del mismo objeto, una subasta ajena compite con la tuya si:

- su ilvl **se puede determinar** y es el tuyo, **o**
- su ilvl no se puede determinar pero sus **bonus ids son los mismos** que los
  de tu objeto.

Si no se puede saber ninguna de las dos cosas, **no se avisa**. Comparar contra
rivales de ilvl desconocido generaba solo falsas alarmas: el equipo de Legion
Remix publica un dato que parece ilvl pero es el nivel del personaje, y esas
subastas de 100 g salian compitiendo contra listados de 10.000 g.

### 5.6 Que esperar

- **Latencia de hasta una hora.** Blizzard regenera los datos de subastas una
  vez por hora. No hay forma de esquivarlo con la API oficial.
- **Un aviso por rival.** Mientras sea el mismo el que te adelanta, no se
  repite. Si reposteas y te vuelven a adelantar, aviso nuevo.

  Lo que decide **si hay mensaje** es que haya alguna nueva; lo que va **dentro**
  del mensaje es **todo lo que ese personaje tiene adelantado ahora mismo**, se
  avisara antes o no, sin marcar cuales son repetidas. Saber cuando se dijo por
  primera vez no cambia nada: vas al buzon a cambiarlas todas igual.

  ```
  ⚔️ Dbardan · WoW 2 — 3 subastas
  • Grebas de las profundidades nocivas — ~~9.000~~ **8.000 g**
  • Zapatillas (292) — ~~5.500~~ **5.100 g**
  • Zapatillas (295) — te igualan a 6.000 g
  ```

  Asi un personaje con tres adelantadas de las que dos ya te avise sale con
  "3 subastas" y las tres lineas, no con "1 nueva" y la sensacion de que las
  otras se arreglaron solas.

  **La foto completa esta siempre en el panel fijado** (ver 5.8).
- **Nada de avisos fantasma.** Si una subasta tuya ya no aparece en la casa de
  subastas (vendida, caducada o cancelada), se descarta sola.
- **Tus otros personajes cuentan como rivales hasta que los visites.** Si
  vendes lo mismo con dos personajes y solo has abierto la Casa de Subastas con
  uno, el otro parece competencia. Abre la CdS con cada personaje que venda y el
  problema desaparece.

### 5.7 En que orden llegan los avisos

Los avisos van agrupados por personaje, y el orden lo pones tu en
`personajes.yaml`, al lado de `config.yaml`. No esta en git: copia
`personajes.example.yaml` y pon tus nombres. En Actions lo trae el workflow del
repositorio privado (apartado 3.0), asi que alli tiene que estar tambien.

```yaml
orden_personajes:
  # --- WoW 1
  - Personaje1
  - Personaje2
  ...
```

Es el orden en que los tienes en el selector, y **no se puede deducir de ningun
fichero**: si lo reordenas arrastrando, ese orden vive en el servidor de
Blizzard, no en tu disco.

Los personajes que no aparezcan en la lista salen detras, por cuenta y reino.
Para cambiar el orden basta con mover lineas; no hay que tocar codigo.

Sin esta lista los grupos salian en el orden en que tocara descargar los reinos,
que cambia de una pasada a otra: nunca podias acostumbrarte a mirar al mismo
sitio.

### 5.8 El panel: como estas ahora mismo

Los avisos cuentan **lo que ha cambiado**; el panel cuenta **como estas**. Es un
unico mensaje en el canal de undercuts que se reescribe cada hora con todas tus
subastas vigiladas y todas las adelantadas, sin filtro de repetidas.

**No lo vas a ver llegar.** Se crea una sola vez y a partir de ahi se edita en
su sitio, asi que nunca sube al final del canal. Tres formas de llegar a el:

- **El enlace del propio aviso.** El ultimo mensaje de cada tanda lleva un
  `📊 Ver el panel con todas` que va directo.
- **Buscando** `Tus subastas` en el canal, con la lupa de Discord.
- **En el log de cada pasada**, que imprime su url:
  `📊 Panel actualizado: https://discord.com/channels/.../...`

Y **fijalo** (`Click derecho > Fijar mensaje`): asi lo tienes en el icono del pin
del canal, tambien desde el movil.

Si lo borras sin querer, no pasa nada: la pasada siguiente publica uno nuevo,
pero tendras que volver a fijarlo.

### 5.9 Con que personaje ir a por un chollo

Los avisos de chollo llevan un campo **Ir con** que dice con que personaje
tuyo, y de que cuenta, puedes comprarlo:

```
Ir con: Hbarfel · WoW 3
```

Y cuando el chollo esta en un reino donde no tienes a nadie, tambien lo dice,
que es igual de util: te ahorra abrir el juego para nada.

La lista sale de las carpetas de WoW, no del addon, asi que incluye tambien los
personajes que no tienen ninguna subasta puesta. La genera `sync_subastas.py`
junto al volcado de subastas, en `mis_personajes.json`, y se actualiza sola
cuando creas un personaje nuevo.

### 5.8 El panel de estado

Ademas de los avisos, el vigilante mantiene **un unico mensaje** en el canal de
undercuts que reescribe cada hora con el estado de todas tus subastas:

```
📊 Tus subastas
Tus 57 subastas vigiladas van primeras. Nada que hacer.

**Mbarval · WoW 2** — 6 vigiladas, todas primeras ✅
**Dbardan · WoW 2** — 4 vigiladas, 1 adelantada
⚠️ Zapatillas del culto siseante (308) — ~~50.000~~ **30.000 g**
```

**Fijalo en el canal** (clic derecho en el mensaje > Fijar) y lo tienes a un
toque desde el movil. Los avisos te cuentan lo que ha cambiado; el panel te
cuenta como estas.

Los personajes que tienen algo que atender salen arriba, y de cada uno solo se
detallan las subastas adelantadas: listar las que van bien seria ilegible.
Cada una lleva su ilvl entre parentesis, igual que los avisos: tienes el mismo
objeto puesto a varios ilvl y cada uno es un producto con su propio precio. Lo
que no escala (patrones, decoracion) va sin el.

No se publica uno nuevo cada hora: se reescribe el mismo, cuyo id se guarda en
`.state/panel.json`. Si lo borras, la pasada siguiente crea otro.

### 5.10 Repostear con una tecla

El addon puede hacer el ciclo de reposteo por ti: cancelar lo que te han
adelantado, recoger lo devuelto del buzon y volver a ponerlo **al precio del que
te adelanto**. Tu solo pulsas una tecla.

**Asignar la tecla**, una vez: `Opciones > Atajos de teclado > AddOns > WoW
Alerts > Reposteo: siguiente paso`. Tambien vale el boton que sale debajo de la
Casa de Subastas y del buzon, que ademas dice que va a hacer.

**El ciclo:**

1. Abre la Casa de Subastas y no toques nada. El boton dice `Leyendo tus
   subastas...` un momento, mientras llega la lista de lo que tienes puesto
   (hasta cinco segundos si no tienes nada puesto), y en cuanto esta entera
   **empieza a buscar solo**: no hace falta pulsar para saber quien te ha
   adelantado. Buscar no es de las cosas que el juego exige que hagas tu, asi
   que puede salir sola; cancelar y postear si, y esas siguen siendo tuyas.
2. `Cancelar (N)`: pulsa una vez por cada subasta adelantada. No hace falta
   esperar a que termine la busqueda: lo que ya sabe que esta adelantado lo
   cancela mientras sigue mirando lo demas.
3. Ve al buzon. `Recoger del buzon`: pulsa una vez por cada carta. Solo recoge
   lo cancelado, el resto del correo no lo toca.
4. Vuelve a la casa. Si han pasado menos de dos minutos desde la busqueda que
   lo cancelo, `Postear` sale nada mas abrir, con el precio de entonces, sin
   buscar ni esperar. Si ha pasado mas, pulsa para buscar otra vez, por si el
   rival se ha movido: solo busca lo devuelto, porque lo que la busqueda anterior
   vio sin nadie delante no se vuelve a mirar durante cinco minutos. Esos cinco
   minutos aguantan un `/reload` y un cambio de personaje, asi que saltar de un
   alt a otro y volver no cuesta un escaneo entero.
5. `Postear`: pulsa una vez por cada objeto. Si el juego pide confirmar el
   precio, el boton dice `Confirmar posteo` y la siguiente pulsacion confirma.
   Mientras el juego crea la subasta, el boton dice `Posteando...`.

**El buzon se recoge solo:** al abrirlo (el de Blizzard o el de TSM), el addon
recoge una detras de otra las cartas de lo cancelado que tiene en la cola, y nada
mas, como el "abrir todo" de TSM. Si el juego da un error (bolsa llena), para, y
vuelve a intentarlo la proxima vez que abras el buzon.

**Todo con una tecla:** si tienes asignada la tecla de interaccion del juego
(`Interactuar con el objetivo`, la que abre el PNJ o el buzon que tienes
delante), mientras la casa o el buzon esten abiertos esa tecla hace el
siguiente paso del reposteo, y al cerrarlos vuelve a ser la de interaccion. El
ciclo queda en: acercarte y pulsar (abre la casa), machacar (cancela), ir al
buzon y pulsar (abre y recoge solo), volver y pulsar (abre la casa), machacar
(repostea), y cambiar de personaje. Si la tecla es la rueda del raton, cuenta
cuando el cursor esta sobre el mundo; sobre una lista, la rueda sigue haciendo
scroll. En combate el addon no toca las teclas.

**La ventana de tus subastas:** al abrir la casa sale a su derecha una ventana
con todo lo que tienes puesto, agrupado en `ADELANTADAS` (en rojo, con el precio
del rival), `RECIEN REPUESTAS` (en azul: lo que acabas de repostear en esta
visita, para ver de un vistazo lo que ya esta hecho), `VAS PRIMERO`, `SIN MIRAR
TODAVIA` y `NO VIGILADAS`. Se va llenando sola conforme avanza la busqueda y se
actualiza al cancelar y al repostear. La `x` de arriba la cierra hasta la
proxima vez que abras la casa.

Debajo de la cabecera hay una **barra de progreso** de lo que el addon esta
haciendo ahora mismo, que se rellena sola: azul mientras escanea (`Escaneando
Grebas 3/7`, diciendo cual esta mirando), naranja mientras cancelas
(`Cancelando 2/5`) y verde mientras repones (`Reposteando 1/4`). Al acabar el
escaneo se queda llena en vez de desaparecer.

Cada fila dice el precio, el ilvl y **lo que le queda de listado** (`11h 32m`),
y lleva a la derecha un boton **`X` que cancela esa subasta**, te hayan
adelantado o no. Cancela una sola con cada clic, igual que la tecla, y lo que
cancelas asi entra en el ciclo normal: se recoge del buzon y se vuelve a poner.
Lo que no esta vigilado se cancela y ya, porque de eso el addon no sabe a que
precio reponerlo. Ojo, que cancelar cuesta el deposito.

Al pasar el raton por una fila sale **la ficha del objeto**, como en las bolsas,
y en las adelantadas debajo **tu precio y el del rival**. El nombre en la fila va
recortado, y con el mismo objeto a varios ilvl a veces hace falta verlo entero.

Puedes machacar la tecla sin mirar: las pulsaciones que llegan mientras el juego
responde no hacen nada. En cuanto en esa ventana ya no queda nada que hacer, sin
esperar a otra pulsacion, sale un aviso en el chat: `Todas
canceladas (N). Recoge lo devuelto en el buzon`, `Vuelve a la casa a postear` o
`Nada que repostear`. Ese aviso espera a que pulses al menos una vez: abrir la
casa para comprar no te suelta nada.

**El precio** es el del rival mas barato que va por delante de ti. Si mientras
ibas al buzon ha desaparecido, se repostea a tu precio de antes: nunca sube.

**Lo que caduca sin venderse** entra en el mismo ciclo. El juego no avisa de
que una subasta caduca, asi que el addon lo sabe por la carta: al abrir el
buzon, cada carta de subasta caducada de un objeto vigilado entra en la cola, se
recoge sola con lo cancelado y se repone en la casa como lo demas. Su precio es
otro: el del mas barato que haya ahora, **suba o baje**, porque a esa nadie la
adelanto, simplemente no se vendio. Solo si nadie mas vende ese objeto se
repone al precio que tenia.

Para saber ese precio, el addon apunta por personaje lo que tienes puesto de
cada objeto e ilvl (el mas barato, si hay varias copias) cada vez que la casa le
manda la lista de tus subastas, y eso incluye lo que pones a mano o con TSM, no
solo lo que posteas con la tecla. Basta con que la casa siga abierta un momento
despues de postear. Si llega la carta de
un objeto del que no tiene precio apuntado (por ejemplo, algo que caduco antes
de tu primera visita a la casa con esta version), no la toca: esa se recoge a
mano.

**Una pulsacion es una accion, siempre.** El juego solo deja cancelar y postear
en respuesta a una tecla o un clic tuyo, igual que la tecla de "Cancel Undercut"
de Auctionator. No uses programas ni teclados que repitan la tecla por ti.

Lo que conviene saber:

- Solo repostea los objetos de `config.yaml` con `repostear` (por defecto, los
  que tienen avisos de undercut), y no toca mascotas. Las recetas llevan
  `avisar_undercut: false` y `repostear: true`: se repostean sin avisarte en
  Discord.
- Tus personajes de `orden_personajes` no cuentan como rivales. Si vendes con
  uno que no esta en la lista, anadelo.
- Solo cancela lo que la busqueda de esta visita ha confirmado: cancelar cuesta
  el deposito. Si la casa no responde a la busqueda de un objeto en diez
  segundos, se salta, y el boton te pide `Cierra y abre la casa para repasar
  precios`.
- La cola se guarda por personaje y sobrevive a `/reload`. Lo que lleve mas de
  48 horas desde que se detecto se descarta, aunque este en la bolsa.
- Lo que se vio sin nadie delante tambien se guarda, y vale para todos los
  personajes de esa cuenta de WoW, porque va por id de subasta. Una subasta
  nueva nunca se salta: su id no esta en la lista. Para forzar un escaneo
  completo de algo que ya estaba puesto, espera los cinco minutos; no hay una
  orden para vaciarlo a mano.
- Si vuelves a poner algo a mano, el addon lo saca de la cola la proxima vez que
  busque en la casa: ve una subasta tuya de ese objeto creada despues de
  cancelarlo y ninguna copia en la bolsa. Si lo vendes o lo envias, lo saca al
  abrir el buzon de Blizzard y ver que no esta ni alli ni en la bolsa. Excepcion:
  si pones a mano otra copia del mismo objeto e ilvl mientras la cancelada sigue
  sin recoger en el buzon, el addon da la cancelada por repuesta.
- Si tienes mas de 50 cartas en el buzon, el juego solo deja ver las primeras:
  el addon no olvida nada mientras tanto. Recoge o borra correo para bajar de 50.
- **Si cambias los objetos, `personajes.yaml` o `listing_hours`**, regenera los
  ficheros del addon y vuelve a copiarlo (apartado 5.1):

```bash
.venv\Scripts\python.exe generar_vigilados.py
```

Escribe `Vigilados.lua` (los objetos, que se sube a git; un test falla si se te
olvida) y `Personajes.lua` (tus personajes, que no se sube). En la Steam Deck,
`instalar_addon_deck.sh` genera el segundo solo, con
`generar_vigilados.py --solo-personajes`, que no necesita credenciales de
Blizzard: basta con que alli este tambien `personajes.yaml`.

## 6. Avisos de venta

Ademas de avisarte de los undercuts, el vigilante te dice **que se te ha
vendido**, en su propio canal, sin tener que entrar al juego a mirar el buzon.
Como los undercuts, solo mira los objetos que vigila `config.yaml`.

### 6.1 Como sabe que se ha vendido

La API de Blizzard **no publica ventas**: solo una foto por hora de lo que sigue
vivo. Una subasta tuya que desaparece pudo venderse, caducar o cancelarse, y
desde fuera las tres se ven igual.

Se separan asi: de cada subasta tuya se guarda **la fecha mas temprana en la que
podria caducar**. Si desaparece antes de esa fecha, es imposible que haya
caducado. Esa fecha se afina cada hora con dos pistas:

- **El tramo de tiempo restante.** Blizzard publica si a una subasta le quedan
  mas de 12 h, entre 2 y 12 h, entre 30 min y 2 h, o menos de 30 min. Verla en
  el tramo de 2-12 h garantiza dos horas de vida: si a la hora siguiente no
  esta, no ha caducado.
- **La ventana de nacimiento.** Si no estaba en el volcado de las 14:31 y si en
  el de las 15:31, se publico entre esas dos horas. Con `listing_hours: 12`, no
  puede caducar antes de las 02:31.

La segunda pista es la buena, y solo vale para las subastas que se publican
estando el vigilante en marcha. Las que ya estaban puestas cuando lo montaste se
apoyan solo en la primera hasta que las reposteas.

Que una subasta sea nueva se decide por su **id**, que crece con el tiempo
dentro de un reino, y no por si el addon la habia exportado ya: el addon puede
tardar dias en volcarla, y tomarla por recien nacida el dia que aparece
convertiria su caducacion en una venta falsa.

### 6.2 Lo que no vas a ver

- **Las ventas de la ultima hora del listado.** Ahi una venta y una caducacion
  producen exactamente el mismo dato, y avisar de todas seria peor: **toda
  subasta que no se vende acaba desapareciendo justo ahi**, asi que el canal se
  llenaria de falsas alarmas.
- **Las ventas de una subasta que hayas cancelado.** Ver mas abajo.
- **Las de un personaje cuyo volcado del addon lleve mas horas sin refrescarse
  que las que dura un listado, si ademas Blizzard ya no la lista.** De esas no
  se puede afirmar nada. Las que Blizzard si lista se siguen vigilando: ver
  6.4.
- **Objetos que no esten en `config.yaml`.**

### 6.3 Los reposteos no cuentan como ventas

Cancelar una subasta y venderla se ven **exactamente igual** desde la API: en
las dos desaparece. Y si reprecias a menudo, cada reposteo tuyo saldria como una
venta. Paso: el 2026-08-31 llegaron 13 avisos de venta, todos falsos, todos
reposteos.

Hay dos defensas, y hacen falta las dos.

**La lista de cancelaciones del addon.** El addon apunta el id de cada subasta
que cancelas y lo sube con el volcado. Es el dato preciso: una cancelacion es
una cancelacion, no hay que adivinar nada. Necesita el addon **v1.9 o
posterior**; si vienes de una version anterior, vuelve a copiarlo (apartado
5.1).

**La espera de una pasada.** Aqui esta el problema que obliga a esperar:

```
16:20  cancelas          -> desaparece del volcado de Blizzard de las 16:31
16:33  pasada            -> cantaria la venta falsa
16:35  el sync sube la cancelacion desde el juego   <- llega tarde
```

Blizzard se entera de tus cancelaciones **antes** que el addon, porque WoW solo
escribe a disco al hacer `/reload`. Por eso una subasta que desaparece no se
canta en el acto: se queda pendiente y solo se anuncia en la pasada siguiente,
si para entonces no ha aparecido en la lista de cancelaciones. Eso le da al
sync una hora entera de margen.

**Coste: las ventas llegan con una hora mas de retraso**, entre 1 y 2 horas en
vez de hasta 1. A cambio, no te mienten.

La fecha de caducidad se sigue juzgando por **cuando desaparecio la subasta**,
no por cuando se toma la decision. Si no, la espera empujaria a la subasta mas
alla de su plazo y se perderian ventas buenas.

**La espera larga cuando te estaban adelantando.** El aviso de undercut te manda
a repostear, asi que una subasta adelantada que desaparece es sospechosa: puede
que hayas ido a reponerla y el addon no lo haya contado todavia. Se le dan dos
pasadas mas en vez de una.

No mas que eso, y aqui esta el porque: **que te adelanten no prueba que hayas
reposteado**. Puedes no haber ido, y una subasta adelantada se vende igual.
Durante un tiempo esto la descartaba para siempre, y se comia ventas de verdad:
el 2026-09-06, a las 04:24 --con el dueño durmiendo, asi que reposteo ninguno--
se trago las 38.002 g de un Yelmo mistico que Journalator tenia apuntado como
vendido.

La espera se corta en cuanto hay respuesta, por cualquiera de los dos lados:

- **El addon vuelve a volcar** despues de que la subasta desapareciera y no la
  lista como cancelada. Ya ha dicho todo lo que tenia que decir: es una venta.
- **Se agotan las dos horas sin que vuelva a volcar.** Cancelarla exige estar
  jugando, y jugar acaba en un `/reload` o en salir del juego, que es cuando WoW
  escribe los SavedVariables y el sync se entera. Si en dos horas no ha escrito
  nada, no has jugado; y si no has jugado, no la has cancelado.

Dos horas caben de sobra antes de que el volcado del addon se pase de las horas
que dura un listado, que es cuando la subasta se soltaria sin veredicto.

Esa espera sigue ahi, pero **ya no es la ultima palabra**: por encima de ella
manda la regla del apartado siguiente, que no vence con el tiempo.

### Ninguna maquina que estuviera jugando se queda sin hablar

Las dos horas de arriba tenian un fallo de fondo: **se median desde la
desaparicion, asi que vencian solas**. Una maquina que ha dejado de sincronizar
no se vuelve fiable porque pasen horas, y el razonamiento "si no ha escrito nada
en dos horas es que no has jugado" solo vale si el sync esta vivo.

El 2026-09-07 costo **ocho ventas falsas** de Dbardan, Mbarlin,
Ebardan y Ebarmar, casi 1,4 millones de oro que nunca llegaron al buzon:

```
00:31  la Deck exporta Adannor    -> el sync lo sube
00:33  la Deck exporta Mbargor  -> el sync lo sube
00:36  la Deck exporta Obarbar     -> el sync lo sube, y ahi se corta
00:4x  sigues la ronda: Dbardan, Mbarlin, Ebardan, Ebarmar
01:23  volcado de Blizzard: sus subastas ya no estan
09:25  se cantan como vendidas
```

Las cancelaciones de esos cuatro se quedaron **dentro de la Deck**. El PC, que
era quien las habia exportado por ultima vez, no sabia nada de ellas, y su lista
de canceladas jamas las iba a tener. Las tres primeras si se taparon: de esas el
sync habia llegado a subir la cancelacion.

Ahora la espera **no vence**: dura hasta que esa maquina vuelve a hablar. En
cada pasada se mira la ultima senal de vida de cada volcado (`pc.json`,
`deck.json`) y, si cae dentro de las dos horas anteriores a la desaparicion, esa
maquina estaba jugando y podria tener una cancelacion que no me ha llegado:

```
⏳ Dbardan de Grebas de las profundidades nocivas: sin noticias de deck
   desde que desaparecio, y ahi se estaba jugando. No la juzgo hasta que vuelva
   a exportar.
```

Cuando la maquina sincroniza otra vez, el caso se cierra solo y bien: con su
lista de cancelaciones al dia, lo que cancelaste se calla y lo que se vendio se
anuncia, con la hora en la que desaparecio de verdad.

**Coste: una venta de verdad ocurrida justo despues de jugar no se anuncia hasta
que vuelvas a entrar en esa maquina.** En aquella tanda le paso a las dos ventas
buenas de Nbarbar (02:23, una hora y media despues de la ultima senal de la
Deck), que habrian esperado. La de Obarfel (08:23, casi ocho horas despues)
salio en su hora, porque a esas alturas ya no habia nadie jugando.

Es el cambio que hace que los avisos de venta no mientan nunca: **si no estabas
jugando no pudiste cancelarla, y si estabas jugando no se decide sin ti**. El
margen esta en `MARGEN_DE_SESION`, en `wowalerts/ventas.py`; bajarlo da avisos
mas rapidos y sube el riesgo de volver a colar una cancelacion como venta.

### El volcado viejo del addon no manda sobre Blizzard

Si una maquina lleva sin exportar mas horas de las que dura un listado, lo que
diga su volcado ya no vale: sus ids pueden llevar horas muertos. Eso es lo que
el 2026-09-02 invento dos ventas de Dbardan, con la Steam Deck 16 h sin
exportar.

Pero soltar **todo** lo de esa maquina era pasarse, y costaba ventas de verdad:
el 2026-09-06 se perdio un Yelmo mistico de Ebardan de 190.000 g, vendido y
jamas anunciado, porque su volcado tenia 16 h y media.

La antiguedad del addon no hace menos real una subasta que Blizzard sigue
listando, y su fecha de caducidad se mantiene con el `time_left` que manda
Blizzard, sin depender del addon para nada. Asi que se salva lo que Blizzard
avala:

- **La que sigue viva** en el volcado de Blizzard.
- **La que estaba viva en la pasada anterior y ahora falta.** Esa desaparicion
  es justo la prueba que hace falta para juzgarla; soltarla seria tirarla cuando
  acaba de llegar.
- **La que ya esta a medio juzgar**, esperando su segunda pasada.

Se suelta lo que solo sostiene el addon: ids que el sigue cantando y Blizzard no
tiene desde hace mas de una pasada. Esos son los zombis.

Todo lo que se tapa queda escrito en el log de la pasada:

```
↩️  Dbardan de Zapatillas del culto siseante: la cancelaste tu, asi que no
    la cuento como venta.
```

**Cuidado al tocar el codificador JSON del addon.** WoW formatea `%d` como
entero de **32 bits**, cuyo tope son 2.147.483.647. Una subasta de 249.999 de
oro son 2.499.990.000 de cobre, y con `%d` eso lanzaba `integer overflow`, que
tumbaba el codificador entero: el volcado se quedaba con los datos del dia
anterior **para todos los personajes de esa cuenta**, sin decir nada. Costo un
dia de vigilancia de treinta personajes y una venta de 142.507 g.

Se usa `%.0f`, que imprime el entero completo sin desbordar. Y ojo: **los tests
no pueden reproducirlo**, porque `lupa` es Lua 5.5 con enteros de 64 bits y ahi
`%d` traga cualquier cosa. Por eso hay un test que mira el codigo fuente y
comprueba que no aparece `string.format("%d"`.

**El addon guarda dos cosas y solo se lee una.** Tiene su tabla de personajes y
una copia en JSON; el sincronizador solo lee la copia. El 2026-09-01 esa copia
se quedo con los datos del dia anterior mientras la tabla iba al dia, y treinta
personajes se pasaron un dia entero sin vigilarse sin que nada lo cantara.

Desde la v1.11 el addon **rehace la copia al salir** (`PLAYER_LOGOUT`), que es el
ultimo momento antes de que WoW escriba a disco y no necesita la Casa de
Subastas abierta. Y `sync_subastas.py` compara las dos fechas en cada pasada:

```
⚠️  El volcado de 403840080#3 se ha quedado atras: su tabla es de 01/09 17:46 y
    lo exportado de 31/08 16:28. Entra con esa cuenta y sal al selector de
    personajes para que se ponga al dia.
```

**Ojo con los personajes que llevas tiempo sin visitar.** El vigilante compara
contra los ids de subasta que le dio el addon. Si esos ids ya no existen porque
las reposteaste, no hay nada que comparar y **ese personaje deja de vigilarse en
silencio**. Por eso el panel avisa:

```
⚠️ Datos caducados en 10 personaje(s): Adanlin, Adannor, Bbarmar...
Ninguna de sus subastas conocidas sigue viva, asi que no puedo vigilarlos.
Entra con ellos, abre la Casa de Subastas y haz /reload.
```

Pasa sobre todo por cuenta: si juegas una tarde entera en WoW 2, los personajes
de WoW 3 se quedan con los datos del ultimo dia que entraste.

**Un volcado viejo se ignora entero.** Cada subasta viaja con la hora a la que
el addon la exporto, y si esa hora tiene mas de `listing_hours`, se suelta del
seguimiento **sin veredicto**. La cota no es arbitraria: si tus listados duran
12 horas, un volcado de hace 13 no puede estar describiendo nada vivo.

```
⚠️ Ignoro 4 subasta(s) de 2 personaje(s) cuyo volcado lleva mas de 12 h sin
   actualizarse (Dbardan, Mbarval). Entra con ellos y sal al selector.
```

Callarse ahi pierde como mucho el aviso de una venta real; no callarse **se
inventa ventas que no han ocurrido**, que es peor. Costo dos ventas falsas el
2026-09-02: la Steam Deck llevaba 16 horas sin exportar --el addon v1.9 se
quedaba colgado al formatear una subasta grande-- y seguia afirmando los ids del
dia anterior, que se habian relistado con ids nuevos.

Los volcados escritos antes de que esto existiera no llevan esa hora y se dan
por buenos: estrenar la comprobacion tirando de golpe todo lo que hay seria peor
que el problema que arregla.

Ademas del panel y del log, **se avisa por Discord la primera vez que un
personaje entra en esa lista**, en el canal de undercuts. Solo la primera:
repetirlo cada hora seria una alarma de las que se aprenden a ignorar. Costo una
venta real de 142.507 g el 2026-09-01, que no se aviso porque el personaje
llevaba un dia sin exportar y el aviso estaba enterrado en un panel que nadie
mira.

**Ojo con varias cuentas de WoW.** `/reload` recarga **solo la sesion en la que
lo haces**. Si tienes WoW 1, WoW 2 y WoW 3, recargar en una deja a las otras
corriendo el addon viejo, que no apunta nada: sus reposteos siguen saliendo como
ventas y no hay forma de notarlo mirando el aviso. Paso el 2026-08-31 con
Adanlin, de WoW 3, mientras las 19 cancelaciones registradas eran todas de
WoW 2.

Por eso `sync_subastas.py` lo canta en cada pasada:

```
⚠️  Estas cuentas de WoW siguen con el addon viejo y no apuntan tus
    cancelaciones: 403840080#1, 403840080#3. Entra con cada una y haz /reload,
    o sus reposteos saldran como ventas.
```

Lo detecta por la clave `canceladas` del volcado, que el addon nuevo escribe
siempre, tenga o no cancelaciones dentro.

**Lo que sigue sin cubrirse:** que canceles y no vuelvas a entrar al juego a
hacer `/reload` antes de la pasada siguiente. Ahi la cancelacion no llega a
tiempo y sale como venta.

### 6.4 Canal propio

Crea un webhook en el canal que quieras y ponlo en `.env`:

```
DISCORD_VENTAS_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Si lo dejas vacio, las ventas van al canal general. Para comprobarlo:

```bash
.venv\Scripts\python.exe main.py --ventas --test-discord
```

En GitHub Actions hace falta el mismo valor como secret del repositorio, con ese
mismo nombre.

### 6.5 Probarlo

```bash
.venv\Scripts\python.exe main.py --ventas --dry-run
```

La **primera pasada nunca detecta ventas**, y es lo correcto: solo puede
declarar vendida una subasta que haya visto viva antes. Sin esa regla, el primer
arranque cantaria como vendidas todas las que el addon tiene apuntadas y hace
dias que no existen.

Para hacer las dos vigilancias con una sola descarga, que es como corre en
Actions:

```bash
.venv\Scripts\python.exe main.py --undercut --ventas
```

### 6.6 Horas en las que no suena nada

En `config.yaml`:

```yaml
settings:
  silencio_desde: 1
  silencio_hasta: 9
  zona_horaria: "Europe/Madrid"
```

De 01:00 a 09:00 en tu hora local no llega nada a Discord. La hora de inicio
entra y la de fin no: a las 09:00 ya suena. Poniendolas iguales no se silencia
nada.

**La zona horaria importa.** Las pasadas corren en GitHub Actions, con el reloj
en UTC. Sin ella la ventana se desplazaria sola en cada cambio de hora, y en
invierno te callaria de 00:00 a 08:00.

**Se calla el envio, no la deteccion.** Las pasadas siguen corriendo cada hora y
el estado sigue actualizandose. Eso no es un detalle: el seguimiento de ventas
se apoya en ver tus subastas hora tras hora, y saltarse ocho pasadas seguidas
degradaria las fechas de caducidad y se tragaria ventas de verdad.

**Y lo que se calla no se pierde:**

- Los **chollos** y los **undercuts** no se marcan como avisados mientras dura
  el silencio, asi que a las 09:00 se envia lo que siga vivo. No te llega la
  lista entera de la noche --lo que se compro o se arreglo mientras dormias no
  te sirve de nada--, solo lo que sigue estando.
- Las **ventas** se quedan pendientes y se deciden al despertar, pero **con la
  hora en que la subasta desaparecio de verdad**, no con la de esa pasada. Si
  no, ocho horas de espera las empujarian mas alla de su fecha de caducidad y se
  perderian.

### 6.7 Las cifras

Van **en neto**: el precio al que estaba puesta menos la comision que se queda
la casa de subastas, que es lo que de verdad te llega al buzon. El porcentaje se
ajusta en `config.yaml` con `ah_cut_pct`.

El aviso lleva el **ilvl** entre parentesis. Con el mismo objeto puesto a 292,
295, 298 y 305 a la vez, sin eso no se sabe cual se ha ido, y al mirar la casa
de subastas ves otro del mismo nombre y crees que no se ha vendido nada.
Los patrones y lo que no escala van sin el: el juego les da ilvl 1, que no dice
nada.

### 6.8 El panel de ventas por reino

En el canal de ventas hay un mensaje fijado que ordena los reinos por numero de
ventas. Un aviso suelto dice que has vendido algo; el panel dice **donde**
vendes, que es lo que decide adonde merece la pena volver a llevar genero. A
igualdad de ventas manda el oro: vender tres cosas de 100.000 no es lo mismo que
tres de 500.

Las cifras **no salen del vigilante**, salen del addon
[Journalator](https://www.curseforge.com/wow/addons/journalator). El vigilante
solo ve una subasta desaparecer y tiene que deducir por cuanto se fue; Journalator
apunta la factura exacta que te llega al buzon, y ademas lleva meses de historial
de antes de que existiera este panel.

Como funciona:

1. Journalator guarda su historial comprimido dentro de `SavedVariables`
   (LibSerialize + LibDeflate + una codificacion a 6 bits).
2. `sync_subastas.py` lo descomprime en cada maquina y escribe un resumen por
   reino y objeto en `mis_ventas/<maquina>.json`. Al repositorio no van las
   facturas una a una: ni tus personajes ni quien te compro cada cosa.
3. `main.py` se queda solo con los objetos que vigilas y dibuja el panel.

**Solo cuentan los objetos de `config.yaml`**, mascotas incluidas: en la casa
de subastas todas son el mismo objeto "jaula", pero en el correo llegan con su
propio nombre, asi que se piden aparte por `pet_species_id`.

**Solo cuentan los objetos de `config.yaml`.** El resumen guarda todo lo que
vendes, asi que si mañana añades un objeto nuevo el panel ya tiene su historial;
pero lo que se enseña es solo el negocio que vigilas, no el material de
artesania.

Dos cosas que conviene saber:

- **El panel va por detras de los avisos.** Journalator apunta la venta cuando
  abres el correo, y el fichero no se escribe hasta que sales al selector de
  personajes. Los avisos siguen llegando al minuto; el panel se pone al dia en
  la siguiente sincronizacion.
- **El PC y la Deck se suman sin repetir.** Una factura se lee del buzon una
  sola vez, en la maquina donde estabas jugando, asi que las dos nunca ven la
  misma venta.

Si no usas Journalator, el panel se queda vacio y el resto sigue igual.


---

## 7. La app del movil

Los avisos te dicen lo que ha cambiado. La app contesta la pregunta que te haces
con el chollo ya comprado en la bolsa: **a que personaje le falta esto, y a
cuanto tendria que ponerlo ahi**.

Eliges el objeto y, si escala, el ilvl exacto que llevas encima. Debajo salen los
personajes de `orden_personajes` que **no** lo tienen puesto, cada uno con su
reino, su cuenta y el precio mas barato que hay de ese producto en su casa de
subastas. Cuando pone **"nadie lo vende ahi"** es que ese reino esta limpio, que
es justo donde interesa entrar.

Pero que falte no basta para decidir. Cuando de tu ilvl **si** hay algo puesto y
al lado hay **uno mejor mas barato**, ninguno de los dos se vende: el comprador
se lleva el 298 de 35.000 antes que el 295 de 44.999, asi que meter otro 295 ahi
es tirar el hueco. Eso sale cantado en rojo --**"te pisa el 298 a 35.000 g"**--
sin tener que abrir nada.

Con tu ilvl vacio no se avisa: no hay nada que comparar, el precio lo pones tu, y
el aviso saldria en casi todos los personajes hasta dejar de leerse.

Al tocar un personaje se despliega la **escalera entera de ilvl de su reino**:
los nueve que vigilas, con lo que hay a la venta en cada uno y cuantos. Los
vacios salen con un guion, porque que un ilvl este vacio es justo la informacion
que buscas y por ausencia no se ve.

### 7.1 De donde saca los datos

Lee tres cosas del repositorio privado (apartado 3.0), con un token tuyo:

- `mis_subastas/*.json` y `mis_personajes/*.json`, de la rama **`subastas`**.
  Es lo que sube `sync_subastas.py` desde cada maquina.
- `catalogo.json` y `precios.json`, de la rama **`datos`**, que publica el
  workflow en cada pasada.

Esos dos ultimos los genera `datos_app.py`:

```bash
.venv\Scripts\python.exe datos_app.py
```

El **catalogo** lleva que objetos vigilas, como se llaman en espanol, su icono y
tu tabla de topes por ilvl. Se genera aqui y no en el movil porque el nombre
traducido y el icono salen de la API de Blizzard, y esas credenciales no deben
viajar dentro de una app.

Los **precios** son el minimo de cada objeto e ilvl en los veinte y pico reinos
donde vendes. Es el dato que no sobrevive a la pasada: el volcado de un reino son
decenas de miles de subastas que se miran y se tiran.

Van a una rama aparte del repositorio privado: dicen en que reinos vendes. Cada reino lleva su marca de cuando se vio, que es lo que permite
distinguir en el movil entre "ahi no lo vende nadie" y "ese reino no se ha
podido mirar esta hora": sin esa marca las dos cosas se verian igual.

### 7.2 Compilar e instalar

Necesitas el SDK de Android y un JDK 17 o mas nuevo. Desde `android/`:

```bash
.\gradlew.bat assembleDebug
```

Y para meterla en el movil, con la depuracion USB aceptada:

```bash
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

En moviles Xiaomi, `gradlew installDebug` falla con
`INSTALL_FAILED_USER_RESTRICTED` salvo que actives "Instalacion via USB" en las
opciones de desarrollador. `adb install` funciona igual sin tocar nada.

La primera vez la app arranca con unas subastas de ejemplo empotradas en el APK
y lo dice en rojo, con la fecha, para que no te confies. En el engranaje se pega
un token de GitHub *fine-grained* sobre los dos repositorios, este y el privado,
y a partir de ahi se actualiza sola y guarda lo ultimo descargado para funcionar
sin cobertura.

El token necesita dos permisos:

| Permiso | Repositorio | Para que |
|---|---|---|
| `Contents: Read-only` | El privado | Leer tus subastas, el catalogo y los precios |
| `Issues: Read and write` | Este | Cambiar topes (ver 7.5) y anadir objetos (ver 7.6) desde la app |

Con solo el primero la app funciona entera salvo cambiar topes y anadir
objetos, que ni siquiera se ofrecen: el tope sale como texto y no como boton, y
el `+` no aparece.

### 7.3 Se abre limpia, y siempre con datos de ahora

**Cada vez que la abres se descarga todo otra vez.** No hay que darle a la flecha
ni acordarse de hacerlo: entras y ya esta bajando, con la ruedecita arriba. Si
sale bien no dice nada, porque un aviso cada vez que entras se acaba ignorando;
si falla si te lo dice, que es cuando importa: significa que lo que tienes
delante no es de ahora.

**Y no se queda en segundo plano.** En cuanto sales --HOME, cambiar de app,
bloquear el movil-- la app se cierra del todo, y tampoco aparece en recientes.
Volver a entrar es siempre empezar por la lista.

Suena agresivo, pero es lo unico que vale aqui. Los precios caducan en una hora.
Si la app sobreviviera en segundo plano, un dia dejarias el movil sobre la mesa
mirando un personaje, volverias por la tarde y leerias **"nadie lo vende ahi"**
sobre un volcado de hace seis horas. Ese cartel es justo el que te hace postear,
y equivocado te cuesta el hueco. Muriendo al salir, no existe una pantalla vieja
que puedas confundir con una recien bajada.

Girar el movil no cuenta como salir: eso no invalida ningun dato, asi que no hay
que volver a bajarlo todo ni perder el objeto que tenias abierto.

### 7.4 Lo que todavia no hace

Las **mascotas** no salen. El addon solo exporta `itemID`, y en las subastas
todas las mascotas son el objeto 82800: sin `battlePetSpeciesID` es imposible
saber cual de las tuyas tiene puesta cada personaje.

Las **monturas** tampoco, pero eso es a proposito: no las repartes entre
personajes, se venden donde caen.

### 7.5 Cambiar un tope sin abrir `config.yaml`

Los topes viven en `config.yaml` y nada mas los define. Pero el momento en que
te das cuenta de que uno esta alto es cuando lo estas mirando: en la app, con el
tope y el precio real del mercado uno al lado del otro. Ese es el sitio para
cambiarlo, no un fichero en el PC.

**Tocas el `tope` de un ilvl, escribes el numero, y ya.**

Lo que pasa detras es que la app **no escribe `config.yaml`**: abre una issue, y
el workflow `.github/workflows/tope.yml` es quien edita el fichero y lo
commitea. Es a proposito, y por dos razones:

- El token del movil **no necesita permiso de escritura sobre el contenido**.
  Le basta `Issues: Read and write`. Uno filtrado no puede tocar un solo fichero
  del repositorio: lo peor que hace es abrirte issues.
- La edicion del YAML la hace **Python, con tests**, en vez de Kotlin a ciegas
  en un movil. Y es una edicion delicada: ver mas abajo.

El tope nuevo entra en vigor **en la pasada siguiente**, como mucho una hora.
Mientras tanto la app ensena `tope 4.000 (pendiente)`, porque el catalogo que
tiene descargado sigue trayendo el viejo. Ese aviso se guarda en disco y no en
memoria: la app se muere al salir (7.3), y en memoria moriria con ella y
volverias a ver el numero viejo justo despues de haberlo cambiado.

#### Los otros dos caminos

El mismo workflow atiende dos formularios de GitHub, que existen porque la app
no siempre esta a mano:

- **Issues -> New -> "Ajustar un tope"**: desplegables con tus objetos y tus
  ilvl. El camino desde el PC.
- **El enlace "Ajustar tope" de cada aviso de Discord**: abre un formulario con
  el objeto y el ilvl **ya rellenos**, y solo tecleas el numero.

Son dos plantillas y no una porque GitHub solo sabe prerrellenar por URL los
campos de texto, nunca un desplegable. El de desplegables es comodo a mano; el
de texto es el unico que puede venir relleno desde un aviso.

Los tres caminos generan exactamente el mismo cuerpo de issue, asi que al otro
lado hay un solo parser.

#### Que hace falta la primera vez

**Crea la etiqueta `tope`** en el repositorio (Issues -> Labels -> New label).
GitHub **no aplica una etiqueta de plantilla que no exista ya**, asi que sin
crearla las issues saldrian sin ella. Por eso el workflow mira tambien el
prefijo `Tope:` del titulo y sigue disparandose igual, pero con la etiqueta
creada las tienes todas juntas y filtrables.

#### Por que no se rompe `config.yaml`

`wowalerts/topes.py` **no pasa por PyYAML**. Un round-trip de carga y volcado
devolveria un YAML equivalente pero reformateado y sin un solo comentario, y los
comentarios de este fichero son la mitad de su valor. Asi que se edita el texto:
se localiza el bloque del objeto, se sustituye ese numero, y el resto queda byte
a byte identico. El diff de un cambio es **una linea**.

Editar YAML con expresiones regulares da miedo, con razon. La red esta en
`aplicar_tope.py`, que despues de editar comprueba tres cosas antes de dejar que
se commitee nada:

1. El resultado carga con `load_config()`.
2. El tope pedido ha quedado en el valor pedido.
3. **Ningun otro tope se ha movido.**

Si algo falla, no escribe, no commitea, y te lo comenta en la issue, que **se
queda abierta** para que puedas corregir. `config.yaml` no se queda a medias
nunca.

#### Lo que no hace

- **Un tope por issue.** Cambiar varios de golpe sigue siendo trabajo de
  `config.yaml`.
- **No anade objetos ni escalones nuevos.** Solo mueve el numero de un ilvl que
  ya esta en tu tabla. En la app, los ilvl que no vigilas salen sin boton.
- **No es instantaneo**, y no tiene por que serlo: la casa de subastas se
  regenera una vez por hora de todas formas.

#### Cuando anadas o quites objetos

El desplegable del formulario tiene las opciones escritas dentro, asi que hay
que regenerarlo:

```bash
.venv\Scripts\python.exe topes_form.py
```

No hace falta acordarse: `tests/test_topes_form.py` falla mientras la plantilla
no cuadre con `config.yaml`.

---

### 7.6 Anadir un objeto sin abrir `config.yaml`

El vigilante no avisa de nada que no este en `items:`. Y eso se nota justo
cuando peor viene: con un parche nuevo salen piezas y recetas que interesan
desde el primer dia, y hasta ahora anadirlas era trabajo de PC.

**Boton `+` de la app, pegas el enlace de Wowhead del objeto, y ya.** El boton
solo sale con el token puesto (ver 7.2) y solo en el listado: dentro de un
objeto no viene a cuento.

Detras pasa lo mismo que con los topes: la app **no escribe `config.yaml`**,
abre una issue y el workflow `.github/workflows/objeto.yml` es quien edita el
fichero y lo commitea. El token del movil no necesita nada nuevo.

El objeto **empieza a vigilarse en la pasada siguiente**, como mucho una hora, y
a partir de ahi sale en la app con sus precios. Aqui no hay "pendiente" como en
los topes: un objeto que todavia no esta no sale en la lista, y ensenarlo a
medias enganaria mas que la ausencia.

#### Que se escribe en el campo del objeto

| Lo que escribes | Como se resuelve |
|---|---|
| `https://www.wowhead.com/es/item=258126/...` | por el `item=` del enlace |
| `258126` | tal cual |
| `Pattern: Arcanoweave Cord` | por busqueda, con el nombre exacto en ingles |

Para algo recien salido, el enlace es el camino bueno: no depende de escribir
bien un nombre en ingles ni se confunde entre dos objetos que se llamen igual.
El nombre que acaba en `config.yaml` lo dice Blizzard, asi que queda escrito
como en el juego. Un nombre con comillas dobles o una barra invertida se
rechaza: `wowalerts/objetos.py` no podria volver a encontrarlo despues para
cambiarle el tope, asi que ese se anade a mano.

El id lo resuelve el workflow y no el movil porque las credenciales de Blizzard
viven en los secretos de Actions: llevarlas dentro de la app seria repartirlas.

#### Los dos tipos

- **Equipo**: lleva tabla por ilvl, y la escribe quien anade la pieza --ya no
  se copian los topes de otra--. La pieza nueva se escribe detras de la
  ultima pieza de equipo.
- **Patron o receta**: lleva un precio unico, y sale con las dos banderas que
  llevan tus recetas --sin avisos de undercut, pero reposteable con la tecla del
  addon--, detras del ultimo objeto reposteable.

Las **mascotas y las monturas** se siguen anadiendo a mano: las mascotas van por
`pet_species_id` y las monturas son trampas para el error de otro, que se ponen
muy de vez en cuando.

#### Como se escribe la tabla de ilvl

En la app son filas de ilvl y precio, con "+ ilvl" para sumar una fila y la X
para quitarla; los campos solo admiten digitos, y "Enviar" no se activa hasta
que la tabla es valida. En el formulario va un escalon por linea, como
`368: 20000` (vale tambien `=`, separadores de miles y una `g` detras; una
vineta delante no estorba y las lineas en blanco no cuentan), pero un decimal
como `20.5` se rechaza. El ilvl va de 1 a 2000 y no puede repetirse --por
encima seguramente el ilvl y el precio estan al reves--. Los ilvl son los que
quieras, los de la temporada recien salida.

#### Que hace falta la primera vez

**Crea la etiqueta `objeto`** en el repositorio (Issues -> Labels -> New label),
por lo mismo que la de `tope`: GitHub no aplica una etiqueta que no exista. El
workflow mira tambien el prefijo `Objeto:` del titulo, asi que funciona igual sin
ella, pero con la etiqueta las tienes juntas.

#### Por que no se rompe `config.yaml`

`wowalerts/objetos.py` edita el texto, sin pasar por PyYAML, por la misma razon
que `wowalerts/topes.py`: un round-trip perderia todos los comentarios. Y la red
de seguridad esta en `anadir_objeto.py`, que antes de dejar commitear comprueba:

1. El resultado carga con `load_config()`.
2. El objeto nuevo ha quedado con el id y, exactamente, la tabla o el precio
   pedidos.
3. **No ha aparecido ni desaparecido ningun otro objeto**: solo se suma el
   nuevo.
4. **Ningun objeto anterior ha cambiado.**

Si algo falla, no escribe, no commitea, y te lo comenta en la issue --el
comentario dice por que--, que se queda abierta para que corrijas y abras otra.
Si el objeto era valido pero ha fallado algo despues --regenerar los ficheros o
subir el commit--, el comentario empieza con "No se ha guardado nada": cierra la
issue y reabrela para reintentar. Y si una issue se queda **sin comentario
ninguno**, tambien: puede ser que `pip install` fallara, o que GitHub solo deje
una ejecucion pendiente por grupo de concurrencia --el mismo que el workflow de
topes--, y la tuya se haya quedado fuera.

Ademas, el workflow **regenera los dos ficheros que dependen de `config.yaml`**
--el desplegable de topes, que gana los escalones de la pieza nueva, y
`Vigilados.lua`--, que es justo lo que se olvida al anadir un objeto a mano.
Para `Vigilados.lua` reutiliza la cache de ids que deja la pasada de cada hora
--solo la lee, no la guarda--, asi no depende de buscar en Blizzard cada
objeto vigilado.

#### Lo que no hace

- **Un objeto por issue.**
- **No anade un escalon a una pieza que ya vigilas.** Eso sigue siendo a mano
  en `config.yaml`: esto solo arranca objetos nuevos, con su tabla completa.
- **No arregla los bonus ids de una temporada nueva.** Los ilvl nuevos los
  pones tu en la tabla, pero si el parche trae bonus ids que no estan en
  `bonus_ilvl_map`, las subastas pueden salir con "ilvl sin confirmar" o no
  casar con la tabla, sin dar error. Eso se arregla en `config.yaml`: ver la
  seccion 2.

### 7.7 Pausar los avisos

La **campana** de arriba, en el listado, para y vuelve a encender todo lo que
llega a Discord: chollos, undercuts, ventas y avisos del propio vigilante. Pide
confirmacion y, mientras estan pausados, la campana sale tachada en rojo y hay
una franja arriba que lo recuerda: pausarlos y olvidarlo es el fallo facil.

Funciona como la ventana de silencio de la seccion 6.6, pero sin hora de fin:
**se calla el envio, no la deteccion**. Las pasadas siguen corriendo cada hora y
lo callado no se pierde; al reanudar te llega lo que siga vigente.

Por dentro va igual que los topes: la app abre una issue `Avisos: pausar` o
`Avisos: reanudar`, el workflow `avisos.yml` cambia una sola linea de
`config.yaml`,

```yaml
settings:
  avisos_pausados: true
```

y lo comenta en la issue. El token no necesita nada nuevo: con `Issues: Read and
write` basta. Hay tambien una plantilla, *Pausar o reanudar avisos*, para
hacerlo desde la web de GitHub.

Tarda **un minuto** en aplicarse (lo que tarda el workflow) y entra en vigor en
la pasada siguiente. Hasta que la app ve el cambio en `config.yaml` lo ensena
como pendiente; si a la media hora no lo ve, algo ha fallado y vuelve a ensenar
lo que dice `config.yaml`: mira la issue, que se queda abierta con el motivo.

---

## 8. La web publica de precios

Ademas del vigilante privado, el repositorio incluye una web publica de solo
lectura con los precios de la region: portada, buscador, indice de
categorias, pagina de producto, pagina de reino, `robots.txt` y
`sitemap.xml`. Vive en `web/` (FastAPI + Jinja2, base SQLite propia,
`web.db`) y no comparte nada con el vigilante salvo el codigo de
`wowalerts/` que habla con la API de Blizzard.

La portada lleva cuanto cubre el sitio, de cuando son los datos y las doce
rebajas mas grandes de toda la region. Esa ultima consulta
(`mejores_rebajas`) es la mas cara de la app —271 ms sobre 932.000 filas de
`precio`, contra los ~23 ms de la pagina de reino— porque no hay un
`reino_id` que recorte el escaneo. Por eso `web/app.py` la cachea contra
`volcado.generado_en`: ese numero solo cambia cuando la pasada horaria
escribe precios nuevos, asi que mientras sea el mismo el resultado tambien
lo es. La primera visita de cada hora paga 310 ms y las demas 6 ms.

**Con pocos reinos la portada sale sin rebajas, y es correcto.** Hace falta
que un objeto este en al menos 15 reinos (`REINOS_PARA_COMPARAR`) para que
su mediana signifique algo, asi que un `web.db` hecho con
`--realms 1305,1329` para probar nunca va a llenar esa tabla. La pasada de
produccion no lleva `--realms` y baja los 92 reinos de la region.

La llena `publicar_web.py`, que se ejecuta aparte de `main.py` a proposito
—no conviene tocar el vigilante para esto— y hace una pasada por toda la
region una vez por hora:

```bash
.venv\Scripts\python.exe publicar_web.py --db web.db
```

De cada objeto nuevo se guardan el nombre en ocho idiomas y el icono, que es
lo que las tres paginas ensenan al lado del nombre: una tabla de cien objetos
de WoW sin sus iconos no se lee, porque los nombres son largos y se parecen
entre si ("Uncanny Combatant's Satin Belt", "Uncanny Combatant's Satin
Pants").

El icono se pide con una peticion aparte por objeto, asi que solo se hace una
vez por producto. Los que ya estaban guardados de antes (18.675 la primera
vez, cuando el icono se dejaba siempre a None) se rellenan a plazos:
`--iconos N` dice cuantos atrasados coger en cada pasada, 3.000 por defecto.
Para hacerlo todo de una sentada, sin bajar subastas ni tocar los precios:

```bash
.venv\Scripts\python.exe publicar_web.py --db web.db --solo-iconos --iconos 20000
```

Va a ~60 objetos por segundo, o sea unos cinco minutos para el catalogo
entero.

### El catalogo navegable: `/items`

Las categorias de la casa de subastas (Weapon, Armor, Recipe, Consumable...)
con sus subcategorias, paginadas, mas un buscador por nombre en la cabecera de
todas las paginas.

Existen por dos motivos a la vez. El primero es el evidente: son los filtros
que se piden para poder mirar el mercado por tipo de objeto. El segundo es el
que de verdad importa, y se midio: de las **19.365 fichas, solo 4.598 estaban
enlazadas** desde alguna pagina de reino (el top 100 de cada uno, con mucho
solape). Las otras **14.767 no tenian ni un enlace** que llevara a ellas, y
tampoco entraban en el sitemap, que solo lista lo que ya se ha pedido. O sea:
tres de cada cuatro paginas no se podian descubrir, ni por Google ni por
nadie. Las paginas de categoria son de donde cuelgan ahora todas.

Los atributos (`clase`, `subclase`, `calidad`, `hueco`, niveles) salen de la
MISMA respuesta de `/data/wow/item/{id}` de la que ya se sacaba el nombre, y
que se estaba tirando entera. Para un objeto nuevo no cuesta ni una peticion
mas. Los que ya estaban guardados se rellenan igual que los iconos:

```bash
.venv\Scripts\python.exe publicar_web.py --db web.db --solo-atributos --atributos 25000
```

**Las listas de categoria NO dicen en que reino esta lo barato**, solo desde
cuanto sale. Es deliberado: el reino mas barato es lo que vende el plan Pro, y
una tabla de cien filas con su reino al lado lo regalaria en bloque.

**No todo lo que esta rebajado es una ganga.** La portada y las paginas de
reino descartan dos clases de basura que salian a la vista con los 92 reinos:
las medianas clavadas en 9.999.999 de oro, que es el maximo que deja teclear
la casa de subastas y no un precio (`TOPE_CDS`), y los descuentos por encima
del 95%, que en la region entera siempre son una mediana rota y no una oferta
(`DESCUENTO_MAXIMO`). Sin eso la portada salia entera a "100% off, normally
9,999,999g".

Para desplegarla en un servidor de verdad, con systemd y nginx, esta todo en
[`despliegue/README.md`](despliegue/README.md).
