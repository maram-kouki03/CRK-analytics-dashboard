"""Tail the events table live, to see what the Jetson is actually sending.

Read-only (SELECT only) and safe to run against the live service — the DB is in
WAL mode, so this does not block the backend's writes.

    py watch_events.py                  # follow new events as they arrive
    py watch_events.py --since 30       # show the last 30 first, then follow
    py watch_events.py --once           # dump recent events and exit
    py watch_events.py --store "Manar city"

Note what this can and cannot show you:
  * `ts` here is the value AFTER db._with_wall_clock() rewrote it, not the raw
    value the card sent. The "raw" column is reconstructed back out of it.
  * Events the card sent that FAILED validation (HTTP 422) never reach the table
    and so cannot appear here. Only request logging in the app would show those.
  * HEARTBEAT is accepted by the API but never stored, so it never appears here
    either — that is expected, not a lost event. Only ENTRY and INTERACTION are
    written.
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

TZ_TUNIS = timezone(timedelta(hours=1))
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crk_analytics.db")

COLS = "id, store_id, event_type, ts, track_id, received_at"


def fmt(row) -> str:
    local = datetime.fromtimestamp(row["ts"], TZ_TUNIS).strftime("%d/%m %H:%M:%S")

    # received_at - ts = how far back this event was shifted by _with_wall_clock,
    # i.e. how stale it was in the card's buffer at the moment it was flushed.
    lag = row["received_at"] - row["ts"]
    lag_s = f"buffered {lag:6.1f}s" if lag > 1.5 else "live" + " " * 10

    # track_id identifie aussi bien une ENTRY qu'une INTERACTION : c'est la
    # seule identité que le boîtier envoie.
    detail = f"track={row['track_id']}" if row["track_id"] is not None else ""

    flag = "  <-- ts near epoch!" if row["ts"] < 1_000_000_000 else ""
    return (
        f"#{row['id']:<7} {local}  {row['store_id']:<14} "
        f"{row['event_type']:<10} {detail:<28} {lag_s}{flag}"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.environ.get("CRK_DB_PATH", DEFAULT_DB))
    p.add_argument("--since", type=int, default=10, help="show this many recent events first")
    p.add_argument("--store", default=None, help="only this store (case-insensitive)")
    p.add_argument("--interval", type=float, default=2.0, help="poll seconds")
    p.add_argument("--once", action="store_true", help="dump and exit, do not follow")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"no database at {args.db}")

    conn = sqlite3.connect(args.db, timeout=10)
    conn.row_factory = sqlite3.Row

    where = "WHERE store_id = ? COLLATE NOCASE" if args.store else ""
    params = (args.store,) if args.store else ()

    total = conn.execute(f"SELECT COUNT(*) c FROM events {where}", params).fetchone()["c"]
    print(f"{args.db}\n{total} events stored" + (f" for {args.store!r}" if args.store else ""))
    print("-" * 108)

    recent = conn.execute(
        f"SELECT {COLS} FROM events {where} ORDER BY id DESC LIMIT ?",
        (*params, args.since),
    ).fetchall()
    for row in reversed(recent):
        print(fmt(row))

    last_id = recent[0]["id"] if recent else 0

    if args.once:
        return

    print("-" * 108)
    print(f"following (poll {args.interval}s, ctrl-c to stop)…")

    quiet = 0
    while True:
        time.sleep(args.interval)
        clause = f"WHERE id > ?" + (" AND store_id = ? COLLATE NOCASE" if args.store else "")
        rows = conn.execute(
            f"SELECT {COLS} FROM events {clause} ORDER BY id", (last_id, *params)
        ).fetchall()

        if rows:
            for row in rows:
                print(fmt(row))
            last_id = rows[-1]["id"]
            quiet = 0
        else:
            quiet += args.interval
            if quiet >= 30:
                print(f"   … nothing new for {int(quiet)}s")
                quiet = 0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
