"""Supprime tout l'historique anterieur a une date, evenements ET caisse.

Usage prevu : repartir proprement apres le passage au format INTERACTION.
Les anciennes lignes PEC_END n'ont pas de track_id, elles ne peuvent donc plus
etre comptees ; les garder afficherait un historique a 0 interaction. Les
supprimer evite un dashboard qui ment sur le passe.

    py purge_db.py --depuis 2026-08-24 --dry-run   # montre, n'ecrit rien
    py purge_db.py --depuis 2026-08-24             # sauvegarde puis supprime

Ce qui est supprime :
  * events    : tout evenement AVANT le 24/08 00:00 (heure de Tunis)
  * pos_daily : toute journee de caisse AVANT le 24/08

Ce qui est conserve : le 24/08 lui-meme et tout ce qui suit.

Une sauvegarde horodatee est creee a cote de la base. ARRETER LE SERVICE avant
de lancer : supprimer sous les pieds d'un backend qui ecrit est une mauvaise
idee.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

# Meme convention que analytics.py : Africa/Tunis, +01:00 fixe, sans DST.
from datetime import timedelta, timezone  # noqa: E402

TZ_TUNIS = timezone(timedelta(hours=1))


def human(n):
    return f"{n:,}".replace(",", " ")


def borne(jour: date) -> float:
    """Timestamp du 00:00 local de ce jour : tout ce qui est avant sera supprime."""
    return datetime(jour.year, jour.month, jour.day, tzinfo=TZ_TUNIS).timestamp()


def main():
    p = argparse.ArgumentParser(description="Purger l'historique avant une date")
    p.add_argument("--depuis", required=True,
                   help="date a CONSERVER a partir de (AAAA-MM-JJ, incluse)")
    p.add_argument("--db", default=os.environ.get("CRK_DB_PATH", "./crk_analytics.db"))
    p.add_argument("--dry-run", action="store_true", help="n'ecrit rien")
    p.add_argument("--no-backup", action="store_true", help="ne pas sauvegarder (deconseille)")
    args = p.parse_args()

    try:
        depuis = date.fromisoformat(args.depuis)
    except ValueError:
        sys.exit("--depuis doit etre une date ISO, par exemple 2026-08-24")

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        sys.exit(f"base introuvable : {db_path}")

    limite = borne(depuis)
    print(f"base    : {db_path}")
    print(f"conserve: a partir du {depuis} 00:00 (heure de Tunis)")
    print(f"supprime: tout ce qui precede")

    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}

    # ------------------------------------------------------------------ avant
    print("\n--- avant ---")
    total_ev = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    a_supp_ev = conn.execute("SELECT COUNT(*) c FROM events WHERE ts < ?", (limite,)).fetchone()["c"]
    garde_ev = total_ev - a_supp_ev
    print(f"  events     : {human(total_ev)} lignes")
    print(f"    a supprimer {human(a_supp_ev):>10}")
    print(f"    conservees  {human(garde_ev):>10}")

    for r in conn.execute(
        """SELECT event_type, COUNT(*) c,
                  SUM(CASE WHEN ts < ? THEN 1 ELSE 0 END) vieux
           FROM events GROUP BY event_type ORDER BY c DESC""", (limite,)
    ):
        print(f"      {r['event_type']:<14} {human(r['c']):>8}  dont {human(r['vieux'])} a supprimer")

    a_supp_pos = garde_pos = 0
    if "pos_daily" in tables:
        a_supp_pos = conn.execute(
            "SELECT COUNT(*) c FROM pos_daily WHERE date < ?", (args.depuis,)).fetchone()["c"]
        garde_pos = conn.execute(
            "SELECT COUNT(*) c FROM pos_daily WHERE date >= ?", (args.depuis,)).fetchone()["c"]
        print(f"  pos_daily  : {human(a_supp_pos)} a supprimer, {human(garde_pos)} conservees")

    # bornes de ce qui restera, pour verifier que c'est bien ce qu'on veut
    reste = conn.execute(
        "SELECT MIN(ts) mn, MAX(ts) mx FROM events WHERE ts >= ?", (limite,)).fetchone()
    print("\n--- ce qui restera ---")
    if reste["mn"] is None:
        print("  AUCUN evenement. La base sera VIDE.")
        print("  Verifier la date : y a-t-il vraiment des donnees a partir de la ?")
    else:
        f = lambda t: datetime.fromtimestamp(t, TZ_TUNIS).strftime("%d/%m/%Y %H:%M")
        print(f"  du {f(reste['mn'])} au {f(reste['mx'])}")
        print(f"  {human(garde_ev)} evenements, {human(garde_pos)} journees de caisse")

    if a_supp_ev == 0 and a_supp_pos == 0:
        print("\nRien a supprimer, la base est deja propre.")
        conn.close()
        return

    if args.dry_run:
        print("\n--dry-run : RIEN n'a ete modifie.")
        conn.close()
        return

    conn.close()

    # -------------------------------------------------------------- sauvegarde
    if not args.no_backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"{db_path}.avant-purge-{stamp}"
        shutil.copy2(db_path, backup)
        print(f"\nsauvegarde : {backup}")

    # ---------------------------------------------------------------- purge
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM events WHERE ts < ?", (limite,))
        if "pos_daily" in tables:
            conn.execute("DELETE FROM pos_daily WHERE date < ?", (args.depuis,))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    conn.execute("VACUUM")  # hors transaction : recompacte le fichier

    # ----------------------------------------------------------- verification
    apres_ev = conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    restants_vieux = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE ts < ?", (limite,)).fetchone()["c"]
    apres_pos = conn.execute("SELECT COUNT(*) c FROM pos_daily").fetchone()["c"] if "pos_daily" in tables else 0
    conn.close()

    print("\n--- verification ---")
    ok = True
    for label, attendu, obtenu in (
        ("evenements conserves", garde_ev, apres_ev),
        ("anciens restants", 0, restants_vieux),
        ("journees caisse", garde_pos, apres_pos),
    ):
        bon = attendu == obtenu
        ok &= bon
        print(f"  {label:<24} attendu {human(attendu):>8}  obtenu {human(obtenu):>8}  {'OK' if bon else 'ECART'}")

    print(f"  taille fichier           {human(os.path.getsize(db_path))} octets")
    if not ok:
        sys.exit("\nECART detecte — restaurer la sauvegarde.")
    print("\nPurge terminee.")


if __name__ == "__main__":
    main()
