"""Explain a gap between what a store measures live and what the dashboard shows
for one specific hour — e.g. an annotated video counts 33 INTERACTION in an hour,
the dashboard shows 5.

Read-only (SELECT only), safe to run against the live service.

    py audit_hour.py --store "Manar city" --date 2026-09-21 --hour 19
    py audit_hour.py --store "Manar city" --date 2026-09-21 --hour 19 --type ENTRY

It checks the three most likely causes, in order:

  1. TOTAL ROWS STORED for that hour, vs. distinct track_id.
     If the raw row count is already far below what was observed live, the
     events never reached the table at all — look at HTTP 422s in the day's
     log file (a batch is all-or-nothing: ONE malformed event in a batch drops
     every event in that same batch, per models.py's discriminated union).
     If the raw row count is close to what was observed but distinct track_id
     is much lower, deduplication (analytics._unique_tracks, keyed on
     (track_id, local day)) is legitimately collapsing repeated re-detections
     of the same few people — see how many rows share each track_id below.

  2. ADJACENT HOURS (hour-1, hour, hour+1). A spike next door to an
     otherwise-low target hour points at a timestamp/bucketing shift: a clock
     skew on the device, a UTC-vs-local mismatch, or db._with_wall_clock()
     reconstructing session-relative timestamps across an hour boundary.

  3. RAW ts SANITY. Flags any row whose ts is suspiciously small (session-relative,
     not real Unix time — see db.EPOCH_FLOOR) and shows the buffering lag
     (received_at - ts), the same way watch_events.py does.

This tool does NOT see events that failed validation (422) — those never reach
the table. Check the day's log file for those:
    Get-Content .\\logs\\crk-YYYY-MM-DD.log | Select-String "422"
"""

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

TZ_TUNIS = timezone(timedelta(hours=1))
EPOCH_FLOOR = 1_000_000_000  # see db.py — anything below this isn't real Unix time
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crk_analytics.db")


def hour_bounds(day: date, hour: int):
    start = datetime(day.year, day.month, day.day, hour, tzinfo=TZ_TUNIS)
    return start.timestamp(), (start + timedelta(hours=1)).timestamp()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.environ.get("CRK_DB_PATH", DEFAULT_DB))
    p.add_argument("--store", required=True, help="store name (case-insensitive)")
    p.add_argument("--date", required=True, help="AAAA-MM-JJ, local (Africa/Tunis) day")
    p.add_argument("--hour", type=int, required=True, help="0-23, local hour to inspect")
    p.add_argument("--type", default="INTERACTION", help="event_type to audit (default INTERACTION)")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"no database at {args.db}")

    day = date.fromisoformat(args.date)
    conn = sqlite3.connect(args.db, timeout=10)
    conn.row_factory = sqlite3.Row

    print(f"db      : {args.db}")
    print(f"store   : {args.store}")
    print(f"date    : {day}  (Africa/Tunis, fixed +01:00)")
    print(f"type    : {args.type}")

    # ------------------------------------------------------------- 1. raw vs dedup
    start_ts, end_ts = hour_bounds(day, args.hour)
    rows = conn.execute(
        """SELECT track_id, ts, received_at FROM events
           WHERE store_id = ? COLLATE NOCASE AND event_type = ?
             AND ts >= ? AND ts < ?
           ORDER BY ts""",
        (args.store, args.type, start_ts, end_ts),
    ).fetchall()

    distinct = {}
    for r in rows:
        distinct.setdefault(r["track_id"], 0)
        distinct[r["track_id"]] += 1

    print(f"\n--- 1. rows stored for {args.hour:02d}h-{args.hour+1:02d}h ---")
    print(f"  raw rows stored     : {len(rows)}")
    print(f"  distinct track_id   : {len(distinct)}  (this is what the dashboard counts)")
    if rows and len(distinct) < len(rows):
        print("  breakdown (track_id: occurrences), most repeated first:")
        for tid, n in sorted(distinct.items(), key=lambda kv: -kv[1])[:15]:
            print(f"    {tid!r:<10} x{n}")
    if not rows:
        print("  -> NOTHING reached the table for this hour at all.")
        print("     Check the log for 422s — a batch is all-or-nothing:")
        print(f'     Get-Content .\\logs\\crk-{day}.log | Select-String "422"')

    # --------------------------------------------------------- 2. adjacent hours
    print(f"\n--- 2. adjacent hours (catches a bucketing/clock shift) ---")
    for h in (args.hour - 1, args.hour, args.hour + 1):
        if h < 0 or h > 23:
            continue
        s, e = hour_bounds(day, h)
        n = conn.execute(
            """SELECT COUNT(*) c FROM events
               WHERE store_id = ? COLLATE NOCASE AND event_type = ?
                 AND ts >= ? AND ts < ?""",
            (args.store, args.type, s, e),
        ).fetchone()["c"]
        marker = "  <-- target hour" if h == args.hour else ""
        print(f"  {h:02d}h-{h+1:02d}h : {n:>4} rows{marker}")

    # ------------------------------------------------------------- 3. ts sanity
    print(f"\n--- 3. raw ts sanity (session-relative timestamps / buffering) ---")
    if not rows:
        print("  (no rows to check)")
    else:
        bad_epoch = [r for r in rows if r["ts"] < EPOCH_FLOOR]
        if bad_epoch:
            print(f"  {len(bad_epoch)} row(s) have ts < {EPOCH_FLOOR} -> NOT real Unix time.")
            print("  These went through db._with_wall_clock()'s reconstruction, which can")
            print("  shift events across an hour boundary. This is a strong lead if hour 2's")
            print("  adjacent-hour counts above show an unexplained spike.")
        else:
            print("  all rows carry real Unix time (>= EPOCH_FLOOR) — no reconstruction involved.")
        lags = [r["received_at"] - r["ts"] for r in rows]
        buffered = [l for l in lags if l > 1.5]
        print(f"  buffered (received_at - ts > 1.5s): {len(buffered)} / {len(rows)} row(s)")
        if buffered:
            print(f"    max buffering lag: {max(buffered):.1f}s")


if __name__ == "__main__":
    main()
