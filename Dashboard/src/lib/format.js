// ============================================================
// Formatage français, partagé par les pages et les rapports.
//
// Règle commune : `null` / `undefined` => « — ». Le backend renvoie null quand
// aucun événement ne permet de calculer l'indicateur ; on ne le remplace jamais
// par 0, qui se lirait comme une vraie mesure nulle.
// ============================================================

export const MISSING = "—";

const isMissing = (v) => v === null || v === undefined || Number.isNaN(v);

export const fmtInt = (v) => (isMissing(v) ? MISSING : Math.round(v).toLocaleString("fr-FR"));

export const fmtNum = (v, digits = 1) =>
  isMissing(v) ? MISSING : v.toFixed(digits).replace(".", ",");

export const fmtPct = (v, digits = 1) => (isMissing(v) ? MISSING : `${fmtNum(v, digits)}%`);

/** Montants en dinars : « 12 586 DT ». digits=2 pour un panier moyen. */
export const fmtDT = (v, digits = 0) =>
  isMissing(v)
    ? MISSING
    : `${(digits ? v.toFixed(digits).replace(".", ",") : Math.round(v).toLocaleString("fr-FR"))} DT`;

export const MOIS_COURT = [
  "Jan", "Fév", "Mars", "Avr", "Mai", "Juin",
  "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
];

export const fmtDate = (d) =>
  `${String(d.getDate()).padStart(2, "0")} ${MOIS_COURT[d.getMonth()]} ${d.getFullYear()}`;

/** « 12 – 18 Juil 2026 », « 28 Juin – 4 Juil 2026 », « 12 Juil 2026 » (1 jour). */
export function fmtRange(start, end) {
  const [d1, m1, y1] = [start.getDate(), start.getMonth(), start.getFullYear()];
  const [d2, m2, y2] = [end.getDate(), end.getMonth(), end.getFullYear()];
  if (d1 === d2 && m1 === m2 && y1 === y2) return `${d2} ${MOIS_COURT[m2]} ${y2}`;
  if (m1 === m2 && y1 === y2) return `${d1} – ${d2} ${MOIS_COURT[m2]} ${y2}`;
  if (y1 === y2) return `${d1} ${MOIS_COURT[m1]} – ${d2} ${MOIS_COURT[m2]} ${y2}`;
  return `${d1} ${MOIS_COURT[m1]} ${y1} – ${d2} ${MOIS_COURT[m2]} ${y2}`;
}

/**
 * Variation d'un indicateur entre la période courante et la précédente.
 * mode "points" pour un indicateur déjà en % (on compare en points), "pct" sinon.
 * `null` si la comparaison n'a pas de sens (période précédente vide, division par 0).
 */
export function computeDelta(current, previous, mode = "pct") {
  if (isMissing(current) || isMissing(previous)) return null;
  if (mode === "points") {
    const diff = current - previous;
    return { text: `${fmtNum(Math.abs(diff))} pts`, up: diff >= 0 };
  }
  if (!previous) return null;
  const pct = ((current - previous) / previous) * 100;
  return { text: fmtPct(Math.abs(pct)), up: pct >= 0 };
}
