// ============================================================
// Agrégation des données sur une période [début, fin]
// Utilisé par le dashboard en mode "analyse par intervalle".
// Comparaison automatique avec la période précédente de même durée.
// ============================================================

import { getDashboardData, getDayRaw, getZoneStats, storeNames } from "./mockData";

const fmtInt = (n) => Math.round(n).toLocaleString("fr-FR");
const fmtPct = (n) => `${n.toFixed(1).replace(".", ",")}%`;
const fmt1 = (n) => n.toFixed(1).replace(".", ",");

function addDays(date, n) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  d.setDate(d.getDate() + n);
  return d;
}

function listDays(start, end) {
  const days = [];
  let d = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const stop = new Date(end.getFullYear(), end.getMonth(), end.getDate());
  while (d <= stop) {
    days.push(d);
    d = addDays(d, 1);
  }
  return days;
}

// agrégats corrects d'une liste de jours bruts
function aggregate(raws) {
  const sum = (k) => raws.reduce((a, r) => a + r[k], 0);
  const avg = (k) => sum(k) / raws.length;
  const clients = sum("clients");
  const pec = sum("pec");
  const tickets = sum("tickets");
  return {
    clients,
    pec,
    tickets,
    // taux agrégés = totaux / totaux (pas la moyenne des taux journaliers)
    tauxPec: (pec / clients) * 100,
    transformation: (tickets / clients) * 100,
    vendeurs: avg("vendeurs"),
    temps: avg("temps"),
    potentiel: raws.reduce((a, r) => a + r.panier * r.clients, 0),
  };
}

