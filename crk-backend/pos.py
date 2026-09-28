"""Données de caisse : tickets vendus (T) et chiffre d'affaires (R).

Ce module décide D'OÙ viennent ces deux chiffres, et le dit toujours :

    Joolan configuré (CRK_JOOLAN_*)  ->  API réelle, source = "joolan"
    sinon                            ->  simulation,  source = "simulation"

Le drapeau `simule` remonte jusqu'au dashboard, qui affiche un bandeau orange
tant qu'il vaut True. Règle du projet : une valeur qui n'est pas mesurée doit se
voir.

Stockage à l'HEURE (table pos_hourly), pas à la journée : l'API renvoie une
heure sur chaque entête, et le dashboard trace le potentiel, le manque à gagner
et la captation heure par heure. Le total de la période est la somme des heures,
il n'y a donc qu'une seule granularité stockée.

Trois raisons au cache :

  * L'API Joolan ne répond que PAR DATE. Une période de 30 jours = 30 requêtes.
    Sans cache, chaque rafraîchissement du dashboard les relancerait toutes.
  * Un appel renvoie TOUS les magasins : on met donc en cache les 8 d'un coup,
    et la page Comparaison ne coûte rien de plus que la Vue d'ensemble.
  * Une journée passée est figée. La journée EN COURS, elle, est redemandée à
    chaque fois, puisque des ventes s'y ajoutent encore.
"""

import hashlib
import random
from datetime import date, datetime, timedelta, timezone

import db
import joolan

# Meme fuseau que analytics.TZ_TUNIS : Africa/Tunis, +01:00 fixe, sans DST.
# Duplique ici plutot qu'importe, car analytics importe deja pos : l'importer
# en retour creerait un cycle. Les deux valeurs doivent rester identiques.
TZ_BOUTIQUE = timezone(timedelta(hours=1))

# Heure conventionnelle des tickets dont l'entête n'a pas d'heure lisible : ils
# comptent dans le total du jour, mais ne sont attribués à aucune tranche.
HEURE_INCONNUE = -1

# Fourchettes de la SIMULATION uniquement — aucune valeur métier, elles
# disparaîtront avec la simulation. Les vrais repères (objectif de conversion,
# panier de référence) sont dans analytics.py, à côté de la formule.
_MOCK_CONVERSION = (0.08, 0.18)      # part de visiteurs acheteurs
_MOCK_PANIER_DT = (240.0, 340.0)     # panier moyen simulé, en dinars


# ------------------------------------------------------------------ simulation

def _rng(store_id: str, jour: str, heure: int) -> random.Random:
    """Générateur déterministe : même magasin + même heure => mêmes chiffres.

    Sans cela, chaque rafraîchissement donnerait un CA différent et les écarts
    « vs période précédente » n'auraient aucun sens.
    """
    cle = f"{store_id}|{jour}|{heure}".encode()
    return random.Random(int(hashlib.sha256(cle).hexdigest()[:12], 16))


def _simuler_heure(store_id: str, jour: str, heure: int, visiteurs: int) -> dict:
    """Ventes plausibles pour une tranche horaire, à partir des visiteurs mesurés."""
    if visiteurs <= 0:
        # Aucun visiteur mesuré : on ne fabrique pas de vente pour autant.
        return {"tickets": 0, "revenue": 0.0}
    rng = _rng(store_id, jour, heure)
    tickets = round(visiteurs * rng.uniform(*_MOCK_CONVERSION))
    if tickets <= 0:
        return {"tickets": 0, "revenue": 0.0}
    return {"tickets": tickets, "revenue": round(tickets * rng.uniform(*_MOCK_PANIER_DT), 2)}


# ----------------------------------------------------------------------- accès

def _jours(du: str, au: str) -> list:
    d1, d2 = date.fromisoformat(du), date.fromisoformat(au)
    return [(d1 + timedelta(days=i)).isoformat() for i in range((d2 - d1).days + 1)]


def _fin_de_journee(jour: str) -> float:
    """Timestamp du minuit qui CLÔT cette journée, heure de la boutique."""
    d = date.fromisoformat(jour) + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=TZ_BOUTIQUE).timestamp()


def _a_recharger(jour: str, vu: dict | None, source_voulue: str) -> bool:
    """Faut-il redemander cette journée à la caisse ?

    Trois cas :
      * jamais lue ;
      * lue depuis une autre source (bascule simulation -> Joolan) ;
      * lue AVANT la fin de la journée, donc forcément incomplète.

    Ce dernier cas est le piège : une journée consultée à 14h ne contient pas
    les ventes du soir. Sans ce test, elle restait figée à 14h pour toujours —
    une soirée entière de chiffre d'affaires disparaissait en silence, y compris
    la journée en cours une fois le lendemain venu.
    """
    if vu is None or vu["source"] != source_voulue:
        return True
    return vu["lu_a"] < _fin_de_journee(jour)


