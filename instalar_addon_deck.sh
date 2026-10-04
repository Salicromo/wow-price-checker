#!/usr/bin/env bash
# Copia el addon WowAlertsExport a la carpeta de addons de WoW en la Steam Deck.
#
# No lleva la ruta de WoW escrita a mano: se la pregunta a sync_subastas.py, que
# ya la sabe buscar. Asi, si la sincronizacion funciona en esta maquina, esto
# tambien, y no hay dos listas de rutas que puedan acabar diciendo cosas
# distintas.
#
# Hay que volver a ejecutarlo cada vez que cambie el addon. Para saber que
# version tienes cargada, en el juego: /wa
set -euo pipefail

proyecto="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
origen="$proyecto/addon/WowAlertsExport"

if [ ! -f "$origen/WowAlertsExport.lua" ]; then
    echo "No encuentro el addon en $origen" >&2
    exit 1
fi

python="$(command -v python3 || true)"
if [ -z "$python" ]; then
    echo "No encuentro python3. Instalalo antes de seguir." >&2
    exit 1
fi

wow_root="$("$python" -c "
import sys
sys.path.insert(0, '$proyecto')
from sync_subastas import detectar_wow_root
ruta = detectar_wow_root()
print(ruta if ruta else '')
")"

if [ -z "$wow_root" ]; then
    echo "No encuentro la carpeta de WoW en esta maquina." >&2
    echo "Las rutas que se prueban estan en RUTAS_HABITUALES, en sync_subastas.py;" >&2
    echo "si la tuya no esta, anadela ahi y vuelve a ejecutar esto." >&2
    exit 1
fi

# Personajes.lua no esta en git: se genera aqui, desde personajes.yaml. Solo
# necesita ese fichero, no credenciales de Blizzard.
if [ -f "$proyecto/personajes.yaml" ]; then
    (cd "$proyecto" && "$python" generar_vigilados.py --solo-personajes)
else
    echo "Aviso: sin personajes.yaml, el reposteo no distinguira tus otras" >&2
    echo "cuentas de un rival. Copialo del PC a $proyecto/personajes.yaml." >&2
fi

destino="$wow_root/Interface/AddOns"
mkdir -p "$destino"
cp -rf "$origen" "$destino/"

# Con sed y no con "grep -oP": la -P no esta en todos los grep, y en SteamOS
# ademas falla si la localizacion no es UTF-8.
version="$(sed -n 's/^local ADDON_VERSION = "\(.*\)"/\1/p' "$origen/WowAlertsExport.lua")"
version="${version:-?}"

echo "Addon v$version copiado a:"
echo "  $destino/WowAlertsExport"
echo
echo "Ahora, dentro del juego, haz /reload. Para comprobarlo: /wa"
