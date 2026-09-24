// ============================================================
// Génération de rapports IA (page Rapports)
// - récupère les données réelles de la période via GET /api/range
// - appelle Gemini (free tier) depuis le navigateur
// - convertit le markdown en HTML stylé CRK pour l'export PDF
//
// Clé API : fichier .env à la racine du projet Dashboard/ :
//   VITE_GEMINI_API_KEY=...
//   VITE_GEMINI_MODEL=gemini-3.5-flash   (optionnel)
// ============================================================

import { fetchRange } from "../api/client";

const API_KEY = import.meta.env.VITE_GEMINI_API_KEY;
const MODEL = import.meta.env.VITE_GEMINI_MODEL || "gemini-3.5-flash";

// ---------- Données de la période (backend, plus aucune génération locale) ----------

/**
 * Payload envoyé au modèle : uniquement des indicateurs mesurés.
 * Les valeurs `null` sont conservées telles quelles — le prompt demande
 * explicitement au modèle de les traiter comme « non mesuré », pas comme zéro.
 */
export async function buildReportPayload(store, start, end) {
  const range = await fetchRange(store, start, end);

  return {
    magasin: range.magasin,
    periode: range.periode,
    indicateursPeriode: range.kpis,
    indicateursPeriodePrecedente: range.kpisPrecedent,
    joursDetail: range.evolutionJours,
    clientsParHeure: range.heureDePointe,
    pecParHeure: range.pecParHeure,
    tauxPecParHeure: range.tauxParHeure,
  };
}

// ---------- Prompt (template IDENTIQUE pour tous les magasins) ----------

const SYSTEM_PROMPT = `Tu es un analyste retail senior travaillant pour CRK, \
une marque tunisienne de maroquinerie disposant de 8 boutiques. Tu analyses \
les indicateurs d'UN magasin sur UNE période donnée et tu rédiges un rapport \
pour la direction, en français.

Toutes les données proviennent de la pipeline de vision par ordinateur installée \
en boutique (comptage caméra). Il n'y a AUCUNE donnée de caisse : ni ticket, ni \
panier moyen, ni chiffre d'affaires. Tu ne dois donc jamais chiffrer une \
recommandation en dinars, ni parler de taux de transformation, de CA ou de \
potentiel de revenu — ces indicateurs ne sont pas mesurés.

Définitions des indicateurs fournis :
- clients_entres : nombre de visiteurs entrés dans la boutique sur la période
- clients_par_jour : moyenne de clients_entres par jour de la période
- pec_count : nombre de prises en charge (un client abordé par un vendeur), \
comptées une fois par identifiant de PEC
- taux_pec : pec_count / clients_entres, en %
- joursDetail : le détail jour par jour (clients, pec, taux)
- clientsParHeure / pecParHeure / tauxPecParHeure : la répartition par heure \
d'ouverture (9h à 20h ; les événements hors plage sont rattachés à l'heure limite)

Règles STRICTES de rédaction :
1. Une valeur \`null\` signifie « non mesuré sur cette période ». Ne la traite \
jamais comme un zéro et ne construis aucun constat dessus : dis simplement que \
l'indicateur n'est pas disponible si c'est pertinent.
2. Appuie CHAQUE constat sur des chiffres précis de la période, en exploitant les \
variations INTERNES : entre jours, entre début et fin de période, heures de pointe \
vs heures creuses, semaine vs week-end. La période précédente est fournie dans \
indicateursPeriodePrecedente : tu peux l'utiliser, mais seulement si elle n'est pas null.
3. Ne réénonce jamais un chiffre sans l'interpréter.
4. Croise les indicateurs entre eux (ex. : affluence en hausse mais taux PEC en \
baisse sur les mêmes heures → couverture vendeurs insuffisante à ces heures).
5. IMPORTANT — contrôle de cohérence : si taux_pec dépasse 100 %, cela signifie \
qu'il y a plus de PEC comptées que de clients comptés, ce qui est impossible en \
réalité. Traite-le comme une ANOMALIE DE MESURE (sur-comptage des PEC ou \
sous-comptage des entrées par la caméra), signale-le explicitement dans les \
constats, et n'en fais jamais une performance commerciale. Dans ce cas, appuie \
tes recommandations sur les volumes bruts (clients_entres, pec_count) et leur \
répartition horaire plutôt que sur le taux.
6. Les recommandations doivent être SPÉCIFIQUES à ce magasin et actionnables, \
chiffrées en volumes mesurés (nombre de clients, de PEC, heures concernées). \
INTERDIT : conseils génériques du type « améliorer l'accueil » ou « motiver les équipes ».
7. Ne jamais recommander de réduire l'effectif de vendeurs. Ne référencer une date \
précise que si les données de ce jour justifient explicitement le constat.
8. Si les données ne permettent pas de conclure sur un point, dis-le honnêtement \
plutôt que d'inventer une cause.
9. Nombres au format français : espace pour les milliers, virgule décimale.
10. Longueur totale : 350 à 500 mots. Ton professionnel, direct, sans emphase.

Structure EXACTE du rapport (markdown), IDENTIQUE pour tous les magasins :
# Rapport d'analyse — {nom du magasin}
## Période
{date début} au {date fin} ({N} jours)
## Chiffres clés
Tableau markdown avec EXACTEMENT ces lignes, dans cet ordre :
| Indicateur | Valeur |
Clients entrés, Clients / jour (moy.), Nombre de PEC, Taux PEC
Écris « non mesuré » dans la colonne Valeur pour tout indicateur à null.
## Constats
(3 à 5 puces, chacune : fait chiffré + interprétation)
## Recommandations
(2 à 3 puces numérotées, spécifiques et actionnables, chiffrées en volumes mesurés)
## Point de vigilance
(1 élément à surveiller sur la période suivante)

Réponds UNIQUEMENT avec le rapport en markdown, sans préambule, sans commentaire \
sur ta démarche, sans balises de code autour.`;

// ---------- Appel Gemini ----------

export async function generateReport(payload) {
  if (!API_KEY) {
    throw new Error(
      "Clé API manquante : ajoute VITE_GEMINI_API_KEY dans le fichier .env du dossier Dashboard/, puis relance npm run dev."
    );
  }

  if (payload.indicateursPeriode.evenements === 0) {
    throw new Error(
      `Aucun événement reçu de ${payload.magasin} entre le ${payload.periode.du} et le ${payload.periode.au} : il n'y a rien à analyser sur cette période.`
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
      Généré automatiquement à partir des données de comptage caméra — à valider
    </div>
  </div>`;
}
