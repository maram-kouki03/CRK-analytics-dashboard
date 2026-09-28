import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

import analytics
import db
from models import BatchRequest, IngestEvent

load_dotenv()

API_KEY = os.environ.get("CRK_API_KEY")
if not API_KEY:
    raise RuntimeError("CRK_API_KEY environment variable is required")

# Dev default covers the Vite dev server on either of the ports it picks. In
# production the dashboard is served from this same process (see below), so it
# is same-origin and no CORS entry is needed at all.
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CRK_ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()
]

# Built dashboard. Default assumes the repo layout (crk-backend/ next to
# Dashboard/); CRK_DASHBOARD_DIST overrides it for other deployments.
DIST_DIR = Path(
    os.environ.get("CRK_DASHBOARD_DIST", Path(__file__).resolve().parent.parent / "Dashboard" / "dist")
).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Affiché au démarrage : lire quel fichier est ouvert et combien d'événements
    # il contient évite de chercher longtemps pourquoi le dashboard semble figé
    # alors qu'il lit simplement une copie périmée.
    # Sans accents : ces lignes s'affichent dans une console Windows dont
    # l'encodage n'est pas garanti, et ce sont justement celles qu'on lit
    # quand quelque chose ne va pas.
    print(f"[crk] base       : {os.path.abspath(db.DB_PATH)}", flush=True)
    print(f"[crk] evenements : {db.get_events_total()}", flush=True)
    print(f"[crk] dashboard  : {DIST_DIR}{'' if DIST_DIR.is_dir() else '   ABSENT'}", flush=True)

    # La lecture fonctionne sur l'ancien schema, mais la base garde alors des
    # colonnes et des lignes (PEC*, HEARTBEAT) qui ne servent plus. On le signale
    # sans rien forcer : migrate_db.py supprime des donnees, c'est un choix.
    legacy = db.legacy_columns_present()
    if legacy:
        print(
            f"[crk] ancien schema detecte (colonnes : {', '.join(legacy)})\n"
            "[crk] -> lecture OK, mais lance `py migrate_db.py` pour nettoyer\n"
            "[crk]    (arrete d'abord tout autre service qui ecrit dans cette base)",
            flush=True,
        )
    yield


app = FastAPI(title="CRK Maroquinier Retail1 Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: str | None = Header(default=None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def _store_or_404(magasin: str) -> str:
    store = db.resolve_store(magasin)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown store")
    return store


def _guard(fn, *args):
    """Run an analytics call, turning bad parameters into a 400."""
    try:
        return fn(*args)
    except analytics.BadRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------------- ingestion

@app.post("/ingest/event", dependencies=[Depends(verify_api_key)])
def ingest_event(event: IngestEvent):
    stored = db.insert_events_batch([event.model_dump()])
    # `stored` vaut 0 pour un HEARTBEAT : accepté, non conservé.
    return {"ok": True, "stored": stored}


@app.post("/ingest/batch", dependencies=[Depends(verify_api_key)])
def ingest_batch(batch: BatchRequest):
    events = [e.model_dump() for e in batch.events]
    inserted = db.insert_events_batch(events)
    # On renvoie les deux nombres : les HEARTBEAT ne sont pas stockés, donc
    # `inserted` peut être plus petit que `received` sans que ce soit une erreur.
    return {"received": len(events), "inserted": inserted}


# -------------------------------------------------------------- dashboard read

@app.get("/api/stores")
def get_stores():
    # dernierEvenementTs lets the dashboard open on the store that is actually
    # live rather than on whichever one happens to be first in STORE_NAMES.
    latest = db.get_stores_last_event()
    return {
        "stores": [
            {
                "nom": name,
                "aDonnees": name in latest,
                "dernierEvenementTs": latest.get(name),
            }
            for name in db.STORE_NAMES
        ]
    }


@app.get("/api/range")
def get_range(magasin: str, du: str, au: str, objectif: float | None = None):
    """Vue d'ensemble: KPIs, hourly curves, daily evolution, heatmap, zones."""
    return _guard(analytics.build_range_response, _store_or_404(magasin), du, au, objectif)


@app.get("/api/dashboard")
def get_dashboard(magasin: str, date: str, objectif: float | None = None):
    """Single-day shorthand for /api/range — same response shape."""
    return _guard(analytics.build_range_response, _store_or_404(magasin), date, date, objectif)


@app.get("/api/comparison")
def get_comparison(du: str, au: str):
    """Comparaison: one aggregated row per store over the range."""
    return _guard(analytics.build_comparison_response, du, au)


@app.get("/api/series")
def get_series(magasin: str, periode: str = "jour", fin: str | None = None):
    """Clients / PEC / taux PEC over time at day, week or month granularity."""
    if fin is None:
        raise HTTPException(status_code=400, detail="fin (YYYY-MM-DD) is required")
    return _guard(analytics.build_series_response, _store_or_404(magasin), periode, fin)


# ----------------------------------------------------------------- diagnostics

@app.get("/api/health")
def get_health():
    return {"status": "ok", "db": "ok", "events_total": db.get_events_total()}


@app.get("/api/last-seen")
def get_last_seen(magasin: str):
    store = _store_or_404(magasin)
    row = db.get_last_event(store)
    if row is None:
        return {
            "store_id": store,
            "last_event_ts": None,
            "last_received_at": None,
            "seconds_ago": None,
        }
    return {
        "store_id": store,
        "last_event_ts": row["ts"],
        "last_received_at": row["received_at"],
        "seconds_ago": int(time.time() - row["received_at"]),
    }


# ------------------------------------------------------------ dashboard statique
# Déclaré EN DERNIER : FastAPI teste les routes dans l'ordre d'enregistrement, et
# le catch-all ci-dessous avalerait /api/* s'il était défini plus haut.
#
# Servir le dashboard depuis ce même processus le rend « same-origin » : plus de
# CORS, plus de reverse proxy, plus de VITE_API_URL à figer au build. Un seul
# service à installer et à surveiller sur la VM.


@app.get("/{full_path:path}", include_in_schema=False)
def serve_dashboard(full_path: str):
    # Une route API inconnue doit rester un 404 JSON, pas la page du dashboard :
    # sinon un appel mal orthographié renverrait 200 + du HTML, et le client
    # échouerait au parsing JSON au lieu de dire clairement ce qui manque.
    if full_path.startswith(("api/", "ingest/")):
        raise HTTPException(status_code=404, detail="unknown endpoint")

    if not DIST_DIR.is_dir():
        return PlainTextResponse(
            f"Dashboard non construit : {DIST_DIR} est introuvable.\n"
            "Lancer `npm ci && npm run build` dans Dashboard/, ou pointer "
            "CRK_DASHBOARD_DIST vers le dossier dist.\n"
            "L'API reste disponible sur /api/*.",
            status_code=503,
        )

    if full_path:
        asset = (DIST_DIR / full_path).resolve()
        # is_relative_to bloque les remontées ../ : sans ce test, une URL
        # forgée lirait n'importe quel fichier de la VM.
        if asset.is_file() and asset.is_relative_to(DIST_DIR):
            return FileResponse(asset)

    # Tout le reste appartient à React Router (/comparaison, /rapports).
    return FileResponse(DIST_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("CRK_HOST", "0.0.0.0"),
        port=int(os.environ.get("CRK_PORT", "8000")),
    )
