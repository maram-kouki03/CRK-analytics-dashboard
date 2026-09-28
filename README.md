# CRK Analytics

**A retail intelligence platform that turns in-store cameras and point-of-sale data into a single, trustworthy dashboard.**

CRK Analytics was built for **CRK Maroquinier**, a leather-goods retailer with 8 stores in Tunisia. A computer-vision pipeline running on an **NVIDIA Jetson** in each store counts customers and staff interactions in real time; a backend cross-references that footfall against **Joolan POS** sales data; a React dashboard turns the result into conversion rates, sales potential, and an opportunity gap that store managers can act on.

[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](Dashboard)
[![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)](Dashboard)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](crk-backend)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)](crk-backend)
[![Ultralytics YOLO11](https://img.shields.io/badge/YOLO11--pose-Ultralytics-00FFFF)](WiseVision)
[![PyTorch](https://img.shields.io/badge/PyTorch-CUDA-EE4C2C?logo=pytorch&logoColor=white)](WiseVision)

> 📘 **Want the full story?** [`DOCUMENT.md`](DOCUMENT.md) is a from-scratch, chapter-by-chapter course covering every layer of this system, every design decision and why it was made, the data model, the API, and the deployment. This README is the fast tour; that document is the deep one.

---

## Live demo

**[crk-analytics-dashboard-wv5.vercel.app](https://crk-analytics-dashboard-wv5.vercel.app/)** — a static deployment of the [`Dashboard`](Dashboard) frontend, running on **mock data**, so anyone can click through the UI without touching real store data.

The production system is not public. It runs on a private Windows Server VM inside CRK's network, fed live by the in-store cameras and the Joolan point-of-sale system — see [Deployment](#deployment) below.

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

**No image ever leaves the store.** The Jetson turns video into discrete events (`ENTRY`, `INTERACTION`) — about 80 bytes each — and only those events cross the network. The backend never re-judges what the AI decided; it counts. Every indicator is computed at read time from raw events, so changing a business rule is a code change, never a data migration. And a number that can't be measured is `null`, shown as `—`, never a silent `0` — see [DOCUMENT.md, "The three rules"](DOCUMENT.md#the-three-rules-that-govern-the-whole-project) for why that discipline is the difference between a trustworthy dashboard and a decorative one.

---

## Repository structure

| Folder | Role | Stack |
|---|---|---|
| [`WiseVision/`](WiseVision) | Edge AI: person detection, staff/customer classification, entry counting, interaction (hand-off) detection — runs on the Jetson in-store | Python, YOLO11-pose, BoT-SORT + OSNet ReID |
| [`crk-backend/`](crk-backend) | Ingests camera events, queries the Joolan POS API, aggregates everything at read time, serves the built dashboard | FastAPI, SQLite (WAL) |
| [`Dashboard/`](Dashboard) | The UI: footfall, sales-potential KPIs, store comparison, AI-generated reports | React 18, Vite 5, Recharts |
| [`deploy/windows/`](deploy/windows) | One idempotent script that installs everything as a self-restarting Windows service | PowerShell |
| [`swagger.yaml`](swagger.yaml) | Full OpenAPI spec of the Joolan POS API this project integrates with | OpenAPI 3 |

Only the backend and the dashboard talk to each other directly (same-origin, one process, one port — no CORS, no reverse proxy). WiseVision is a separate, standalone pipeline: it emits events over HTTP and has no other coupling to the rest of the codebase.

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
- **People are deduplicated correctly.** A tracker's ID is recycled within a day and across days; entries are keyed on `(track_id, local day)`, which fixed an **8.2% over-count** from re-detections and an **8.4% under-count** from ID recycling — see [DOCUMENT.md §5.2](DOCUMENT.md#52-deduplication-the-heart-of-the-count).
- **A missing measurement is visible, not zero.** `null` renders as `—` everywhere — on the dashboard and in the AI-generated reports — so "nobody came in" is never confused with "the camera sent nothing."
- **Simulated data announces itself.** Until a store's Joolan mapping is configured, sales figures are simulated and flagged with an orange banner and `simule: true` in the API — never silently presented as real.
- **Anomalies are never capped away.** The hand-off rate can (and currently does, on one measured store) exceed 100% — a defect in the vision pipeline, not the aggregation. The dashboard shows it as-is instead of clamping the axis, because a hidden anomaly is a bug nobody ever finds.

---

## Documentation

| Document | Content |
|---|---|
| [`DOCUMENT.md`](DOCUMENT.md) | **The complete course** — architecture, data model, deduplication logic, Joolan integration, deployment internals, security model, known limitations |
| [`crk-backend/README.md`](crk-backend/README.md) | API endpoints, computation rules, timestamp handling |
| [`crk-backend/JOOLAN_INTEGRATION.md`](crk-backend/JOOLAN_INTEGRATION.md) | State of the POS integration, what's left to confirm with CRK |
| [`Dashboard/README.md`](Dashboard/README.md) | Pages, structure, customization |
| [`WiseVision/README.md`](WiseVision/README.md) | The vision pipeline: detection, role classification, entry/interaction counting, camera onboarding |
| [`deploy/windows/README.md`](deploy/windows/README.md) | Operations runbook — install, update, backup, troubleshooting |
| [`swagger.yaml`](swagger.yaml) | Joolan POS API v2 specification |

---

## Status

Actively used in production for CRK Maroquinier's Manar City store, with the remaining 7 stores pending camera rollout and POS store-code mapping. Known gaps and next steps — the hand-off-rate anomaly, POS field definitions still to confirm, missing automated tests — are tracked in [DOCUMENT.md §16](DOCUMENT.md#16-known-limitations-and-next-steps).

This is a client project built for CRK Maroquinier; the code is shared here for portfolio and architecture-reference purposes.
