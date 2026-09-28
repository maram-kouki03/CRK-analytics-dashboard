"""Remet en place la base recuperee dans la corbeille, sans perdre le present.

Deux bases coexistent apres l'incident :

    SOURCE    celle qui a ete jetee          24/08 10:01 -> 30/08 14:47
    ACTUELLE  celle creee au redemarrage     30/08 14:51 -> maintenant

Le script les FUSIONNE : la source sert de base, les evenements de la base
actuelle y sont ajoutes. Aucun n'est perdu, aucun n'est double.

Deroulement :
    py restaurer.py --source "<chemin>"              analyse, n'ecrit RIEN
    py restaurer.py --source "<chemin>" --appliquer  effectue la restauration

--depuis AAAA-MM-JJ ecarte tout evenement anterieur a ce jour. La coupure
est appliquee sur la copie de travail, jamais sur la source.

ARRETE LE SERVICE AVANT --appliquer. Le script le verifie de deux facons :
il demande son etat a Windows (`sc query`), et si le service est inconnu il
observe la base pendant trois secondes pour voir si quelqu'un y ecrit. Dans les
deux cas il s'arrete avant d'avoir touche quoi que ce soit.

La base actuelle est sauvegardee avant tout remplacement.

ATTENTION POWERSHELL : les chemins de la corbeille contiennent des $. Il faut
des guillemets SIMPLES, sinon PowerShell les prend pour des variables et le
chemin arrive tronque ou vide.
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=1))
COLONNES = ("store_id", "event_type", "ts", "track_id", "received_at")


def f(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d/%m/%Y %H:%M") if ts else "-"


def ouvrir_ro(chemin):
    return sqlite3.connect("file:" + chemin + "?mode=ro", uri=True, timeout=10)


def resume(chemin, titre):
    """Ce que contient une base, sans y ecrire."""
    print("\n  " + titre)
    print("    " + chemin)
    if not os.path.exists(chemin):
        print("    ABSENT")
        return None
    c = ouvrir_ro(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(events)")]
    if not cols:
        print("    pas de table `events`")
        c.close()
        return None
    n = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"    evenements : {n}")
    if n:
        mn, mx = c.execute("SELECT MIN(ts), MAX(ts) FROM events").fetchone()
        print(f"    periode    : {f(mn)}  ->  {f(mx)}")
        for t, k in c.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"
        ):
            print(f"      {t:<12} {k:>6}")
    print("    colonnes   : " + ", ".join(cols))
    c.close()
    return {"n": n, "cols": cols}


def service_actif(nom):
    """Le service Windows tourne-t-il ? True / False / None si on ne sait pas.

    On interroge Windows directement plutot que de sonder le fichier : un
    verrou SQLite n'empeche PAS de renommer la base (mesure sur ce systeme),
    donc la sonde par renommage laissait passer une restauration a chaud.
    """
    try:
        r = subprocess.run(["sc", "query", nom], capture_output=True,
                           text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None                      # service inconnu sur cette machine
    return "RUNNING" in r.stdout.upper()


def base_ecrite_maintenant(chemin, secondes=3.0):
    """Quelqu'un ecrit-il dans la base en ce moment ?

    Dernier filet quand l'etat du service est inconnu : si le dernier evenement
    ou la date du fichier bouge pendant l'observation, un backend tourne.
    """
    def empreinte():
        e = [os.path.getmtime(chemin)]
        for suffixe in ("-wal", "-shm"):
            e.append(os.path.getmtime(chemin + suffixe)
                     if os.path.exists(chemin + suffixe) else 0)
        try:
            c = ouvrir_ro(chemin)
            e.append(c.execute("SELECT COUNT(*), IFNULL(MAX(ts),0) FROM events").fetchone())
            c.close()
        except sqlite3.Error:
            pass
        return e

    depart = empreinte()
    time.sleep(secondes)
    return empreinte() != depart


SCHEMA_MINIMAL = """
CREATE TABLE events_normalise (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id     TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    ts           REAL    NOT NULL,
    track_id     INTEGER,
    received_at  REAL    NOT NULL
);
"""


def normaliser_schema(conn):
    """Ramene `events` au schema minimal si des colonnes mortes trainent.

    La base recuperee vient d'avant la reduction du schema : elle porte encore
    pec_id, duration_s, seller_count, zone_id. Sans ce passage, la base
    restauree les reintroduirait et le backend afficherait « ancien schema
    detecte » a chaque demarrage.

    Aucune ligne n'est filtree ici - on ne change que la forme de la table. Le
    compte est verifie avant/apres et toute difference interrompt tout.
    """
    colonnes = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    mortes = [c for c in colonnes if c not in ("id",) + COLONNES]
    if not mortes:
        return

    avant = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    cols = ", ".join(COLONNES)
    conn.execute("DROP TABLE IF EXISTS events_normalise")
    conn.executescript(SCHEMA_MINIMAL)
    conn.execute("INSERT INTO events_normalise (" + cols + ") "
                 "SELECT " + cols + " FROM events ORDER BY ts")
    apres = conn.execute("SELECT COUNT(*) FROM events_normalise").fetchone()[0]
    if apres != avant:
        conn.rollback()
        sys.exit(f"\nECART pendant la normalisation ({avant} -> {apres}) - rien remplace")
    conn.execute("DROP TABLE events")
    conn.execute("ALTER TABLE events_normalise RENAME TO events")
    conn.commit()
    print("schema normalise : colonnes retirees -> " + ", ".join(mortes))


def main():
    p = argparse.ArgumentParser(description="Restauration de la base recuperee")
    p.add_argument("--source", required=True, help="base recuperee (corbeille)")
    p.add_argument("--cible", default=os.environ.get("CRK_DB_PATH", "./crk_analytics.db"),
                   help="base actuellement utilisee par le service")
    p.add_argument("--service", default="CRKAnalytics",
                   help="service Windows a verifier arrete")
    p.add_argument("--depuis", metavar="AAAA-MM-JJ",
                   help="ne garder que les evenements a partir de ce jour inclus")
    p.add_argument("--appliquer", action="store_true", help="ecrire (sinon : analyse seule)")
    args = p.parse_args()

    source = os.path.abspath(args.source)
    cible = os.path.abspath(args.cible)

    print("=" * 70)
    print("RESTAURATION")
    print("=" * 70)

    if not os.path.exists(source):
        sys.exit("\nsource introuvable : " + source +
                 "\n(sous PowerShell, entoure le chemin de guillemets SIMPLES)")

    info_src = resume(source, "SOURCE (recuperee)")
    info_cible = resume(cible, "ACTUELLE (utilisee par le service)")
    if info_src is None or info_src["n"] == 0:
        sys.exit("\nla source ne contient aucun evenement - rien a restaurer")

    # Les deux bases doivent partager les colonnes qu'on transporte.
    manquantes = [c for c in COLONNES if c not in info_src["cols"]]
    if manquantes:
        sys.exit(f"\nla source n'a pas les colonnes {manquantes} - schema incompatible")

    a_reprendre = 0
    if info_cible and info_cible["n"]:
        manquantes = [c for c in COLONNES if c not in info_cible["cols"]]
        if manquantes:
            sys.exit(f"\nla base actuelle n'a pas les colonnes {manquantes}")
        a_reprendre = info_cible["n"]

    print("\n" + "-" * 70)
    print(f"  resultat attendu : {info_src['n']} + {a_reprendre} = "
          f"{info_src['n'] + a_reprendre} evenements")
    print("  (moins les doublons eventuels, comptes a la fin)")
    print("-" * 70)

    if not args.appliquer:
        print("\nANALYSE SEULE - rien n'a ete modifie.")
        print("Relance avec --appliquer, SERVICE ARRETE, pour restaurer.")
        return

    # Restaurer pendant que le backend ecrit, c'est perdre les evenements
    # arrives entre la copie et le remplacement - et risquer un fichier
    # incoherent. Deux verifications, dans l'ordre de fiabilite.
    etat = service_actif(args.service)
    if etat is True:
        sys.exit("\nLE SERVICE " + args.service + " TOURNE ENCORE."
                 "\nArrete-le puis relance :"
                 "\n    Stop-Service " + args.service +
                 "\nRien n'a ete modifie.")
    if etat is None and os.path.exists(cible):
        print(f"\netat du service inconnu ({args.service} introuvable) -"
              " observation de la base...")
        if base_ecrite_maintenant(cible):
            sys.exit("\nLA BASE EST EN COURS D'ECRITURE : un backend tourne."
                     "\nArrete-le (Stop-Service, ou ferme la fenetre qui lance"
                     " main.py) puis relance."
                     "\nRien n'a ete modifie.")
        print("  aucune ecriture detectee, on continue.")

    horodatage = time.strftime("%Y%m%d-%H%M%S")

    # 1. La base actuelle est sauvegardee AVANT tout, meme si elle est petite :
    #    c'est la seule copie des evenements arrives depuis le redemarrage.
    if os.path.exists(cible):
        sauvegarde = cible + ".avant-restauration-" + horodatage
        shutil.copy2(cible, sauvegarde)
        print("\nsauvegarde de la base actuelle : " + sauvegarde)

    # 2. La source est copiee a cote de la cible, puis completee. On ne travaille
    #    JAMAIS sur le fichier de la corbeille lui-meme.
    travail = cible + ".restauration-" + horodatage
    shutil.copy2(source, travail)
    print("copie de travail               : " + travail)

    conn = sqlite3.connect(travail, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")

        # Coupure d'anciennete : la garantie est appliquee, pas supposee. Meme
        # si la source contenait par erreur des journees plus anciennes, elles
        # ne peuvent pas atteindre la base finale.
        if args.depuis:
            j = date.fromisoformat(args.depuis)
            limite = datetime(j.year, j.month, j.day, tzinfo=TZ).timestamp()
            coupes = conn.execute("DELETE FROM events WHERE ts < ?", (limite,)).rowcount
            conn.commit()
            print(f"\nfiltre --depuis {args.depuis} : {coupes} evenement(s) anterieur(s) ecarte(s)")

        avant = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        ajoutes = 0
        if a_reprendre:
            conn.execute("ATTACH DATABASE ? AS actuelle", (cible,))
            cols = ", ".join(COLONNES)
            # NOT EXISTS plutot que INSERT OR IGNORE : les deux bases ont des
            # `id` autoincrement independants, un identifiant commun ne veut
            # donc rien dire. L'identite d'un evenement, c'est son contenu.
            conn.execute(
                "INSERT INTO events (" + cols + ") "
                "SELECT " + cols + " FROM actuelle.events a "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM events e"
                "  WHERE e.store_id   = a.store_id"
                "    AND e.event_type = a.event_type"
                "    AND e.ts         = a.ts"
                "    AND IFNULL(e.track_id, -1) = IFNULL(a.track_id, -1))")
            conn.commit()
            apres = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            ajoutes = apres - avant
            conn.execute("DETACH DATABASE actuelle")

        normaliser_schema(conn)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_store_ts ON events(store_id, ts)")
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        mn, mx = conn.execute("SELECT MIN(ts), MAX(ts) FROM events").fetchone()
        types = list(conn.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"))
    finally:
        conn.close()

    print(f"\nevenements repris de la base actuelle : {ajoutes} "
          f"({a_reprendre - ajoutes} doublons ecartes)")

    # 3. Mise en place. Les fichiers -wal/-shm de l'ancienne base doivent partir
    #    avec elle : laisses la, SQLite les rejouerait sur le nouveau fichier.
    for suffixe in ("-wal", "-shm"):
        reste = cible + suffixe
        if os.path.exists(reste):
            os.remove(reste)
    if os.path.exists(cible):
        os.remove(cible)
    os.rename(travail, cible)
    for suffixe in ("-wal", "-shm"):
        reste = travail + suffixe
        if os.path.exists(reste):
            os.rename(reste, cible + suffixe)

    print("\n" + "=" * 70)
    print("RESTAURATION TERMINEE")
    print("=" * 70)
    print("  base       : " + cible)
    print(f"  evenements : {total}")
    print(f"  periode    : {f(mn)}  ->  {f(mx)}")
    for t, k in types:
        print(f"    {t:<12} {k:>6}")
    print("\nRedemarre le service :  Start-Service CRKAnalytics")


if __name__ == "__main__":
    main()
