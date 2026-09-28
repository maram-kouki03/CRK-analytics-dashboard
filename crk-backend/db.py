import os
import sqlite3
import time
from contextlib import contextmanager

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("CRK_DB_PATH", "./crk_analytics.db")

STORE_NAMES = [
    "Tunisia Mall",
    "Mall of Sousse",
    "Mall of Sfax",
    "Sfax 1",
    "La Marsa",
    "Azur City",
    "MANAR CITY",
    "Menzah 5",
]

# Cards and frontend disagree on capitalisation — the event stream carries
# 'Manar city' while STORE_NAMES says 'MANAR CITY'. Resolve requests to the
# canonical name instead of 404-ing, and read with COLLATE NOCASE so rows
# already written under any casing stay visible.
_STORE_LOOKUP = {s.casefold(): s for s in STORE_NAMES}


def resolve_store(name: str | None) -> str | None:
    if not name:
        return None
    return _STORE_LOOKUP.get(name.strip().casefold())


# Schéma minimal : on ne stocke que ce que le dashboard calcule réellement.
#   ENTRY       -> store_id, ts, track_id
#   INTERACTION -> store_id, ts, track_id
# Les deux types portent la même identité : track_id. Il n'y a plus de colonne
# pec_id — les anciens types PEC* ne sont plus ni reçus ni comptés. Une base
# existante garde sa colonne pec_id, simplement plus jamais lue.
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id     TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    ts           REAL    NOT NULL,
    track_id     INTEGER,
    received_at  REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_store_ts ON events(store_id, ts);

-- Cache des données de caisse, un enregistrement par magasin et par jour.
-- L'API Joolan ne répond que par date : sans ce cache, afficher une période de
-- 30 jours déclencherait 30 requêtes HTTP à CHAQUE rafraîchissement du
-- dashboard. Un jour passé est figé, on ne le redemande jamais deux fois.
CREATE TABLE IF NOT EXISTS pos_hourly (
    store_id   TEXT    NOT NULL,
    date       TEXT    NOT NULL,   -- AAAA-MM-JJ, heure locale boutique
    hour       INTEGER NOT NULL,   -- 0..23 ; -1 si l'entête n'a pas d'heure lisible
    tickets    INTEGER NOT NULL,
    revenue    REAL    NOT NULL,
    source     TEXT    NOT NULL,   -- 'joolan' | 'simulation'
    fetched_at REAL    NOT NULL,
    PRIMARY KEY (store_id, date, hour)
);
"""

# Seuls ces types sont écrits en base. HEARTBEAT est accepté par l'API — le
# boîtier ne doit jamais recevoir d'erreur pour un événement qu'il a le droit
# d'envoyer — mais n'est pas conservé : aucun indicateur ne s'en sert.
STORED_EVENT_TYPES = ("ENTRY", "INTERACTION")

# Colonnes de l'ancien schéma. Leur présence signale une base à migrer
# (voir migrate_db.py) ; la lecture fonctionne dans les deux cas. track_id n'en
# fait plus partie : c'est l'identifiant d'une ENTRY comme d'une INTERACTION.
LEGACY_COLUMNS = ("pec_id", "duration_s", "seller_count", "zone_id")


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    # Un CRK_DB_PATH pointant vers un dossier inexistant fait échouer sqlite3 sur
    # « unable to open database file », qui ne dit pas quel chemin est en cause.
    # On vérifie avant, et on nomme le coupable.
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    if not os.path.isdir(folder):
        raise RuntimeError(
            f"CRK_DB_PATH pointe vers un dossier inexistant : {folder}\n"
            f"  valeur lue   : {DB_PATH}\n"
            # Message volontairement sans accent : il s'affiche dans une console
            # Windows dont l'encodage n'est pas garanti.
            "  Corrige CRK_DB_PATH dans crk-backend/.env"
        )

    with get_connection() as conn:
        conn.executescript(SCHEMA)

        # track_id avait été retiré du schéma minimal avant que le boîtier
        # n'envoie des INTERACTION, qui s'identifient justement par lui. Une base
        # déjà passée par migrate_db.py ne l'a donc plus : on la remet, sinon
        # toute INTERACTION serait stockée sans identité.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        if "track_id" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN track_id INTEGER")


def legacy_columns_present() -> list:
    """Colonnes de l'ancien schéma encore dans la table, [] si base déjà propre.

    On ne migre PAS automatiquement : la base peut être partagée avec un autre
    service qui écrit encore ces colonnes, et la supprimer sous ses pieds le
    casserait. C'est migrate_db.py, lancé volontairement, qui fait le ménage.
    """
    with get_connection() as conn:
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    return [c for c in LEGACY_COLUMNS if c in existing]


# Anything at or above this is real Unix clock time (~2001-09). Session-relative
# ts — seconds since the card booted — are small numbers, orders of magnitude
# below any plausible epoch, so the two forms are trivially distinguishable.
EPOCH_FLOOR = 1_000_000_000


def _with_wall_clock(events: list, received_at: float) -> list:
    # Preferred case: the card sends real Unix time, so trust it exactly as sent.
    # A buffered batch flushed late then keeps the times the events really
    # happened at instead of being dragged forward to its arrival moment.
    if all(e["ts"] >= EPOCH_FLOOR for e in events):
        return events

    # Fallback for cards sending stream-relative seconds-since-session-start:
    # anchor the most recent event in this call to `received_at` and shift the
    # rest backward by the same relative spacing, so a flushed batch of buffered
    # events reconstructs its intra-day distribution instead of collapsing onto
    # the moment it was received. This is a reconstruction, not a measurement —
    # it assumes the newest event in the batch happened just now, which breaks
    # if the card restarted mid-batch. Sending epoch time avoids all of it.
    anchor = max(e["ts"] for e in events)
    resolved = []
    for e in events:
        e = dict(e)
        e["ts"] = received_at - (anchor - e["ts"])
        resolved.append(e)
    return resolved


def insert_event(event: dict):
    insert_events_batch([event])


def insert_events_batch(events: list) -> int:
    """Écrit les événements conservés. Renvoie le nombre réellement stocké.

    Le recalage d'horloge est fait AVANT le filtrage : l'ancre est « l'événement
    le plus récent de cet envoi », et un HEARTBEAT — jeté ensuite — peut très
    bien être le plus récent. Filtrer d'abord décalerait tout le lot vers le
    passé.
    """
    if not events:
        return 0
    received_at = time.time()
    resolved = _with_wall_clock(events, received_at)

    rows = [
        (e["store_id"], e["event_type"], e["ts"], e.get("track_id"), received_at)
        for e in resolved
        if e["event_type"] in STORED_EVENT_TYPES
    ]
    if not rows:
        return 0

    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO events (store_id, event_type, ts, track_id, received_at)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def get_events_in_range(store_id: str, start_ts: float, end_ts: float):
    # Ces trois colonnes existent dans l'ancien comme dans le nouveau schéma :
    # la lecture marche donc sur une base pas encore migrée.
    # Ordonné par ts pour que le découpage horaire soit déterministe et non
    # dépendant de l'ordre de restitution de SQLite.
    with get_connection() as conn:
        cur = conn.execute(
            """SELECT event_type, ts, track_id
               FROM events
               WHERE store_id = ? COLLATE NOCASE AND ts >= ? AND ts < ?
               ORDER BY ts""",
            (store_id, start_ts, end_ts),
        )
        return cur.fetchall()


def get_stores_last_event() -> dict:
    """{canonical store name: ts of its most recent event} — only stores with events.

    Cards write the store name with their own capitalisation, so several raw
    store_id values can fold onto one canonical name; keep the latest of them.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT store_id, MAX(ts) AS last_ts FROM events GROUP BY store_id"
        ).fetchall()

    latest = {}
    for row in rows:
        name = resolve_store(row["store_id"])
        if name is None:
            continue  # store no longer in STORE_NAMES
        if name not in latest or row["last_ts"] > latest[name]:
            latest[name] = row["last_ts"]
    return latest


