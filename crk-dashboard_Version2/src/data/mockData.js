// ============================================================
// Données de démonstration CRK
// Les données du dashboard sont GÉNÉRÉES par magasin + par date
// (déterministe : même magasin + même date = mêmes chiffres).
// À remplacer plus tard par un fetch vers l'API de la pipeline.
// ============================================================

export const storeNames = [
  "Mall of Sousse",
  "Tunisia Mall",
  "Mall of Sfax",
  "Sfax 1",
  "La Marsa",
  "Azur City",
  "MANAR CITY",
  "Menzah 5",
];

// Profil de base de chaque magasin (taille / performance moyenne)
// panier = panier moyen en DT (donnée fournie par CRK / caisses)
// conv = taux de transformation de base en % (tickets / visiteurs)
const profiles = {
  "Mall of Sousse": { clients: 1010, taux: 88.5, vendeurs: 11, temps: 19, panier: 165, conv: 11.5 },
  "Tunisia Mall":   { clients: 1340, taux: 83.8, vendeurs: 12, temps: 18, panier: 180, conv: 10.2 },
  "Mall of Sfax":   { clients: 1130, taux: 82.0, vendeurs: 14, temps: 17, panier: 150, conv: 9.8 },
  "Sfax 1":         { clients: 620,  taux: 79.0, vendeurs: 7,  temps: 20, panier: 135, conv: 8.5 },
  "La Marsa":       { clients: 960,  taux: 74.5, vendeurs: 10, temps: 16, panier: 195, conv: 7.9 },
  "Azur City":      { clients: 740,  taux: 76.5, vendeurs: 8,  temps: 21, panier: 145, conv: 8.2 },
  "MANAR CITY":     { clients: 540,  taux: 76.0, vendeurs: 6,  temps: 22, panier: 140, conv: 7.5 },
  "Menzah 5":       { clients: 480,  taux: 75.0, vendeurs: 6,  temps: 23, panier: 130, conv: 7.1 },
};

