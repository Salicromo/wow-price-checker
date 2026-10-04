"""Deja el paquete wowalerts importable desde los tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

# Los webhooks de verdad estan en .env, y main.py lo carga al arrancar. Sin
# esto, cualquier test que llegue a un canal que no haya pinchado a mano
# apuntaria al Discord real: lo unico que lo evita es que requests_mock corte la
# peticion, y eso es demasiado fino para dejarlo al azar.
FALSOS = {
    "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc",
    "DISCORD_UNDERCUT_WEBHOOK_URL": "https://discord.com/api/webhooks/2/undercut",
    "DISCORD_VENTAS_WEBHOOK_URL": "https://discord.com/api/webhooks/3/ventas",
}


@pytest.fixture(autouse=True)
def sin_webhooks_de_verdad(monkeypatch):
    # load_dotenv no pisa lo que ya existe, asi que dejarlos puestos aqui basta
    # para que .env no se cuele.
    for nombre, valor in FALSOS.items():
        monkeypatch.setenv(nombre, valor)