def get_events_total() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]


def get_last_event(store_id: str):
    with get_connection() as conn:
        return conn.execute(
            """SELECT ts, received_at FROM events
               WHERE store_id = ? COLLATE NOCASE
               ORDER BY received_at DESC LIMIT 1""",
            (store_id,),
        ).fetchone()


# --------------------------------------------------------------- cache caisse

def get_pos_hours(store_id: str, dates: list) -> dict:
    """{(date, heure): {tickets, revenue, source}} pour les dates en cache.

    `heure` vaut -1 pour les tickets dont l'entête n'avait pas d'heure lisible :
    ils comptent dans le total du jour sans être attribués à une tranche.
    """
    if not dates:
        return {}
    marques = ",".join("?" * len(dates))
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT date, hour, tickets, revenue, source, fetched_at FROM pos_hourly
                WHERE store_id = ? COLLATE NOCASE AND date IN ({marques})""",
            (store_id, *dates),
        ).fetchall()
    return {
        (r["date"], r["hour"]): {
            "tickets": r["tickets"], "revenue": r["revenue"], "source": r["source"],
            # `fetched_at` sert à savoir si la journée était TERMINÉE au moment
            # où on l'a lue : une journée lue à 14h ne contient pas la soirée.
            "fetched_at": r["fetched_at"],
        }
        for r in rows
    }


def put_pos_hours(rows: list):
    """Écrit ou remplace des tranches horaires de caisse.

    `rows` : [(store_id, date, hour, tickets, revenue, source)].
    REPLACE et non INSERT : la journée en cours est réécrite à chaque
    rafraîchissement, puisque des ventes s'y ajoutent encore.
    """
    if not rows:
        return
    horodatage = time.time()
    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO pos_hourly
               (store_id, date, hour, tickets, revenue, source, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(*r, horodatage) for r in rows],
        )


def delete_pos_days(store_id: str, dates: list) -> int:
    """Efface toutes les tranches de ces journées, avant de les réécrire.

    Sans cela, une heure qui n'a plus de vente (ticket annulé) garderait
    indéfiniment son ancienne valeur : INSERT OR REPLACE ne supprime rien.
    """
    if not dates:
        return 0
    marques = ",".join("?" * len(dates))
    with get_connection() as conn:
        cur = conn.execute(
            f"""DELETE FROM pos_hourly
                WHERE store_id = ? COLLATE NOCASE AND date IN ({marques})""",
            (store_id, *dates),
        )
        return cur.rowcount


def clear_pos_cache(source: str | None = None) -> int:
    """Vide le cache caisse. `source` pour ne purger que 'simulation'.

    Sert au basculement vers la vraie API : les jours simulés doivent partir,
    sinon ils resteraient affichés indéfiniment à la place des vrais chiffres.
    """
    with get_connection() as conn:
        if source:
            cur = conn.execute("DELETE FROM pos_hourly WHERE source = ?", (source,))
        else:
            cur = conn.execute("DELETE FROM pos_hourly")
        return cur.rowcount
