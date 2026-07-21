#!/usr/bin/env python3
"""Agent IA de rapports hebdomadaires CRK.

Lit les fichiers JSON produits par export_data.mjs (agent/data/), envoie
les données de chaque magasin a l'API Gemini, et ecrit un rapport
markdown par magasin dans agent/reports/.

Ne depend que de la bibliotheque standard Python (urllib pour le HTTP,
parsing .env manuel) — aucune dependance externe a installer.

Usage :
    python agent/agent.py                    # tous les magasins
    python agent/agent.py --magasin "Sfax 1" # un seul magasin
"""

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"
ENV_FILE = ROOT_DIR / ".env"

DEFAULT_MODEL = "gemini-2.5-flash"
TEMPERATURE = 0.4
PAUSE_SECONDS = 5  # entre deux appels API, pour rester dans le quota free tier
REQUEST_TIMEOUT = 60

SYSTEM_PROMPT = """\
Tu es analyste retail senior chez CRK Maroquinier, une marque tunisienne de \
maroquinerie qui exploite 8 boutiques en Tunisie. Tu rediges des rapports \
hebdomadaires de performance a partir de donnees remontees par un pipeline \
de vision par ordinateur en boutique (comptage des clients entrants, \
detection des prises en charge par un vendeur) croisees avec les donnees \
de caisse (tickets, panier moyen).

Regles strictes, a respecter impérativement :

1. Chaque constat doit s'appuyer sur des chiffres precis (valeurs et ecarts \
en % ou en points vs la semaine precedente). N'affirme jamais une evolution \
sans la chiffrer.
2. Croise systematiquement au moins deux indicateurs entre eux pour \
expliquer une evolution plutot que de les lister isolement (par exemple : \
trafic vs taux de transformation, taux PEC vs temps avant PEC, nombre de \
vendeurs actifs vs taux PEC).
3. Chaque recommandation doit etre specifique, actionnable des la semaine \
suivante, et chiffrer l'enjeu associe en dinars tunisiens (DT) a partir des \
donnees fournies (par exemple une estimation du gain de potentiel de revenu \
si un indicateur s'ameliore de X points). Il est strictement interdit de \
donner un conseil generique du type "ameliorer l'accueil client" ou \
"renforcer la formation des equipes" sans le rattacher a un chiffre et une \
action precise et mesurable pour ce magasin.
4. Si les donnees fournies ne permettent pas de conclure sur un point \
(echantillon trop faible, une seule semaine de recul, correlation non \
etablie), dis-le explicitement plutot que de speculer.
5. Longueur totale du rapport (hors tableau) : entre 350 et 500 mots.
6. Redige uniquement en francais, dans un ton professionnel et direct, \
adapte a un comite de direction retail.

Structure imposee du rapport, en Markdown, dans cet ordre exact et sans \
aucun texte en dehors de cette structure :

# <Nom du magasin>
## Periode
## Chiffres cles
Un tableau markdown avec les colonnes : Indicateur | Semaine actuelle | \
Semaine precedente | Evolution
La colonne Indicateur doit contenir exactement et exhaustivement les \
lignes suivantes, dans cet ordre, et aucune autre : Clients entres, PEC, \
Taux PEC, Vendeurs actifs, Temps avant PEC, Clients acheteurs, Taux de \
transformation.
Le panier moyen ne doit jamais figurer dans ce tableau et ne doit faire \
l'objet d'aucun commentaire sur son evolution : c'est une valeur de \
reference interne, utilisee uniquement pour chiffrer en dinars tunisiens \
(DT) le gain estime dans la section Recommandations.
## Constats
## Recommandations
Une liste numerotee.
## Point de vigilance
"""

LEGENDE_CHAMPS = """\
Legende des champs (valeurs numeriques brutes) :
- clients : nombre de clients entres dans la boutique
- pec : nombre de "prises en charge" (client aborde par un vendeur)
- tauxPec : pec / clients, en %
- vendeursActifs : nombre de vendeurs actifs sur la journee/moyenne semaine
- tempsAvantPec : temps moyen avant prise en charge, en secondes
- tickets : nombre de tickets de caisse (ventes conclues)
- panierMoyen : panier moyen en dinars tunisiens (DT)
- tauxTransformation : tickets / clients, en % (taux de transformation caisse)
- potentiel : panier moyen x clients entres, en DT (potentiel de revenu \
si tous les visiteurs avaient converti)
"""


