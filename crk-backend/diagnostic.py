"""Ou sont passees les donnees ? Lecture seule, n'ecrit rien, ne supprime rien.

Cherche toutes les bases et toutes les sauvegardes du dossier, affiche pour
chacune ce qu'elle contient et sur quelle periode, et dit laquelle le service
utilise reellement.

    py diagnostic.py
"""

import glob
import io
import os
import sqlite3
from datetime import datetime, timedelta, timezone

# Cet outil doit tourner meme quand l'environnement est casse : si python-dotenv
# n'est pas installe (Python systeme au lieu du venv), on lit le .env a la main
# plutot que d'echouer. Un diagnostic qui exige un environnement sain ne sert a
# rien le jour ou l'environnement ne l'est pas.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    _env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env):
        for _ligne in io.open(_env, encoding="utf-8-sig"):
            _ligne = _ligne.strip()
            if not _ligne or _ligne.startswith("#") or "=" not in _ligne:
                continue
            _cle, _val = _ligne.split("=", 1)
            os.environ.setdefault(_cle.strip(), _val.strip().strip('"').strip("'"))
        print("(python-dotenv absent : .env lu directement)")
    else:
        print("(python-dotenv absent, et aucun .env trouve)")

TZ = timezone(timedelta(hours=1))
DOSSIER = os.path.dirname(os.path.abspath(__file__))
UTILISEE = os.path.abspath(os.environ.get("CRK_DB_PATH", "./crk_analytics.db"))


def f(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d/%m/%Y %H:%M") if ts else "-"


def decrire(chemin):
    print(f"\n  {os.path.basename(chemin)}")
    print(f"    chemin  : {chemin}")
    print(f"    taille  : {os.path.getsize(chemin):,} o".replace(",", " "))
    print(f"    modifie : {f(os.path.getmtime(chemin))}")
    if os.path.abspath(chemin) == UTILISEE:
        print("    >>> C'EST CELLE QUE LE SERVICE UTILISE <<<")

    try:
        c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=5)
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        if "events" not in tables:
            print("    (pas de table events)")
            c.close()
            return

        total = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"    evenements : {total}")
        if total:
            mn, mx = c.execute("SELECT MIN(ts), MAX(ts) FROM events").fetchone()
            print(f"    periode    : {f(mn)}  ->  {f(mx)}")
            for r in c.execute(
                """SELECT event_type, COUNT(*), MIN(ts), MAX(ts)
                   FROM events GROUP BY event_type ORDER BY 2 DESC"""
            ):
                print(f"      {r[0]:<12} {r[1]:>7}   {f(r[2])} -> {f(r[3])}")
            print("    par jour :")
            for r in c.execute(
                """SELECT date(ts,'unixepoch','+1 hour') j, COUNT(*)
                   FROM events GROUP BY j ORDER BY j DESC LIMIT 12"""
            ):
                print(f"      {r[0]}  {r[1]:>6}")
        c.close()
    except Exception as exc:
        print(f"    illisible : {exc}")


print("=" * 72)
print("BASES ET SAUVEGARDES TROUVEES")
print("=" * 72)
print(f"CRK_DB_PATH (.env) : {os.environ.get('CRK_DB_PATH', '(non defini)')}")
print(f"resolu en          : {UTILISEE}")
print(f"existe ?           : {os.path.exists(UTILISEE)}")

motifs = ["*.db", "*.db.backup-*", "*.db.avant-purge-*", "*.db-wal"]
trouves = {c for m in motifs for c in glob.glob(os.path.join(DOSSIER, m))}

# La base historique peut avoir ete laissee derriere lors d'un changement de
# dossier (ex : Wisevision -> Wisevision-OLD). On balaie donc aussi le Bureau
# de chaque compte, sur 4 niveaux : c'est la que vivent ces dossiers.
COMPTES = os.path.dirname(os.path.expanduser("~"))          # C:/Users
racines = [os.path.dirname(DOSSIER)]
for compte in glob.glob(os.path.join(COMPTES, "*")):
    for coin in ("Desktop", "Bureau"):
        if os.path.isdir(os.path.join(compte, coin)):
            racines.append(os.path.join(compte, coin))

for racine in racines:
    for prof in range(1, 5):
        for c in glob.glob(os.path.join(racine, *(["*"] * prof), "*.db*")):
            if os.path.isfile(c) and "crk" in os.path.basename(c).lower():
                trouves.add(c)

if os.path.exists(UTILISEE):
    trouves.add(UTILISEE)
trouves = sorted(trouves)

if not trouves:
    print("\nAUCUN fichier .db dans ce dossier.")
else:
    for p in trouves:
        if p.endswith("-wal"):
            print(f"\n  {os.path.basename(p)}  ({os.path.getsize(p):,} o)".replace(",", " "))
            continue
        decrire(p)

print("\n" + "=" * 72)
print("CAISSE (Joolan)")
print("=" * 72)
for nom in ("CRK_JOOLAN_DOMAIN", "CRK_JOOLAN_ENSEIGNE", "CRK_JOOLAN_MAGASINS"):
    print(f"  {nom:<22} {os.environ.get(nom) or '(VIDE)'}")
cle = os.environ.get("CRK_JOOLAN_API_KEY") or ""
print(f"  {'CRK_JOOLAN_API_KEY':<22} {'defini (' + str(len(cle)) + ' car.)' if cle else '(VIDE)'}")
if not (os.environ.get("CRK_JOOLAN_DOMAIN") and os.environ.get("CRK_JOOLAN_ENSEIGNE") and cle):
    print("\n  >>> Joolan NON configure : le dashboard simule tickets et CA.")
    print("      C'est ce qui affiche le badge « SIMULE ».")
