// ============================================================
// Client HTTP du backend crk-backend.
//
// Un indicateur que le backend renvoie à `null` (pas d'événement pour le
// calculer) reste `null` jusqu'à l'affichage, où il devient « — » : une mesure
// absente doit rester visiblement absente.
//
// Base d'URL : VITE_API_URL (ex. http://localhost:8080).
// Non définie => URLs relatives, servies par le proxy /api de Vite en dev
// (voir vite.config.js) ou par le reverse proxy en production — SAUF si aucun
// backend n'est joignable du tout (déploiement de présentation, ex. Vercel) :
// dans ce cas on bascule sur des données fictives générées dans le navigateur
// (./mockData.js), avec exactement la même forme de réponse.
// ============================================================

import * as mock from "./mockData";

const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const USE_MOCK = !BASE;

export class ApiError extends Error {
  constructor(message, { status = null, cause = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.cause = cause;
  }
}

export const iso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

async function get(path, params) {
  const query = new URLSearchParams(params ?? {}).toString();
  const url = `${BASE}/api/${path}${query ? `?${query}` : ""}`;

  let resp;
  try {
    resp = await fetch(url);
  } catch (cause) {
    // fetch ne rejette que sur erreur réseau : backend arrêté, mauvaise URL, CORS.
    throw new ApiError(
      `Backend injoignable sur ${BASE || window.location.origin}. ` +
        "Vérifie que crk-backend tourne (py main.py) et que VITE_API_URL pointe dessus.",
      { cause }
    );
  }

  if (!resp.ok) {
    let detail = "";
    try {
      const body = await resp.json();
      detail = body?.detail ? ` — ${JSON.stringify(body.detail)}` : "";
    } catch {
      /* réponse non JSON : on garde juste le code HTTP */
    }
    throw new ApiError(`${path} : HTTP ${resp.status}${detail}`, { status: resp.status });
  }

  return resp.json();
}

/** [{ nom, aDonnees }] — les 8 magasins, avec le drapeau « a déjà envoyé des événements ». */
export const fetchStores = () =>
  (USE_MOCK ? mock.fetchStores() : get("stores")).then((r) => r.stores);

/** Tout ce que dessine la page Vue d'ensemble pour un magasin sur une période.
 *
 * `objectif` (0-100) est l'objectif de conversion choisi dans l'interface. Omis,
 * le backend retombe sur CRK_CR_TARGET_PCT. Il ne déplace que le potentiel de
 * vente et ce qui en dérive — jamais une mesure.
 */
export const fetchRange = (magasin, start, end, objectif) =>
  USE_MOCK
    ? mock.fetchRange(magasin, start, end, objectif)
    : get("range", {
        magasin,
        du: iso(start),
        au: iso(end),
        ...(objectif == null ? {} : { objectif }),
      });

/** Une ligne agrégée par magasin sur la période (page Comparaison). */
export const fetchComparison = (start, end) =>
  USE_MOCK ? mock.fetchComparison(start, end) : get("comparison", { du: iso(start), au: iso(end) });

/** Série temporelle clients / PEC / taux PEC. periode : "jour" | "semaine" | "mois". */
export const fetchSeries = (magasin, periode, fin) =>
  USE_MOCK ? mock.fetchSeries(magasin, periode, fin) : get("series", { magasin, periode, fin: iso(fin) });

/** Diagnostic : dernier événement reçu pour ce magasin. */
export const fetchLastSeen = (magasin) =>
  USE_MOCK ? mock.fetchLastSeen(magasin) : get("last-seen", { magasin });