HTML_CSS = """\
:root {
  --crk-cream: #fdfaf7;
  --crk-brick: #96402e;
  --crk-brick-dark: #7a3325;
  --crk-text: #2b2320;
  --crk-border: #e4d9d0;
  --crk-row-alt: #f6efe9;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  padding: 0;
  background: var(--crk-cream);
  color: var(--crk-text);
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.6;
}

.page {
  max-width: 860px;
  margin: 0 auto;
  padding: 32px 24px 64px;
}

header.report-header {
  border-bottom: 3px solid var(--crk-brick);
  padding-bottom: 16px;
  margin-bottom: 32px;
}

header.report-header .eyebrow {
  color: var(--crk-brick);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.8rem;
  font-weight: 600;
  margin: 0 0 4px;
}

header.report-header h1 {
  margin: 0 0 4px;
  font-size: 1.9rem;
  color: var(--crk-brick-dark);
}

header.report-header .periode {
  margin: 0;
  font-size: 1rem;
  color: var(--crk-text);
  opacity: 0.8;
}

.report-body h1 {
  display: none;
}

.report-body h2 {
  color: var(--crk-brick-dark);
  border-bottom: 1px solid var(--crk-border);
  padding-bottom: 6px;
  margin-top: 36px;
  font-size: 1.25rem;
}

.report-body h3 {
  color: var(--crk-brick-dark);
  font-size: 1.05rem;
}

.report-body p {
  margin: 12px 0;
  text-align: justify;
}

.report-body ul,
.report-body ol {
  padding-left: 24px;
}

.report-body li {
  margin: 6px 0;
}

table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0 24px;
  font-size: 0.95rem;
}

thead th {
  background: var(--crk-brick);
  color: var(--crk-cream);
  text-align: left;
  padding: 10px 12px;
  font-weight: 600;
}

tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--crk-border);
}

tbody tr:nth-child(even) {
  background: var(--crk-row-alt);
}

footer.report-footer {
  margin-top: 48px;
  padding-top: 16px;
  border-top: 1px solid var(--crk-border);
  font-size: 0.8rem;
  color: var(--crk-text);
  opacity: 0.65;
  text-align: center;
}

@media print {
  body {
    background: #ffffff;
  }

  .page {
    max-width: none;
    margin: 0;
    padding: 12mm 14mm;
  }

  table {
    page-break-inside: avoid;
  }

  tr,
  thead {
    page-break-inside: avoid;
  }

  h2 {
    page-break-after: avoid;
  }

  footer.report-footer {
    page-break-inside: avoid;
  }
}
"""


def escape_html(text):
    return html_lib.escape(text, quote=False)


