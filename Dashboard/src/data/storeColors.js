// ============================================================
// Couleur de courbe par magasin (page Comparaison).
// Choix graphique uniquement — la liste des magasins vient de /api/stores,
// pas d'ici. Un magasin absent de cette table retombe sur la palette.
// ============================================================

const EXPLICIT = {
  "Mall of Sousse": "#1e9e5a",
  "Tunisia Mall": "#96402e",
  "Mall of Sfax": "#d97a1a",
  "Sfax 1": "#c2a11a",
  "La Marsa": "#2e6bd6",
  "Azur City": "#8e44ad",
  "MANAR CITY": "#d64533",
  "Menzah 5": "#5a8a8a",
};

const FALLBACK = ["#96402e", "#1e9e5a", "#2e6bd6", "#d97a1a", "#8e44ad", "#5a8a8a", "#c2a11a"];

export function storeColor(nom, index = 0) {
  return EXPLICIT[nom] ?? FALLBACK[index % FALLBACK.length];
}
