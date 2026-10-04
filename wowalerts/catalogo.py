"""Que objetos son monturas y cuales son juguetes.

En las subastas no viene nada de esto: una montura es un objeto como otro
cualquiera, y un juguete tambien. Para poder filtrar por categoria hay que
traerse antes las dos listas de Blizzard y cruzarlas por id.

Sale caro --los juguetes son mas de mil peticiones, una por juguete-- y no
cambia mas que cuando sale contenido nuevo, asi que se guarda en disco y se
reutiliza. Con `--refrescar-catalogo` se vuelve a pedir.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

# Clase "Miscelanea", subclase "Montura", que es donde Blizzard mete todo lo
# que se monta, desde el caballo de banda hasta el cerdito del bazar.
CLASE_MISCELANEA = 15
SUBCLASE_MONTURA = 5


def construir(client, max_workers: int = 8) -> dict[str, list[int]]:
    """Pide a Blizzard las listas de ids de montura y de juguete."""
    monturas = client.item_ids_por_subclase(CLASE_MISCELANEA, SUBCLASE_MONTURA)
    log.info("  monturas: %s objetos", len(monturas))

    ids_juguete = client.toy_ids()
    log.info("  juguetes: %s en el indice, pidiendo su objeto...", len(ids_juguete))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        juguetes = [i for i in pool.map(client.toy_item_id, ids_juguete) if i]
    log.info("  juguetes: %s objetos", len(juguetes))

    return {"monturas": sorted(set(monturas)), "juguetes": sorted(set(juguetes))}


def cargar(client, ruta: Path, refrescar: bool = False, max_workers: int = 8):
    """El catalogo, del disco si ya estaba, y si no pidiendolo y guardandolo."""
    if ruta.exists() and not refrescar:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return {k: set(v) for k, v in datos.items()}

    log.info("Construyendo el catalogo de monturas y juguetes...")
    datos = construir(client, max_workers)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    log.info("Catalogo guardado en %s", ruta)
    return {k: set(v) for k, v in datos.items()}
