// ============================================================
// Export des KPI hebdomadaires vers agent/data/*.json
//
// Usage :  node agent/export_data.mjs            → semaine se terminant aujourd'hui
//          node agent/export_data.mjs 2026-07-12 → semaine se terminant à cette date
//
// Réutilise le générateur du dashboard (src/data/mockData.js)
// pour que l'agent analyse EXACTEMENT les mêmes chiffres que
// ceux affichés à l'écran. En production, ce script sera
// remplacé par une requête vers la base (Supabase).
// ============================================================

import { writeFileSync, mkdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { storeNames, getWeekRaw } from "../src/data/mockData.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "data");
mkdirSync(outDir, { recursive: true });

// date de fin de semaine : argument CLI ou aujourd'hui
const endDate = process.argv[2] ? new Date(process.argv[2]) : new Date();
if (isNaN(endDate)) {
  console.error("Date invalide. Format attendu : AAAA-MM-JJ");
  process.exit(1);
}

// agrégats d'une liste de jours
function aggregate(days) {
  const sum = (k) => days.reduce((a, d) => a + d[k], 0);
  const clients = sum("clients");
  const tickets = sum("tickets");
  return {
    clients,
    pec: sum("pec"),
    tickets,
    tauxPecMoyen: Number((days.reduce((a, d) => a + d.tauxPec, 0) / days.length).toFixed(1)),
    tempsAvantPecMoyen: Number((days.reduce((a, d) => a + d.tempsAvantPec, 0) / days.length).toFixed(1)),
    // taux agrégé = total tickets / total clients (pas la moyenne des taux)
    tauxTransformation: Number(((tickets / clients) * 100).toFixed(1)),
    potentiel: sum("potentiel"),
    caEstime: sum("caEstime"),
  };
}

const slug = (s) => s.toLowerCase().replace(/\s+/g, "-");
const fmtDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

for (const store of storeNames) {
  const semaine = getWeekRaw(store, endDate);

  // semaine précédente, pour que l'agent puisse comparer
  const prevEnd = new Date(endDate);
  prevEnd.setDate(prevEnd.getDate() - 7);
  const semainePrecedente = getWeekRaw(store, prevEnd);

  const payload = {
    magasin: store,
    periode: { du: semaine[0].date, au: semaine[6].date },
    joursDetail: semaine,
    totauxSemaine: aggregate(semaine),
    totauxSemainePrecedente: aggregate(semainePrecedente),
  };

  const file = join(outDir, `${slug(store)}_${fmtDate(endDate)}.json`);
  writeFileSync(file, JSON.stringify(payload, null, 2), "utf-8");
  console.log(`✓ ${file}`);
}

console.log(`\n${storeNames.length} fichiers générés dans agent/data/`);
