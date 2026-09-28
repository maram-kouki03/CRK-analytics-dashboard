"""ETAPE 1 : decouvrir ce que l'API Joolan renvoie REELLEMENT.

Le swagger ne suffit pas. Son exemple de reponse montre 5 champs
(Entete, Magasin, Date, Nature, Total_TTC) mais ne les LIMITE pas : le schema dit
seulement « object ». Or /import-tickets.do declare un champ `Heure` sur une
entete — donc Joolan STOCKE une heure par ticket. Reste a savoir si l'export la
renvoie. Un seul appel reel repond a la question.

Ce script ne calcule aucun indicateur. Il regarde, il liste, il montre.

    py inspect_joolan.py                     # hier
    py inspect_joolan.py --date 2026-08-20
    py inspect_joolan.py --date 2026-08-20 --json   # reponse brute complete

Lecture seule : aucune ecriture en base.
"""

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta

import joolan

# Noms de champ susceptibles de porter une heure. On cherche large : Joolan peut
# l'appeler Heure, Time, Heure_Vente, DateHeure...
MOTIFS_HEURE = re.compile(r"heure|time|hour|horaire", re.IGNORECASE)
# Une valeur qui ressemble a une heure : "14:35", "14:35:02", "2026-08-20 14:35:02"
MOTIF_VALEUR_HEURE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?\b")


def titre(t):
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


def brut(date_iso: str) -> dict:
    """Reponse JSON complete, sans aucun traitement."""
    params = urllib.parse.urlencode(
        {"enseigne": joolan.ENSEIGNE, "api-key": joolan.API_KEY, "Date": date_iso}
    )
    url = f"{joolan.SCHEME}://{joolan.DOMAIN}/api/v2/export-tickets.do?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=joolan.TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset))


def _montant(e) -> float:
    try:
        return float(e.get("Total_TTC") or 0)
    except (TypeError, ValueError):
        return 0.0


