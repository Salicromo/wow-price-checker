"""Revisa si el vigilante se esta ejecutando de verdad en GitHub Actions.

Responde a la pregunta que no contesta Discord: cuando no llega ningun aviso,
puede ser que no haya chollos... o que la pasada no se haya ejecutado. Aqui se
ven las dos cosas por separado, incluidos los huecos del horario.

Necesita el cliente `gh` instalado y autenticado.

    py estado.py                # ultimas 24 horas
    py estado.py --horas 48
    py estado.py --detalle      # ademas, el resumen del log de cada pasada
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

WORKFLOW = "WoW Price Monitor"
# Minuto en el que se espera la ejecucion de cada hora. Es el del cron externo
# que dispara el workflow por la API (ver README), no el del 'schedule' del
# workflow, que solo actua de red de seguridad cada 3 horas.
MINUTO_CRON = 33

# Eventos que cuentan como pasada de esa hora. El disparo externo llega como
# workflow_dispatch, asi que mirar solo 'schedule' daria todo por perdido.
EVENTOS_VALIDOS = ("schedule", "workflow_dispatch")

# GitHub lanza los workflows programados tarde con normalidad: los retrasos
# medidos en este repositorio han llegado a 38 minutos. Hasta que pase este
# margen, un slot sin ejecucion se considera pendiente y no un fallo.
GRACIA_MIN = 40

SIMBOLO = {"success": "✓", "failure": "✗", "cancelled": "-", None: "…"}


class GhError(Exception):
    """No se ha podido hablar con GitHub."""


def gh(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise GhError(
            "No encuentro el comando 'gh'. Instala GitHub CLI desde https://cli.github.com"
        ) from exc
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout).strip()[:300])
    return proc.stdout


def listar_runs(limite: int) -> list[dict]:
    salida = gh(
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--limit",
        str(limite),
        "--json",
        "databaseId,event,conclusion,status,startedAt",
    )
    return json.loads(salida)


def resumen_del_log(run_id: int) -> str:
    """Extrae del log la linea que dice que encontro la pasada."""
    try:
        log = gh("run", "view", str(run_id), "--log")
    except GhError:
        return "(log no disponible)"

    if "Ningun chollo nuevo" in log:
        return "sin chollos nuevos"
    enviados = re.search(r"Enviados a Discord (\d+) chollo", log)
    if enviados:
        return f"{enviados.group(1)} chollo(s) enviados"
    if "--dry-run" in log:
        return "pasada en seco"
    return "(sin resumen)"


def slot_de(inicio: datetime, minuto: int = MINUTO_CRON) -> datetime:
    """Hora prevista a la que corresponde una ejecucion.

    Nunca se lanza antes de la hora prevista, pero si despues, asi que una
    ejecucion a las 15:52 es la del slot de las 15:33, y una a las 15:10 es la
    del slot de las 14:33.
    """
    slot = inicio.replace(minute=minuto, second=0, microsecond=0)
    if inicio.minute < minuto:
        slot -= timedelta(hours=1)
    return slot


def slots_esperados(
    ahora: datetime,
    horas: int,
    no_antes_de: datetime | None = None,
    minuto: int = MINUTO_CRON,
) -> list[datetime]:
    """Ejecuciones que ya deberian haber ocurrido dentro de la ventana.

    `no_antes_de` recorta por abajo. Sirve para no inventarse huecos en un
    periodo en el que el workflow todavia no existia o tenia otro horario:
    marcarlos como 'NO SE EJECUTO' seria una falsa alarma.
    """
    desde = ahora - timedelta(hours=horas)
    if no_antes_de and no_antes_de > desde:
        desde = no_antes_de

    slot = ahora.replace(minute=minuto, second=0, microsecond=0)
    if slot > ahora:
        slot -= timedelta(hours=1)

    esperados: list[datetime] = []
    while slot >= desde:
        esperados.append(slot)
        slot -= timedelta(hours=1)
    return list(reversed(esperados))


def esta_pendiente(slot: datetime, ahora: datetime) -> bool:
    """Un slot recien cumplido todavia puede llegar: no es un fallo aun."""
    return (ahora - slot) < timedelta(minutes=GRACIA_MIN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba si el vigilante se esta ejecutando en GitHub Actions."
    )
    parser.add_argument("--horas", type=int, default=24, help="Ventana a revisar.")
    parser.add_argument(
        "--desde",
        help="No mirar antes de esta fecha y hora local (formato 'AAAA-MM-DD HH:MM'). "
        "Util despues de cambiar el minuto del cron: lo anterior no es comparable.",
    )
    parser.add_argument(
        "--detalle",
        action="store_true",
        help="Descarga el log de cada pasada para decir que encontro. Mas lento.",
    )
    args = parser.parse_args(argv)

    try:
        runs = listar_runs(min(args.horas * 2 + 20, 200))
    except GhError as exc:
        print(f"❌ {exc}")
        return 1

    ahora = datetime.now(timezone.utc)

    # Antes de la primera ejecucion conocida el workflow no existia, asi que no
    # tiene sentido reclamar pasadas de entonces.
    inicios = [
        datetime.fromisoformat(r["startedAt"].replace("Z", "+00:00")) for r in runs
    ]
    no_antes_de = min(inicios) if inicios else None
    nota_recorte = "el workflow todavia no existia"

    if args.desde:
        try:
            elegido = datetime.strptime(args.desde, "%Y-%m-%d %H:%M").astimezone()
        except ValueError:
            print("❌ --desde espera el formato 'AAAA-MM-DD HH:MM', por ejemplo")
            print("   --desde \"2026-08-30 14:35\"")
            return 1
        if no_antes_de is None or elegido > no_antes_de:
            no_antes_de = elegido
            nota_recorte = "lo has acotado con --desde"

    desde = ahora - timedelta(hours=args.horas)
    if no_antes_de and no_antes_de > desde:
        desde = no_antes_de

    por_slot: dict[datetime, dict] = {}
    for run in runs:
        if run["event"] not in EVENTOS_VALIDOS:
            continue
        inicio = datetime.fromisoformat(run["startedAt"].replace("Z", "+00:00"))
        if inicio < desde:
            continue
        slot = slot_de(inicio)
        por_slot.setdefault(slot, {"run": run, "retraso": inicio - slot})

    esperados = slots_esperados(ahora, args.horas, no_antes_de)
    pendientes = [
        s for s in esperados if s not in por_slot and esta_pendiente(s, ahora)
    ]
    huecos = [s for s in esperados if s not in por_slot and s not in pendientes]

    print(f"Ventana: ultimas {args.horas} h  (ahora {ahora.astimezone():%H:%M} local)")
    if no_antes_de and no_antes_de > ahora - timedelta(hours=args.horas):
        print(
            f"Se mira desde {no_antes_de.astimezone():%d/%m %H:%M} "
            f"porque antes {nota_recorte}."
        )
    linea_resumen = (
        f"Esperadas: {len(esperados)}   "
        f"ejecutadas: {len(esperados) - len(huecos) - len(pendientes)}   "
        f"sin ejecutar: {len(huecos)}"
    )
    if pendientes:
        linea_resumen += f"   pendientes: {len(pendientes)}"
    print(linea_resumen)
    print()

    for slot in esperados:
        hora = slot.astimezone().strftime("%d/%m %H:%M")
        entrada = por_slot.get(slot)
        if entrada is None:
            if slot in pendientes:
                print(f"  {hora}   …   pendiente (GitHub suele lanzar tarde)")
            else:
                print(f"  {hora}   ✗   NO SE EJECUTO")
            continue
        run = entrada["run"]
        marca = SIMBOLO.get(run["conclusion"], "?")
        retraso = int(entrada["retraso"].total_seconds() // 60)
        linea = f"  {hora}   {marca}   {run['conclusion'] or run['status']}"
        if retraso:
            linea += f", {retraso} min tarde"
        if args.detalle:
            linea += f"  ·  {resumen_del_log(run['databaseId'])}"
        print(linea)

    print()
    if not esperados:
        print("Aun no ha tocado ninguna ejecucion programada en esta ventana.")
    elif not huecos:
        print("✅ No falta ninguna. Si no te ha llegado nada a Discord, es que no")
        print("   habia chollos por debajo de tus precios.")
    else:
        print(f"⚠️  Faltan {len(huecos)} de {len(esperados)}. GitHub descarta")
        print("   ejecuciones programadas cuando va cargado; si el hueco es grande,")
        print("   prueba a mover el minuto del cron en .github/workflows/monitor.yml.")
        print()
        print("   Si acabas de cambiar el minuto del cron, lo anterior al cambio no")
        print("   es comparable: acota con --desde \"AAAA-MM-DD HH:MM\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
