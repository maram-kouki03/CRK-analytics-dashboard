// ============================================================
// Données de démonstration (fake data), générées dans le navigateur.
//
// Utilisées par client.js quand VITE_API_URL n'est pas défini — typiquement un
// déploiement de présentation (Vercel) sans crk-backend derrière. Chaque
// fonction reproduit EXACTEMENT la forme de réponse de l'API réelle
// (crk-backend/analytics.py), pour que les pages n'aient rien à savoir de la
// source des données.
//
// Tout est dérivé d'un PRNG seedé par magasin + jour (+ heure) : recharger la
// même période, ou la lire depuis deux pages différentes, donne toujours les
// mêmes chiffres — comme s'ils venaient d'une vraie base.
// ============================================================

const STORE_NAMES = [
  "Tunisia Mall",
  "Mall of Sousse",
  "Mall of Sfax",
  "Sfax 1",
  "La Marsa",
  "Azur City",
  "MANAR CITY",
  "Menzah 5",
];

// Boutique volontairement "sans flux" : montre que le dashboard gère bien un
// magasin dont le boîtier ne remonte aucun événement (cartes vides, drapeau
// "sans données", exclue du classement).
const SILENT_STORE = "Sfax 1";

const STORE_PROFILES = {
  "Tunisia Mall": { base: 430, pecRate: 0.74, basket: 305 },
  "Mall of Sousse": { base: 265, pecRate: 0.7, basket: 275 },
  "Mall of Sfax": { base: 215, pecRate: 0.68, basket: 260 },
  "La Marsa": { base: 310, pecRate: 0.79, basket: 320 },
  "Azur City": { base: 150, pecRate: 0.66, basket: 250 },
  "MANAR CITY": { base: 345, pecRate: 0.81, basket: 300 },
  "Menzah 5": { base: 185, pecRate: 0.71, basket: 270 },
};

const AB_REFERENCE = 290;
const CR_TARGET_DEFAULT = 20;

const HOURS = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
const HOUR_WEIGHTS = [0.035, 0.06, 0.085, 0.09, 0.07, 0.06, 0.075, 0.09, 0.11, 0.125, 0.105, 0.08];
const WEEKDAY_MULT = [0.9, 0.88, 0.92, 0.97, 1.15, 1.3, 1.05]; // Lun..Dim

const JOUR_LABELS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const MOIS_LABELS = ["Jan", "Fév", "Mars", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"];

// ---------------------------------------------------------------- PRNG seedé

function xmur3(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return (h ^= h >>> 16) >>> 0;
  };
}