def extraire_heure(valeur) -> str | None:
    """Renvoie 'HH' si la valeur contient une heure, sinon None."""
    m = MOTIF_VALEUR_HEURE.search(str(valeur))
    return f"{int(m.group(1)):02d}" if m else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=(date.today() - timedelta(days=1)).isoformat())
    p.add_argument("--json", action="store_true", help="afficher la reponse brute complete")
    args = p.parse_args()

    if not joolan.is_configured():
        print("Joolan non configure. Renseigner dans crk-backend/.env :")
        print("  CRK_JOOLAN_DOMAIN, CRK_JOOLAN_ENSEIGNE, CRK_JOOLAN_API_KEY")
        return 1

    titre(f"Appel reel : export-tickets.do  Date={args.date}")
    print(f"  domaine  : {joolan.DOMAIN}")
    print(f"  enseigne : {joolan.ENSEIGNE}")
    try:
        payload = brut(args.date)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error_message", "")
        except Exception:
            pass
        print(f"  ECHEC HTTP {exc.code} : {detail or exc.reason}")
        return 1
    except Exception as exc:
        print(f"  ECHEC : {exc}")
        return 1

    print(f"  result   : {payload.get('result')}")
    if payload.get("result") != "ok":
        print(f"  refus    : {payload.get('error_message')}")
        return 1

    data = payload.get("data") or {}
    print(f"  sections : {', '.join(data.keys())}")

    if args.json:
        titre("Reponse brute")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:8000])

    entetes = data.get("entetes") or []
    if not entetes:
        titre("Aucune entete ce jour-la")
        print("  Reessayer avec --date sur un jour ouvre connu.")
        return 0

    # -------------------------------------------------- champs reellement presents
    titre(f"1. Champs presents sur les entetes  ({len(entetes)} tickets)")
    champs = Counter()
    exemples = {}
    for e in entetes:
        for k, v in e.items():
            champs[k] += 1
            if k not in exemples and v not in (None, ""):
                exemples[k] = v

    print(f"  {'CHAMP':<24} {'PRESENT':<10} EXEMPLE")
    print(f"  {'-' * 24} {'-' * 10} {'-' * 28}")
    for k, n in champs.most_common():
        marque = "  <<<" if MOTIFS_HEURE.search(k) else ""
        print(f"  {k:<24} {n}/{len(entetes):<7} {str(exemples.get(k, ''))[:28]}{marque}")

    # ------------------------------------------------------ la question de l'heure
    titre("2. Y a-t-il une HEURE exploitable ?")

    par_nom = [k for k in champs if MOTIFS_HEURE.search(k)]
    par_valeur = [k for k, v in exemples.items() if extraire_heure(v)]
    candidats = list(dict.fromkeys(par_nom + par_valeur))

    if candidats:
        print("  OUI. Champ(s) utilisable(s) :")
        for k in candidats:
            print(f"    {k:<22} exemple : {exemples.get(k)}")
        print("\n  -> ETAPE 2 possible : chiffre d'affaires par heure.")
    else:
        print("  NON. Aucun champ ne porte d'heure dans cette reponse.")
        print("  Les entetes ne donnent que la date, donc :")
        print("    - le NOMBRE DE TICKETS par jour reste faisable ;")
        print("    - le CA PAR HEURE est impossible depuis cet endpoint.")
        print("  A demander a CRK / Joolan : ajouter Heure a export-tickets.do")
        print("  (import-tickets.do l'accepte deja, la donnee existe en base).")

    # ------------------------------------------- natures reellement rencontrees
    titre("3. Natures rencontrees")
    par_nature = defaultdict(lambda: [0, 0.0])
    for e in entetes:
        n = str(e.get("Nature") or "?").strip().upper()
        par_nature[n][0] += 1
        par_nature[n][1] += _montant(e)
    for n, (c, ca) in sorted(par_nature.items(), key=lambda x: -x[1][0]):
        role = {
            "VENTE": "VENTE ENCAISSEE -> a compter",
            "AVOIR": "avoir / retour -> a soustraire si CA net",
        }.get(n, "pas une vente -> exclu")
        print(f"  {n:<24} {c:>5} tk  {ca:>13,.2f} DT   {role}".replace(",", " "))
    print("\n  Filtre actuel (CRK_JOOLAN_NATURES) :", ", ".join(joolan.NATURES))

    # ------------------------------------------------------ magasins rencontres
    titre(f"4. Codes Magasin  (natures retenues : {', '.join(joolan.NATURES)})")
    ventes = [e for e in entetes
              if str(e.get("Nature") or "").strip().upper() in joolan.NATURES]
    print(f"  {len(ventes)} ventes retenues sur {len(entetes)} entetes\n")
    par_magasin = defaultdict(lambda: [0, 0.0])
    for e in ventes:
        m = str(e.get("Magasin") or "?").strip()
        par_magasin[m][0] += 1
        par_magasin[m][1] += _montant(e)
    for m, (n, ca) in sorted(par_magasin.items()):
        print(f"  {m:<24} {n:>5} tickets   {ca:>12,.2f} DT".replace(",", " "))
    print("\n  Ces codes sont a mettre dans CRK_JOOLAN_MAGASINS s'ils different")
    print("  des noms CRK (MANAR CITY, Tunisia Mall, ...).")

    # ------------------------- apercu CA par heure, si une heure a ete trouvee
    if candidats:
        champ = candidats[0]
        titre(f"5. CA par heure des VENTES (champ '{champ}')")
        par_heure = defaultdict(lambda: [0, 0.0])
        illisibles = 0
        for e in ventes:                      # ventes uniquement, pas les transferts
            h = extraire_heure(e.get(champ))
            if h is None:
                illisibles += 1
                continue
            par_heure[h][0] += 1
            par_heure[h][1] += _montant(e)
        for h in sorted(par_heure):
            n, ca = par_heure[h]
            print(f"  {h}h   {n:>5} tickets   {ca:>12,.2f} DT".replace(",", " "))
        if illisibles:
            print(f"  ({illisibles} entete(s) sans heure lisible)")
        print("\n  -> Si ce tableau est coherent, l'etape 2 peut etre construite.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
