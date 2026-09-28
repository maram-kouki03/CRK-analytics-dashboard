"""Retrouve une base d'evenements CRK n'importe ou sur les disques.

Lecture seule : n'ecrit rien, ne supprime rien, ne restaure rien.

Trois filets, du plus large au plus fin :
  1. tout fichier dont le nom evoque la base (crk / analytics / .db) ;
  2. dans la corbeille, les noms sont perdus ($R...) : on lit donc les 16
     premiers octets et on garde ce qui commence par « SQLite format 3 » ;
  3. tout dossier nomme Wisevision*, l'ancien emplacement du service.

Chaque candidat est ouvert en lecture seule pour dire ce qu'il contient
vraiment. Un fichier sans table `events` est ecarte du classement.

    py retrouver_base.py
"""

import os
import sqlite3
import string
import sys
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=1))
MAGIE = b"SQLite format 3\x00"

# Branches sans interet, et couteuses a parcourir.
IGNORES = {
    "windows", "program files", "program files (x86)", "programdata",
    "node_modules", ".git", "venv", ".venv", "__pycache__", "$windows.~ws",
    "system volume information", "onedrivetemp",
}


def f(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d/%m/%Y %H:%M") if ts else "-"


def est_sqlite(chemin):
    try:
        with open(chemin, "rb") as fh:
            return fh.read(16) == MAGIE
    except OSError:
        return False


def disques():
    trouves = []
    for lettre in string.ascii_uppercase:
        racine = lettre + ":" + os.sep
        if os.path.isdir(racine):
            trouves.append(racine)
    return trouves


candidats = set()
dossiers_wisevision = []
scannes = 0

print("balayage en cours...", flush=True)
for racine in disques():
    for dossier, sous, fichiers in os.walk(racine, topdown=True, onerror=lambda e: None):
        bas = os.path.basename(dossier).lower()
        corbeille = "$recycle.bin" in dossier.lower()

        # On elague, sauf dans la corbeille qu'on veut voir en entier.
        if not corbeille:
            sous[:] = [d for d in sous if d.lower() not in IGNORES]
        for d in sous:
            if d.lower().startswith("wisevision"):
                dossiers_wisevision.append(os.path.join(dossier, d))

        scannes += 1
        if scannes % 20000 == 0:
            print(f"  ... {scannes} dossiers", flush=True)

        for nom in fichiers:
            chemin = os.path.join(dossier, nom)
            n = nom.lower()
            if ".db" in n and ("crk" in n or "analytic" in n):
                candidats.add(chemin)
            elif corbeille:
                try:
                    if os.path.getsize(chemin) > 4096 and est_sqlite(chemin):
                        candidats.add(chemin)
                except OSError:
                    pass

print(f"termine : {scannes} dossiers parcourus\n")

if dossiers_wisevision:
    print("DOSSIERS Wisevision* TROUVES")
    for d in dossiers_wisevision:
        print("  " + d)
    print()

resultats = []
for chemin in sorted(candidats):
    if not est_sqlite(chemin):
        continue
    try:
        c = sqlite3.connect("file:" + chemin.replace("?", "%3f") + "?mode=ro",
                            uri=True, timeout=5)
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "events" not in tables:
            c.close()
            continue
        n = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        mn = mx = None
        types = []
        if n:
            mn, mx = c.execute("SELECT MIN(ts), MAX(ts) FROM events").fetchone()
            types = list(c.execute(
                "SELECT event_type, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"))
        c.close()
        resultats.append((n, chemin, mn, mx, types))
    except Exception as exc:
        print(f"  illisible : {chemin}  ({exc})")

if not resultats:
    print("AUCUNE base contenant une table `events` trouvee sur les disques.")
    sys.exit(0)

print("=" * 72)
print("BASES D'EVENEMENTS TROUVEES (la plus fournie en premier)")
print("=" * 72)
for n, chemin, mn, mx, types in sorted(resultats, reverse=True):
    print(f"\n  {n} evenements")
    print(f"    {chemin}")
    print(f"    modifie : {f(os.path.getmtime(chemin))}")
    if n:
        print(f"    periode : {f(mn)}  ->  {f(mx)}")
        print("    types   : " + ", ".join(f"{t}={c}" for t, c in types))
