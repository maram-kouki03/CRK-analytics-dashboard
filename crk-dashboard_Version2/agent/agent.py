



# ============================================================
# Agent IA — Rapports hebdomadaires CRK
#
# Lit les KPI hebdomadaires (agent/data/*.json), les envoie à
# Gemini avec un prompt d'analyste retail, et rédige un rapport
# par magasin dans agent/reports/.
#
# Usage :
#   1. node agent/export_data.mjs        (génère les données)
#   2. python agent/agent.py             (génère les rapports)
#   ou pour un seul magasin :
#   python agent/agent.py --magasin "Tunisia Mall"
#
# Prérequis : fichier agent/.env avec GEMINI_API_KEY=...
# ============================================================

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"


def load_env(path: Path):
    """Mini-chargeur de fichier .env (aucune librairie externe requise)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_env(BASE_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
# Modèle : voir la liste sur https://ai.google.dev/gemini-api/docs/models
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)

# ------------------------------------------------------------
# Le prompt : c'est ici que la qualité du rapport se joue.
# ------------------------------------------------------------
SYSTEM_PROMPT = """Tu es un analyste retail senior travaillant pour CRK, \
une marque tunisienne de maroquinerie disposant de 8 boutiques. Tu analyses \
les indicateurs hebdomadaires d'UN magasin et tu rédiges un rapport pour la \
direction, en français.

Définitions des indicateurs :
- clients : nombre de visiteurs entrés dans la boutique (comptage caméra)
- pec : nombre de clients pris en charge par un vendeur
- tauxPec : pec / clients, en %
- tempsAvantPec : délai moyen (secondes) avant qu'un client soit pris en charge
- vendeurs : nombre de vendeurs actifs
- tickets : nombre d'achats enregistrés en caisse
- tauxTransformation : tickets / clients, en % (part des visiteurs qui achètent)
- panierMoyen : montant moyen d'un achat, en dinars tunisiens (DT)
- potentiel : panierMoyen × clients = CA théorique si tous les visiteurs achetaient
- caEstime : panierMoyen × tickets = CA réellement capté

Règles STRICTES de rédaction :
1. Appuie CHAQUE constat sur des chiffres précis tirés des données (valeurs, \
écarts en % ou en points vs la semaine précédente, jours concernés).
2. Ne réénonce jamais un chiffre sans l'interpréter : dis ce qu'il signifie \
pour le magasin.
3. Croise les indicateurs entre eux (ex. : affluence en hausse mais taux PEC \
en baisse → possible manque de vendeurs).
4. Les recommandations doivent être SPÉCIFIQUES à ce magasin et actionnables \
dès la semaine suivante (qui, quoi, quel jour/créneau). INTERDIT : conseils \
génériques du type "améliorer l'accueil" ou "motiver les équipes".
5. Chiffre l'enjeu quand c'est possible (ex. : "revenir au taux de \
transformation de la semaine précédente représenterait ~X DT de CA").
6. Si les données ne permettent pas de conclure sur un point, dis-le \
honnêtement plutôt que d'inventer une cause.
7. Longueur totale : 350 à 500 mots. Ton professionnel, direct, sans emphase.

Structure EXACTE du rapport (markdown) :
# Rapport hebdomadaire — {nom du magasin}
## Période
## Chiffres clés de la semaine
(tableau : indicateur | cette semaine | semaine précédente | évolution)
## Constats
(3 à 5 puces, chacune : fait chiffré + interprétation)
## Recommandations
(2 à 3 puces numérotées, spécifiques et actionnables, avec l'enjeu chiffré)
## Point de vigilance
(1 élément à surveiller la semaine prochaine)
"""


def build_user_prompt(data: dict) -> str:
    return (
        "Voici les données hebdomadaires du magasin. Rédige le rapport en "
        "respectant strictement les règles et la structure.\n\n"
        f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    )


def call_gemini(data: dict) -> str:
    """Envoie les KPI à Gemini et retourne le rapport en markdown."""
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {"role": "user", "parts": [{"text": build_user_prompt(data)}]}
        ],
        "generationConfig": {
            "temperature": 0.4,       # factuel, peu de créativité
            "maxOutputTokens": 2048,
        },
    }
    req = urllib.request.Request(
        f"{API_URL}?key={API_KEY}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Erreur API {e.code} : {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connexion impossible : {e.reason}") from e
    try:
        parts = body["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Réponse inattendue de l'API : {body}") from e


def main():
    parser = argparse.ArgumentParser(description="Agent IA — rapports hebdo CRK")
    parser.add_argument(
        "--magasin",
        help='Nom du magasin (ex. "Tunisia Mall"). Par défaut : tous.',
    )
    args = parser.parse_args()

    if not API_KEY:
        sys.exit(
            "❌ GEMINI_API_KEY manquante.\n"
            "   Copie agent/.env.example vers agent/.env et renseigne ta clé\n"
            "   (obtenue sur https://aistudio.google.com)."
        )

    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        sys.exit(
            "❌ Aucune donnée trouvée dans agent/data/.\n"
            "   Lance d'abord :  node agent/export_data.mjs"
        )

    if args.magasin:
        slug = args.magasin.lower().replace(" ", "-")
        files = [f for f in files if f.name.startswith(slug)]
        if not files:
            sys.exit(f"❌ Aucun fichier de données pour « {args.magasin} ».")

    REPORTS_DIR.mkdir(exist_ok=True)
    print(f"Modèle : {MODEL} — {len(files)} rapport(s) à générer\n")

    for i, file in enumerate(files):
        data = json.loads(file.read_text(encoding="utf-8"))
        store, period = data["magasin"], data["periode"]
        print(f"→ {store} ({period['du']} → {period['au']}) ...", flush=True)

        try:
            report = call_gemini(data)
        except RuntimeError as e:
            print(f"  ⚠️  échec : {e}")
            continue

        out = REPORTS_DIR / f"{file.stem}_rapport.md"
        out.write_text(report + "\n", encoding="utf-8")
        print(f"  ✓ {out}")

        # free tier : rester sous les limites de requêtes/minute
        if i < len(files) - 1:
            time.sleep(5)

    print("\nTerminé. Rapports dans agent/reports/")


if __name__ == "__main__":
    main()