def inline_markdown(text):
    """Convertit le formatage inline markdown (gras) apres echappement HTML."""
    text = escape_html(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def render_table(table_lines):
    def split_row(row):
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [cell.strip() for cell in row.split("|")]

    if len(table_lines) < 2:
        return ""

    header_cells = split_row(table_lines[0])
    body_rows = [split_row(row) for row in table_lines[2:]]  # ligne 1 = separateur ---

    thead = "<tr>" + "".join(f"<th>{inline_markdown(c)}</th>" for c in header_cells) + "</tr>"
    tbody = "\n".join(
        "<tr>" + "".join(f"<td>{inline_markdown(c)}</td>" for c in row) + "</tr>"
        for row in body_rows
    )
    return f"<table>\n<thead>{thead}</thead>\n<tbody>\n{tbody}\n</tbody>\n</table>"


def markdown_to_html(md_text):
    """Mini-convertisseur markdown -> HTML (titres, tableaux, listes, gras).

    Couvre uniquement le sous-ensemble de markdown produit par SYSTEM_PROMPT ;
    ne vise pas a etre un convertisseur markdown generaliste.
    """
    lines = md_text.strip("\n").split("\n")
    blocks = []
    para_buf = []

    def flush_paragraph():
        if para_buf:
            text = " ".join(l.strip() for l in para_buf)
            blocks.append(f"<p>{inline_markdown(text)}</p>")
            para_buf.clear()

    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        header_match = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if header_match:
            flush_paragraph()
            level = len(header_match.group(1))
            blocks.append(f"<h{level}>{inline_markdown(header_match.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            blocks.append(render_table(table_lines))
            continue

        if re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            blocks.append("<ol>" + "".join(f"<li>{inline_markdown(it)}</li>" for it in items) + "</ol>")
            continue

        if re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            blocks.append("<ul>" + "".join(f"<li>{inline_markdown(it)}</li>" for it in items) + "</ul>")
            continue

        para_buf.append(stripped)
        i += 1

    flush_paragraph()
    return "\n".join(blocks)


def format_date_fr(iso_date):
    try:
        year, month, day = iso_date.split("-")
        return f"{day}/{month}/{year}"
    except (ValueError, AttributeError):
        return iso_date


def build_html_report(store, data, report_md):
    periode = data.get("periodeActuelle") or {}
    debut = format_date_fr(periode.get("debut", ""))
    fin = format_date_fr(periode.get("fin", ""))
    periode_label = f"{debut} - {fin}" if debut and fin else ""

    body_html = markdown_to_html(report_md)
    store_safe = escape_html(store)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CRK — Rapport hebdomadaire — {store_safe}</title>
<style>
{HTML_CSS}
</style>
</head>
<body>
<div class="page">
<header class="report-header">
<p class="eyebrow">CRK — Rapport hebdomadaire</p>
<h1>{store_safe}</h1>
<p class="periode">{escape_html(periode_label)}</p>
</header>
<div class="report-body">
{body_html}
</div>
<footer class="report-footer">
Genere automatiquement — donnees a valider
</footer>
</div>
</body>
</html>
"""


def load_env(path):
    """Parse un fichier .env simple (KEY=VALUE, lignes # ignorees)."""
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_config():
    env = load_env(ENV_FILE)
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL") or env.get("GEMINI_MODEL") or DEFAULT_MODEL

    if not api_key:
        sys.exit(
            "Erreur : cle API Gemini manquante.\n"
            f"  -> Copiez agent/.env.example vers {ENV_FILE.name} dans agent/ "
            "et renseignez GEMINI_API_KEY=...\n"
            "  -> Ou exportez la variable d'environnement GEMINI_API_KEY avant de lancer le script."
        )
    return api_key, model


def compute_deltas(current, previous):
    deltas = {}
    for key, c in current.items():
        p = previous.get(key)
        if not isinstance(c, (int, float)) or not isinstance(p, (int, float)):
            continue
        diff = c - p
        pct = (diff / p * 100) if p else None
        deltas[key] = {
            "valeur": round(diff, 2),
            "pourcent": round(pct, 1) if pct is not None else None,
        }
    return deltas


def build_user_prompt(data):
    deltas = compute_deltas(data["totauxActuels"], data["totauxPrecedents"])
    payload = {
        "magasin": data["magasin"],
        "periodeActuelle": data["periodeActuelle"],
        "periodePrecedente": data["periodePrecedente"],
        "totauxSemaineActuelle": data["totauxActuels"],
        "totauxSemainePrecedente": data["totauxPrecedents"],
        "ecartsSemaineActuelleVsPrecedente": deltas,
        "detailJournalierSemaineActuelle": data["joursActuels"],
        "detailJournalierSemainePrecedente": data["joursPrecedents"],
    }
    return (
        f"{LEGENDE_CHAMPS}\n"
        "Voici les donnees brutes de la boutique pour la semaine a analyser, "
        "au format JSON (le champ ecartsSemaineActuelleVsPrecedente est deja "
        "calcule, utilise-le directement plutot que de recalculer les ecarts). "
        "Redige le rapport hebdomadaire en respectant strictement le role et "
        "les regles definis dans les instructions systeme.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )


def call_gemini(api_key, model, user_prompt):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": TEMPERATURE},
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"l'API Gemini a repondu HTTP {err.code} : {detail[:500]}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"impossible de contacter l'API Gemini ({err.reason})") from err
    except TimeoutError as err:
        raise RuntimeError("l'appel a l'API Gemini a expire (timeout)") from err

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"reponse Gemini illisible (pas du JSON) : {raw[:500]}") from err

    try:
        parts = parsed["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as err:
        raise RuntimeError(
            f"format de reponse Gemini inattendu : {json.dumps(parsed, ensure_ascii=False)[:500]}"
        ) from err

    if not text.strip():
        raise RuntimeError("l'API Gemini a renvoye une reponse vide (verifiez d'eventuels filtres de securite)")

    return text.strip() + "\n"


def load_store_files(magasin_filter):
    if not DATA_DIR.exists():
        sys.exit(
            f"Erreur : le dossier {DATA_DIR} n'existe pas.\n"
            "  -> Lancez d'abord : node agent/export_data.mjs"
        )

    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        sys.exit(
            f"Erreur : aucun fichier JSON trouve dans {DATA_DIR}.\n"
            "  -> Lancez d'abord : node agent/export_data.mjs"
        )

    entries = []
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"! {file.name} ignore (JSON invalide : {err})", file=sys.stderr)
            continue
        entries.append((file, data))

    if magasin_filter:
        entries = [(f, d) for f, d in entries if d.get("magasin") == magasin_filter]
        if not entries:
            sys.exit(
                f"Erreur : aucune donnee pour le magasin \"{magasin_filter}\" dans {DATA_DIR}.\n"
                "  -> Verifiez le nom exact (voir src/data/mockData.js -> storeNames) "
                "et relancez node agent/export_data.mjs si besoin."
            )

    return entries


def main():
    parser = argparse.ArgumentParser(description="Genere les rapports hebdomadaires CRK via l'API Gemini.")
    parser.add_argument("--magasin", help="Nom exact d'un seul magasin a traiter (sinon : tous)")
    args = parser.parse_args()

    api_key, model = get_config()
    entries = load_store_files(args.magasin)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    ok, failed = 0, 0
    for i, (file, data) in enumerate(entries):
        store = data.get("magasin", file.stem)
        print(f"-> Generation du rapport pour {store} (modele {model})...", flush=True)

        prompt = build_user_prompt(data)
        try:
            report = call_gemini(api_key, model, prompt)
        except RuntimeError as err:
            print(f"x  Echec pour {store} : {err}", file=sys.stderr)
            failed += 1
        else:
            out_file = REPORTS_DIR / f"{file.stem}.md"
            out_file.write_text(report, encoding="utf-8")

            html_report = build_html_report(store, data, report)
            html_file = REPORTS_DIR / f"{file.stem}.html"
            html_file.write_text(html_report, encoding="utf-8")

            print(f"OK {store} -> {out_file} + {html_file.name}")
            ok += 1

        if i < len(entries) - 1:
            time.sleep(PAUSE_SECONDS)

    print(f"\n{ok} rapport(s) genere(s), {failed} echec(s).")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
