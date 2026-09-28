"""Verifie la connexion a l'API caisse Joolan, et rien d'autre.

A lancer des que CRK fournit domaine + enseigne + cle API. Il diagnostique dans
l'ordre : configuration, joignabilite, autorisation, contenu, correspondance des
noms de magasins. Chaque etape dit quoi corriger si elle echoue.

    py test_joolan.py                  # hier
    py test_joolan.py --date 2026-08-20
    py test_joolan.py --brut           # affiche la reponse JSON telle quelle

Lecture seule : aucune ecriture en base, aucun effet de bord.
"""

import argparse
import json
from datetime import date, timedelta

import db
import joolan


def titre(t):
    print(f"\n=== {t}")


def ok(m):
    print(f"    OK   {m}")


def ko(m):
    print(f"    !!   {m}")


def info(m):
    print(f"         {m}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=(date.today() - timedelta(days=1)).isoformat(),
                   help="date a tester (AAAA-MM-JJ), hier par defaut")
    p.add_argument("--brut", action="store_true", help="afficher la reponse JSON brute")
    args = p.parse_args()

    # ---------------------------------------------------------- configuration
    titre("1. Configuration")
    manquants = [
        nom for nom, val in (
            ("CRK_JOOLAN_DOMAIN", joolan.DOMAIN),
            ("CRK_JOOLAN_ENSEIGNE", joolan.ENSEIGNE),
            ("CRK_JOOLAN_API_KEY", joolan.API_KEY),
        ) if not val
    ]
    if manquants:
        ko("il manque dans crk-backend/.env : " + ", ".join(manquants))
        info("Sans ces trois valeurs le dashboard reste en mode simulation.")
        info("Voir la section « Ce qu'il faut demander a CRK » du README backend.")
        return 1

    ok(f"domaine  : {joolan.DOMAIN}")
    ok(f"enseigne : {joolan.ENSEIGNE}")
    ok(f"cle API  : {joolan.API_KEY[:4]}...{joolan.API_KEY[-2:]} ({len(joolan.API_KEY)} caracteres)")
    ok(f"natures comptees comme vente : {', '.join(joolan.NATURES)}")

    # ------------------------------------------------------------ appel reel
    titre(f"2. Appel /export-tickets.do pour le {args.date}")
    try:
        par_magasin = joolan.fetch_day(args.date)
    except joolan.JoolanError as exc:
        ko(str(exc))
        info("")
        info("Pistes selon le message :")
        info("  'invalid api key'  -> cle erronee, ou permission api_export_tickets absente")
        info("  'enseigne'         -> nom d'enseigne errone")
        info("  injoignable        -> domaine errone, ou la VM n'a pas d'acces Internet")
        info("  HTTP 404           -> le domaine ne sert pas /api/v2")
        return 1

    ok("Joolan a repondu result=ok")

    if args.brut:
        titre("Reponse brute")
        print(json.dumps(par_magasin, ensure_ascii=False, indent=2))

    # -------------------------------------------------------------- contenu
    titre("3. Contenu renvoye")
    if not par_magasin:
        ko(f"aucun ticket pour le {args.date}")
        info("Ce n'est pas forcement une erreur : boutique fermee, ou date sans vente.")
        info("Reessayer avec --date sur un jour ouvre connu.")
    else:
        ok(f"{len(par_magasin)} magasin(s) avec des ventes ce jour-la")
        for magasin, v in sorted(par_magasin.items()):
            info(f"  {magasin:<24} {v['tickets']:>5} tickets   {v['revenue']:>12,.2f} DT"
                 .replace(",", " "))

    # ------------------------------------------- correspondance des magasins
    titre("4. Correspondance des noms de magasins")
    info("Joolan doit renvoyer, pour chaque boutique CRK, le code attendu.")
    info("Sinon renseigner CRK_JOOLAN_MAGASINS dans .env.\n")

    inconnus = set(par_magasin)
    trouves = 0
    for store in db.STORE_NAMES:
        attendu = joolan.magasin_joolan(store)
        if attendu in par_magasin:
            ok(f"{store:<18} -> {attendu}")
            inconnus.discard(attendu)
            trouves += 1
        else:
            print(f"    --   {store:<18} -> {attendu:<18} (absent de la reponse)")

    if inconnus:
        print()
        ko("codes renvoyes par Joolan sans correspondance CRK : " + ", ".join(sorted(inconnus)))
        info("Ajouter la correspondance, par exemple :")
        exemple = {db.STORE_NAMES[0]: sorted(inconnus)[0]}
        info(f'  CRK_JOOLAN_MAGASINS={json.dumps(exemple, ensure_ascii=False)}')

    # ----------------------------------------------------------------- bilan
    titre("Bilan")
    if trouves:
        ok(f"{trouves} magasin(s) correctement relie(s).")
        ok("Redemarrer le service : le bandeau « donnees simulees » doit disparaitre.")
        info("Purger d'abord les jours simules :")
        info("  py -c \"import db; print(db.clear_pos_cache('simulation'), 'jours purges')\"")
    else:
        ko("aucun magasin relie : les noms ne correspondent pas encore.")
        info("Le dashboard resterait a 0 ticket et 0 DT partout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
