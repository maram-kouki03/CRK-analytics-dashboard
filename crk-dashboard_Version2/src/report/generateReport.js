// ============================================================
// Génération de rapports IA (page Rapports)
// - construit les données de la période (mockdata → futur : API)
// - appelle Gemini (free tier) depuis le navigateur
// - convertit le markdown en HTML stylé CRK pour l'export PDF
//
// Clé API : fichier .env à la racine du projet :
//   VITE_GEMINI_API_KEY=...
//   VITE_GEMINI_MODEL=gemini-3.5-flash   (optionnel)
// ============================================================

import { getDayRaw } from "../data/mockData";
import { getZoneStatsRange } from "../data/rangeData";
import shopMaps from "../data/shopMaps";

const API_KEY = import.meta.env.VITE_GEMINI_API_KEY;
const MODEL = import.meta.env.VITE_GEMINI_MODEL || "gemini-3.5-flash";

// ---------- Données de la période ----------

function addDays(date, n) {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  d.setDate(d.getDate() + n);
  return d;
}

function listDays(start, end) {
  const days = [];
  let d = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const stop = new Date(end.getFullYear(), end.getMonth(), end.getDate());
  while (d <= stop) { days.push(d); d = addDays(d, 1); }
  return days;
}

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function aggregate(raws) {
  const sum = (k) => raws.reduce((a, r) => a + r[k], 0);
  const clients = sum("clients");
  const tickets = sum("tickets");
  return {
    clients,
    pec: sum("pec"),
    clientsAcheteurs: tickets,
    tauxPec: Number((((sum("pec")) / clients) * 100).toFixed(1)),
    tauxTransformation: Number(((tickets / clients) * 100).toFixed(1)),
    vendeursMoyens: Number((sum("vendeurs") / raws.length).toFixed(1)),
    potentiel: Math.round(raws.reduce((a, r) => a + r.panier * r.clients, 0)),
    caEstime: Math.round(raws.reduce((a, r) => a + r.panier * r.tickets, 0)),
  };
}

export function buildReportPayload(store, start, end) {
  const days = listDays(start, end);
  const raws = days.map((d) => getDayRaw(store, d));

  const mapConfig = shopMaps[store];
  const zones = getZoneStatsRange(store, start, end).map((z) => ({
    id: z.id,
    nom: mapConfig?.zones.find((zz) => zz.id === z.id)?.nom || `Zone ${z.id}`,
    clients: z.clients,
    pec: z.pec,
  }));

  return {
    magasin: store,
    periode: { du: iso(days[0]), au: iso(days[days.length - 1]), nbJours: days.length },
    joursDetail: days.map((d, i) => ({
      date: iso(d),
      clients: raws[i].clients,
      pec: raws[i].pec,
      tauxPec: Number(raws[i].tauxPec.toFixed(1)),
      vendeurs: raws[i].vendeurs,
      clientsAcheteurs: raws[i].tickets,
      tauxTransformation: Number(((raws[i].tickets / raws[i].clients) * 100).toFixed(1)),
      potentiel: Math.round(raws[i].panier * raws[i].clients),
    })),
    totauxPeriode: aggregate(raws),
    zones,
  };
}

// ---------- Prompt (template IDENTIQUE pour tous les magasins) ----------