export function getRangeData(store, start, end) {
  const days = listDays(start, end);
  const raws = days.map((d) => getDayRaw(store, d));

  // période précédente de même durée, juste avant
  const prevEnd = addDays(start, -1);
  const prevStart = addDays(start, -days.length);
  const prevRaws = listDays(prevStart, prevEnd).map((d) => getDayRaw(store, d));

  const A = aggregate(raws);
  const B = aggregate(prevRaws);
  const deltaPct = (a, b) => (b === 0 ? 0 : ((a - b) / b) * 100);

  const kpis = [
    {
      id: "clients", label: "Clients entrés", value: fmtInt(A.clients),
      delta: `${fmt1(Math.abs(deltaPct(A.clients, B.clients)))}%`,
      up: A.clients >= B.clients,
    },
    {
      id: "pec", label: "Nombre de PEC", value: fmtInt(A.pec),
      delta: `${fmt1(Math.abs(deltaPct(A.pec, B.pec)))}%`,
      up: A.pec >= B.pec,
    },
    {
      id: "taux", label: "Taux PEC", value: fmtPct(A.tauxPec),
      delta: `${fmt1(Math.abs(A.tauxPec - B.tauxPec))} pts`,
      up: A.tauxPec >= B.tauxPec,
    },
    {
      id: "vendeurs", label: "Vendeurs actifs (moy.)", value: fmt1(A.vendeurs),
      delta: fmt1(Math.abs(A.vendeurs - B.vendeurs)),
      up: A.vendeurs >= B.vendeurs,
    },
    {
      id: "transformation", label: "Taux de transformation", value: fmtPct(A.transformation),
      delta: `${fmt1(Math.abs(A.transformation - B.transformation))} pts`,
      up: A.transformation >= B.transformation,
    },
    {
      id: "potentiel", label: "Potentiel de revenu", value: `${fmtInt(A.potentiel)} DT`,
      delta: `${fmt1(Math.abs(deltaPct(A.potentiel, B.potentiel)))}%`,
      up: A.potentiel >= B.potentiel,
    },
  ];

  // Courbes horaires : moyenne heure par heure sur la période
  const daily = days.map((d) => getDashboardData(store, d));
  const nHours = daily[0].heureDePointe.length;

  const heureDePointe = Array.from({ length: nHours }, (_, i) => ({
    h: daily[0].heureDePointe[i].h,
    clients: Math.round(
      daily.reduce((a, day) => a + day.heureDePointe[i].clients, 0) / daily.length
    ),
  }));

  const tauxParHeure = Array.from({ length: nHours }, (_, i) => ({
    h: daily[0].tauxParHeure[i].h,
    taux: Number(
      (daily.reduce((a, day) => a + day.tauxParHeure[i].taux, 0) / daily.length).toFixed(1)
    ),
  }));

  // Heatmap : moyenne cellule par cellule
  const rows = daily[0].heatmapData.length;
  const cols = daily[0].heatmapData[0].length;
  const heatmapData = Array.from({ length: rows }, (_, r) =>
    Array.from({ length: cols }, (_, c) =>
      daily.reduce((a, day) => a + day.heatmapData[r][c], 0) / daily.length
    )
  );

  // Évolution jour par jour du taux PEC sur la période sélectionnée
  const evolutionJours = days.map((d, i) => ({
    label: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`,
    taux: Number(raws[i].tauxPec.toFixed(1)),
  }));

  return { kpis, heureDePointe, tauxParHeure, evolutionJours, heatmapData, nbJours: days.length };
}

// ============================================================
// Statistiques par zone agrégées sur une période
// clients = nombre total de clients ayant visité la zone sur la période (somme journalière)
// pec = total des prises en charge dans la zone sur la période (somme journalière)
// ============================================================

export function getZoneStatsRange(store, start, end) {
  const days = listDays(start, end);
  const perDay = days.map((d) => getZoneStats(store, d));
  const nZones = perDay[0].length;

  return Array.from({ length: nZones }, (_, i) => ({
    id: perDay[0][i].id,
    clients: perDay.reduce((a, zones) => a + zones[i].clients, 0),
    pec: perDay.reduce((a, zones) => a + zones[i].pec, 0),
  }));
}

// ============================================================
// Page Comparaison : agrégats des 8 magasins sur une période
// ============================================================

const bestBy = (arr, key) => [...arr].sort((a, b) => b[key] - a[key])[0];

export function getComparisonData(start, end) {
  const days = listDays(start, end);

  const magasins = storeNames
    .map((nom) => {
      const raws = days.map((d) => getDayRaw(nom, d));
      const A = aggregate(raws);
      return {
        nom,
        clients: Math.round(A.clients),
        pec: Math.round(A.pec),
        taux: Number(A.tauxPec.toFixed(1)),
        vendeurs: Number(A.vendeurs.toFixed(1)),
        clientsAcheteurs: Math.round(A.tickets),
        tauxTransformation: Number(A.transformation.toFixed(1)),
        potentiel: Math.round(A.potentiel),
      };
    })
    .sort((a, b) => b.clients - a.clients)
    .map((m, i) => ({ rang: i + 1, ...m }));

  const bTaux = bestBy(magasins, "taux");
  const bPec = bestBy(magasins, "pec");
  const bClients = bestBy(magasins, "clients");
  const bVendeurs = bestBy(magasins, "vendeurs");

  const bestCards = [
    { label: "Meilleur taux PEC", store: bTaux.nom, value: fmtPct(bTaux.taux), icon: "trophy" },
    { label: "Meilleur nombre de PEC", store: bPec.nom, value: fmtInt(bPec.pec), icon: "handshake" },
    { label: "Meilleur nombre de clients", store: bClients.nom, value: fmtInt(bClients.clients), icon: "globe" },
    { label: "Meilleur taux de vendeurs actifs", store: bVendeurs.nom, value: fmt1(bVendeurs.vendeurs), icon: "users" },
  ];

  const conclusions = [
    { icon: "trophy", label: "Meilleur taux PEC", detail: `${bTaux.nom} (${fmtPct(bTaux.taux)})` },
    { icon: "handshake", label: "Meilleur nombre de PEC", detail: `${bPec.nom} (${fmtInt(bPec.pec)})` },
    { icon: "globe", label: "Meilleur nombre de clients", detail: `${bClients.nom} (${fmtInt(bClients.clients)})` },
  ];

  // Évolution du taux PEC sur la période : une ligne par magasin, un point par jour
  const evolutionJours = days.map((d) => {
    const row = { label: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}` };
    storeNames.forEach((nom) => {
      row[nom] = Number(getDayRaw(nom, d).tauxPec.toFixed(1));
    });
    return row;
  });

  return { magasins, bestCards, conclusions, evolutionJours };
}
