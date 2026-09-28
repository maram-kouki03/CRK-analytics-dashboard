# CRK Analytics — The Complete Course

### From the Jetson camera to the dashboard: understanding every layer of the system

---

> **Who this document is for**
>
> You, in six months, once you've forgotten why `pos.py` exists.
> Whoever picks up the project next.
> And above all: anyone who wants to understand **the general blueprint** of a
> product that combines embedded AI with ordinary software. CRK is just the
> pretext; the architecture itself is reusable as-is.
>
> The document is written like a course: it starts from the general principle,
> works down into the concrete details of the project, and every decision is
> justified. Whenever a lesson goes beyond CRK, it's flagged with a
> **"General lesson"** box.

---

## Table of Contents

| # | Chapter | What you'll learn |
|---|---|---|
| 0 | [The system map](#0-the-system-map) | One-page overview |
| 1 | [The AI + software architecture pattern](#1-the-ai--software-architecture-pattern) | The 5 layers, valid beyond CRK |
| 2 | [Layer 1 — The Jetson device](#2-layer-1--the-jetson-device-embedded-ai) | What the AI does, and what it's not allowed to do |
| 3 | [Layer 2 — Ingestion](#3-layer-2--ingestion-how-an-event-enters-the-system) | HTTP, API key, validation, clock realignment |
| 4 | [Layer 3 — The database](#4-layer-3--the-database-yes-there-is-one) | SQLite vs PostgreSQL, schema, index, WAL |
| 5 | [Layer 4 — Aggregation](#5-layer-4--aggregation-turning-rows-into-indicators) | Deduplication, timezone, `null` vs `0` |
| 6 | [The Joolan POS API](#6-the-joolan-pos-api) | Endpoints, constraints, cache, mapping |
| 7 | [The 6 "Sales Potential" KPIs](#7-the-6-sales-potential-kpis) | The formulas and their undefined cases |
| 8 | [Full reference of CRK endpoints](#8-full-reference-of-crk-endpoints) | Every route, parameter, response |
| 9 | [Layer 5 — The React frontend](#9-layer-5--the-react-frontend) | Structure, data flow, display rules |
| 10 | [Generative AI: the Gemini reports](#10-generative-ai-the-gemini-reports) | Prompt, guardrails, markdown → PDF |
| 11 | [The build: what `dist/` is for](#11-the-build-what-dist-is-for) | Vite, hashing, code splitting, same-origin |
| 12 | [Deployment: the `deploy/` folder](#12-deployment-the-deploy-folder) | install.ps1, scheduled task, firewall, logs |
| 13 | [The security model](#13-the-security-model) | What's protected, what isn't |
| 14 | [Operations and tooling](#14-operations-and-tooling) | The diagnostic scripts |
| 15 | [Actual measured state of the data](#15-actual-measured-state-of-the-data) | What the database really contains |
| 16 | [Known limitations and next steps](#16-known-limitations-and-next-steps) | What's left to do |
| A | [Appendices](#appendix-a--all-environment-variables) | Variables, glossary, decision log |

---

# 0. The system map

Before any detail, the 10,000-meter view. Five boxes, four arrows.

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  STORE                                                                   │
 │                                                                          │
 │   Camera  ─────►  NVIDIA Jetson device                                  │
 │                   (detection + tracking, embedded AI)                   │
 │                          │                                              │
 │                          │  decides: "this is an ENTRY"                 │
 └──────────────────────────┼──────────────────────────────────────────────┘
                            │
                            │  HTTP POST /ingest/batch
                            │  header : X-API-Key
                            │  body   : { "events": [ {...}, {...} ] }
                            ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  WINDOWS SERVER VM — a single process, a single port (8000)             │
 │                                                                          │
 │   ┌────────────┐  writes    ┌─────────────────────┐                     │
 │   │ main.py    │ ─────────► │  SQLite (WAL mode)  │                     │
 │   │ FastAPI    │            │  crk_analytics.db   │                     │
 │   │            │ ◄───────── │  events             │                     │
 │   └────────────┘   reads    │  pos_hourly         │                     │
 │         │                   └─────────────────────┘                     │
 │         │                             ▲                                 │
 │         │  aggregates at read time    │ POS cache                       │
 │         │  (analytics.py)             │                                 │
 │         │                   ┌─────────┴───────────┐   HTTPS             │
 │         │                   │ pos.py / joolan.py  │ ─────────►  Joolan  │
 │         │                   └─────────────────────┘  export-tickets.do  │
 │         ▼                                                                │
 │   GET /api/range · /api/comparison · /api/series · /api/stores          │
 │   GET /*  ───►  serves Dashboard/dist (the React build)                 │
 └──────────────────────────────────────────────────────────────────────────┘
                            │
                            │  fetch() with a relative URL
                            ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  BROWSER                                                                 │
 │   React + Recharts: Overview · Comparison · Reports                     │
 │                                        │                                │
 │                                        └──► Gemini API (AI reports)     │
 └──────────────────────────────────────────────────────────────────────────┘
```

**What to take away from this map:**

1. The AI lives **at the edge** (in the store), not in the center. The server
   never sees an image, only events that have already been interpreted.
2. There is **a single database**, and it's a file.
3. There is **a single server process**, which does three jobs: receive,
   compute, serve the web page.
4. The browser talks **only to that server** — except for the AI reports,
   where it calls Gemini directly from the browser.

---

# 1. The AI + software architecture pattern

This is the most important chapter if you want to reuse this knowledge
elsewhere.

Any product that combines an AI model with business software breaks down into
**five layers**. They're always the same, whatever the domain (retail,
industry, healthcare, security):

```
 ┌─────────────────────────────────────────────────────────────────┐
 │ 1. PERCEPTION      The model looks at the world and produces    │
 │                    discrete EVENTS.                             │
 │                    "a person entered at 2:32pm"                 │
 ├─────────────────────────────────────────────────────────────────┤
 │ 2. TRANSPORT       Events cross the network,                    │
 │                    authenticated and tolerant of failures.      │
 ├─────────────────────────────────────────────────────────────────┤
 │ 3. PERSISTENCE     We keep the RAW FACTS, never the             │
 │                    conclusions. One store, a minimal schema.    │
 ├─────────────────────────────────────────────────────────────────┤
 │ 4. AGGREGATION     Facts become INDICATORS,                     │
 │                    at read time, not at write time.             │
 ├─────────────────────────────────────────────────────────────────┤
 │ 5. RESTITUTION     Show the indicator, and above all show       │
 │                    WHEN YOU DON'T KNOW.                         │
 └─────────────────────────────────────────────────────────────────┘
```

The mapping onto CRK:

| Layer | Where it lives in this repo |
|---|---|
| 1. Perception | Jetson device in-store (outside the repo) |
| 2. Transport | `POST /ingest/batch` — [`main.py`](crk-backend/main.py), [`models.py`](crk-backend/models.py) |
| 3. Persistence | [`db.py`](crk-backend/db.py) → `crk_analytics.db` |
| 4. Aggregation | [`analytics.py`](crk-backend/analytics.py), [`pos.py`](crk-backend/pos.py), [`joolan.py`](crk-backend/joolan.py) |
| 5. Restitution | [`Dashboard/src/`](Dashboard/src) → React + Recharts |

### The three rules that govern the whole project

They come back in every chapter. Learn them now, you'll recognize them
everywhere.

> **Rule 1 — The boundary of judgment.**
> The AI judges ("this is a person, they're entering"). The software counts.
> The backend **never** re-judges a decision made by the model: it doesn't
> filter out interactions that are too short, it doesn't correct an
> implausible rate. If it did, nobody would know where the truth actually is
> anymore.

> **Rule 2 — Store the fact, compute at read time.**
> We don't store "340 customers on August 14th." We store 340 `ENTRY` rows.
> Changing a computation rule then becomes a code change, not a data
> migration. That's what allowed the deduplication rule to change several
> times without ever touching the historical data.

> **Rule 3 — The absence of a measurement must be visible.**
> An indicator that can't be computed is `null`, never `0`, and is displayed
> as `—`. Otherwise "nobody came in" becomes indistinguishable from "the
> camera was unplugged." This is THE rule that separates a trustworthy
> dashboard from a decorative one.

> **General lesson**
> These three rules aren't specific to CRK. They apply to any pipeline where
> a model produces observations that software has to synthesize. The day you
> see an architecture that stores pre-computed aggregates, or replaces
> missing values with zeros, you know it will lie sooner or later.

---

# 2. Layer 1 — The Jetson device (embedded AI)

## 2.1 What it does

An NVIDIA Jetson device is installed in the store, connected to a camera. It
runs a computer-vision pipeline locally:

```
   video stream
       │
       ▼
   person detection            (embedded detection model)
       │
       ▼
   multi-object tracking       (assigns a track_id to each tracked person)
       │
       ▼
   embedded business rules     (crossing a line = ENTRY,
       │                        sustained staff/customer proximity = INTERACTION)
       ▼
   emits JSON EVENTS
```

**No image ever leaves the store.** This is a major architectural choice:

- **Bandwidth**: an event is ~80 bytes, an image is 500 KB.
- **Privacy**: the server holds no biometric data at all. The only trace of a
  person is an integer (`track_id`) that gets reassigned regularly.
- **Resilience**: if the network goes down, the device keeps counting and
  buffers its events to send later.

> **General lesson — edge inference**
> Running the model at the edge rather than at the center changes everything
> else about the architecture: the server becomes a simple collector,
> bandwidth collapses, and the regulatory problem disappears. When designing
> a vision system, the first question is always: *where does the model run?*
> Everything else follows from that.

## 2.2 The event contract

The device emits three types of events, and nothing else. This contract is
defined server-side in **[`crk-backend/models.py`](crk-backend/models.py)**:

| Type | Fields sent | Meaning |
|---|---|---|
| `ENTRY` | `store_id`, `ts`, `track_id?` | a person entered |
| `INTERACTION` | `store_id`, `ts`, `track_id`, `duration_s?` | a staff member engaged with a customer |
| `HEARTBEAT` | `store_id`, `ts`, `seller_count` | the device's heartbeat |

Real payload example:

```json
{
  "events": [
    { "store_id": "Manar city", "event_type": "ENTRY",
      "ts": 1787845632.11, "track_id": 417 },
    { "store_id": "Manar city", "event_type": "INTERACTION",
      "ts": 1787845701.42, "track_id": 417, "duration_s": 23.5 },
    { "store_id": "Manar city", "event_type": "HEARTBEAT",
      "ts": 1787845710.00, "seller_count": 3 }
  ]
}
```

## 2.3 The ingestion tolerance principle

Look closely at this table, it's a subtle design point:

| Type / field | Accepted by the API? | Stored in DB? |
|---|---|---|
| `ENTRY` | yes | **yes** |
| `INTERACTION` | yes | **yes** |
| `HEARTBEAT` | yes | no |
| `duration_s` | yes | no |
| `seller_count` | yes | no |

Why accept what we don't keep? Because **rejecting an event would fail the
whole batch**. A batch can contain up to 1000 events: a `HEARTBEAT` rejected
with an HTTP 422 would lose 999 real measurements along with it.

```python
# db.py — only these two types are ever written
STORED_EVENT_TYPES = ("ENTRY", "INTERACTION")
```

`HEARTBEAT` gets a `200 OK`, and then vanishes. The device is happy, the
database stays clean.

Same logic for `duration_s`: the device applies its own minimum-duration rule
**itself** before emitting an `INTERACTION`. The backend counts whatever
arrives, it doesn't second-guess it (Rule 1).

> **General lesson — Postel's law**
> "Be liberal in what you accept, strict in what you produce." At the
> boundaries of a distributed system, input tolerance costs three lines of
> code and prevents silent data loss. Every ingestion API should be designed
> this way.

## 2.4 The history of formats (why the code still talks about `PEC`)

The device changed format partway through the project. You need to know this,
because the database contains both generations:

| Generation | Events emitted | Identity of a hand-off |
|---|---|---|
| **v1** (until late August 2026) | `ENTRY`, `PEC_START`, `PEC_END` | a `pec_id`, with a start/end pair |
| **v2** (current) | `ENTRY`, `INTERACTION`, `HEARTBEAT` | the person's `track_id` |

v2 is better: the device emits **only one line** per real hand-off, already
filtered on-device. The backend no longer has to pair up STARTs with ENDs, nor
handle STARTs with no END (a person detected, then lost track of). On the v1
data, there were **5,189 `PEC_START` for 1,750 `PEC_END`** — meaning 2/3 of the
candidate detections were not real hand-offs.

Concrete consequence: the `PEC_*` rows still sitting in the database **are no
longer counted at all**. The scripts [`migrate_db.py`](crk-backend/migrate_db.py)
and [`purge_db.py`](crk-backend/purge_db.py) exist to delete them rather than
show a history stuck at 0 interactions.

---

# 3. Layer 2 — Ingestion: how an event enters the system

## 3.1 The two routes

File: **[`crk-backend/main.py`](crk-backend/main.py)**

```python
@app.post("/ingest/event", dependencies=[Depends(verify_api_key)])
def ingest_event(event: IngestEvent):
    stored = db.insert_events_batch([event.model_dump()])
    return {"ok": True, "stored": stored}


@app.post("/ingest/batch", dependencies=[Depends(verify_api_key)])
def ingest_batch(batch: BatchRequest):
    events = [e.model_dump() for e in batch.events]
    inserted = db.insert_events_batch(events)
    return {"received": len(events), "inserted": inserted}
```

`/ingest/batch` is the route actually used: one HTTP call for up to 1000
events, instead of 1000 calls. The response returns **two** numbers —
`received` and `inserted` — and the gap between them is normal, not an error:
those are the discarded `HEARTBEAT`s.

## 3.2 Authentication: `CRK_API_KEY`

This is a **shared secret**. The same value exists in two places:

1. `crk-backend/.env`, on the VM
2. the configuration of **every** Jetson device

On every send, the device attaches the key in an HTTP header:

```http
POST http://192.168.2.210:8000/ingest/batch
X-API-Key: 9bcc4a25…………………
Content-Type: application/json

{ "events": [ … ] }
```

The backend compares it:

```python
def verify_api_key(x_api_key: str | None = Header(default=None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
```

**Why this is essential.** The `/ingest/*` routes **write to the database**.
Without a key, anyone reaching the port could inject thousands of fake events,
and there would be **no way at all** to tell real rows from fake ones after
the fact. The key guarantees one simple thing: only the devices you've
configured can write.

**Warning — it protects WRITES, not READS.** See
[chapter 13](#13-the-security-model), that's a deliberate choice.

### Changing the key: the three steps go together

1. new value in `crk-backend\.env`
2. restart the service
3. **the same** value on **every** Jetson device

> ⚠️ Changing only the server side **silently** stops all ingestion. The
> devices get `401`, and the data for that period is lost.
>
> Verification after a change:
> ```powershell
> Invoke-RestMethod "http://localhost:8000/api/last-seen?magasin=MANAR%20CITY"
> ```
> If `seconds_ago` keeps increasing past 30 minutes during opening hours, the
> devices are being rejected: the key differs on the two sides.

## 3.3 Validation: Pydantic and the discriminated union

```python
IngestEvent = Annotated[
    Union[EntryEvent, InteractionEvent, HeartbeatEvent],
    Field(discriminator="event_type"),
]

class BatchRequest(BaseModel):
    events: List[IngestEvent] = Field(..., max_length=1000)
```

`discriminator="event_type"` tells Pydantic: *read the `event_type` field
first, then validate against only the matching model.* Without this, Pydantic
would try all three models in sequence and produce unreadable error messages.

`max_length=1000` is a memory guardrail: a batch of ten million events would
blow up the process before it even reached the database.

## 3.4 Clock realignment (`_with_wall_clock`)

The real problem: **not every device sends the same kind of `ts`.**

- The preferred case: real **Unix time** (`1787845632.11`). It's trusted as-is
  — a batch buffered during a network outage keeps the instants the events
  **actually** happened at.
- The degraded case: **seconds since the device booted** (`142.7`).

How do you tell the two apart? By order of magnitude:

```python
EPOCH_FLOOR = 1_000_000_000   # ≈ September 2001

def _with_wall_clock(events, received_at):
    if all(e["ts"] >= EPOCH_FLOOR for e in events):
        return events                      # real time: leave it untouched

    anchor = max(e["ts"] for e in events)  # the most recent event in the batch
    return [
        {**e, "ts": received_at - (anchor - e["ts"])}
        for e in events
    ]
```

The reconstruction anchors **the most recent event in the batch** to the
moment it was received, and shifts all the others backward while keeping
their relative spacing. A batch of 50 events spread over 20 minutes stays
spread over 20 minutes, instead of collapsing onto a single second.

> This is a **reconstruction, not a measurement**. It assumes the last event
> in the batch just happened — a false assumption if the device restarted
> mid-batch. Sending Unix time avoids the whole problem: that's what should be
> requested from the Jetson team.

A subtle, deliberate ordering detail:

```python
received_at = time.time()
resolved = _with_wall_clock(events, received_at)   # 1. realignment
rows = [... for e in resolved
        if e["event_type"] in STORED_EVENT_TYPES]  # 2. filtering
```

**Realignment happens before filtering.** Because the anchor is "the most
recent event in the batch," and a `HEARTBEAT` — discarded afterward — could
very well be the most recent one. Filtering first would shift the entire
batch into the past.

---

# 4. Layer 3 — The database (yes, there is one)

> This is the question you were asking. Short answer: **yes, there's a real
> SQL database.** It's called SQLite.

## 4.1 "No PostgreSQL" ≠ "no database"

This is the most common confusion. The project uses **SQLite**, which is a
real SQL database: real tables, real indexes, real ACID transactions, real
SQL. Every query the dashboard runs is a `SELECT … WHERE … GROUP BY` against
this database.

Measured state on the local copy of the repo:

```
SQLite version : 3.49.1 (bundled with Python)
file           : crk-backend/crk_analytics.db
rows           : 7,601 events
size           : 946 KB
index          : idx_store_ts on (store_id, ts)
mode           : WAL
```

## 4.2 The real difference: a SERVER vs. a FILE

| | PostgreSQL / MySQL | SQLite |
|---|---|---|
| What it is | a **program** that runs permanently | a **file** the program reads directly |
| To install | server + user + password + port | nothing, it ships with Python |
| Where data lives | inside the server's internal storage | inside `crk_analytics.db` |
| Backing up | `pg_dump`, a dedicated tool | copy the file |
| Moving it | export then import | copy the file |

That last row is something we actually lived through: to recover the history
from the old `Wisevision` folder into the new one, a plain `Copy-Item` of the
file was enough. With PostgreSQL it would have taken a dump, a restore, and
recreating users and permissions.

## 4.3 Why SQLite is the right choice HERE

- **A single writer.** Only the backend writes to the database. This is
  exactly the use case where SQLite excels.
- **Small volume.** ~350 events per day per store. With 8 stores, that's about
  1 million rows per year. SQLite handles hundreds of millions of rows
  without breaking a sweat.
- **The index does the work.** The `(store_id, ts)` index matches exactly the
  question the dashboard asks: *"this store, between these two dates."*
  Instant answer.
- **WAL mode lets you read while writing.** That's why running
  `watch_events.py` doesn't disturb the service, and why the current backend
  can read a database that another process is feeding.
- **Fewer things that can break.** No server to start, no port to fight over,
  no password to lose. Given the time spent on port and service conflicts
  during deployment, that's not a minor detail.

### WAL mode, in one picture

```
   Classic mode (rollback journal)        WAL mode
   ──────────────────────────────         ────────────────────────────────
   The writer LOCKS the database.         The writer writes to a side
   Readers wait.                          file (.db-wal).
                                          Readers keep reading the main
                                          database file the whole time.
```

Practical consequence: the database is actually **three files** —
`crk_analytics.db`, `.db-wal`, `.db-shm`. For a hot backup, all **three** need
to be copied, or the service stopped first.

## 4.4 The schema

File: **[`crk-backend/db.py`](crk-backend/db.py)**

```sql
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id     TEXT    NOT NULL,   -- "Manar city", exactly as the device writes it
    event_type   TEXT    NOT NULL,   -- 'ENTRY' | 'INTERACTION'
    ts           REAL    NOT NULL,   -- Unix time, after realignment
    track_id     INTEGER,            -- identity of the tracked person
    received_at  REAL    NOT NULL    -- moment the server received the batch
);

CREATE INDEX IF NOT EXISTS idx_store_ts ON events(store_id, ts);
```

**Six columns. That's it.** Every column exists because some calculation
actually uses it:

| Column | Who uses it |
|---|---|
| `store_id` | filtering by store, `resolve_store()` |
| `event_type` | separating customers / hand-offs |
| `ts` | hourly, daily, and heatmap bucketing |
| `track_id` | deduplicating people ([§5.2](#52-deduplication-the-heart-of-the-count)) |
| `received_at` | `last-seen` diagnostic, measuring a batch's lag |
| `id` | technical primary key |

The second table is a **cache**, not a source of truth:

```sql
CREATE TABLE IF NOT EXISTS pos_hourly (
    store_id   TEXT    NOT NULL,
    date       TEXT    NOT NULL,   -- YYYY-MM-DD, store's local time
    hour       INTEGER NOT NULL,   -- 0..23 ; -1 if the header has no readable hour
    tickets    INTEGER NOT NULL,
    revenue    REAL    NOT NULL,
    source     TEXT    NOT NULL,   -- 'joolan' | 'simulation'
    fetched_at REAL    NOT NULL,
    PRIMARY KEY (store_id, date, hour)
);
```

It's explained in [chapter 6](#6-the-joolan-pos-api).

## 4.5 The minimal schema is a decision, not laziness

The old version of the table had **ten columns**: `pec_id`, `duration_s`,
`seller_count`, `zone_id` in addition. All were removed because
**no displayed indicator was using them**.

The benefit isn't disk space (a few tens of KB), it's:

1. **An easy future migration.** Six columns to PostgreSQL is an afternoon of
   work, not a rewrite.
2. **No false promise.** A column present in a schema is a column somebody
   will believe they can rely on.

Detecting the old schema happens at startup, but **migration is never
automatic**:

```python
legacy = db.legacy_columns_present()
if legacy:
    print(f"[crk] legacy schema detected (columns: {', '.join(legacy)})")
    print("[crk] -> reads OK, but run `py migrate_db.py` to clean up")
```

Why not migrate automatically? Because the database might be shared with
another service still writing those columns, and deleting them out from under
it would break it. **A destructive operation must never be a side effect of
startup.**

## 4.6 When you WILL have to move to PostgreSQL

As soon as **any single one** of these conditions becomes true:

1. **Several machines** writing to the same database.
2. **Several services** writing at the same time (not just the backend).
3. Tens of millions of rows **and** queries that are getting slow.
4. A need for replication or a hot standby server.

Today, none of these apply.

> **General lesson — choosing your database**
> The question isn't "which database is the most powerful" but "**how many
> concurrent writers, and across how many machines?**" A single writer on one
> machine → SQLite is enough and removes an entire class of operational
> problems. Multiple writers or multiple machines → you need a database
> server. Everything else (volume, indexes, transactions) is secondary to
> that one question.

## 4.7 A housekeeping note

The database also contains two leftovers from earlier versions:
- `store_config` (8 rows, `panier_moyen` per store) — **no code reads it**;
- `pos_daily` (22 rows) — replaced by `pos_hourly` once we discovered Joolan
  really did return an hour.

They don't get in the way of anything and can be dropped during a cleanup.

---

# 5. Layer 4 — Aggregation: turning rows into indicators

File: **[`crk-backend/analytics.py`](crk-backend/analytics.py)** (588 lines,
the intellectual core of the backend).

## 5.1 Aggregation at read time

**Nothing is pre-computed.** Every HTTP request re-reads the raw events for
the requested window and recalculates everything:

```python
start_ts, _ = _day_bounds(d1)
_, end_ts   = _day_bounds(d2)
events = db.get_events_in_range(store_id, start_ts, end_ts)
# … then every indicator is derived from `events`
```

At this volume, with the `(store_id, ts)` index, it's instant. And the payoff
is huge: **changing a computation rule requires no data migration at all.**

## 5.2 Deduplication: the heart of the count

This is the finest-grained passage in the project. It's worth reading twice.

**The problem.** The `track_id` the tracker assigns is unique **neither over
time nor within a day**.

- **Within a day**, the same track reappears when the tracker loses and then
  re-finds the person (they walk behind a display stand, leave the frame).
  Measured on MANAR CITY: **54 repeats out of 658 entries**, median gap
  **10.7 s**, 50 of the 54 under 60 s. These are re-detections of a single
  person, not second entries — counting them separately inflated the total by
  **+8.2 %**.
- **From one day to the next**, the number gets reassigned: the tracker's
  counter restarts low every time the device reboots, and one identifier
  reappeared as much as **90 hours** later. Counting distinct `track_id`s
  without accounting for the day would have wrongly merged them: **−8.4 %**
  on the historical data.

**The fix:** a composite key `(track_id, local day)`.

```python
def _unique_tracks(events, event_type: str) -> dict:
    """{(track_id, local day): earliest ts} — one entry per real person."""
    first = {}
    for index, e in enumerate(events):
        if e["event_type"] != event_type:
            continue
        track_id = e["track_id"]
        key = (track_id, _local_day(e["ts"])) if track_id is not None else ("?", index)
        if key not in first or e["ts"] < first[key]:
            first[key] = e["ts"]
    return first
```

Three properties worth noticing:

1. **The day in the key merges** the within-day re-detections and
   **separates** the across-day reassignments. One line of code solves two
   opposite problems at once.
2. **An event with no `track_id`** gets a key of its own (`("?", index)`): it
   is counted **once** instead of being lost.
3. **We keep the earliest `ts`**: the person is tied to the moment they
   **appeared**, not to their last re-detection.

**A valuable corollary:** a batch resent by the device (network timeout,
retry) reproduces exactly the same keys. It can therefore **never** inflate a
total. The count is *idempotent*.

> **General lesson — identity in a tracking pipeline**
> An identifier produced by a tracker is **never** a primary key. It's local
> to a session, recycled, and unstable. Any aggregation that counts distinct
> `track_id`s without bounding them in time is wrong. The question to always
> ask: *"over what window is this identifier guaranteed to be unique?"* — and
> put that window into the key.

## 5.3 Time: a fixed timezone, chosen on purpose

```python
TZ_TUNIS = timezone(timedelta(hours=1))
```

Africa/Tunis, **fixed +01:00, no daylight saving**. Two reasons:

1. `zoneinfo` relies on the IANA database, which **Windows doesn't ship** by
   default. A fixed offset removes the dependency.
2. Without DST, **a local day is exactly 86,400 s** — which is exactly what
   the daily bucketing depends on:

```python
def _bucket_by_day(events, day_start_ts, nb_jours):
    buckets = [[] for _ in range(nb_jours)]
    for e in events:
        offset = int((e["ts"] - day_start_ts) // 86400)   # ← only true without DST
        if 0 <= offset < nb_jours:
            buckets[offset].append(e)
    return buckets
```

## 5.4 The hourly window: derived from the data, not imposed

```python
CRK_OPEN_HOUR  = 9   # (10 in production, see .env)
CRK_CLOSE_HOUR = 20  # (22 in production)
```

These are **not hard bounds**, but a **minimum display range** — to keep a
stable scale from one period to another. The window **expands** to fit any
hour actually observed:

```python
debut = min([DEFAULT_OPEN_HOUR, *heures])
fin   = max([DEFAULT_CLOSE_HOUR, *heures])
return list(range(debut, fin + 1))
```

Previously, any event outside the range was **folded** onto the limit hour: a
hand-off at 9:30pm was counted at 8pm. That was wrong, and it hid the very
fact that the store was closing later than expected.

Accepted consequence: an isolated event at 3am stretches the axis out to 3am.
**That's intentional** — the anomaly should be visible, not diluted into the
first bucket.

Technical corollary: since no event is ever folded, **an hourly total is
always exactly equal to the KPI for the period**. The two views can never
contradict each other.

## 5.5 Footfall KPIs

```python
def compute_kpis(events, nb_jours):
    clients   = len(_unique_tracks(events, "ENTRY"))
    pec_count = len(_unique_tracks(events, "INTERACTION"))
    return {
        "clients_entres":   clients,
        "clients_par_jour": round(clients / nb_jours, 1) if nb_jours else None,
        "pec_count":        pec_count,
        "taux_pec":         round(pec_count / clients * 100, 1) if clients else None,
        "evenements":       len(events),
    }
```

Notice the repeated `X if Y else None` pattern — that's Rule 3 applied
mechanically: **never a division by zero disguised as `0`**.

`evenements` exists for diagnostics: it lets the frontend say "no events
received" instead of showing silent zeros.

## 5.6 The other aggregates

| Function | What it produces | Used by |
|---|---|---|
| `_hourly()` | customers / hand-offs / rate per hourly bucket | 3 charts on the Overview page |
| `_heatmap()` | hour × weekday matrix | heatmap |
| `_bucket_by_day()` | events grouped by local day | daily evolution |
| `_series_buckets()` | 7 days / 8 weeks / 6 months | `/api/series` |
| `build_range_response()` | **everything** the Overview page draws | `/api/range` |
| `build_comparison_response()` | one row per store | `/api/comparison` |

An important point about `_hourly()`: it redistributes **the same
deduplicated sets** as `compute_kpis`, not the raw events. Otherwise the
hourly bars wouldn't sum to the period's KPI, and the dashboard would
contradict itself.

## 5.7 The "vs previous period" comparison

```python
prev_first = d1 - timedelta(days=nb_jours)
prev_events = db.get_events_in_range(store_id, prev_start_ts, prev_end_ts)
kpis_prec = compute_kpis(prev_events, nb_jours) if prev_events else None
```

The previous window has **exactly the same length**. And if it's empty, we
return `None` — not zeros. The dashboard then **hides** the delta badge,
instead of announcing a meaningless "+100 %" jump.

---

# 6. The Joolan POS API

So far, everything came from the device. To compute a conversion rate, you
need the other half: **what was actually sold**. That comes from the point of
sale, via the Joolan API.

## 6.1 What Joolan is

Joolan is CRK's point-of-sale software (a retail ERP). It exposes a **REST API
v2** documented in the [`swagger.yaml`](swagger.yaml) file at the repo root —
4,000 lines, roughly thirty endpoints (stock, customers, tickets, products,
logistics, B2B trade…).

**We use exactly one of them:** `/export-tickets.do`.

### Joolan authentication

Nothing to do with our own `X-API-Key`. Joolan authenticates **via URL
parameters**:

```
GET https://{domain}/api/v2/export-tickets.do
    ?enseigne={brand}
    &api-key={key}
    &Date=YYYY-MM-DD
```

Three pieces of information are needed, and they live in `crk-backend/.env`:

| Variable | Role | Production value |
|---|---|---|
| `CRK_JOOLAN_DOMAIN` | the brand's domain | `caisse.oopos.fr` |
| `CRK_JOOLAN_ENSEIGNE` | the database name | `CRK` |
| `CRK_JOOLAN_API_KEY` | the key, with the `api_export_tickets` permission | *(secret, in `.env`)* |

> **The Joolan permissions trap.** The spec ties each endpoint to an
> `api_<permission>` column in the `api_keys` table. A **valid** key without
> `api_export_tickets` returns `invalid api key` — a misleading message, since
> the key isn't actually invalid, it's just not authorized for this endpoint.

### The response

```json
{
  "result": "ok",
  "data": {
    "entetes":    [ { "Entete": 12345, "Magasin": "CRK Manar City",
                      "Date": "2026-08-14", "Heure": "20:28:22",
                      "Nature": "VENTE", "Total_TTC": 149.90 } ],
    "lignes":     [ { "Entete": 12345, "Produit": "SAC-001",
                      "Quantite": 1, "Prix_Vente": 149.90 } ],
    "reglements": [ { "Entete": 12345, "Mode": "CB", "Montant": 149.90 } ]
  }
}
```

On rejection, Joolan responds with **HTTP 400** and an explicit JSON body:

```json
{ "result": "ko", "error_message": "invalid api key" }
```

We only use `entetes` (headers): one ticket = one header. `lignes` (line-item
detail) and `reglements` (payment method) don't feed any current indicator.

## 6.2 The three API properties that dictate the whole design

This is the passage to remember: **the cache architecture isn't a whim, it's
imposed by the shape of the remote API.**

### Property 1 — One day per call

`export-tickets.do` takes a **required** `Date` parameter. No range.

→ A 30-day period would require **30 HTTP calls**. Without a cache, every
dashboard refresh would fire all of them again. Hence the `pos_hourly` table.

### Property 2 — One call returns ALL stores

The `Magasin` field on each header lets you break it down.

→ So we call it **once per date, never per store**. A week for the 8 stores
costs **7 requests, not 56**. And the Comparison page costs nothing more than
the Overview page, since the cache is filled for all 8 in one go.

```python
for store in db.STORE_NAMES:
    heures = par_magasin.get(joolan.magasin_joolan(store), {})
    # … all 8 stores get cached from the same call
```

### Property 3 — The hour IS returned (discovered empirically)

The swagger doesn't document **any** response field: the schema just says
`type: object`. The example shows only 5 fields, no `Heure`.

It was the script [`inspect_joolan.py`](crk-backend/inspect_joolan.py) that
settled the question by actually calling the API: the `Heure` field
(`"20:28:22"`) is present on **332 headers out of 332**.

→ Revenue **per hour** is therefore *measurable*, not reconstructed. That's
what allowed the move from `pos_daily` to `pos_hourly`, and the ability to
chart potential, opportunity gap, and capture rate **hour by hour**.

> **General lesson — the spec isn't reality**
> API documentation describes what the vendor took the time to write down,
> not what the server actually returns. Before designing around an assumed
> constraint ("there's no hour field"), **make a real call and look**. Cost: a
> 200-line script. Payoff here: an entire dimension of analysis.

## 6.3 The client: `joolan.py`

**Zero added dependency.** The standard library's `urllib` is enough for a GET
— the VM doesn't need to install anything.

```python
def fetch_day(date_iso: str) -> dict:
    """{store_code: {hour: {"tickets": int, "revenue": float}}} for this date."""
```

Design points worth noting:

**1. Never silent zeros.** Any error raises a `JoolanError`.

```python
class JoolanError(RuntimeError):
    """Joolan call impossible or refused. Never silent: bubbled up."""
```

An `except: return {}` would have produced 0 DT revenue, indistinguishable
from a day with no sales at all. This is Rule 3 applied to a network call.

**2. The API key is masked in logs.**

```python
def _masque(url: str) -> str:
    return url.replace(API_KEY, "***") if API_KEY else url
```

Without this, the production key would end up in plaintext in
`logs/crk-2026-09-06.log`.

**3. Mapping store names.** Our names aren't Joolan's:

```
CRK_JOOLAN_MAGASINS={"MANAR CITY":"CRK Manar City"}
```

Without this mapping, every store would show **0 tickets and 0 DT** — and
nothing on screen would explain why. This is the #1 trap in this kind of
integration.

**4. Filtering by `Nature`.**

```python
NATURES = ("VENTE",)   # configurable via CRK_JOOLAN_NATURES
```

A header whose `Nature` isn't in the list is ignored (credit note, transfer,
till opening/closing…). **Still to confirm with CRK**: the possible values,
and whether returns should be counted as negative — that would change
revenue, average basket, and the capture rate.

**5. The hour extracted with a regular expression.**

```python
_MOTIF_HEURE = re.compile(r"([01]?\d|2[0-3]):[0-5]\d")
```

It accepts `"20:28:22"` just as well as `"2026-08-21 20:28:22"`. A header
whose hour is unreadable isn't lost: it gets the conventional hour `-1`,
counted in the **day's total** without being attributed to any bucket.

## 6.4 The switchboard: `pos.py`

This module decides **where** tickets and revenue come from, and it **always
says so**:

```
Joolan configured (all 3 CRK_JOOLAN_*)  ->  real API, source = "joolan"
otherwise                               ->  simulation,  source = "simulation"
```

The `simule` flag bubbles all the way up to the dashboard, which shows an
**orange banner** as long as it's `true`.

> **General lesson — a simulated value must denounce itself**
> An unmeasured number that looks like a measured one is worse than no number
> at all. If you have to simulate to ship, then: (a) isolate all of the
> provisional logic in **one single file**, (b) bubble a provenance flag
> **all the way to the screen**, (c) display it in a way that's impossible to
> miss. All three, not two out of three.

### The cache refresh logic

This is the most subtle passage in `pos.py`:

```python
def _a_recharger(jour, vu, source_voulue) -> bool:
    if vu is None or vu["source"] != source_voulue:
        return True
    return vu["lu_a"] < _fin_de_journee(jour)
```

Three cases trigger a reload:

1. **Never read before.**
2. **Read from a different source** — this is what allows a clean switch from
   simulation to Joolan.
3. **Read BEFORE the day ended**, and therefore necessarily incomplete.

The third case is the trap. A day checked at 2pm doesn't contain the evening's
sales. Without this test, it would stay **frozen at 2pm forever**: an entire
evening's worth of revenue would silently disappear, including for the
current day once the next day arrived.

### Delete before rewriting

```python
db.delete_pos_days(store_id, chargees)   # ← essential
db.put_pos_hours(nouveaux)               # INSERT OR REPLACE
```

`INSERT OR REPLACE` alone deletes nothing: an hour that **no longer** has a
sale (a cancelled ticket) would keep its old value forever. So the whole day
is wiped before being rewritten.

### A failed day is never cached

```python
except joolan.JoolanError as exc:
    print(f"[crk] pos {jour} unavailable: {exc}", flush=True)
    echecs.append(jour)
    continue
```

The day goes into `joursManquants`, surfaced up to the dashboard which shows a
banner: *"Joolan didn't respond for: … Revenue for the period is
understated."* A hidden zero would read as "no sales."

### The zero row: a cache subtlety

```python
if not heures:
    lignes.append((store, jour, HEURE_INCONNUE, 0, 0.0, "joolan"))
```

If a store has no sales that day (closed store, or `Magasin` code not yet
mapped), a zero row is written **anyway**. Without it, the cache would stay
empty for that store and Joolan would be re-called **on every single page
load**. It adds nothing to the totals and doesn't show up in any hourly
bucket.

### The simulation's deterministic generator

Even while simulating, values aren't drawn randomly on every call:

```python
def _rng(store_id, jour, heure):
    cle = f"{store_id}|{jour}|{heure}".encode()
    return random.Random(int(hashlib.sha256(cle).hexdigest()[:12], 16))
```

Same store + same hour ⇒ **same numbers**. Without this, every refresh would
produce a different revenue figure and the "vs previous period" deltas would
be meaningless.

## 6.5 The full POS flow, in one picture

```
  /api/range requested for MANAR CITY, 08/05 → 08/14 (10 days)
        │
        ▼
  pos.fetch_pos_data()
        │
        ├─ reads pos_hourly for these 10 days
        │
        ├─ for each day, _a_recharger() ?
        │      never read? source changed? read before midnight?
        │
        ├─ days needing a reload ──► joolan.fetch_day("2026-08-14")
        │                              │  1 HTTPS call = ALL stores
        │                              ▼
        │                        {"CRK Manar City": {11: {tickets:2, revenue:508.0},
        │                                            12: {...}, ...},
        │                         "other store":     {...}}
        │                              │
        │                              ▼
        │                        delete_pos_days() then put_pos_hours()
        │                        (all 8 stores at once)
        │
        ▼
  {tickets: 303, revenue: 74712.12, par_heure: {...},
   simule: false, source: "joolan", jours_manquants: []}
```

## 6.6 The reverse path (not implemented)

The same API exposes `/import-compteurs-passages.do` (permission
`api_compteurs_passages`), which accepts `Magasin`, `Date`, `Heure`,
`Compteur`, `Entrees`, `Sorties`.

We could therefore **push our camera counts into Joolan**, where management
would see footfall and sales side by side in the tool they already use. Not
implemented, but the API is there and the direction makes sense: we're the
ones producing the footfall data.

Another convenience path: the `api_query` permission grants access to
`/query.do`, which accepts read-only SQL — enough to aggregate an entire
period in **a single call** instead of one per day. The cache makes this
optional, and it's a broad privilege that CRK may not want to grant.

---

# 7. The 6 "Sales Potential" KPIs

Spec: `CRK_Dashboard_Sales_Potential_KPIs.pdf` (WiseVision AI).
Implementation: `analytics.compute_ventes()`.

## 7.1 The four base quantities

| Symbol | Quantity | Source |
|---|---|---|
| **V** | visitors | Jetson (deduplicated `ENTRY`) |
| **A** | visitors engaged | Jetson (deduplicated `INTERACTION`) |
| **T** | tickets | POS (Joolan) |
| **R** | revenue | POS (Joolan) |

**The first two come from the camera, the last two from the till.** The
whole point of the dashboard is right there: cross-referencing two
independent sources.

## 7.2 The six formulas

| # | Indicator | Formula | `null` if |
|---|---|---|---|
| 1 | `conversion_rate` | T / V × 100 | V = 0 |
| 2 | `average_basket` | R / T | T = 0 |
| 3 | `pec_rate` | A / V × 100 | V = 0 |
| 4 | `sales_potential` | V × (CR_target / 100) × AB_reference | — |
| 5 | `opportunity_gap` | max(potential − R, 0) | — |
| 6 | `opportunity_capture_rate` | R / potential × 100 | potential = 0 |

## 7.3 The two business reference values

```python
CR_TARGET_PCT = float(os.environ.get("CRK_CR_TARGET_PCT", "20"))   # conversion target, %
AB_REFERENCE  = float(os.environ.get("CRK_AB_REFERENCE", "290"))   # reference basket, DT
```

These are **not simulated values**: they're **business parameters** supplied
by CRK, adjustable via environment variable without touching the code.

They deliberately live in `analytics.py`, **next to the formula that consumes
them**, and not in `pos.py`: `pos.py` is the provisional file that will
disappear along with the simulation, and these reference values need to
outlive it.

> **General lesson — where to put a constant**
> A constant belongs next to the **calculation that uses it**, not next to
> the data it happens to resemble. Put it with the data instead, and it will
> vanish the day that data changes source.

## 7.4 The adjustable target from the UI

```python
def parse_objectif(value) -> float:
    if value is None:
        return CR_TARGET_PCT
    pct = float(value)
    if not 0 <= pct <= 100:
        raise BadRequest("objectif doit être compris entre 0 et 100")
    return pct
```

The dashboard lets management move this target on the fly (the
`ObjectifPicker` component). **This isn't a measurement, it's a working
hypothesis**, and watching the potential shift along with it is exactly the
point.

A point of rigor: when computing the previous period for the delta, **the
same target** is used — otherwise the "vs previous period" gap would be
comparing two different hypotheses.

## 7.5 Hourly consistency

A single definition of the potential serves both the whole period **and**
each hourly bucket:

```python
def _potentiel(visiteurs, cr_target_pct):
    return visiteurs * (cr_target_pct / 100) * AB_REFERENCE
```

Since the formula is linear in V, **the sum of the hourly potentials is
exactly the potential for the period**. The two views of the same number can
never diverge.

On the other hand, the two measurements for a given bucket don't come from
the same source: an hour can have sales with no visitor counted (a camera
glitch) or the reverse. **Nothing is corrected** — that's exactly what needs
to be seen.

---

# 8. Full reference of CRK endpoints

Production base URL: `http://<vm-ip>:8000`
Auto-generated interactive docs (FastAPI): `/docs`

## 8.1 Ingestion — `X-API-Key` required

### `POST /ingest/event`

A single event.

```http
POST /ingest/event
X-API-Key: <key>
Content-Type: application/json

{ "store_id": "Manar city", "event_type": "ENTRY", "ts": 1787845632.11, "track_id": 417 }
```

Response: `{ "ok": true, "stored": 1 }` — `stored: 0` for a `HEARTBEAT`
(accepted, not kept).

### `POST /ingest/batch`

Up to 1000 events. **This is the route to use.**

```http
POST /ingest/batch
X-API-Key: <key>
Content-Type: application/json

{ "events": [ {...}, {...}, ... ] }
```

Response: `{ "received": 42, "inserted": 40 }`

### Ingestion error codes

| Code | Cause | What to do |
|---|---|---|
| `401` | missing or mismatched key | compare `.env` against the device's config |
| `422` | malformed event (unknown type, missing required field) | **the entire batch is rejected** — fix the sender |
| `404` | route misspelled (`/ingest/batches`) | 404 JSON, never HTML |

## 8.2 Reads — public

### `GET /api/stores`

No parameters. The list is authoritative in `db.STORE_NAMES`.

```json
{
  "stores": [
    { "nom": "Tunisia Mall", "aDonnees": false, "dernierEvenementTs": null },
    { "nom": "MANAR CITY",   "aDonnees": true,  "dernierEvenementTs": 1787845632.11 }
  ]
}
```

`dernierEvenementTs` lets the dashboard open on the store that is **actually
active**, rather than the first one in the list (which could have been silent
for weeks and make the dashboard look broken).

### `GET /api/range` — the main endpoint

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `magasin` | string | yes | store name (case-insensitive) |
| `du` | `YYYY-MM-DD` | yes | first day, inclusive |
| `au` | `YYYY-MM-DD` | yes | last day, inclusive |
| `objectif` | number 0-100 | no | conversion target, in % |

A reversed range is **put back the right way**. Beyond 400 days, it's
rejected (`400`).

Structure of the response (this is *everything* the Overview page draws). The
values below are **illustrative**: the cash-register figures are the ones
actually measured on MANAR CITY (Aug 5→14), the footfall figures are a
coherent example — the actually measured hand-off rate exceeds 100 %, see
[§15.4](#154-the-known-measurement-anomaly).

```jsonc
{
  "magasin": "MANAR CITY",
  "periode": { "du": "2026-08-05", "au": "2026-08-14", "nbJours": 10 },

  "kpis": {                       // measured by the device
    "clients_entres": 658, "clients_par_jour": 65.8,
    "pec_count": 412, "taux_pec": 62.6, "evenements": 1204
  },
  "kpisPrecedent": { ... } | null,   // null if the previous window is empty

  "ventes": {                     // camera x POS cross-reference
    "visiteurs": 658, "pris_en_charge": 412,
    "tickets": 303, "revenue": 74712.12,
    "conversion_rate": 46.0, "average_basket": 246.57, "pec_rate": 62.6,
    "sales_potential": 38164.0, "opportunity_gap": 0.0,
    "opportunity_capture_rate": 195.8,
    "cr_target_pct": 20, "ab_reference": 290,
    "simule": false, "source": "joolan", "joursManquants": [],
    "parHeure": [ { "h": "11h", "visiteurs": 42, "tickets": 2,
                    "revenue": 508.0, "potentiel": 2436.0,
                    "manque": 1928.0, "captation": 20.9,
                    "conversion": 4.8 }, ... ]
  },
  "ventesPrecedent": { ... } | null,

  "heureDePointe":  [ { "h": "10h", "clients": 12 }, ... ],
  "pecParHeure":    [ { "h": "10h", "pec": 8 }, ... ],
  "tauxParHeure":   [ { "h": "10h", "taux": 66.7 } | { "h": "03h", "taux": null }, ... ],
  "evolutionJours": [ { "date": "2026-08-05", "label": "05/08", "jour": "Wed",
                        "clients": 71, "pec": 44, "taux": 62.0 }, ... ],
  "heatmap": { "heures": ["10h", ...], "jours": ["Mon", ...],
               "data": [[...]], "max": 23 }
}
```

### `GET /api/dashboard`

Single-day shortcut: `magasin`, `date`, `objectif?`. **Same response shape**
as `/api/range` (it's literally `build_range_response(store, date, date)`).

### `GET /api/comparison`

Parameters: `du`, `au`. One aggregated row **per store**.

```jsonc
{
  "periode": { "du": "...", "au": "...", "nbJours": 10 },
  "magasins": [
    { "nom": "MANAR CITY", "aDonnees": true,
      "clients_entres": 658, "clients_par_jour": 65.8,
      "pec_count": 412, "taux_pec": 62.6, "evenements": 1204,
      "revenue": 74712.12, "sales_potential": 38164.0,
      "opportunity_gap": 0.0, "opportunity_capture_rate": 195.8,
      "ventesSimulees": false }
  ],
  "evolutionJours": [
    { "label": "05/08", "date": "2026-08-05",
      "MANAR CITY": 62.0, "Tunisia Mall": null, ... }   // hand-off rate per store
  ]
}
```

### `GET /api/series`

| Parameter | Values | Meaning |
|---|---|---|
| `magasin` | string | required |
| `periode` | `jour` \| `semaine` \| `mois` | granularity |
| `fin` | `YYYY-MM-DD` | **required** — last point of the series |

The number of points depends on the granularity:

| `periode` | Points returned |
|---|---|
| `jour` | last 7 days (`fin` included) |
| `semaine` | last 8 weeks (Monday → Sunday) |
| `mois` | last 6 calendar months |

```json
{ "magasin": "MANAR CITY", "periode": "jour", "fin": "2026-08-14",
  "points": [ { "label": "08/08", "du": "2026-08-08", "au": "2026-08-08",
                "clients": 71, "pec": 44, "taux": 62.0 } ] }
```

## 8.3 Diagnostics

### `GET /api/health`

```json
{ "status": "ok", "db": "ok", "events_total": 7601 }
```

This is the endpoint `install.ps1` queries at the end of installation.

### `GET /api/last-seen?magasin=…`

```json
{ "store_id": "MANAR CITY", "last_event_ts": 1787845632.11,
  "last_received_at": 1787845640.03, "seconds_ago": 812 }
```

**The #1 tool for checking whether a device is still transmitting.**
`seconds_ago` exceeding 30 minutes during opening hours = a problem (network,
device powered off, or a mismatched API key).

## 8.4 The static dashboard — the catch-all route

```python
@app.get("/{full_path:path}", include_in_schema=False)
def serve_dashboard(full_path: str):
    if full_path.startswith(("api/", "ingest/")):
        raise HTTPException(status_code=404, detail="unknown endpoint")
    ...
```

Four design points packed into these few lines:

1. **Declared LAST.** FastAPI tests routes in **registration order**.
   Declared earlier, this route would swallow every `/api/*` call.
2. **An unknown `/api/*` stays a 404 JSON.** Otherwise a misspelled call would
   return `200 OK` + HTML, and the client would fail JSON parsing instead of
   getting a clear message about what's missing.
3. **Protection against directory traversal:**
   ```python
   asset = (DIST_DIR / full_path).resolve()
   if asset.is_file() and asset.is_relative_to(DIST_DIR):
       return FileResponse(asset)
   ```
   Without `is_relative_to`, a crafted URL like `/../crk-backend/.env` would
   read any file on the VM.
4. **SPA fallback.** Everything else returns `index.html`, so React Router can
   handle `/comparaison` and `/rapports` — including on a page refresh (F5) or
   a shared link.

If `dist/` doesn't exist, the route returns an explicit **503** explaining how
to build the dashboard, and the API keeps responding.

## 8.5 Common conventions

| Situation | Response |
|---|---|
| Unknown store | `404 {"detail": "unknown store"}` |
| Non-ISO date | `400 {"detail": "du must be an ISO date (YYYY-MM-DD)"}` |
| Range > 400 days | `400 {"detail": "range too long (…)"}` |
| `objectif` outside [0,100] | `400` |
| Uncomputable indicator | `null` in the JSON (never `0`) |

The mechanism is centralized:

```python
def _guard(fn, *args):
    """Run an analytics call, turning bad parameters into a 400."""
    try:
        return fn(*args)
    except analytics.BadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

`analytics.py` knows nothing about HTTP: it raises `BadRequest`, and
`main.py` translates it. **The business layer stays testable with no server
involved.**

---

# 9. Layer 5 — The React frontend

Folder: **[`Dashboard/`](Dashboard)**

## 9.1 The tech stack

| Tool | Version | Role |
|---|---|---|
| **React** | 18 | UI library |
| **Vite** | 5 | dev server + production bundler |
| **react-router-dom** | 6 | navigation across the 3 pages, no full reload |
| **Recharts** | 2 | every chart (SVG, declarative) |
| **lucide-react** | — | icons |
| **html2pdf.js** | — | PDF export of the reports |

## 9.2 The annotated file tree

```
Dashboard/
├── index.html                    HTML entry point (dev)
├── vite.config.js                proxies /api -> crk-backend
├── package.json                  dependencies + scripts (dev/build/preview)
├── .env.example                  configuration template
├── dist/                         ← THE BUILD (chapter 11)
└── src/
    ├── main.jsx                  mounts <App> into #root
    ├── App.jsx                   routing + shared date range
    ├── index.css                 917 lines: ALL the styles, CRK palette
    │
    ├── api/
    │   ├── client.js             ⭐ THE ONLY entry point for data
    │   └── useApi.js             loading/error hook + useStores()
    │
    ├── lib/
    │   └── format.js             fr-FR formatting, "—" for null, deltas
    │
    ├── components/
    │   ├── Sidebar.jsx           navigation, logo, collapse
    │   ├── Topbar.jsx            title + store picker + period picker
    │   ├── Calendar.jsx          date range selection
    │   ├── SalesPotential.jsx    funnel, potential, banners (415 lines)
    │   └── States.jsx            loading / error / no-data
    │
    ├── pages/
    │   ├── Dashboard.jsx         Overview (460 lines)
    │   ├── Comparaison.jsx       all 8 stores side by side
    │   └── Rapports.jsx          AI report generation + history + PDF
    │
    ├── data/
    │   └── storeColors.js        curve colors per store
    │
    └── report/
        └── generateReport.js     payload -> Gemini -> markdown -> HTML -> PDF
```

## 9.3 The golden rule: a single entry point

**`src/api/client.js` is the only file in the frontend that ever does a
`fetch()` to the backend.** No component calls `fetch` directly. No local data
generator exists anywhere.

```js
const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");

async function get(path, params) {
  const query = new URLSearchParams(params ?? {}).toString();
  const url = `${BASE}/api/${path}${query ? `?${query}` : ""}`;
  ...
}

export const fetchStores     = ()                          => get("stores").then(r => r.stores);
export const fetchRange      = (magasin, start, end, obj)  => get("range", {...});
export const fetchComparison = (start, end)                => get("comparison", {...});
export const fetchSeries     = (magasin, periode, fin)     => get("series", {...});
export const fetchLastSeen   = (magasin)                   => get("last-seen", { magasin });
```

Three immediate benefits:

1. **Changing the backend URL touches one file.**
2. **Error handling is unified and meaningful.** `fetch` only rejects on a
   network error, so the message says so:
   ```js
   throw new ApiError(
     `Backend unreachable at ${BASE || window.location.origin}. ` +
     "Check that crk-backend is running (py main.py) and that VITE_API_URL points to it."
   );
   ```
   On a non-OK HTTP response, FastAPI's `detail` is extracted and surfaced
   as-is. **The dashboard shows the real error, never a generic "oops."**
3. **The `null` discipline is preserved end to end**: a `null` returned by the
   backend stays `null` all the way to display, where `format.js` turns it
   into `—`.

> **General lesson — the anti-corruption layer**
> In any client application, put **a single** layer between the API and the
> UI. It absorbs URL changes, normalizes errors, and prevents the shape of
> the JSON from leaking into 30 components. The day the API changes, you
> touch one file.

## 9.4 The `useApi` hook

```js
export function useApi(fetcher, deps) {
  const run = useCallback(fetcher, deps);
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let current = true;
    setState(prev => ({ ...prev, loading: true, error: null }));  // ← keeps `data`
    run().then(
      data  => current && setState({ data, error: null, loading: false }),
      error => current && setState({ data: null, error, loading: false })
    );
    return () => { current = false; };   // ← cancel if the component changes
  }, [run]);

  return state;
}
```

Two details that make a real difference in practice:

- **`{ ...prev, loading: true }`** keeps the previous data around while
  reloading. Switching stores doesn't make the page **flash** by clearing
  every chart before the new response arrives.
- **The `current` flag** prevents a slow response arriving after a selection
  change from overwriting the newer one. This is the classic pattern against
  *race conditions* in React.

And `useStores()`, built on top of it, answers a real product question:

```js
const actifs = liste.filter(s => s.dernierEvenementTs != null);
const defaut = actifs.length
  ? actifs.reduce((a, b) => (b.dernierEvenementTs > a.dernierEvenementTs ? b : a)).nom
  : liste[0]?.nom ?? null;
```

*Which store should the dashboard open on?* On **the most recently active
one**. Taking the first item in the list could land on a store that's been
silent for weeks, and the dashboard would open empty without that being a
bug.

## 9.5 The three pages

### Overview (`/`) — [`Dashboard.jsx`](Dashboard/src/pages/Dashboard.jsx)

Three sections, **organized by the provenance of the numbers** — this is what
keeps the page readable despite the number of indicators:

| Section | Provenance | Content |
|---|---|---|
| **1. Footfall & hand-offs** | device only | Customers entered, Customers/day, Number of hand-offs |
| **2. Sales & potential** | device **×** POS | Revenue, Tickets, funnel, potential, opportunity gap, capture rate, conversion (each with its hourly breakdown) |
| **3. Hourly and daily detail** | device only | peak hours, hand-offs/hour, rate/hour, time series, heatmap |

It fires **3 requests**: one `fetchRange` and two `fetchSeries` (the two
day/week/month pickers on the two series are independent).

### Comparison (`/comparaison`) — [`Comparaison.jsx`](Dashboard/src/pages/Comparaison.jsx)

A single `fetchComparison` request. All 8 stores side by side, a ranking,
"best hand-off rate / most hand-offs / most customers" cards, and a per-store
hand-off-rate curve.

A rigor detail: rankings **ignore** stores with no measurement.

```js
function bestBy(magasins, key) {
  const candidats = magasins.filter(m => m[key] !== null && m[key] !== undefined);
  if (candidats.length === 0) return null;
  return candidats.reduce((a, b) => (b[key] > a[key] ? b : a));
}
```

A store with no data feed can't accidentally end up "best."

### Reports (`/rapports`) — [`Rapports.jsx`](Dashboard/src/pages/Rapports.jsx)

See [chapter 10](#10-generative-ai-the-gemini-reports).

## 9.6 Shared state: minimal and deliberate

```jsx
// App.jsx
const [rangeStart, setRangeStart] = useState(() => {
  const d = new Date(); d.setDate(d.getDate() - 6); return d;
});
const [rangeEnd, setRangeEnd] = useState(new Date());
```

**No Redux, no Zustand, no Context.** A single piece of state is shared — the
date range — and it flows down as props into two pages. Adding a state
management library for two dates would be gratuitous complexity.

The useful effect: moving from Overview to Comparison **keeps the selected
period**.

## 9.7 Display rules that carry meaning

These choices aren't cosmetic — each one prevents a misreading.

| Decision | Reason |
|---|---|
| **Bars, not an area**, for hourly buckets | an area would interpolate between 10am and 11am, suggesting a gradual arrival, when these are 12 independent counts |
| **No 100 % ceiling** on the hand-off rate axis | the measured rate genuinely exceeds 100 %; capping the axis would hide the anomaly |
| **`connectNulls={false}`** on lines | an hour with no measurement creates a **gap**, not a made-up segment |
| **The tooltip writes `11h – 12h`** | the axis shows "11h" for lack of space, but the value covers a bucket, not an instant |
| **Revenue has no bar** in the funnel | comparing dinars to people on the same scale means nothing |
| **An explicit cumulative label** (`cumulative from 10am to now`) | the top cards accumulate over the period, the charts break it down — the page has to say which one you're looking at |
| **Stores with no data feed marked** in the picker | an empty dashboard then reads as "no feed," not "bug" |

## 9.8 Development mode: the Vite proxy

```js
// vite.config.js
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.CRK_BACKEND_URL || env.VITE_API_URL || 'http://localhost:8080'
  return {
    plugins: [react()],
    server: { proxy: { '/api': { target, changeOrigin: true } } },
  }
})
```

In dev, the browser loads the page from `localhost:5173` while the backend
listens on a different port. Without a proxy, that would be a **cross-origin**
request and the browser would block it (CORS).

The dev-server proxy solves this: the client calls `/api/...` **relatively**,
and Vite relays it to the backend. Result: **no backend URL hardcoded
anywhere**, and the same code works in dev and in production.

> ⚠️ A trap we hit: the proxy targets `http://localhost:8080` by default, but
> production uses port **8000**. If the backend isn't listening on 8080,
> `CRK_BACKEND_URL` must be set in `Dashboard/.env`. Symptom otherwise: HTML
> 404 responses instead of JSON.

---

# 10. Generative AI: the Gemini reports

This is the project's second AI, and it's very different from the first. The
Jetson device does **vision** (perception). Gemini does **writing**
(synthesis). The contrast is instructive.

## 10.1 The flow

```
  The user picks a store + period, clicks "Generate"
        │
        ▼
  buildReportPayload()  ──►  GET /api/range   (the actually measured data)
        │
        ▼
  JSON payload: kpis, kpisPrecedent, joursDetail, clientsParHeure, …
        │
        ▼
  generateReport()  ──►  POST https://generativelanguage.googleapis.com/…
        │                       system_instruction = SYSTEM_PROMPT
        │                       contents           = the JSON
        ▼
  validated markdown  ──► stored in localStorage (history)
        │
        ▼
  reportHtmlDocument()  ──► CRK-styled HTML  ──► html2pdf.js  ──► downloaded PDF
```

**The browser calls Gemini directly.** The backend isn't part of the AI loop.
Consequence to be aware of: `VITE_GEMINI_API_KEY` is **included in the
JavaScript bundle**, so it's visible to anyone who opens the developer tools.
Acceptable for a free-tier key on a corporate network; should be moved
server-side if the dashboard were ever exposed publicly.

## 10.2 The prompt: engineering, not conversation

The `SYSTEM_PROMPT` runs to about 60 lines. Its structure is worth studying,
since it's a reusable pattern:

**1. The role and the frame**
> *"You are a senior retail analyst working for CRK… you write a report for
> management, in French."*

**2. What the model is NOT allowed to do**
> *"There is NO cash-register data at all… You must never quantify a
> recommendation in dinars."*

Explicitly forbidding something is more effective than hoping the model will
just refrain. *(Note: this constraint predates the Joolan integration and
should be updated now that revenue is real — see
[chapter 16.3](#163-identified-technical-debt).)*

**3. The indicator dictionary**
Every key in the JSON is defined in one line. Without this, the model
*invents* a plausible definition for `taux_pec` on its own.

**4. Strict, numbered rules** — 10 rules. The three most important:

> **Rule 1** — `null` means "not measured." **Never treat it as a zero.**
> *(the project's Rule 3, handed down to the model)*

> **Rule 5** — Consistency check: *"if `taux_pec` exceeds 100 %, that's
> physically impossible. Treat it as a MEASUREMENT ANOMALY, flag it
> explicitly, and never present it as commercial performance."*

> **Rule 6** — *"FORBIDDEN: generic advice like 'improve the welcome
> experience' or 'motivate the team.'"*

**5. The EXACT output structure** — headings, order, markdown table, number
of bullets, length (350-500 words).

> **General lesson — a production prompt isn't a question**
> A prompt going into production has five blocks: *role*, *forbidden moves*,
> *data dictionary*, *numbered rules*, *exact output format*. The forbidden
> moves and the consistency check are the most valuable: they turn a model
> that flatters the numbers into one that questions them. And the exact
> format makes the output **verifiable by code**.

## 10.3 Code-side guardrails

The model is never trusted at its word.

**Before the call — don't waste a request:**
```js
if (payload.indicateursPeriode.evenements === 0) {
  throw new Error(`No events received from ${payload.magasin} between … : nothing to analyze.`);
}
```

**Retries only on transient errors:**
```js
const delays = [0, 10000, 30000];   // immediate, +10s, +30s
...
if (resp.status !== 503 && resp.status !== 429) throw lastError;
```
`503` (overloaded) and `429` (per-minute quota) are **temporary**: retry them.
A `400` (bad request) will never fix itself: bubble it up immediately.
Retrying a permanent error only delays the useful message.

**After the call — three checks:**
```js
if (finishReason === "MAX_TOKENS")  throw new Error("Report truncated…");
if (!text)                          throw new Error("Empty response from the API.");
const requiredSections = ["## Constats", "## Recommandations", "## Point de vigilance"];
if (!requiredSections.every(s => text.includes(s))) throw new Error("Invalid response from the model");
```

The third one is the most interesting: **the exact format requested in the
prompt becomes an automatic test.** A report that doesn't have the right
structure gets rejected before it ever reaches the user.

> **General lesson — treat an LLM like an unreliable service**
> A call to a generative model should be handled exactly like a call to an
> unstable third-party service: timeout, **selective** retry, and **shape
> validation** of the response before using it. The difference from a
> classic API: there's no enforced schema, so it's on you to impose one and
> check it.

## 10.4 Markdown → HTML → PDF

The markdown is stored as-is (in `localStorage`, under the key
`crk-rapports`), then converted on demand to CRK-styled HTML, then captured
by `html2pdf.js`.

An interesting technical trap, documented right in the code:

```js
// html2pdf clones the node passed to .from() as-is and reinserts it into its
// own auto-height container: if that node is itself in a position: absolute/
// fixed layout, it falls out of the flow and the container's height
// collapses to 0 → blank PDF.
```

The fix: keep the captured element's own position **static**, and hide it via
an **outer wrapper** with `position: fixed; left: -10000px` — a wrapper
html2pdf never clones. Plus an explicit check:

```js
if (el.offsetHeight === 0) {
  throw new Error("The report container has zero height, the PDF capture would be blank.");
}
```

Better a clear error than a blank PDF silently downloaded.

---

# 11. The build: what `dist/` is for

This is the question you were asking: *why is there a `dist` folder, and
how does it work?*

## 11.1 The problem a build solves

The React source code **isn't executable by a browser**:

| In `src/` | What a browser understands |
|---|---|
| JSX (`<Sidebar />`) | nothing at all |
| `import logo from "./assets/logo.png"` | nothing at all |
| `import { useState } from "react"` | resolving `node_modules`: no |
| ~40 files + 6 npm dependencies | 40+ cascading HTTP requests |

So it has to be **transformed** (JSX → JavaScript), **resolved** (merging in
`node_modules`), and **optimized** (minified, hashed, split).

That's what `npm run build` does — i.e. `vite build`.

## 11.2 What `npm run build` produces

```
Dashboard/dist/
├── index.html                            784 bytes
└── assets/
    ├── index-CbXTDnBb.js                 604 KB   ← React + Recharts + every page
    ├── html2pdf-CkMC4Pqp.js              983 KB   ← loaded ONLY when clicking "PDF"
    ├── index-DV2-kJ3f.css                 16 KB   ← minified index.css
    └── logo-crk-Ciwtij74.png               22 KB
```

And the HTML gets **rewritten** to point at these files:

```html
<!-- src : index.html (dev) -->
<link rel="icon" href="/src/assets/logo-crk.png" />
<script type="module" src="/src/main.jsx"></script>

<!-- dist/index.html (production) -->
<link rel="icon" href="/assets/logo-crk-Ciwtij74.png" />
<script type="module" crossorigin src="/assets/index-CbXTDnBb.js"></script>
<link rel="stylesheet" crossorigin href="/assets/index-DV2-kJ3f.css">
```

### Content hashing in the filename

`index-CbXTDnBb.js`: `CbXTDnBb` is a **hash of the content**.

This is the answer to the web's most classic caching problem:

```
   Without a hash                          With a hash
   ──────────────────────────────         ─────────────────────────────────
   /assets/index.js                       /assets/index-CbXTDnBb.js
   The browser already cached it.         A new build = new content
   New deployment?                        = a new filename
   It serves the old version.             = a URL never seen before = fetched.
   The user sees a stale                  And the old one can safely be
   dashboard and can't figure out why.    cached for a year.
```

### Splitting the code (`code splitting`)

Why is `html2pdf` in its own **separate** file? Because of this line in
`Rapports.jsx`:

```js
const html2pdf = (await import("html2pdf.js")).default;
```

A **dynamic** `import()` = Vite puts the library into its own chunk, loaded
only when the function actually runs. Concretely: **983 KB nobody downloads
unless they click "download PDF"** — 60 % of the total weight avoided for the
vast majority of visits.

> **General lesson — a build is not a formality**
> Three things distinguish a build from a plain file copy: **transformation**
> (the browser doesn't understand your source language), **hashing** (without
> it, users see a stale version for days), and **splitting** (without it,
> everyone pays for the feature that 5 % of them use). If there's only one
> thing to remember: content hashing is the only caching strategy that
> actually works.

## 11.3 Why the BACKEND serves `dist/`

Here is the single most structuring architectural choice in the project.

### What we could have done

```
   nginx :80  ────► serves Dashboard/dist
        │
        └─ /api/*  ──proxy──►  uvicorn :8000
```

That would have meant: installing nginx on Windows, writing its
configuration, maintaining it, running **two** services, and debugging the
proxy whenever it breaks.

### What we actually did

```
   uvicorn :8000  ────►  /api/*     : SQLite aggregates
                  ────►  /ingest/*  : camera devices
                  ────►  /*         : Dashboard/dist
```

**A single process. A single port. A single service to install and watch.**

```python
DIST_DIR = Path(os.environ.get(
    "CRK_DASHBOARD_DIST",
    Path(__file__).resolve().parent.parent / "Dashboard" / "dist"
)).resolve()
```

### The four consequences

**1. Same-origin ⇒ no CORS at all, anywhere.**
The page comes from `http://vm:8000/`, and calls go to
`http://vm:8000/api/...`. Same origin: the browser doesn't ask a single
question. `CRK_ALLOWED_ORIGINS` now only matters for development.

**2. No backend URL baked into the build.**
```js
const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
// empty ⇒ relative URLs ⇒ "whichever server served me this page"
```
The **same** `dist/` works on `localhost`, on `192.168.2.210`, or behind any
domain name. **Nothing to rebuild to change the address.**

**3. SPA routing works on page refresh.**
`/comparaison` doesn't exist as a file. Falling back to `index.html` means F5
or a shared link both work — React Router takes over client-side.

**4. Deployment becomes a folder copy.**
No Node on the VM? Build elsewhere, copy `Dashboard\dist`, run
`install.ps1 -SkipBuild`. The script explicitly handles this case.

> **General lesson — letting the API serve the frontend**
> For an internal, single-server application, having the backend serve the
> build removes, in one move: CORS configuration, a reverse proxy, a backend
> URL variable, and a second service to watch. The cost: the backend gains 25
> lines of code. An excellent trade — worth revisiting only the day the
> frontend needs to live on a CDN.

## 11.4 `dist/` and git

`dist/` is in `.gitignore` (both at the root and in `Dashboard/`). It's
**generated** code: committing it would produce unreadable conflicts on
every build.

It gets rebuilt:
- in development, on demand (`npm run build`);
- in production, by `install.ps1` on every deployment.

The `Dashboard/dist/` folder present on your machine is therefore a **local
artifact**, not a source. It can be deleted and regenerated at any time.

---

# 12. Deployment: the `deploy/` folder

```
deploy/
└── windows/
    ├── install.ps1        full install / update (idempotent)
    ├── run-service.ps1     launcher run by the scheduled task
    └── README.md           operations runbook
```

## 12.1 The target

A **Windows Server VM**, on CRK's network. The stores' Jetson devices reach
it via its IP (e.g. `192.168.2.210:8000`).

## 12.2 `install.ps1`, step by step

Run in an **administrator** PowerShell console:

```powershell
cd C:\path\to\CRK-analytics-dashboard
.\deploy\windows\install.ps1 -Port 8000
```

| Step | What it does | Detail worth knowing |
|---|---|---|
| **0. Admin** | checks elevation | otherwise fails immediately with a clear message |
| **1. Tools** | Python ≥ 3.10, npm | `py` can exist **without** any interpreter installed — the script checks the **output**, not just its presence |
| **2. venv** | creates `crk-backend\venv` | **recreates** the venv if it's broken (a common case after a Python upgrade) |
| **3. Dependencies** | `pip install -r requirements.txt` | **pinned** versions |
| **4. `.env`** | creates it if missing, **generates a random API key** | if it exists, it's **kept as-is** — and its `CRK_PORT` **wins** over `-Port` |
| **5. Build** | `npm ci && npm run build` | `-SkipBuild` if `dist/` is already copied over |
| **6. Service** | registers the "CRK Analytics" scheduled task | SYSTEM, at boot, auto-restart |
| **7. Firewall** | inbound TCP rule for the port | `-NoFirewall` to skip it |
| **8. Verification** | queries `/api/health` then `/` | up to 20 attempts, 750 ms apart |

And at the end it prints:

```
────────────────────────────────────────────────────
 Dashboard : http://192.168.2.210:8000/
 Ingestion : http://192.168.2.210:8000/ingest/batch   (header X-API-Key)
 Logs      : C:\...\logs

 GENERATED API KEY (to configure on every camera device):
   9bcc4a25...........................
 It's stored in crk-backend\.env and won't be shown again.
────────────────────────────────────────────────────
```

### Idempotence, a central property

The script is **idempotent**: rerunning it after a `git pull` rebuilds the
dashboard and restarts the service **without touching `.env` or the
database**.

Updating therefore boils down to:

```powershell
git pull
.\deploy\windows\install.ps1
```

> **General lesson — a deployment script must be replayable**
> If it can only be run once, it's not a deployment, it's an installation.
> The difference comes down to three reflexes: **never overwrite anything
> holding a secret or state**, **rebuild what's broken instead of failing**,
> and **verify at the end that it actually responds**.

## 12.3 Why a scheduled task and not a "real" Windows service

A native Windows service requires an executable that implements the Service
Control Manager protocol. Python doesn't do that natively — it would take a
wrapper (NSSM, `pywin32`), meaning one more dependency to install and
maintain.

A **scheduled task** offers everything needed, with nothing extra to
install:

```powershell
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew
```

| Setting | Why |
|---|---|
| `-AtStartup` | starts when the VM boots |
| `UserId 'SYSTEM'` | **runs with no session open** — survives an RDP disconnect |
| `RestartCount 99` / 1 min | restarts on a crash |
| `ExecutionTimeLimit 0` | **no time limit** — otherwise Windows would kill it after 3 days |
| `MultipleInstances IgnoreNew` | never two backends writing to the same database |

## 12.4 `run-service.ps1`: two PowerShell traps solved

This little script exists for two non-obvious reasons.

### Trap #1 — under Task Scheduler, `stdout` is lost

Without redirection, a crash at startup would be **invisible**. Hence:

```powershell
$log = Join-Path $logDir ('crk-{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))
$env:PYTHONUNBUFFERED = '1'   # otherwise output stays buffered
& cmd.exe /c "`"$python`" main.py >> `"$log`" 2>&1"
```

`PYTHONUNBUFFERED` is essential: a service that never stops would never
flush its buffer, so it would **never** write its log.

### Trap #2 — `$ErrorActionPreference = 'Stop'` kills the service

```powershell
# NEVER 'Stop' here.
$ErrorActionPreference = 'Continue'
```

PowerShell 5.1 wraps **every line** an executable writes to `stderr` inside
an `ErrorRecord`. And **uvicorn logs to stderr**. With `'Stop'`, the script
died on uvicorn's very first log line and took the backend down with it.

Symptom actually experienced: *the task starts, nothing is listening, and the
log only contains "starting up" with nothing after it.* A very hard bug to
diagnose without knowing about this behavior.

That's also why the redirection is handed off to **`cmd.exe`**: it writes
both streams as-is, without PowerShell's `ErrorRecord` wrapping described
above.

## 12.5 Script encoding: UTF-8 **with BOM**

`install.ps1` and `run-service.ps1` are saved as **UTF-8 with BOM**.

PowerShell 5.1 — the one that ships by default with Windows Server — reads a
file **without a BOM as ANSI**. Accented characters then turn into garbage
bytes that **break the script parsing**.

If you edit these files, keep the BOM:

```powershell
$t = Get-Content -Raw -Encoding UTF8 .\deploy\windows\install.ps1
[System.IO.File]::WriteAllText((Resolve-Path .\deploy\windows\install.ps1), $t,
                               (New-Object System.Text.UTF8Encoding $true))
```

Syntax check before deploying:

```powershell
$e = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path .\deploy\windows\install.ps1), [ref]$null, [ref]$e)
$e
```

## 12.6 The occupied-port trap

This is the single most time-consuming bug in the project. Essential to
know.

**Symptom:** the API returns **HTML 404** instead of JSON, even though
uvicorn started without any error at all.

**Cause:** another program (the Oracle **TNSLSNR** listener, on this
machine) is listening on `127.0.0.1:8080`. Uvicorn binds to `0.0.0.0:8080` —
which **succeeds** — but on Windows, **the more specific binding wins**:
requests to `localhost:8080` go to Oracle instead.

**Diagnosis:**
```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen
# two lines = conflict
```

**Fix:** use port **8000**, which is what the project uses everywhere.

> **General lesson**
> "The process started without an error" doesn't prove it's reachable. A
> deployment should always end with a **check from the outside** — which is
> exactly what step 8 of `install.ps1` does.

## 12.7 Day-to-day operations

```powershell
# service status
Get-ScheduledTask -TaskName 'CRK Analytics' | Get-ScheduledTaskInfo

# stop / start
Stop-ScheduledTask  -TaskName 'CRK Analytics'
Start-ScheduledTask -TaskName 'CRK Analytics'

# logs (one file per startup day)
Get-Content .\logs\crk-*.log -Tail 50 -Wait

# health
Invoke-RestMethod http://localhost:8000/api/health

# who last transmitted
Invoke-RestMethod 'http://localhost:8000/api/last-seen?magasin=MANAR%20CITY'

# live event stream
.\crk-backend\venv\Scripts\python.exe .\crk-backend\watch_events.py --since 30
```

### Backup

**All the state lives in one file.**

```powershell
Stop-ScheduledTask -TaskName 'CRK Analytics'
Copy-Item .\crk-backend\crk_analytics.db "D:\backup\crk-$(Get-Date -f yyyyMMdd).db"
Start-ScheduledTask -TaskName 'CRK Analytics'
```

WAL mode requires copying `.db`, `.db-wal` **and** `.db-shm` together, or
stopping the service first (as above).

### What the backend prints at startup

```
[crk] base       : C:\...\crk_analytics.db
[crk] evenements : 7601
[crk] dashboard  : C:\...\Dashboard\dist
```

Three lines that pre-answer the three troubleshooting questions: *which
database? how much data? is the dashboard there?* They're deliberately
**without accents**: they display in a Windows console whose encoding isn't
guaranteed, and these are exactly the lines you read when something's wrong.

---

# 13. The security model

## 13.1 What's protected, and what isn't

```
   POST /ingest/event   ──►  X-API-Key REQUIRED   ✅ protected (writes)
   POST /ingest/batch   ──►  X-API-Key REQUIRED   ✅ protected (writes)

   GET  /api/*          ──►  no key at all        ⚠️ PUBLIC (reads)
   GET  /  (dashboard)  ──►  no key at all        ⚠️ PUBLIC
```

**Anyone who can reach `http://<vm-ip>:8000` can see the stores' numbers.**

## 13.2 This is a deliberate choice

It's what lets a colleague open the dashboard **without installing anything
and without an account**. On a controlled corporate network, that's the
right trade-off: the usability wins, and the data is neither personal nor
financially sensitive enough to justify a whole user-management system.

The asymmetry makes sense: **writing** can durably corrupt the history with
no way to sort it out afterward; **reading** can't break anything.

## 13.3 Two consequences to know

**1. The network perimeter is the real protection.**
On an untrusted network: restrict the firewall rule to the stores'
addresses, or put the service behind a VPN.

**2. The traffic is HTTP, not HTTPS.**
The API key travels **in the clear** over the network. Acceptable on a
private local network. **Not acceptable over the internet.** For HTTPS: put a
reverse proxy (IIS or nginx) in front and close the application port
externally.

## 13.4 What else is protected

| Protection | Where | Against |
|---|---|---|
| `is_relative_to(DIST_DIR)` | `main.py` | reading arbitrary files via `/../crk-backend/.env` |
| `max_length=1000` | `models.py` | memory exhaustion from a giant batch |
| `MAX_RANGE_DAYS = 400` | `analytics.py` | a request asking for a decade of data |
| `_masque(url)` | `joolan.py` | the Joolan key showing up in plaintext logs |
| `.env` in `.gitignore` | 3 files | secrets committed by accident |
| Bound SQL parameters (`?`) | `db.py` | SQL injection |

## 13.5 The project's secrets — summary

| Secret | Where it lives | Who knows it | Risk if lost |
|---|---|---|---|
| `CRK_API_KEY` | `crk-backend/.env` **and** every Jetson device | server + devices | ingestion silently stops (401) |
| `CRK_JOOLAN_API_KEY` | `crk-backend/.env` | server only | revenue unavailable, falls back to simulation |
| `VITE_GEMINI_API_KEY` | `Dashboard/.env`, **included in the bundle** | any dashboard visitor | quota consumed by a third party |

**None of these three is in git.** The repo's three `.gitignore` files all
exclude `.env`.

---

# 14. Operations and tooling

The backend contains **8 scripts** that aren't needed by the service itself
but exist to understand and repair it. All are documented with a docstring
at the top of the file, and all state clearly whether they write or not.

| Script | Writes? | What it's for |
|---|---|---|
| [`watch_events.py`](crk-backend/watch_events.py) | **no** | follow events live, see what the Jetson is actually sending |
| [`diagnostic.py`](crk-backend/diagnostic.py) | **no** | find **every** database in the folder and say which one the service is really using |
| [`test_joolan.py`](crk-backend/test_joolan.py) | **no** | diagnose the POS connection in 5 steps |
| [`inspect_joolan.py`](crk-backend/inspect_joolan.py) | **no** | discover the fields Joolan actually returns |
| [`retrouver_base.py`](crk-backend/retrouver_base.py) | **no** | find a lost database anywhere on disk (including the recycle bin) |
| [`migrate_db.py`](crk-backend/migrate_db.py) | **yes** | move a database from the old schema to the minimal one |
| [`purge_db.py`](crk-backend/purge_db.py) | **yes** | delete history before a given date |
| [`restaurer.py`](crk-backend/restaurer.py) | **yes** | merge a recovered database with the current one |

## 14.1 `watch_events.py` — seeing what arrives

```bash
py watch_events.py                        # follow live
py watch_events.py --since 30             # last 30, then follow
py watch_events.py --store "Manar city" --once
```

Read-only, **safe against the running service** thanks to WAL mode.

What the script takes care to point out, which prevents drawing the wrong
conclusions:

- the `ts` shown is the one **after** `_with_wall_clock`, not the raw value
  the device sent;
- it shows `buffered 142.3s` when an event was sitting in a buffer — that's
  `received_at - ts`;
- events rejected with a `422` **never reach the table**, so they can never
  show up here;
- `HEARTBEAT`s never show up: that's **expected**, not a loss.

## 14.2 `test_joolan.py` — the 5-step POS diagnostic

```powershell
py test_joolan.py                     # yesterday
py test_joolan.py --date 2026-08-20   # a specific date
py test_joolan.py --brut              # the raw JSON response as-is
```

It diagnoses **in order**: configuration → reachability → authorization →
content → store-name mapping. Every failure says **what to fix**.

It's the one that shows the actual `Magasin` codes Joolan returns — the
information needed to fill in `CRK_JOOLAN_MAGASINS`.

## 14.3 `diagnostic.py` — "where did the data go?"

Written after a real incident (the database had ended up in the recycle
bin). It looks for every database and backup in the folder, shows what each
one contains and over what period, and says **which one the service is
actually using**.

A remarkable design detail:

```python
try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    # manually parse the .env file
```

**The tool has to run even when the environment is broken.** A diagnostic
tool that requires a healthy environment is useless on the exact day the
environment isn't healthy.

> **General lesson — tooling for the degraded case**
> The scripts that matter aren't the ones that work when everything is fine.
> Write your diagnostic tools assuming the venv is broken, the service is
> dead, and the `.env` points to the wrong place.

## 14.4 The destructive scripts and their discipline

`migrate_db.py`, `purge_db.py` and `restaurer.py` all write. They all share
the same **four guardrails**:

1. **A `--dry-run` mode available by default**: show before acting.
2. **Automatic timestamped backup** created next to the database.
3. **Announce the cost**: `migrate_db.py` shows how many archived hand-offs
   will be lost **before** writing anything at all.
4. **Verification that the service is stopped**: `restaurer.py` asks Windows
   (`sc query`) **and**, if the service is unknown, watches the database for
   three seconds to see if anyone is writing to it. Either way, it stops
   **before** touching anything.

> **General lesson — the anatomy of a destructive script**
> Show before acting, back up automatically, announce the cost, and check
> that nobody else is writing. All four, every time. The cost is 30 lines;
> the payoff is never having to write a `restaurer.py` at all.

## 14.5 Troubleshooting table

| Symptom | Likely cause | Check |
|---|---|---|
| API returns **HTML 404** instead of JSON | port taken by another service | `Get-NetTCPConnection -LocalPort 8000 -State Listen` |
| **503** "Dashboard not built" | `Dashboard\dist` missing | rerun `install.ps1` without `-SkipBuild` |
| The service won't start | broken venv, or `.env` missing `CRK_API_KEY` | `Get-Content .\logs\crk-*.log -Tail 30` |
| Devices get **401** | mismatched API key | compare `.env` against the Jetson config |
| Blank page from another machine | firewall | `Get-NetFirewallRule -DisplayName 'CRK Analytics*'` |
| Dashboard empty, no active store | no device is transmitting | `Invoke-RestMethod .../api/health` → `events_total` |
| Orange "simulated data" banner | Joolan not configured | `py test_joolan.py` |
| Revenue at 0 for a store | `Magasin` code not mapped | `CRK_JOOLAN_MAGASINS` |
| `seconds_ago` climbing | silent or rejected device | `/api/last-seen` |

---

# 15. Actual measured state of the data

Measurements taken directly on the local copy of the repo, on 2026-09-06.

## 15.1 The `events` table

```
7,601 rows · 946 KB · SQLite 3.49.1 · idx_store_ts index

  Manar city     ENTRY        661   →  606 distinct track_ids
  Manar city     PEC_END    1,750
  Manar city     PEC_START  5,189
  Tunisia Mall   PEC_START      1
```

**What this local copy tells us:**

- It contains the **old v1 format** (`PEC_START` / `PEC_END`), not yet the
  `INTERACTION` format. Zero `INTERACTION` rows: this copy predates the move
  to v2.
- The schema is the **old** one: 10 columns (`pec_id`, `duration_s`,
  `seller_count`, `zone_id` still present). The current backend detects this
  at startup and reports it without forcing anything.
- Direct consequence: opened as-is with the current code, this database
  would show **0 hand-offs** — since `PEC_*` rows are no longer counted.
- **21 rows have a `ts` < 10⁹** (shown as "1970-01-01"): session-relative
  timestamps written by a version of the backend that predates
  `_with_wall_clock`.
- **661 `ENTRY` for 606 distinct `track_id`s**: right there, in one line, is
  the numeric proof of the identifier recycling that motivates the
  `(track_id, day)` key from [§5.2](#52-deduplication-the-heart-of-the-count).

> ⚠️ **The production database is not this file.** In production, `.env`
> points `CRK_DB_PATH` to the database the device actually feeds
> (`…\Wisevision\crk-backend\crk_analytics.db`). WAL mode lets one process
> write while this one reads. Always verify **which** database is actually
> open with `py diagnostic.py`.

## 15.2 The `pos_hourly` table — the POS is connected

```
179 rows · source = 'joolan' (100 %) · 2026-08-05 → 2026-08-14

  MANAR CITY       109 rows   303 tickets   74,712.12 DT
  Azur City         10 rows     0 ticket           0 DT
  La Marsa          10 rows     0 ticket           0 DT
  Mall of Sfax      10 rows     0 ticket           0 DT
  Mall of Sousse    10 rows     0 ticket           0 DT
  Menzah 5          10 rows     0 ticket           0 DT
  Sfax 1            10 rows     0 ticket           0 DT
  Tunisia Mall      10 rows     0 ticket           0 DT
```

**Reading this table:**

1. **The Joolan integration works.** No `simulation` rows at all: the orange
   banner no longer shows. `caisse.oopos.fr`, brand `CRK`.
2. **Only MANAR CITY is mapped.** `CRK_JOOLAN_MAGASINS={"MANAR CITY":"CRK Manar City"}`.
   The other 7 each have exactly **10 rows** — the 10 zero-rows from the
   anti-re-call mechanism described in [§6.4](#64-the-switchboard-pospy).
   These are **`Magasin` codes still to confirm with CRK**, not stores
   without sales.
3. **109 rows for MANAR CITY over 10 days** ≈ 11 active hourly buckets per
   day — consistent with a 10am-10pm opening window.
4. **Real average basket: 74,712.12 / 303 = 246.57 DT.** Worth comparing
   against the configured reference basket `AB_REFERENCE = 290 DT`. The gap
   is a genuine business question: either the 290 DT reference should be
   revised, or it correctly represents an unmet target.

## 15.3 Vestiges

| Table | Rows | Status |
|---|---|---|
| `store_config` | 8 | **dead** — no code reads it |
| `pos_daily` | 22 | **dead** — replaced by `pos_hourly` |

## 15.4 The known measurement anomaly

On the MANAR CITY data, **the hand-off rate exceeds 100 %**: more hand-offs
counted than customers who entered.

This is a **defect in the vision pipeline**, not in the aggregation. Two
possible causes, not mutually exclusive:

- **over-counting of interactions** (the same customer engaged counted
  several times);
- **under-counting of entries** (people not detected when crossing the
  threshold).

The system doesn't correct this and doesn't cap its axes:

- the API returns the measured value as-is;
- the "Hand-off rate per hour" chart uses `domain={[0, "auto"]}`, with no
  ceiling;
- the Gemini prompt contains a dedicated rule that **forces** the model to
  treat a rate above 100 % as a measurement anomaly rather than as
  performance.

> **General lesson — never silently correct an implausible measurement**
> Capping an axis at 100 %, or clamping the value server-side, would make the
> symptom disappear without fixing the cause — and nobody would ever find
> out the pipeline has a defect. A visible anomaly is a bug you fix; a
> smoothed-over anomaly is a bug you live with forever.

---

# 16. Known limitations and next steps

## 16.1 Measurement quality (priority 1)

| Topic | Detail |
|---|---|
| **Hand-off rate > 100 %** | needs investigation on the vision-pipeline side — see [§15.4](#154-the-known-measurement-anomaly) |
| **Definition of A** | the spec defines A as the number of **visitors** engaged; `pec_count` counts **distinct interactions**. A visitor approached twice counts as 2. A serious lead on the >100 % rate |
| **Only one active store** | 7 of 8 stores have never sent a single event |
| **Timestamps** | ask the Jetson team to always send real **Unix time**, which would remove the entire `_with_wall_clock` reconstruction |

## 16.2 POS integration

| Topic | Detail |
|---|---|
| **`Magasin` codes** | 7 stores still need mapping in `CRK_JOOLAN_MAGASINS` |
| **`Nature` values** | to confirm: returns, credit notes, exchanges — count them, and as negative? |
| **`Total_TTC`** | VAT-included or not? Are discounts and credit notes included? The average basket must use the same definition management uses |
| **Cancelled tickets** | does a cancelled header disappear from the export, or does it change `Nature`? |
| **`AB_REFERENCE = 290 DT`** | to reconcile against the actual measured basket (246.57 DT) |

## 16.3 Identified technical debt

| Topic | Action |
|---|---|
| **The Gemini prompt is outdated** | it still claims *"there is NO cash-register data at all,"* which was true before Joolan. It needs access to `ventes` and permission to reason in dinars |
| **Dead tables** | drop `store_config` and `pos_daily` |
| **Production database on the old schema** | run `migrate_db.py` after a backup, or `purge_db.py` to start fresh from the v2 cutover |
| **Gemini key in the bundle** | move it server-side if the dashboard becomes reachable outside the internal network |
| **No automated tests** | `_unique_tracks`, `_with_wall_clock`, and the 6 KPI formulas are pure functions: they're **testable with no server and no database**. This is the best available return on investment |
| **Plaintext HTTP** | a TLS reverse proxy if the service ever leaves the local network |

## 16.4 Natural extensions

- **Push footfall into Joolan** via `/import-compteurs-passages.do`
  ([§6.6](#66-the-reverse-path-not-implemented)): management would see
  footfall and sales side by side in the tool they already use.
- **Dynamic reference values**: the spec anticipates `CR_target` and
  `AB_reference` becoming variable by store, weekday, or season. The only
  place that needs to change is the top of `analytics.py`.
- **Silent-device alert**: a job that polls `/api/last-seen` and notifies
  when `seconds_ago` crosses a threshold during opening hours.

---

# Appendix A — All environment variables

## `crk-backend/.env`

| Variable | Default | Role |
|---|---|---|
| `CRK_API_KEY` | *(none — required)* | shared secret with the Jetson devices. The backend **refuses to start** without it |
| `CRK_DB_PATH` | `./crk_analytics.db` | path to the SQLite database |
| `CRK_HOST` | `0.0.0.0` | listening interface |
| `CRK_PORT` | `8000` | port. **Avoid 8080** (Oracle listener) |
| `CRK_DASHBOARD_DIST` | `../Dashboard/dist` | folder the build is served from |
| `CRK_ALLOWED_ORIGINS` | Vite ports | CORS — irrelevant in production (same-origin) |
| `CRK_OPEN_HOUR` | `9` (**10** in prod) | minimum hour shown on the charts |
| `CRK_CLOSE_HOUR` | `20` (**22** in prod) | minimum maximum hour shown |
| `CRK_CR_TARGET_PCT` | `20` | conversion target, in % |
| `CRK_AB_REFERENCE` | `290` | reference basket, in DT |
| `CRK_JOOLAN_DOMAIN` | *(empty)* | Joolan domain — `caisse.oopos.fr` |
| `CRK_JOOLAN_ENSEIGNE` | *(empty)* | brand name — `CRK` |
| `CRK_JOOLAN_API_KEY` | *(empty)* | Joolan key, `api_export_tickets` permission |
| `CRK_JOOLAN_MAGASINS` | `{}` | JSON, CRK name → Joolan code mapping |
| `CRK_JOOLAN_NATURES` | `VENTE` | header natures counted as a sale |
| `CRK_JOOLAN_SCHEME` | `https` | `http` only if Joolan is internal with no TLS |
| `CRK_JOOLAN_TIMEOUT` | `20` | timeout in seconds |

**The three variables `CRK_JOOLAN_DOMAIN` / `_ENSEIGNE` / `_API_KEY` are the
simulation ↔ real switch.** All three filled in ⇒ real data; any one of them
empty ⇒ simulation + orange banner.

## `Dashboard/.env`

| Variable | Default | Role |
|---|---|---|
| `CRK_BACKEND_URL` | `http://localhost:8080` | target of the Vite proxy **in dev** |
| `VITE_API_URL` | *(empty)* | API base URL. **Leave empty** unless the frontend is hosted separately |
| `VITE_GEMINI_API_KEY` | *(empty)* | Gemini key for the Reports page |
| `VITE_GEMINI_MODEL` | `gemini-3.5-flash` | model used |

> Reminder: anything starting with `VITE_` is **included in the JavaScript
> bundle** and therefore visible in the browser. Never put a secret that
> matters in there.

---

# Appendix B — Glossary

| Term | Definition |
|---|---|
| **Jetson** | embedded NVIDIA device running the vision model in-store |
| **`track_id`** | number the tracker assigns to a tracked person. **Recycled** — never a primary key |
| **`ENTRY`** | event: a person entered |
| **`INTERACTION`** | event: a staff member engaged a customer (v2 format) |
| **`PEC`** | "prise en charge" (hand-off/engagement). Historically `PEC_START`/`PEC_END` (v1) |
| **`HEARTBEAT`** | the device's heartbeat. Accepted, never stored |
| **WAL** | *Write-Ahead Logging* — SQLite mode allowing reads while writing |
| **Same-origin** | same protocol + host + port. Eliminates any CORS question |
| **CORS** | browser mechanism that blocks requests to a different origin |
| **SPA** | *Single Page Application* — one HTML page, routing handled in JavaScript |
| **`dist/`** | the production build's output folder |
| **Idempotent** | can be rerun without changing the outcome |
| **Joolan** | CRK's point-of-sale software, REST API v2 |
| **Enseigne** | in Joolan, the name of the client's database ("brand") |
| **V / A / T / R** | Visitors / engaged (Accueillis) / Tickets / Revenue |
| **CR_target** | conversion rate target, in % |
| **AB_reference** | reference average basket, in dinars |

---

# Appendix C — Decision log

Each row: a decision, its reason, and what was ruled out.

| # | Decision | Reason | Alternative rejected |
|---|---|---|---|
| 1 | **AI at the edge** (Jetson) | bandwidth, privacy, network resilience | streaming video to the server |
| 2 | **Events, not images** | the server holds no biometric data at all | storing frame sequences |
| 3 | **SQLite** | single writer, small volume, zero ops overhead | PostgreSQL |
| 4 | **6-column schema** | trivial future migration, no false promises | keeping columns "just in case" |
| 5 | **Aggregation at read time** | changing a rule needs no data migration | pre-computed aggregate tables |
| 6 | **`(track_id, day)` key** | fixes +8.2 % re-detections **and** −8.4 % recycling | `track_id` alone, or `(track_id, ts)` |
| 7 | **`null`, never `0`** | distinguishing "nothing happened" from "not measured" | defaulting to zero |
| 8 | **Fixed +01:00 timezone** | `zoneinfo` absent on Windows; a day is exactly 86,400 s | `zoneinfo` + IANA database |
| 9 | **Elastic hourly window** | never fold an event onto a limit hour | fixed 9am-8pm bounds |
| 10 | **Never cap the hand-off rate** | keep the vision pipeline's defect visible | a 100 % ceiling |
| 11 | **The backend serves `dist/`** | removes CORS, reverse proxy, baked-in URL, a 2nd service | nginx in front of uvicorn |
| 12 | **Hourly POS cache** | the Joolan API only answers per date | one call per page load |
| 13 | **Cache all 8 stores at once** | one Joolan call returns all of them | one call per store |
| 14 | **Simulation that denounces itself** | an unmeasured value must be visible as such | a silent simulation |
| 15 | **Scheduled task** | no dependency (NSSM/pywin32) to install | a native Windows service |
| 16 | **Pinned versions** | a VM reinstalled months later gets exactly what was tested | open version constraints |
| 17 | **Gemini called from the browser** | no proxy to write, free tier | routing through the backend |
| 18 | **Strict-format prompt** | makes the model's output **verifiable by code** | a conversational prompt |
| 19 | **No global state management** | a single piece of shared state: the date range | Redux / Zustand |
| 20 | **Migration never automatic** | a destructive operation isn't a side effect | migrating at startup |

---

# In three sentences

1. **The Jetson perceives, the backend counts, the frontend shows — and
   nobody re-judges the previous layer's work.** That's what keeps the whole
   system traceable end to end.

2. **SQLite is a real database**: the project doesn't need PostgreSQL today
   (a single writer, low volume), and its six-column schema would make a
   future migration easy if that ever became necessary.

3. **Anything that isn't measured must be visible as such** — `null`
   displayed as `—`, an orange banner on simulated data, missing POS days
   flagged, an implausible rate never capped. That's the only discipline that
   keeps a dashboard from becoming decorative.

---

## To go further in this repo

| Document | Content |
|---|---|
| [`README.md`](README.md) | quick start, overview |
| [`crk-backend/README.md`](crk-backend/README.md) | endpoints, computation rules, timestamps |
| [`crk-backend/JOOLAN_INTEGRATION.md`](crk-backend/JOOLAN_INTEGRATION.md) | state of the POS integration, what's left to confirm |
| [`Dashboard/README.md`](Dashboard/README.md) | pages, structure, customization |
| [`deploy/windows/README.md`](deploy/windows/README.md) | full operations runbook |
| [`swagger.yaml`](swagger.yaml) | Joolan API v2 specification |