const SYSTEM_PROMPT = `Tu es un analyste retail senior travaillant pour CRK, \
une marque tunisienne de maroquinerie disposant de 8 boutiques. Tu analyses \
les indicateurs d'UN magasin sur UNE période donnée et tu rédiges un rapport \
pour la direction, en français.

Définitions des indicateurs :
- clients : nombre de visiteurs entrés dans la boutique (comptage caméra)
- pec : nombre de clients pris en charge par un vendeur
- tauxPec : pec / clients, en %
- vendeurs : nombre de vendeurs actifs
- clientsAcheteurs : nombre de clients ayant réalisé un achat
- tauxTransformation : clientsAcheteurs / clients, en % (part des visiteurs qui achètent)
- potentiel : CA théorique si tous les visiteurs achetaient (panier moyen de référence × clients), en dinars tunisiens (DT)
- caEstime : CA réellement capté, en DT
- zones : la boutique est découpée en 3 zones caméra (comptage par la pipeline vision). Pour chaque zone sur la période : clients (nombre de clients ayant visité la zone sur la période, cumul journalier — pas une affluence simultanée) et pec (nombre de prises en charge réalisées par un vendeur dans cette zone sur la période)

Règles STRICTES de rédaction :
1. Appuie CHAQUE constat sur des chiffres précis tirés des données de la période, en exploitant les variations INTERNES à la période (comparaisons entre jours, entre début et fin de période, jours de pic vs jours creux, semaine vs week-end). N'invoque jamais de période antérieure : elle n'est pas fournie.
2. Ne réénonce jamais un chiffre sans l'interpréter.
3. Croise les indicateurs entre eux (ex. : affluence en hausse mais taux PEC en baisse → possible manque de vendeurs).
4. Les recommandations doivent être SPÉCIFIQUES à ce magasin et actionnables, avec l'enjeu chiffré en DT. INTERDIT : conseils génériques du type "améliorer l'accueil" ou "motiver les équipes".
5. Au moins UNE recommandation doit exploiter les données de zones : compare le nombre de clients d'une zone à son nombre de PEC pour détecter un déséquilibre — ex. zone très fréquentée mais peu de PEC → y positionner un vendeur supplémentaire ; zone à faible affluence et peu de PEC → revoir son merchandising ou son implantation. Toujours avec un enjeu chiffré (nombre de PEC manqués estimé, ou DT via le panier moyen).
6. Ne jamais recommander de réduire l'effectif de vendeurs, sauf si les données journalières démontrent explicitement une corrélation négative. Ne référencer une date précise que si les données de ce jour justifient explicitement le constat.
7. Le panier moyen est une valeur de référence fixe : ne pas commenter son évolution. Il sert uniquement à convertir les gains en DT.
8. Si les données ne permettent pas de conclure sur un point, dis-le honnêtement plutôt que d'inventer une cause.
9. Nombres au format français : espace pour les milliers, virgule décimale.
10. Longueur totale : 350 à 500 mots. Ton professionnel, direct, sans emphase.

Structure EXACTE du rapport (markdown), IDENTIQUE pour tous les magasins :
# Rapport d'analyse — {nom du magasin}
## Période
{date début} au {date fin} ({N} jours)
## Chiffres clés
Tableau markdown avec EXACTEMENT ces lignes, dans cet ordre :
| Indicateur | Valeur |
Clients entrés, Nombre de PEC, Taux PEC, Vendeurs actifs (moy.), Clients acheteurs, Taux de transformation, Potentiel de revenu (DT)
## Répartition par zone
Tableau markdown avec EXACTEMENT ces colonnes :
| Zone | Clients | PEC |
Une ligne par zone (nom de la zone, clients, pec)
## Constats
(3 à 5 puces, chacune : fait chiffré + interprétation)
## Recommandations
(2 à 3 puces numérotées, spécifiques et actionnables, avec l'enjeu chiffré en DT)
## Point de vigilance
(1 élément à surveiller sur la période suivante)

Réponds UNIQUEMENT avec le rapport en markdown, sans préambule, sans commentaire sur ta démarche, sans balises de code autour.`;

// ---------- Appel Gemini ----------

export async function generateReport(payload) {
  if (!API_KEY) {
    throw new Error(
      "Clé API manquante : ajoute VITE_GEMINI_API_KEY dans le fichier .env à la racine du projet, puis relance npm run dev."
    );
  }

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${API_KEY}`;
  const body = {
    system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: [
      {
        role: "user",
        parts: [
          {
            text:
              "Voici les données du magasin pour la période. Rédige le rapport en respectant strictement les règles et la structure.\n\n```json\n" +
              JSON.stringify(payload, null, 2) +
              "\n```",
          },
        ],
      },
    ],
    generationConfig: { temperature: 0.4, maxOutputTokens: 8192 },
  };

  // retry sur les erreurs transitoires (503 surcharge, 429 quota/minute)
  const delays = [0, 10000, 30000];
  let lastError = null;

  for (const delay of delays) {
    if (delay) await new Promise((res) => setTimeout(res, delay));
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (resp.ok) {
      const data = await resp.json();
      const finishReason = data?.candidates?.[0]?.finishReason;
      if (finishReason === "MAX_TOKENS") {
        throw new Error("Rapport tronqué par la limite de tokens — réessayer");
      }
      const parts = data?.candidates?.[0]?.content?.parts;
      const text = (parts || []).map((p) => p.text || "").join("").trim();
      if (!text) throw new Error("Réponse vide de l'API.");
      const requiredSections = ["## Constats", "## Recommandations", "## Point de vigilance"];
      if (!requiredSections.every((s) => text.includes(s))) {
        throw new Error("Réponse invalide du modèle");
      }
      return text;
    }

    const errText = await resp.text();
    lastError = new Error(`API Gemini HTTP ${resp.status} : ${errText.slice(0, 300)}`);
    if (resp.status !== 503 && resp.status !== 429) throw lastError; // erreurs non transitoires
  }
  throw lastError;
}

