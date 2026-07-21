#!/usr/bin/env node
// ============================================================
// Export des données brutes hebdomadaires (8 magasins) pour
// l'agent de rapports IA. Réutilise le générateur déterministe
// de src/data/mockData.js — aucune donnée réelle n'est lue ici.
//
// Usage : node agent/export_data.mjs [AAAA-MM-JJ]
//   Sans argument : la semaine se termine aujourd'hui.
// ============================================================

import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { storeNames, getWeekRaw } from "../src/data/mockData.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, "data");

function parseEndDate() {
  const arg = process.argv[2];
  if (!arg) return new Date();

  const d = new Date(arg);
  if (Number.isNaN(d.getTime())) {
    console.error(`Date invalide : "${arg}" (format attendu AAAA-MM-JJ)`);
    process.exit(1);
  }
  return d;
}

function slugify(name) {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function main() {
  const endDate = parseEndDate();
  mkdirSync(OUT_DIR, { recursive: true });

  for (const store of storeNames) {
    const data = getWeekRaw(store, endDate);
    const file = path.join(OUT_DIR, `${slugify(store)}.json`);
    writeFileSync(file, JSON.stringify(data, null, 2), "utf-8");
    console.log(`✓ ${store} -> ${path.relative(process.cwd(), file)}`);
  }

  console.log(
    `\n${storeNames.length} fichiers écrits dans ${path.relative(process.cwd(), OUT_DIR)}/ ` +
      `(semaine se terminant le ${endDate.toISOString().slice(0, 10)})`
  );
}

main();