def fetch_pos_data(store_id: str, du: str, au: str, visiteurs: int,
                   visiteurs_par_jour: dict | None = None,
                   visiteurs_par_heure: dict | None = None) -> dict:
    """Ventes de la période : total, et ventilation par heure.

    Renvoie {tickets, revenue, par_heure, simule, source, jours_manquants}
    où `par_heure` est {heure: {tickets, revenue}} cumulé sur toute la période.

    `visiteurs_par_heure` ({heure: nb}) ne sert qu'à la simulation, pour que les
    tickets restent cohérents avec la fréquentation réellement mesurée. L'API
    réelle n'en a pas besoin.
    """
    jours = _jours(du, au)
    source_voulue = "joolan" if joolan.is_configured() else "simulation"

    cache = db.get_pos_hours(store_id, jours)
    # Par journée : la source, et le PLUS ANCIEN moment où on l'a lue.
    etat = {}
    for (jour, _h), v in cache.items():
        vu = etat.setdefault(jour, {"source": v["source"], "lu_a": v["fetched_at"]})
        vu["lu_a"] = min(vu["lu_a"], v["fetched_at"])

    a_charger = [j for j in jours if _a_recharger(j, etat.get(j), source_voulue)]

    manquants = []
    if a_charger:
        if source_voulue == "joolan":
            nouveaux, manquants = _charger_joolan(a_charger)
        else:
            nouveaux = _simuler(store_id, a_charger, visiteurs_par_heure or {})

        # On efface la journée entière avant de la réécrire : une heure dont les
        # ventes ont disparu doit disparaître aussi, ce qu'un REPLACE seul ne
        # ferait pas.
        chargees = sorted({r[1] for r in nouveaux} | (set(a_charger) - set(manquants)))
        db.delete_pos_days(store_id, chargees)
        db.put_pos_hours(nouveaux)
        cache = db.get_pos_hours(store_id, jours)

    par_heure = {}
    tickets = 0
    revenue = 0.0
    for (_jour, heure), v in cache.items():
        tickets += v["tickets"]
        revenue += v["revenue"]
        if heure == HEURE_INCONNUE:
            continue  # compté dans le total, pas rattaché à une tranche
        agg = par_heure.setdefault(heure, {"tickets": 0, "revenue": 0.0})
        agg["tickets"] += v["tickets"]
        agg["revenue"] = round(agg["revenue"] + v["revenue"], 2)

    return {
        "tickets": tickets,
        "revenue": round(revenue, 2),
        "par_heure": par_heure,
        "simule": source_voulue == "simulation",
        "source": source_voulue,
        # Jours que Joolan n'a pas pu fournir : le dashboard peut le signaler
        # plutôt que de laisser croire à un CA nul ces jours-là.
        "jours_manquants": manquants,
    }


def _simuler(store_id: str, jours: list, visiteurs_par_heure: dict) -> list:
    """Lignes simulées, une par (jour, heure) ayant des visiteurs mesurés."""
    lignes = []
    for jour in jours:
        for heure, nb in (visiteurs_par_heure.get(jour) or {}).items():
            v = _simuler_heure(store_id, jour, heure, nb)
            if v["tickets"]:
                lignes.append((store_id, jour, heure, v["tickets"], v["revenue"], "simulation"))
    return lignes


def _charger_joolan(jours: list):
    """Interroge Joolan pour ces dates. Un appel par date, tous magasins.

    Renvoie (lignes_a_cacher, jours_en_echec). Un jour en échec n'est PAS mis en
    cache : on préfère le redemander au prochain affichage plutôt que de figer un
    zéro qui se lirait comme « aucune vente ».
    """
    lignes, echecs = [], []
    for jour in jours:
        try:
            par_magasin = joolan.fetch_day(jour)
        except joolan.JoolanError as exc:
            print(f"[crk] caisse {jour} indisponible : {exc}", flush=True)
            echecs.append(jour)
            continue

        # Un appel couvre tous les magasins : on cache les 8 d'un coup.
        for store in db.STORE_NAMES:
            heures = par_magasin.get(joolan.magasin_joolan(store), {})
            for heure, v in heures.items():
                lignes.append((
                    store, jour,
                    HEURE_INCONNUE if heure is None else heure,
                    v["tickets"], v["revenue"], "joolan",
                ))
            if not heures:
                # Aucune vente pour ce magasin ce jour-là — boutique fermée, ou
                # code Magasin pas encore relié. On écrit quand même une ligne à
                # zéro : sans elle le cache resterait vide pour ce magasin, et on
                # rappellerait Joolan à CHAQUE affichage. Elle n'ajoute rien aux
                # totaux et n'apparaît dans aucune tranche horaire.
                lignes.append((store, jour, HEURE_INCONNUE, 0, 0.0, "joolan"))
    return lignes, echecs