// ---------- Markdown → HTML stylé CRK (pour le PDF) ----------

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inline(s) {
  return escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

const STYLE = {
  h2: "color:#7a3325; border-bottom:1px solid #e4d9d0; padding-bottom:4px; margin:18px 0 8px; font-size:15px;",
  p: "margin:7px 0; text-align:justify;",
  list: "padding-left:20px; margin:6px 0;",
  li: "margin:4px 0;",
  table: "width:100%; border-collapse:collapse; margin:10px 0 14px; font-size:11.5px; page-break-inside:avoid;",
  th: "background:#96402e; color:#fdfaf7; text-align:left; padding:6px 8px; font-weight:600;",
  td: "padding:5px 8px; border-bottom:1px solid #e4d9d0;",
  trOdd: "background:#f6efe9;",
};

export function markdownToHtml(md) {
  const lines = md.split("\n");
  const out = [];
  let i = 0;
  let list = null; // "ul" | "ol"

  const closeList = () => {
    if (list) { out.push(`</${list}>`); list = null; }
  };

  while (i < lines.length) {
    const line = lines[i];

    // tableau markdown
    if (line.trim().startsWith("|") && lines[i + 1]?.trim().match(/^\|[\s:|-]+\|$/)) {
      closeList();
      const headers = line.split("|").slice(1, -1).map((c) => c.trim());
      out.push(
        `<table style="${STYLE.table}"><thead><tr>` +
        headers.map((h) => `<th style="${STYLE.th}">${inline(h)}</th>`).join("") +
        "</tr></thead><tbody>"
      );
      i += 2;
      let rowIndex = 0;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].split("|").slice(1, -1).map((c) => c.trim());
        const trStyle = rowIndex % 2 === 1 ? ` style="${STYLE.trOdd}"` : "";
        out.push(
          `<tr${trStyle}>` +
          cells.map((c) => `<td style="${STYLE.td}">${inline(c)}</td>`).join("") +
          "</tr>"
        );
        i++; rowIndex++;
      }
      out.push("</tbody></table>");
      continue;
    }

    if (line.startsWith("## ")) { closeList(); out.push(`<h2 style="${STYLE.h2}">${inline(line.slice(3))}</h2>`); }
    else if (line.startsWith("# ")) { closeList(); /* le titre est déjà dans l'en-tête du document */ }
    else if (/^\d+\.\s/.test(line.trim())) {
      if (list !== "ol") { closeList(); out.push(`<ol style="${STYLE.list}">`); list = "ol"; }
      out.push(`<li style="${STYLE.li}">${inline(line.trim().replace(/^\d+\.\s/, ""))}</li>`);
    }
    else if (/^[-*]\s/.test(line.trim())) {
      if (list !== "ul") { closeList(); out.push(`<ul style="${STYLE.list}">`); list = "ul"; }
      out.push(`<li style="${STYLE.li}">${inline(line.trim().replace(/^[-*]\s/, ""))}</li>`);
    }
    else if (line.trim() === "") { closeList(); }
    else { closeList(); out.push(`<p style="${STYLE.p}">${inline(line)}</p>`); }
    i++;
  }
  closeList();
  return out.join("\n");
}

// document complet prêt pour la conversion PDF
export function reportHtmlDocument(md, store, periodLabel) {
  return `
  <div style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#2b2320; padding: 8px 6px; line-height:1.55; font-size:12.5px;">
    <div style="border-bottom:3px solid #96402e; padding-bottom:10px; margin-bottom:18px;">
      <div style="color:#96402e; text-transform:uppercase; letter-spacing:0.08em; font-size:10px; font-weight:600;">CRK — Rapport d'analyse</div>
      <div style="font-size:22px; font-weight:700; color:#7a3325; margin-top:2px;">${escapeHtml(store)}</div>
      <div style="font-size:12px; opacity:0.75; margin-top:2px;">${escapeHtml(periodLabel)}</div>
    </div>
    <div>${markdownToHtml(md)}</div>
    <div style="margin-top:24px; padding-top:10px; border-top:1px solid #e4d9d0; font-size:9.5px; opacity:0.6; text-align:center;">
      Généré automatiquement — données à valider
    </div>
  </div>`;
}
