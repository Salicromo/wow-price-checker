import os, sys, time
from datetime import datetime, timezone
sys.path.insert(0, os.getcwd())
from wowalerts.blizzard import BlizzardClient
c = BlizzardClient(os.getenv("BLIZZARD_CLIENT_ID"), os.getenv("BLIZZARD_CLIENT_SECRET"), region="eu")
ANTES = datetime(2026, 10, 16, 19, 36, 30, tzinfo=timezone.utc)
VIGILAR = {
    ("Silvermoon", 3391): {1075886968: "Helm 321 85.000", 1077934424: "Helm 321 85.000",
                           1077688895: "Greaves 311 25.000", 1077969418: "Greaves 311 25.000",
                           1077730283: "Greatbelt 308 26.999"},
    ("Nemesis", 1316): {1077911642: "Coif 324 125.000"},
    ("Elune", 1315): {1077786117: "Pauldrons 311 20.000"},
    ("Drak'thul", 1092): {1068433712: "Helm 308 20.000 (SHORT)", 1077973192: "Helm 308 20.000"},
    ("Gordunni", 1602): {1077761261: "Slippers 308 19.999"},
    ("Darkmoon Faire", 1096): {1072648893: "Girdle 308 20.000", 1077758319: "Girdle 308 20.000"},
}
limite = time.time() + 2 * 3600
pendientes = dict(VIGILAR)
while pendientes and time.time() < limite:
    for (nombre, rid), subastas in list(pendientes.items()):
        t = c.auction_dump_time(rid)
        if t and t > ANTES:
            snap = c.auctions(rid)
            vivas = {a["id"]: a for a in snap.auctions}
            print(f"== {nombre}: volcado {snap.taken_at}", flush=True)
            for aid, desc in subastas.items():
                a = vivas.get(aid)
                estado = f"SIGUE (quedan {a.get('time_left')}, {a.get('buyout',0)//10000} g)" if a else "YA NO ESTA"
                print(f"   {desc:28} id={aid}: {estado}", flush=True)
            del pendientes[(nombre, rid)]
    if pendientes:
        time.sleep(120)
if pendientes:
    print("Sin volcado nuevo para:", [n for n, _ in pendientes])
