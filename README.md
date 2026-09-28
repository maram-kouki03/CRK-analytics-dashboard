# CRK Analytics

**A retail intelligence platform that turns in-store cameras and point-of-sale data into a single, trustworthy dashboard.**

CRK Analytics was built for **CRK Maroquinier**, a leather-goods retailer with 8 stores in Tunisia. A computer-vision pipeline running on an **NVIDIA Jetson** in each store counts customers and staff interactions in real time; a backend cross-references that footfall against **Joolan POS** sales data; a React dashboard turns the result into conversion rates, sales potential, and an opportunity gap that store managers can act on.

[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](Dashboard)
[![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)](Dashboard)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](crk-backend)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)](crk-backend)
[![Ultralytics YOLO11](https://img.shields.io/badge/YOLO11--pose-Ultralytics-00FFFF)](WiseVision)
[![PyTorch](https://img.shields.io/badge/PyTorch-CUDA-EE4C2C?logo=pytorch&logoColor=white)](WiseVision)

---

## Live demo

**[crk-analytics-dashboard-wv5.vercel.app](https://crk-analytics-dashboard-wv5.vercel.app/)** — a static deployment of the [`Dashboard`](Dashboard) frontend, running on **mock data**, so anyone can click through the UI without touching real store data.

The production system is not public. It runs on a private Windows Server VM inside CRK's network, fed live by the in-store cameras and the Joolan point-of-sale system — see [Deployment](#deployment) below.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Repository structure](#repository-structure)
3. [Data model](#data-model)
4. [Sales-potential KPIs](#sales-potential-kpis)
5. [Joolan POS integration](#joolan-pos-integration)
6. [API reference](#api-reference)
7. [Security model](#security-model)
8. [Quick start (development)](#quick-start-development)
9. [Deployment](#deployment)
10. [What makes the numbers trustworthy](#what-makes-the-numbers-trustworthy)
11. [Known limitations](#known-limitations)
12. [Documentation](#documentation)

---

## How it works

```
   In-store camera                                       Joolan POS
         │                                                     ▲
         ▼                                                     │
┌──────────────────┐   HTTP POST /ingest/batch      ┌──────────┴──────────┐
│   WiseVision      │   (X-API-Key, every few sec)   │  crk-backend        │
│   Jetson / edge AI│ ──────────────────────────────►│  FastAPI + SQLite   │
│                    │   ENTRY / INTERACTION events   │  (WAL mode)         │
│  YOLO11-pose       │                                 │                      │
│  + BoT-SORT ReID   │                                 │  aggregates at      │
│  role + zone logic │                                 │  READ time, never   │
└──────────────────┘                                 │  pre-computed        │
                                                        └──────────┬──────────┘
                                                                   │ GET /api/*
                                                                   ▼
                                                        ┌──────────────────────┐
                                                        │  Dashboard (React)    │
                                                        │  Overview · Compare   │
                                                        │  · AI-written reports │
                                                        └──────────────────────┘
```

**No image ever leaves the store.** The Jetson turns video into discrete events (`ENTRY`, `INTERACTION`) — about 80 bytes each — and only those events cross the network. The backend never re-judges what the AI decided; it counts. Every indicator is computed at read time from raw events, so changing a business rule is a code change, never a data migration. And a number that can't be measured is `null`, shown as `—`, never a silent `0`.

**One process, one port.** `crk-backend` both serves the API and the built dashboard (`Dashboard/dist`) from the same FastAPI process. The browser and the API share an origin, so there's no CORS to configure, no reverse proxy, and no backend URL baked into the frontend build — the same build works on `localhost`, an internal IP, or behind a domain name.

---

## Repository structure

| Folder | Role | Stack |
|---|---|---|
| [`WiseVision/`](WiseVision) | Edge AI: person detection, staff/customer classification, entry counting, interaction (hand-off) detection — runs on the Jetson in-store | Python, YOLO11-pose, BoT-SORT + OSNet ReID |
| [`crk-backend/`](crk-backend) | Ingests camera events, queries the Joolan POS API, aggregates everything at read time, serves the built dashboard | FastAPI, SQLite (WAL) |
| [`Dashboard/`](Dashboard) | The UI: footfall, sales-potential KPIs, store comparison, AI-generated reports | React 18, Vite 5, Recharts |
| [`deploy/windows/`](deploy/windows) | One idempotent script that installs everything as a self-restarting Windows service | PowerShell |
| [`swagger.yaml`](swagger.yaml) | Full OpenAPI spec of the Joolan POS API this project integrates with | OpenAPI 3 |

Only the backend and the dashboard talk to each other directly. WiseVision is a separate, standalone pipeline: it emits events over HTTP and has no other coupling to the rest of the codebase.

---

## Data model

SQLite (WAL mode) is a deliberate choice, not a placeholder for "real" database: a single writer, a few thousand events per store per week, and an index on `(store_id, ts)` that matches exactly the question the dashboard asks. It stays the right choice until any of these becomes true: several machines writing concurrently, several services writing at once, tens of millions of rows with slow queries, or a need for replication — none of which apply today. Moving to PostgreSQL at that point is a small job, because the schema is deliberately minimal.

**`events`** — the raw facts, six columns, nothing pre-computed:

| Column | Purpose |
|---|---|
| `store_id` | which store |
| `event_type` | `ENTRY` or `INTERACTION` |
| `ts` | Unix timestamp, after clock realignment |
| `track_id` | the tracker's ID for that person — recycled, never a primary key |
| `received_at` | when the server got the batch (used for `last-seen` diagnostics) |

**`pos_hourly`** — a cache of Joolan sales data, one row per `(store, date, hour)`; see [Joolan POS integration](#joolan-pos-integration) for why it exists.

### Deduplication: the heart of the count

A tracker's `track_id` is **not** a stable identity. Within a day, the same person can be assigned a new ID when the tracker briefly loses and re-finds them (measured on one store: 54 repeat detections out of 658 entries, median gap 10.7s — counting them separately inflated the total by **+8.2%**). Across days, IDs are recycled from a counter that restarts on every device reboot — counting distinct `track_id`s without bounding by day merged unrelated people and undercounted by **−8.4%**.

The fix is a composite key: **`(track_id, local day)`**. The day boundary merges the within-day re-detections and separates the cross-day reassignments — one key solves both problems. A resent batch (network retry) reproduces the exact same keys, so the count is idempotent by construction. An event with no `track_id` gets a key of its own instead of being dropped.

```
clients_entres = distinct (track_id, day) over ENTRY events
pec_count      = distinct (track_id, day) over INTERACTION events
taux_pec       = pec_count / clients_entres × 100   (null if clients_entres = 0)
```

---

## Sales-potential KPIs

Six indicators cross-reference what the camera measures (visitors, engaged customers) against what the till measures (tickets, revenue):

| Symbol | Quantity | Source |
|---|---|---|
| **V** | Visitors | Jetson (deduplicated `ENTRY`) |
| **A** | Visitors engaged | Jetson (deduplicated `INTERACTION`) |
| **T** | Tickets | Joolan POS |
| **R** | Revenue | Joolan POS |

| # | Indicator | Formula | `null` if |
|---|---|---|---|
| 1 | `conversion_rate` | T / V × 100 | V = 0 |
| 2 | `average_basket` | R / T | T = 0 |
| 3 | `pec_rate` | A / V × 100 | V = 0 |
| 4 | `sales_potential` | V × (`CR_target`/100) × `AB_reference` | — |
| 5 | `opportunity_gap` | max(potential − R, 0) | — |
| 6 | `opportunity_capture_rate` | R / potential × 100 | potential = 0 |

`CR_target` (default 20%) and `AB_reference` (default 290 DT) are business parameters, adjustable via environment variable and, for the conversion target, from the dashboard itself — moving the target is a working hypothesis, not a measurement, and watching the potential shift with it is the point. Every one of the six is also broken down **hour by hour**, using the same formula, so the hourly bars always sum exactly to the period total.

---

## Joolan POS integration

Joolan is CRK's point-of-sale software. The integration uses exactly one endpoint, `export-tickets.do`, and its shape dictates the whole caching design:

1. **One day per call** — the API takes a required `Date` parameter, no range. A 30-day dashboard view would mean 30 HTTP calls on every refresh without a cache, hence the `pos_hourly` table.
2. **One call returns every store** — the `Magasin` field on each ticket header lets the response be split per store. So Joolan is called once per **date**, never per store: a week across 8 stores costs 7 requests, not 56.
3. **The hour is returned**, discovered by actually calling the API rather than trusting the (incomplete) spec — which is what makes hour-by-hour revenue a measurement rather than a reconstruction.

Until a store's `CRK_JOOLAN_MAGASINS` mapping and the three Joolan credentials (`CRK_JOOLAN_DOMAIN` / `_ENSEIGNE` / `_API_KEY`) are all configured, [`pos.py`](crk-backend/pos.py) **simulates** tickets and revenue with a deterministic generator and returns `simule: true` — the dashboard shows an orange banner rather than presenting a guess as a measurement. A day Joolan couldn't answer is never cached as a zero; it's listed in `joursManquants`, and the dashboard says the period's revenue is understated.

State of the integration and what's still pending confirmation from CRK: [`crk-backend/JOOLAN_INTEGRATION.md`](crk-backend/JOOLAN_INTEGRATION.md).

---

## API reference

Base URL in production: `http://<vm-ip>:8000`. Interactive docs: `/docs`.

**Ingestion** (requires header `X-API-Key`):

| Method | Route | Body | Response |
|---|---|---|---|
| POST | `/ingest/event` | one event | `{ok, stored}` |
| POST | `/ingest/batch` | `{"events": [...]}`, up to 1000 | `{received, inserted}` |

The API accepts `ENTRY`, `INTERACTION` and `HEARTBEAT` — rejecting any single event would fail the whole batch — but only stores the first two. `inserted < received` is normal, not an error: it's the discarded heartbeats.

**Reads** (public — no key; CORS restricted to `CRK_ALLOWED_ORIGINS` in dev):

| Route | Parameters | Returns |
|---|---|---|
| `GET /api/stores` | — | store list with last-seen timestamps |
| `GET /api/range` | `magasin`, `du`, `au`, `objectif?` | everything the Overview page renders |
| `GET /api/dashboard` | `magasin`, `date`, `objectif?` | single-day shortcut, same shape as `/api/range` |
| `GET /api/comparison` | `du`, `au` | one aggregated row per store |
| `GET /api/series` | `magasin`, `periode` (`jour`/`semaine`/`mois`), `fin` | time series |
| `GET /api/health` | — | service + database status |
| `GET /api/last-seen` | `magasin` | seconds since that store's last event — the #1 tool for checking a device is still transmitting |

Dates are ISO `YYYY-MM-DD`. An unknown store is a 404; an invalid parameter is a 400 with the reason; a reversed date range is corrected automatically; ranges over 400 days are rejected. Full response shapes: [`crk-backend/README.md`](crk-backend/README.md) and the interactive `/docs`.

---

## Security model

| Protected | How |
|---|---|
| Writes (`/ingest/*`) | `X-API-Key` header, shared secret with every Jetson device |
| Path traversal | `is_relative_to(DIST_DIR)` check before serving any static file |
| Oversized batches | `max_length=1000` on the ingestion payload |
| Oversized queries | 400-day cap on any date range |
| Joolan key leaking into logs | masked before every log line |
| SQL injection | bound parameters everywhere, no string-built queries |
| Secrets in git | `.env` is gitignored in all three sub-projects |

**Reads (`/api/*`) are intentionally public** on the local network — no key required. This is a deliberate trade-off: writing can corrupt history with no way to sort it out afterward, so it's locked down; reading can't break anything, and an open read API is what lets a store manager open the dashboard with no login. The real perimeter is the network: the firewall rule should be scoped to the stores' and office's addresses, and traffic is plain HTTP, acceptable on a private network but not meant to cross the public internet as-is — a TLS reverse proxy is the next step if that ever changes.

---

## Quick start (development)

Two terminals — the backend first.

```bash
# Terminal A — backend
cd crk-backend
pip install -r requirements.txt
cp .env.example .env          # set CRK_API_KEY
py main.py                    # http://localhost:8000

# Terminal B — dashboard
cd Dashboard
npm install
npm run dev                   # http://localhost:5173
```

The dashboard calls `/api/...` with relative URLs; Vite's dev proxy (`Dashboard/vite.config.js`) forwards them to `CRK_BACKEND_URL` (`http://localhost:8080` by default — set it in `Dashboard/.env` if your backend listens elsewhere, e.g. port 8000).

Running WiseVision's pipeline locally (against your own footage) is documented in [`WiseVision/README.md`](WiseVision/README.md).

---

## Deployment

A single service serves the dashboard **and** the API on the same port — no nginx, no CORS, no backend URL baked into the frontend build. On the target Windows Server VM, in an **administrator** PowerShell console:

```powershell
cd C:\path\to\CRK-analytics-dashboard
.\deploy\windows\install.ps1 -Port 8000
```

The script provisions the Python venv, installs pinned dependencies, generates `.env` with a random API key, builds the dashboard, registers a self-restarting scheduled task, opens the firewall, and verifies the deployment before exiting. It's **idempotent** — rerunning it after a `git pull` updates the service without touching `.env` or the database.

Full runbook (operations, backup, troubleshooting): [`deploy/windows/README.md`](deploy/windows/README.md).

---

## What makes the numbers trustworthy

- **The AI is never second-guessed.** The backend stores exactly what the Jetson decided — it doesn't filter, re-score, or "clean up" a detection.
- **People are deduplicated correctly.** See [Data model](#data-model) — the `(track_id, local day)` key fixed an 8.2% over-count and an 8.4% under-count at once.
- **A missing measurement is visible, not zero.** `null` renders as `—` everywhere — on the dashboard and in the AI-generated reports — so "nobody came in" is never confused with "the camera sent nothing."
- **Simulated data announces itself.** Until a store's Joolan mapping is configured, sales figures are simulated and flagged with an orange banner and `simule: true` in the API — never silently presented as real.
- **Anomalies are never capped away.** The hand-off rate can (and currently does, on one measured store) exceed 100% — a defect in the vision pipeline, not the aggregation. The dashboard shows it as-is instead of clamping the axis, because a hidden anomaly is a bug nobody ever finds.

---

## Known limitations

- **Hand-off rate exceeding 100%** on the one active store — a vision-pipeline defect (likely over-counted interactions or under-counted entries), still under investigation; the system reports it rather than hiding it.
- **7 of 8 stores** have no camera feed yet and no confirmed Joolan store-code mapping, so they show zero footfall and zero revenue rather than real numbers.
- **POS field definitions** (`Nature` values for returns/credit notes, whether `Total_TTC` includes discounts, how a cancelled ticket appears) are still to be confirmed with CRK — see [`crk-backend/JOOLAN_INTEGRATION.md`](crk-backend/JOOLAN_INTEGRATION.md).
- **No automated tests yet.** The deduplication and KPI-formula functions are pure functions, testable without a server or database — the best available return on investment for future work.
- **The AI-report prompt** (Gemini, in `Dashboard/src/report/generateReport.js`) predates the Joolan integration and still claims there is no cash-register data at all; it needs updating now that revenue is real.

---

## Documentation

| Document | Content |
|---|---|
| [`crk-backend/README.md`](crk-backend/README.md) | API endpoints, computation rules, timestamp handling |
| [`crk-backend/JOOLAN_INTEGRATION.md`](crk-backend/JOOLAN_INTEGRATION.md) | State of the POS integration, what's left to confirm with CRK |
| [`Dashboard/README.md`](Dashboard/README.md) | Pages, structure, customization |
| [`WiseVision/README.md`](WiseVision/README.md) | The vision pipeline: detection, role classification, entry/interaction counting, camera onboarding |
| [`deploy/windows/README.md`](deploy/windows/README.md) | Operations runbook — install, update, backup, troubleshooting |
| [`swagger.yaml`](swagger.yaml) | Joolan POS API v2 specification |

---

## Status

Actively used in production for CRK Maroquinier's Manar City store, with the remaining 7 stores pending camera rollout and POS store-code mapping.

This is a client project built for CRK Maroquinier; the code is shared here for portfolio and architecture-reference purposes.