// ---------- Générateur pseudo-aléatoire déterministe ----------
// même graine (magasin + date) => toujours les mêmes valeurs
function hashString(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makeRng(store, date) {
  const key = `${store}|${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
  return mulberry32(hashString(key));
}

// variation autour d'une valeur : base ± pct%
const vary = (rng, base, pct) => base * (1 + (rng() * 2 - 1) * pct);

const HEURES = ["09h","10h","11h","12h","13h","14h","15h","16h","17h","18h","19h","20h"];
// forme de la courbe d'affluence sur la journée (pic 12h-13h)
const SHAPE = [0.36, 0.54, 0.78, 1.0, 0.9, 0.66, 0.52, 0.44, 0.39, 0.31, 0.21, 0.09];

const fmtInt = (n) => Math.round(n).toLocaleString("fr-FR");
const fmtPct = (n) => `${n.toFixed(1).replace(".", ",")}%`;

// ---------- Chiffres bruts d'un magasin pour une date ----------
function rawDayStats(store, date) {
  const p = profiles[store];
  const rng = makeRng(store, date);
  const clients = Math.round(vary(rng, p.clients, 0.12));
  const taux = Math.min(96, Math.max(55, vary(rng, p.taux, 0.05)));
  const pec = Math.round((clients * taux) / 100);
  const vendeurs = Math.max(3, Math.round(vary(rng, p.vendeurs, 0.15)));
  const temps = Math.max(10, Math.round(vary(rng, p.temps, 0.15)));
  // Données caisse (démo) : taux de transformation et panier moyen du jour
  const conv = Math.min(25, Math.max(3, vary(rng, p.conv, 0.15)));   // %
  const tickets = Math.round((clients * conv) / 100);
  const panier = p.panier;                                           // DT (valeur de référence fixe fournie par CRK)
  return { clients, pec, taux, vendeurs, temps, conv, tickets, panier, rng };
}

// ---------- Statistiques par zone (pipeline vision SC.py, simulées) ----------
// counting_per_zone : nombre de clients ayant visité la zone sur la journée (cumul)
// pec_per_zone : prises en charge par zone
// 3 zones (Z1, Z2, Z3) ; Z2 (îlots centraux) est la plus fréquentée par défaut.
const ZONE_BASE_WEIGHTS = [0.32, 0.43, 0.25];

export function getZoneStats(store, date) {
  const day = rawDayStats(store, date);
  const rng = day.rng;

  // pondération du jour par zone, variée légèrement autour de la base
  // (une zone reste dominante par magasin grâce à ZONE_BASE_WEIGHTS)
  const weights = ZONE_BASE_WEIGHTS.map((w) => Math.max(0.05, vary(rng, w, 0.2)));
  const weightSum = weights.reduce((a, b) => a + b, 0);

  // les 3 zones couvrent 60-80% des clients entrés du jour
  // (tous les visiteurs ne s'arrêtent pas dans une zone : caisse directe, passage rapide, etc.)
  const zonesClientsShare = 0.6 + rng() * 0.2;
  const totalZonesClients = day.clients * zonesClientsShare;

  // les 3 zones couvrent 85-95% du total des PEC du jour (reste : caisse, essayage, etc.)
  const zonesPecShare = 0.85 + rng() * 0.1;
  const totalZonesPec = day.pec * zonesPecShare;

  let allocatedClients = 0;
  let allocatedPec = 0;
  return weights.map((w, i) => {
    const share = w / weightSum;
    const isLast = i === weights.length - 1;
    const clients = isLast
      ? Math.max(0, Math.round(totalZonesClients - allocatedClients))
      : Math.max(0, Math.round(vary(rng, totalZonesClients * share, 0.15)));
    if (!isLast) allocatedClients += clients;
    const pec = isLast
      ? Math.max(0, Math.round(totalZonesPec - allocatedPec))
      : Math.max(0, Math.round(totalZonesPec * share));
    if (!isLast) allocatedPec += pec;
    return { id: i + 1, clients, pec };
  });
}

// ---------- Export pour l'analyse par période ----------
// Statistiques brutes (numériques) d'une seule journée.
export function getDayRaw(store, date) {
  const s = rawDayStats(store, date);
  return {
    clients: s.clients,
    pec: s.pec,
    tauxPec: s.taux,
    vendeurs: s.vendeurs,
    temps: s.temps,
    tickets: s.tickets,
    panier: s.panier,
  };
}

// ---------- Export pour l'agent IA ----------
// Statistiques brutes (nombres, pas de formatage) d'une semaine
// se terminant à endDate : utilisé par agent/export_data.mjs
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function getWeekRaw(store, endDate) {
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate());
    d.setDate(d.getDate() - i);
    const s = rawDayStats(store, d);
    days.push({
      date: iso(d),
      jour: ["Dim","Lun","Mar","Mer","Jeu","Ven","Sam"][d.getDay()],
      clients: s.clients,
      pec: s.pec,
      tauxPec: Number(s.taux.toFixed(1)),
      vendeurs: s.vendeurs,
      tempsAvantPec: s.temps,
      tickets: s.tickets,
      panierMoyen: Number(s.panier.toFixed(0)),
      tauxTransformation: Number(((s.tickets / s.clients) * 100).toFixed(1)),
      potentiel: Math.round(s.panier * s.clients),
      caEstime: Math.round(s.panier * s.tickets),
    });
  }
  return days;
}

// ---------- Données complètes du dashboard ----------
export function getDashboardData(store, date) {
  const today = rawDayStats(store, date);

  // la veille, pour calculer les variations "vs hier"
  const prevDate = new Date(date);
  prevDate.setDate(prevDate.getDate() - 1);
  const hier = rawDayStats(store, prevDate);

  const delta = (a, b) => ((a - b) / b) * 100;

  const kpis = [
    {
      id: "clients", label: "Clients entrés", value: fmtInt(today.clients),
      delta: `${Math.abs(delta(today.clients, hier.clients)).toFixed(1).replace(".", ",")}%`,
      up: today.clients >= hier.clients,
    },
    {
      id: "pec", label: "Nombre de PEC", value: fmtInt(today.pec),
      delta: `${Math.abs(delta(today.pec, hier.pec)).toFixed(1).replace(".", ",")}%`,
      up: today.pec >= hier.pec,
    },
    {
      id: "taux", label: "Taux PEC", value: fmtPct(today.taux),
      delta: `${Math.abs(today.taux - hier.taux).toFixed(1).replace(".", ",")} pts`,
      up: today.taux >= hier.taux,
    },
    {
      id: "vendeurs", label: "Vendeurs actifs", value: String(today.vendeurs),
      delta: String(Math.abs(today.vendeurs - hier.vendeurs)),
      up: today.vendeurs >= hier.vendeurs,
    },
    {
      id: "temps", label: "Temps moyen avant PEC", value: `${today.temps} s`,
      delta: `${Math.abs(today.temps - hier.temps)} s`,
      // pour le temps d'attente, une BAISSE est une bonne nouvelle
      up: today.temps <= hier.temps,
    },
    {
      // Taux de transformation = tickets caisse / visiteurs entrés
      id: "transformation", label: "Taux de transformation",
      value: fmtPct((today.tickets / today.clients) * 100),
      delta: `${Math.abs((today.tickets / today.clients) * 100 - (hier.tickets / hier.clients) * 100).toFixed(1).replace(".", ",")} pts`,
      up: today.tickets / today.clients >= hier.tickets / hier.clients,
    },
    {
      // Potentiel = panier moyen (caisse) × nombre de visiteurs (vision)
      id: "potentiel", label: "Potentiel de revenu",
      value: `${fmtInt(today.panier * today.clients)} DT`,
      delta: `${Math.abs(delta(today.panier * today.clients, hier.panier * hier.clients)).toFixed(1).replace(".", ",")}%`,
      up: today.panier * today.clients >= hier.panier * hier.clients,
    },
  ];

  const rng = today.rng;

  // Affluence par heure : distribution du total de clients sur la journée
  const shapeSum = SHAPE.reduce((a, b) => a + b, 0);
  const heureDePointe = HEURES.map((h, i) => ({
    h,
    clients: Math.round(
      ((today.clients * SHAPE[i]) / shapeSum) * (0.9 + rng() * 0.2)
    ),
  }));

  // Taux PEC par heure : décroît doucement dans la journée
  const tauxParHeure = HEURES.map((h, i) => ({
    h,
    taux: Number(Math.min(98, Math.max(40,
      today.taux + 6 - i * 1.6 + (rng() * 2 - 1) * 4
    )).toFixed(1)),
  }));

  // Évolution hebdo : cette semaine vs semaine dernière
  const jours = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
  const evolutionHebdo = jours.map((jour) => ({
    jour,
    cette: Number(Math.min(98, Math.max(55, vary(rng, today.taux, 0.06))).toFixed(1)),
    derniere: Number(Math.min(98, Math.max(55, vary(rng, hier.taux, 0.06))).toFixed(1)),
  }));

  // Heatmap : intensité par heure (ligne) et jour (colonne)
  const weekendBoost = [0.95, 1.0, 0.97, 1.02, 1.08, 1.2, 0.55]; // Lun..Dim
  const heatmapData = SHAPE.map((s) =>
    weekendBoost.map((w) =>
      Math.min(1, Math.max(0.03, s * w * (0.85 + rng() * 0.3)))
    )
  );

  return { kpis, heureDePointe, tauxParHeure, evolutionHebdo, heatmapData };
}

// ============================================================
// Séries temporelles : taux de transformation & potentiel
// period : "jour" (14 derniers jours) | "semaine" (8 semaines) | "mois" (6 mois)
// ============================================================

const MOIS_COURT = ["Jan","Fév","Mars","Avr","Mai","Juin","Juil","Août","Sept","Oct","Nov","Déc"];

function dayValue(store, date, metric) {
  const s = rawDayStats(store, date);
  if (metric === "transformation") return { tickets: s.tickets, clients: s.clients };
  return { potentiel: s.panier * s.clients };
}

function aggregate(store, dates, metric) {
  if (metric === "transformation") {
    // taux agrégé = total tickets / total visiteurs (pas la moyenne des taux)
    let tickets = 0, clients = 0;
    dates.forEach((d) => { const v = dayValue(store, d, metric); tickets += v.tickets; clients += v.clients; });
    return Number(((tickets / clients) * 100).toFixed(1));
  }
  let total = 0;
  dates.forEach((d) => { total += dayValue(store, d, metric).potentiel; });
  return Math.round(total);
}

export function getKpiSeries(store, metric, period, endDate) {
  const points = [];
  const end = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate());

  if (period === "jour") {
    // 14 derniers jours, un point par jour
    for (let i = 13; i >= 0; i--) {
      const d = new Date(end); d.setDate(d.getDate() - i);
      points.push({
        label: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`,
        value: aggregate(store, [d], metric),
      });
    }
  } else if (period === "semaine") {
    // 8 dernières semaines (lundi → dimanche), un point par semaine
    const monday = new Date(end);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7)); // lundi de la semaine courante
    for (let w = 7; w >= 0; w--) {
      const start = new Date(monday); start.setDate(start.getDate() - w * 7);
      const dates = [];
      for (let j = 0; j < 7; j++) {
        const d = new Date(start); d.setDate(d.getDate() + j);
        if (d <= end) dates.push(d);
      }
      if (dates.length === 0) continue;
      points.push({
        label: `${String(start.getDate()).padStart(2, "0")}/${String(start.getMonth() + 1).padStart(2, "0")}`,
        value: aggregate(store, dates, metric),
      });
    }
  } else {
    // 6 derniers mois, un point par mois
    for (let m = 5; m >= 0; m--) {
      const first = new Date(end.getFullYear(), end.getMonth() - m, 1);
      const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
      const dates = [];
      for (let j = 1; j <= daysInMonth; j++) {
        const d = new Date(first.getFullYear(), first.getMonth(), j);
        if (d <= end) dates.push(d);
      }
      if (dates.length === 0) continue;
      points.push({
        label: MOIS_COURT[first.getMonth()],
        value: aggregate(store, dates, metric),
      });
    }
  }
  return points;
}

export const heatmapHeures = HEURES;
export const heatmapJours = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"];

// ============================================================
// Page comparaison : couleurs de courbe par magasin
// (les données agrégées sur la période viennent de rangeData.js)
// ============================================================

export const lineColors = {
  "Mall of Sousse": "#1e9e5a",
  "Tunisia Mall": "#96402e",
  "Mall of Sfax": "#d97a1a",
  "Sfax 1": "#c2a11a",
  "La Marsa": "#2e6bd6",
  "Azur City": "#8e44ad",
  "MANAR CITY": "#d64533",
  "Menzah 5": "#5a8a8a",
};
