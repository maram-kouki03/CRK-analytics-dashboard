"""Client de l'API caisse Joolan — endpoint /export-tickets.do.

Spécification : swagger.yaml (Joolan API v2).

  GET https://{domaine}/api/v2/export-tickets.do
      ?enseigne={enseigne}&api-key={cle}&Date=AAAA-MM-JJ

  200 -> { "result": "ok",
           "data": { "entetes": [...], "lignes": [...], "reglements": [...] } }
  400 -> { "result": "ko", "error_message": "invalid api key" }

Deux propriétés de cette API dictent toute la conception :

1. UN SEUL JOUR PAR APPEL. Pas de plage de dates. Une période de 30 jours
   demanderait 30 requêtes — d'où le cache journalier dans db.py.

2. UN APPEL RENVOIE TOUS LES MAGASINS. Le champ `Magasin` des entêtes permet de
   ventiler. On appelle donc une fois PAR DATE, jamais par magasin : 7 requêtes
   pour la semaine des 8 boutiques, pas 56.

3. L'HEURE EST BIEN RENVOYEE. Le swagger ne documente aucun champ de réponse,
   mais l'appel réel montre un champ `Heure` ("20:28:22") sur 332/332 entêtes.
   Le chiffre d'affaires par heure est donc mesurable, pas reconstitué.

Aucune dépendance ajoutée : urllib suffit pour un GET, et le déploiement de la
VM n'a donc rien à réinstaller.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

DOMAIN = os.environ.get("CRK_JOOLAN_DOMAIN", "").strip()
# https par defaut, comme le prevoit la spec. Configurable pour deux cas reels :
# un Joolan installe en interne sans TLS, et les tests contre un faux serveur.
SCHEME = os.environ.get("CRK_JOOLAN_SCHEME", "https").strip().lower()
ENSEIGNE = os.environ.get("CRK_JOOLAN_ENSEIGNE", "").strip()
API_KEY = os.environ.get("CRK_JOOLAN_API_KEY", "").strip()
TIMEOUT = float(os.environ.get("CRK_JOOLAN_TIMEOUT", "20"))

# Natures d'entête comptées comme une vente. La spec documente « VENTE » ;
# À CONFIRMER AVEC CRK : les autres valeurs possibles (retour, échange, avoir…)
# et s'il faut les compter. Un retour compté en négatif change R et le panier.
NATURES = tuple(
    n.strip().upper()
    for n in os.environ.get("CRK_JOOLAN_NATURES", "VENTE").split(",")
    if n.strip()
)

# Correspondance nom CRK -> code Magasin dans Joolan, en JSON.
# Ex. {"MANAR CITY": "MANAR", "Tunisia Mall": "TUNISMALL"}
# Vide => on suppose que Joolan utilise les mêmes noms que STORE_NAMES.
try:
    _MAP_RAW = json.loads(os.environ.get("CRK_JOOLAN_MAGASINS", "") or "{}")
except json.JSONDecodeError:
    _MAP_RAW = {}
    print("[crk] CRK_JOOLAN_MAGASINS n'est pas du JSON valide, correspondance ignoree", flush=True)

# Comparaison insensible à la casse, comme pour les noms venant des boîtiers.
_MAGASIN_PAR_CRK = {k.strip(): str(v).strip() for k, v in _MAP_RAW.items()}


# Champ portant l'heure de l'entête, vérifié sur la vraie API : "20:28:22".
# Configurable au cas où Joolan le renommerait — inspect_joolan.py liste les
# champs réellement présents.
CHAMP_HEURE = os.environ.get("CRK_JOOLAN_CHAMP_HEURE", "Heure").strip()

# "20:28:22" -> 20. Accepte aussi "2026-08-21 20:28:22".
_MOTIF_HEURE = re.compile(r"([01]?\d|2[0-3]):[0-5]\d")


def _heure_de(entete) -> int | None:
    """Heure entière de l'entête, ou None si illisible."""
    m = _MOTIF_HEURE.search(str(entete.get(CHAMP_HEURE) or ""))
    return int(m.group(1)) if m else None


