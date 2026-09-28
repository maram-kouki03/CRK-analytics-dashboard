"""Transforme une base de l'ancien schema vers le schema minimal.

Ce qui est conserve :
    ENTRY         store_id, ts, track_id
    INTERACTION   store_id, ts, track_id

Ce qui est supprime :
    les lignes PEC, PEC_START, PEC_END  (le boitier ne les envoie plus)
    les lignes HEARTBEAT                (aucun indicateur ne s'en sert)
    les colonnes pec_id, duration_s, seller_count, zone_id

ATTENTION - cette migration N'EST PAS neutre pour le dashboard. Les PEC
archivees etaient comptees sur pec_id ; en supprimant ces lignes, toute periode
anterieure au passage au format INTERACTION affichera 0 PEC. Le script affiche
combien de PEC archivees seront perdues avant d'ecrire quoi que ce soit : lance
d'abord --dry-run, et garde la sauvegarde qu'il cree.

    py migrate_db.py                 # utilise CRK_DB_PATH du .env
    py migrate_db.py --db C:\\...\\x.db
    py migrate_db.py --dry-run       # montre ce qui serait fait, n'ecrit rien

ATTENTION : arrete d'abord tout service qui ecrit dans cette base. Un ancien
backend qui inserait encore track_id ou duration_s echouerait apres migration.
Une sauvegarde horodatee est creee automatiquement a cote de la base.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import time

from dotenv import load_dotenv

load_dotenv()

KEPT_TYPES = ("ENTRY", "INTERACTION")
DROPPED_TYPES = ("PEC", "PEC_START", "PEC_END", "HEARTBEAT")
# track_id n'est plus une colonne « ancienne » : c'est l'identifiant d'une ENTRY
# comme d'une INTERACTION, la migration doit donc le conserver. pec_id le
# redevient : plus aucun type reçu ne le remplit.
LEGACY_COLUMNS = ("pec_id", "duration_s", "seller_count", "zone_id")

NEW_SCHEMA = """
CREATE TABLE events_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id     TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    ts           REAL    NOT NULL,
    track_id     INTEGER,
    received_at  REAL    NOT NULL
);
"""


def human(n):
    return f"{n:,}".replace(",", " ")


def main():
    p = argparse.ArgumentParser(description="Migration vers le schema minimal")
    p.add_argument("--db", default=os.environ.get("CRK_DB_PATH", "./crk_analytics.db"))
    p.add_argument("--dry-run", action="store_true", help="n'ecrit rien")
    p.add_argument("--no-backup", action="store_true", help="ne pas sauvegarder (deconseille)")
    args = p.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        sys.exit(f"base introuvable : {db_path}")

    print(f"base : {db_path}")

    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    columns = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    if not columns:
        sys.exit("table `events` introuvable")

    legacy = [c for c in LEGACY_COLUMNS if c in columns]

    print("\n--- avant ---")
    total = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    print(f"  {human(total)} lignes")
    for r in conn.execute(
        "SELECT event_type, COUNT(*) c FROM events GROUP BY event_type ORDER BY c DESC"
    ):
        mark = "  supprime" if r["event_type"] in DROPPED_TYPES else "  garde"
        print(f"    {r['event_type']:<12} {human(r['c']):>8}{mark}")
    print(f"  colonnes a retirer : {', '.join(legacy) if legacy else 'aucune'}")

    kept = conn.execute(
        f"SELECT COUNT(*) c FROM events WHERE event_type IN ({','.join('?' * len(KEPT_TYPES))})",
        KEPT_TYPES,
    ).fetchone()["c"]

    # Ce que la migration DETRUIT : les PEC archivees, comptees sur pec_id. On
    # ne le lit que si la colonne existe encore (base deja migree = 0).
    columns_now = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    if "pec_id" in columns_now:
        pec_before = conn.execute(
            "SELECT COUNT(DISTINCT pec_id) c FROM events "
            "WHERE event_type IN ('PEC','PEC_END') AND pec_id IS NOT NULL"
        ).fetchone()["c"]
    else:
        pec_before = 0
    entries_before = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type='ENTRY'"
    ).fetchone()["c"]
    if pec_before:
        print(f"\n  ATTENTION : {human(pec_before)} PEC archivees seront SUPPRIMEES.")
        print("  Toute periode anterieure au format INTERACTION affichera 0 PEC.")

    print("\n--- apres ---")
    print(f"  {human(kept)} lignes  ({human(total - kept)} supprimees)")
    print(f"  PEC distinctes : {human(pec_before)}   entrees : {human(entries_before)}")

    if not legacy and total == kept:
        print("\nBase deja au schema minimal, rien a faire.")
        conn.close()
        return

    if args.dry_run:
        print("\n--dry-run : rien n'a ete modifie.")
        conn.close()
        return

    conn.close()

    if not args.no_backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"{db_path}.backup-{stamp}"
        # copy2 preserve les dates ; les fichiers -wal/-shm sont repris par
        # SQLite au prochain acces, la sauvegarde du .db suffit une fois le
        # service arrete (WAL rejoue au premier open).
        shutil.copy2(db_path, backup)
        print(f"\nsauvegarde : {backup}")

    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TABLE IF EXISTS events_new")
        conn.executescript(NEW_SCHEMA)
        conn.execute(
            f"""INSERT INTO events_new
                    (store_id, event_type, ts, track_id, received_at)
                SELECT store_id, event_type, ts, track_id, received_at
                FROM events
                WHERE event_type IN ({','.join('?' * len(KEPT_TYPES))})
                ORDER BY id""",
            KEPT_TYPES,
        )
        conn.execute("DROP TABLE events")
        conn.execute("ALTER TABLE events_new RENAME TO events")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_store_ts ON events(store_id, ts)")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    # VACUUM hors transaction : recompacte le fichier apres la suppression.
    conn.execute("VACUUM")

    after = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    # Apres migration il n'y a plus de pec_id : on compte les INTERACTION, qui
    # sont desormais la seule source de PEC.
    pec_after = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type='INTERACTION'"
    ).fetchone()["c"]
    entries_after = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE event_type='ENTRY'"
    ).fetchone()["c"]
    cols_after = [r["name"] for r in conn.execute("PRAGMA table_info(events)")]
    conn.close()

    print("\n--- verification ---")
    ok = True
    for label, before, now in (
        ("lignes conservees", kept, after),
        ("PEC distinctes", pec_before, pec_after),
        ("entrees", entries_before, entries_after),
    ):
        good = before == now
        ok &= good
        print(f"  {label:<20} attendu {human(before):>8}  obtenu {human(now):>8}  {'OK' if good else 'ECART'}")
    print(f"  colonnes : {', '.join(cols_after)}")

    size = os.path.getsize(db_path)
    print(f"  taille   : {human(size)} octets")

    if not ok:
        sys.exit("\nECART detecte - restaure la sauvegarde et signale le probleme.")
    print("\nMigration terminee.")


if __name__ == "__main__":
    main()
