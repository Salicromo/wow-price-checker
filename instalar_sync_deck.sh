#!/usr/bin/env bash
# Instala en la Steam Deck la sincronizacion de subastas.
#
# Usa unidades de systemd de usuario, que son el equivalente a la tarea
# programada de Windows y no necesitan permisos de administrador ni tocar el
# sistema de solo lectura de SteamOS. Todo esto funciona en modo juego: no hace
# falta entrar al escritorio.
#
# Se instalan tres cosas, porque una sola no cubre como se usa la Deck de
# verdad: entras, posteas, sales del juego y la apagas.
#
#   .path   dispara en cuanto WoW escribe sus datos, que es al salir del juego.
#           Es la importante: el addon solo vuelca al salir, y si esperaramos al
#           temporizador lo normal seria apagar la Deck antes de que subiera.
#           Entonces la venta de esa noche no se detecta nunca, porque al
#           siguiente encendido la subasta ya ha caducado.
#   .timer  cada 15 minutos, como red de seguridad mientras juegas.
#   apagado corre una ultima vez al cerrar la sesion, por si apagas tan rapido
#           que el .path no llega a terminar de subir.
#
# Para quitarlo:
#   systemctl --user disable --now wow-subastas-sync.timer
#   systemctl --user disable --now wow-subastas-sync.path
#   systemctl --user disable --now wow-subastas-apagado.service
set -euo pipefail

proyecto="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unidades="$HOME/.config/systemd/user"

if [ ! -f "$proyecto/sync_subastas.py" ]; then
    echo "No encuentro sync_subastas.py en $proyecto" >&2
    exit 1
fi

python="$(command -v python3 || true)"
if [ -z "$python" ]; then
    echo "No encuentro python3. Instalalo antes de seguir." >&2
    exit 1
fi

mkdir -p "$unidades"

cat > "$unidades/wow-subastas-sync.service" <<UNIDAD
[Unit]
Description=Sube a GitHub las subastas que exporta el addon WowAlertsExport
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$proyecto
ExecStart=$python $proyecto/sync_subastas.py --maquina deck
UNIDAD

cat > "$unidades/wow-subastas-sync.timer" <<UNIDAD
[Unit]
Description=Sincroniza las subastas de WoW cada 15 minutos

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
# Recupera la pasada perdida si la Deck estaba suspendida a su hora.
Persistent=true

[Install]
WantedBy=timers.target
UNIDAD

# --- Disparo en cuanto el addon escribe -----------------------------------
#
#  WoW guarda los SavedVariables de todos los addons de golpe al salir, asi que
#  vigilar esa carpeta es vigilar "acabas de salir del juego". Se vigila la
#  carpeta y no el fichero suelto porque WoW escribe creando y renombrando, y un
#  inotify sobre el fichero se quedaria mirando un inodo que ya no existe.
guardados="$("$python" -c "
import sys
sys.path.insert(0, '$proyecto')
from sync_subastas import detectar_wow_root
raiz = detectar_wow_root()
if raiz:
    for d in sorted((raiz / 'WTF' / 'Account').glob('*/SavedVariables')):
        print(d)
")"

if [ -z "$guardados" ]; then
    echo "Aviso: no encuentro carpetas SavedVariables de WoW." >&2
    echo "Se instala solo el temporizador; entra al juego una vez y vuelve a" >&2
    echo "ejecutar esto para que sincronice tambien al salir." >&2
else
    {
        echo "[Unit]"
        echo "Description=Sincroniza en cuanto WoW guarda los datos del addon"
        echo
        echo "[Path]"
        while IFS= read -r carpeta; do
            [ -n "$carpeta" ] && echo "PathChanged=$carpeta"
        done <<< "$guardados"
        echo "Unit=wow-subastas-sync.service"
        echo
        echo "[Install]"
        echo "WantedBy=paths.target"
    } > "$unidades/wow-subastas-sync.path"
fi

# --- Ultima pasada al apagar ----------------------------------------------
#
#  RemainAfterExit deja la unidad "activa" sin hacer nada, y asi systemd ejecuta
#  el ExecStop al cerrar la sesion, que es cuando apagas la Deck. Es el ultimo
#  cartucho: si apagas antes de que el .path termine de subir, esto lo recoge.
cat > "$unidades/wow-subastas-apagado.service" <<UNIDAD
[Unit]
Description=Sube las subastas pendientes al apagar la Deck
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=$python $proyecto/sync_subastas.py --maquina deck
# De sobra: subir tarda unos segundos. Pero si la red ya no responde, mejor
# rendirse que dejar la Deck colgada al apagarse.
TimeoutStopSec=45

[Install]
WantedBy=default.target
UNIDAD

systemctl --user daemon-reload
systemctl --user enable --now wow-subastas-sync.timer
systemctl --user enable --now wow-subastas-apagado.service
# Con "if" y no con "[ -f ... ] && ...": bajo set -e, un test que falla al final
# de una lista && termina el script en error, y no encontrar ese fichero es un
# caso normal (la primera vez, antes de haber entrado nunca al juego).
if [ -f "$unidades/wow-subastas-sync.path" ]; then
    systemctl --user enable --now wow-subastas-sync.path
fi

echo
echo "Timer instalado. Comprueba que funciona con:"
echo "  systemctl --user start wow-subastas-sync.service"
echo "  journalctl --user -u wow-subastas-sync.service -n 20"
echo
echo "Y cuando se ejecutara con:"
echo "  systemctl --user list-timers wow-subastas-sync.timer"
echo
echo "Lo que vigila la salida del juego:"
echo "  systemctl --user status wow-subastas-sync.path"