function mulberry32(seed) {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Même clé => même tirage. Recharger la période ne fait donc pas "sauter" les chiffres. */
function rngFor(...parts) {
  return mulberry32(xmur3(parts.join("|"))());
}

// -------------------------------------------------------------- date helpers

const isoDate = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

const shortLabel = (d) => `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;

const hourLabel = (h) => `${String(h).padStart(2, "0")}h`;

function addDays(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

/** Copie sans l'heure : évite les décalages d'un jour dus à l'horaire courant. */
function atMidnight(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function enumerateDays(start, end) {
  const days = [];
  let d = atMidnight(start);
  const last = atMidnight(end);
  while (d <= last) {
    days.push(d);
    d = addDays(d, 1);
  }
  return days;
}

const round1 = (v) => Math.round(v * 10) / 10;
const round2 = (v) => Math.round(v * 100) / 100;

// --------------------------------------------------- répartition horaire

/** Répartit `total` sur les poids donnés, en entiers dont la somme vaut EXACTEMENT `total`. */
function distributeInt(total, weights) {
  const raw = weights.map((w) => w * total);
  const floors = raw.map(Math.floor);
  const used = floors.reduce((a, b) => a + b, 0);
  const remainder = total - used;
  const order = raw
    .map((v, i) => [v - Math.floor(v), i])
    .sort((a, b) => b[0] - a[0]);
  const result = floors.slice();
  for (let k = 0; k < remainder; k++) result[order[k][1]] += 1;
  return result;
}

function hourlyDistribution(store, dateObj, total) {
  const map = {};
  if (total <= 0) {
    HOURS.forEach((h) => (map[h] = 0));
    return map;
  }
  const rng = rngFor(store, isoDate(dateObj), "hourw");
  const weights = HOUR_WEIGHTS.map((w) => Math.max(0.01, w * (0.7 + rng() * 0.6)));
  const sum = weights.reduce((a, b) => a + b, 0);
  const norm = weights.map((w) => w / sum);
  const counts = distributeInt(total, norm);
  HOURS.forEach((h, i) => (map[h] = counts[i]));
  return map;
}

// ------------------------------------------------------------- une journée

/** { visitors, pec, hourlyVisitors: {h: n}, hourlyPec: {h: n} } pour un magasin + un jour. */
function buildDay(store, dateObj) {
  if (store === SILENT_STORE) {
    const zero = {};
    HOURS.forEach((h) => (zero[h] = 0));
    return { visitors: 0, pec: 0, hourlyVisitors: zero, hourlyPec: { ...zero } };
  }

  const profile = STORE_PROFILES[store];
  const weekday = (dateObj.getDay() + 6) % 7; // 0 = Lundi
  const rngV = rngFor(store, isoDate(dateObj), "visitors");
  const total = Math.max(1, Math.round(profile.base * WEEKDAY_MULT[weekday] * (0.85 + rngV() * 0.3)));
  const hourlyVisitors = hourlyDistribution(store, dateObj, total);

  const rngRate = rngFor(store, isoDate(dateObj), "pecrate");
  const rngAnom = rngFor(store, isoDate(dateObj), "anomaly");
  let dayRate = profile.pecRate + (rngRate() - 0.5) * 0.12;
  // Rare anomalie de mesure (PEC > clients) : le dashboard sait déjà l'afficher
  // comme telle (badge "anomaly"), autant le montrer de temps en temps.
  if (rngAnom() < 0.05) dayRate = 1.0 + rngAnom() * 0.1;
  dayRate = Math.max(0.3, dayRate);

  const hourlyPec = {};
  let pecTotal = 0;
  for (const h of HOURS) {
    const c = hourlyVisitors[h];
    if (c <= 0) {
      hourlyPec[h] = 0;
      continue;
    }
    const rngH = rngFor(store, isoDate(dateObj), "pec", h);
    const rate = Math.max(0, dayRate + (rngH() - 0.5) * 0.15);
    const p = Math.round(c * rate);
    hourlyPec[h] = p;
    pecTotal += p;
  }

  return { visitors: total, pec: pecTotal, hourlyVisitors, hourlyPec };
}

// ---------------------------------------------------------------- ventes

/** Simule les ventes d'une tranche horaire à partir des visiteurs — même principe que crk-backend/pos.py. */
function hourSales(store, dateObj, hour, visitors, profile) {
  if (!visitors || visitors <= 0) return { tickets: 0, revenue: 0 };
  const rng = rngFor(store, isoDate(dateObj), "sale", hour);
  const tickets = Math.round(visitors * (0.08 + rng() * 0.1));
  if (tickets <= 0) return { tickets: 0, revenue: 0 };
  const basketMin = Math.max(120, profile.basket - 45);
  const basketMax = profile.basket + 45;
  const revenue = round2(tickets * (basketMin + rng() * (basketMax - basketMin)));
  return { tickets, revenue };
}

function buildKpis(dayRecords, nbJours) {
  const clients = dayRecords.reduce((s, r) => s + r.visitors, 0);
  const pec = dayRecords.reduce((s, r) => s + r.pec, 0);
  return {
    clients_entres: clients,
    clients_par_jour: nbJours ? round1(clients / nbJours) : null,
    pec_count: pec,
    taux_pec: clients ? round1((pec / clients) * 100) : null,
    evenements: clients + pec + Math.round(clients * 0.05),
  };
}

function buildVentes(store, days, dayRecords, crTargetPct) {
  const profile = STORE_PROFILES[store] || { basket: 260 };
  const visiteurs = dayRecords.reduce((s, r) => s + r.visitors, 0);
  const pec = dayRecords.reduce((s, r) => s + r.pec, 0);

  const hourVisitors = {};
  const hourTickets = {};
  const hourRevenue = {};
  HOURS.forEach((h) => {
    hourVisitors[h] = 0;
    hourTickets[h] = 0;
    hourRevenue[h] = 0;
  });

  let tickets = 0;
  let revenue = 0;
  days.forEach((d, i) => {
    const rec = dayRecords[i];
    HOURS.forEach((h) => {
      const v = rec.hourlyVisitors[h] || 0;
      hourVisitors[h] += v;
      const sale = hourSales(store, d, h, v, profile);
      hourTickets[h] += sale.tickets;
      hourRevenue[h] = round2(hourRevenue[h] + sale.revenue);
      tickets += sale.tickets;
      revenue += sale.revenue;
    });
  });
  revenue = round2(revenue);

  const potentielTotal = visiteurs * (crTargetPct / 100) * AB_REFERENCE;

  const parHeure = HOURS.map((h) => {
    const v = hourVisitors[h];
    const ca = round2(hourRevenue[h]);
    const pot = round2(v * (crTargetPct / 100) * AB_REFERENCE);
    return {
      h: hourLabel(h),
      visiteurs: v,
      tickets: hourTickets[h],
      revenue: ca,
      potentiel: pot,
      manque: round2(Math.max(pot - ca, 0)),
      captation: pot ? round1((ca / pot) * 100) : null,
      conversion: v ? round1((hourTickets[h] / v) * 100) : null,
    };
  });

  return {
    parHeure,
    simule: true,
    source: "simulation",
    joursManquants: [],
    cr_target_pct: crTargetPct,
    ab_reference: AB_REFERENCE,
    visiteurs,
    pris_en_charge: pec,
    tickets,
    revenue,
    conversion_rate: visiteurs ? round1((tickets / visiteurs) * 100) : null,
    average_basket: tickets ? round2(revenue / tickets) : null,
    pec_rate: visiteurs ? round1((pec / visiteurs) * 100) : null,
    sales_potential: round2(potentielTotal),
    opportunity_gap: round2(Math.max(potentielTotal - revenue, 0)),
    opportunity_capture_rate: potentielTotal ? round1((revenue / potentielTotal) * 100) : null,
  };
}

// ------------------------------------------------------------- range (jour)

function buildRangeData(store, start, end, objectifRaw) {
  const cible = objectifRaw == null ? CR_TARGET_DEFAULT : objectifRaw;
  const days = enumerateDays(start, end);
  const nbJours = days.length;
  const dayRecords = days.map((d) => buildDay(store, d));

  const kpis = buildKpis(dayRecords, nbJours);
  const ventes = buildVentes(store, days, dayRecords, cible);

  const prevStart = addDays(days[0], -nbJours);
  const prevEnd = addDays(days[0], -1);
  const prevDays = enumerateDays(prevStart, prevEnd);
  const prevRecords = prevDays.map((d) => buildDay(store, d));
  const prevHasEvents = prevRecords.some((r) => r.visitors > 0 || r.pec > 0);
  const kpisPrecedent = prevHasEvents ? buildKpis(prevRecords, nbJours) : null;
  const ventesPrecedent = prevHasEvents ? buildVentes(store, prevDays, prevRecords, cible) : null;

  const heureDePointe = HOURS.map((h) => ({
    h: hourLabel(h),
    clients: dayRecords.reduce((s, r) => s + (r.hourlyVisitors[h] || 0), 0),
  }));
  const pecParHeure = HOURS.map((h) => ({
    h: hourLabel(h),
    pec: dayRecords.reduce((s, r) => s + (r.hourlyPec[h] || 0), 0),
  }));
  const tauxParHeure = HOURS.map((h, i) => {
    const c = heureDePointe[i].clients;
    const p = pecParHeure[i].pec;
    return { h: hourLabel(h), taux: c ? round1((p / c) * 100) : null };
  });

  const evolutionJours = days.map((d, i) => {
    const r = dayRecords[i];
    return {
      date: isoDate(d),
      label: shortLabel(d),
      jour: JOUR_LABELS[(d.getDay() + 6) % 7],
      clients: r.visitors,
      pec: r.pec,
      taux: r.visitors ? round1((r.pec / r.visitors) * 100) : null,
    };
  });

  const matrix = HOURS.map(() => [0, 0, 0, 0, 0, 0, 0]);
  days.forEach((d, i) => {
    const weekday = (d.getDay() + 6) % 7;
    const r = dayRecords[i];
    HOURS.forEach((h, hi) => {
      matrix[hi][weekday] += r.hourlyVisitors[h] || 0;
    });
  });
  const heatmapMax = matrix.reduce((m, row) => Math.max(m, ...row), 0);

  return {
    magasin: store,
    periode: { du: isoDate(days[0]), au: isoDate(days[days.length - 1]), nbJours },
    kpis,
    ventes,
    kpisPrecedent,
    ventesPrecedent,
    heureDePointe,
    pecParHeure,
    tauxParHeure,
    evolutionJours,
    heatmap: { heures: HOURS.map(hourLabel), jours: JOUR_LABELS, data: matrix, max: heatmapMax },
  };
}

// --------------------------------------------------------------- comparison

function buildComparisonData(start, end) {
  const days = enumerateDays(start, end);
  const nbJours = days.length;

  const magasins = STORE_NAMES.map((store) => {
    const recs = days.map((d) => buildDay(store, d));
    const k = buildKpis(recs, nbJours);
    const v = buildVentes(store, days, recs, CR_TARGET_DEFAULT);
    return {
      nom: store,
      aDonnees: k.clients_entres > 0 || k.pec_count > 0,
      ...k,
      revenue: v.revenue,
      sales_potential: v.sales_potential,
      opportunity_gap: v.opportunity_gap,
      opportunity_capture_rate: v.opportunity_capture_rate,
      ventesSimulees: v.simule,
    };
  });

  const evolutionJours = days.map((d) => {
    const row = { label: shortLabel(d), date: isoDate(d) };
    STORE_NAMES.forEach((store) => {
      const r = buildDay(store, d);
      row[store] = r.visitors ? round1((r.pec / r.visitors) * 100) : null;
    });
    return row;
  });

  return { periode: { du: isoDate(days[0]), au: isoDate(days[days.length - 1]), nbJours }, magasins, evolutionJours };
}

// ------------------------------------------------------------------ series

function seriesBuckets(periode, finDate) {
  if (periode === "jour") {
    const days = [];
    for (let i = 6; i >= 0; i--) days.push(addDays(finDate, -i));
    return days.map((d) => ({ label: shortLabel(d), first: d, last: d }));
  }

  if (periode === "semaine") {
    const monday = addDays(finDate, -((finDate.getDay() + 6) % 7));
    const buckets = [];
    for (let w = 7; w >= 0; w--) {
      const bStart = addDays(monday, -w * 7);
      const rawEnd = addDays(bStart, 6);
      const last = rawEnd < finDate ? rawEnd : finDate;
      buckets.push({ label: shortLabel(bStart), first: bStart, last });
    }
    return buckets;
  }

  const buckets = [];
  for (let back = 5; back >= 0; back--) {
    const first = new Date(finDate.getFullYear(), finDate.getMonth() - back, 1);
    const nextFirst = new Date(first.getFullYear(), first.getMonth() + 1, 1);
    const rawEnd = addDays(nextFirst, -1);
    const last = rawEnd < finDate ? rawEnd : finDate;
    buckets.push({ label: MOIS_LABELS[first.getMonth()], first, last });
  }
  return buckets;
}

function buildSeriesData(store, periode, finDate) {
  const buckets = seriesBuckets(periode, finDate);
  const points = buckets.map(({ label, first, last }) => {
    const days = enumerateDays(first, last);
    const recs = days.map((d) => buildDay(store, d));
    const clients = recs.reduce((s, r) => s + r.visitors, 0);
    const pec = recs.reduce((s, r) => s + r.pec, 0);
    return {
      label,
      du: isoDate(first),
      au: isoDate(last),
      clients,
      pec,
      taux: clients ? round1((pec / clients) * 100) : null,
    };
  });
  return { magasin: store, periode, fin: isoDate(finDate), points };
}

// ------------------------------------------------------------- last-seen

function storeLastSeen(store) {
  if (store === SILENT_STORE) return null;
  const rng = rngFor(store, "lastseen");
  const offsetSeconds = Math.round(rng() * 1800); // jusqu'à 30 min
  return Math.floor(Date.now() / 1000) - offsetSeconds;
}

// -------------------------------------------------------------- API publique

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const networkDelay = () => 150 + Math.random() * 250;

export async function fetchStores() {
  await delay(networkDelay());
  return {
    stores: STORE_NAMES.map((nom) => ({
      nom,
      aDonnees: nom !== SILENT_STORE,
      dernierEvenementTs: storeLastSeen(nom),
    })),
  };
}

export async function fetchRange(magasin, start, end, objectif) {
  await delay(networkDelay());
  return buildRangeData(magasin, start, end, objectif);
}

export async function fetchComparison(start, end) {
  await delay(networkDelay());
  return buildComparisonData(start, end);
}

export async function fetchSeries(magasin, periode, fin) {
  await delay(networkDelay());
  return buildSeriesData(magasin, periode, fin);
}

export async function fetchLastSeen(magasin) {
  await delay(networkDelay());
  const ts = storeLastSeen(magasin);
  return {
    store_id: magasin,
    last_event_ts: ts,
    last_received_at: ts,
    seconds_ago: ts == null ? null : Math.floor(Date.now() / 1000) - ts,
  };
}