class JoolanError(RuntimeError):
    """Appel Joolan impossible ou refusé. Jamais silencieux : on remonte."""


def is_configured() -> bool:
    """True si les trois informations indispensables sont présentes."""
    return bool(DOMAIN and ENSEIGNE and API_KEY)


def magasin_joolan(store_id: str) -> str:
    """Code Magasin attendu par Joolan pour un magasin CRK."""
    return _MAGASIN_PAR_CRK.get(store_id, store_id)


def _url(date_iso: str) -> str:
    params = urllib.parse.urlencode(
        {"enseigne": ENSEIGNE, "api-key": API_KEY, "Date": date_iso}
    )
    return f"{SCHEME}://{DOMAIN}/api/v2/export-tickets.do?{params}"


def _masque(url: str) -> str:
    """URL sans la clé API, pour pouvoir la journaliser sans fuite."""
    return url.replace(API_KEY, "***") if API_KEY else url


def fetch_day(date_iso: str) -> dict:
    """{code_magasin: {heure: {"tickets": int, "revenue": float}}} pour cette date.

    Un seul appel HTTP, tous les magasins. Lève JoolanError en cas d'échec —
    l'appelant décide quoi faire, on ne renvoie jamais de zéros silencieux qui
    se liraient comme « aucune vente ce jour-là ».
    """
    if not is_configured():
        raise JoolanError(
            "Joolan non configure : renseigner CRK_JOOLAN_DOMAIN, "
            "CRK_JOOLAN_ENSEIGNE et CRK_JOOLAN_API_KEY dans crk-backend/.env"
        )

    url = _url(date_iso)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            payload = json.loads(resp.read().decode(charset))
    except urllib.error.HTTPError as exc:
        # Joolan renvoie ses refus en 400 avec un corps JSON explicite.
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error_message", "")
        except Exception:
            pass
        raise JoolanError(f"HTTP {exc.code} sur {_masque(url)} — {detail or exc.reason}")
    except urllib.error.URLError as exc:
        raise JoolanError(f"Joolan injoignable ({_masque(url)}) — {exc.reason}")
    except json.JSONDecodeError:
        raise JoolanError(f"Reponse non JSON de {_masque(url)}")

    if payload.get("result") != "ok":
        raise JoolanError(
            f"Joolan a refuse la requete : {payload.get('error_message', 'raison inconnue')}"
        )

    entetes = (payload.get("data") or {}).get("entetes") or []
    return _agreger(entetes)


def _agreger(entetes: list) -> dict:
    """{magasin: {heure: {"tickets": n, "revenue": x}}} — ventes ventilées par heure.

    Une entête sans heure lisible tomberait dans le vide : elle est rattachée à
    la clé None, que l'appelant peut compter dans le total du jour sans
    l'attribuer à une tranche horaire qu'on ne connaît pas.
    """
    par_magasin = {}
    for e in entetes:
        magasin = str(e.get("Magasin") or "").strip()
        if not magasin:
            continue  # entête sans magasin : inexploitable, on l'ignore
        if NATURES and str(e.get("Nature") or "").strip().upper() not in NATURES:
            continue  # avoir, transfert, ouverture/fermeture de caisse…

        heures = par_magasin.setdefault(magasin, {})
        agg = heures.setdefault(_heure_de(e), {"tickets": 0, "revenue": 0.0})
        agg["tickets"] += 1
        try:
            agg["revenue"] += float(e.get("Total_TTC") or 0)
        except (TypeError, ValueError):
            # Montant illisible : le ticket compte quand même, mais on ne
            # fabrique pas de chiffre d'affaires à partir de rien.
            pass

    for heures in par_magasin.values():
        for agg in heures.values():
            agg["revenue"] = round(agg["revenue"], 2)
    return par_magasin
