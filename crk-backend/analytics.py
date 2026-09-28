"""Agrégations servies au dashboard.

Tout est dérivé des seuls événements stockés — ENTRY et INTERACTION, tous deux
identifiés par leur track_id. Un indicateur qu'aucun événement ne permet de
calculer vaut None, jamais 0 : le frontend l'affiche « — », pour qu'une mesure
absente reste visiblement absente au lieu de ressembler à un vrai zéro.
"""

import os
from datetime import date, datetime, timedelta, timezone

import db
import pos

# Fixed +01:00 offset (Africa/Tunis, no DST) — avoids relying on the IANA tz
# database via zoneinfo, which Windows does not ship by default. No DST also
# means a local day is exactly 86400s, which the day bucketing below relies on.
TZ_TUNIS = timezone(timedelta(hours=1))

# Plage horaire affichée par défaut, même sans événement : elle donne une échelle
# stable d'une période à l'autre. Ce n'est PAS une borne — voir _hour_window.
DEFAULT_OPEN_HOUR = int(os.environ.get("CRK_OPEN_HOUR", "9"))
DEFAULT_CLOSE_HOUR = int(os.environ.get("CRK_CLOSE_HOUR", "20"))

# Monday-first, matching date.weekday().
JOUR_LABELS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
MOIS_LABELS = [
    "Jan", "Fév", "Mars", "Avr", "Mai", "Juin",
    "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
]

# Les deux seuls types comptés. Le boîtier n'en envoie pas d'autres (HEARTBEAT
# est accepté puis jeté à l'ingestion). Les anciens PEC / PEC_START / PEC_END ne
# sont plus ni stockés ni comptés : les lignes déjà en base sont ignorées.
ENTRY_TYPE = "ENTRY"
PEC_TYPE = "INTERACTION"

# Guards against a hand-typed URL asking for a decade of days in one request.
MAX_RANGE_DAYS = 400

SERIES_PERIODS = ("jour", "semaine", "mois")


class BadRequest(ValueError):
    """Caller-supplied parameters are unusable — surfaced as HTTP 400."""


# ---------------------------------------------------------------- time helpers

def _day_bounds(d: date):
    start = datetime(d.year, d.month, d.day, tzinfo=TZ_TUNIS)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _local_hour(ts: float) -> int:
    return datetime.fromtimestamp(ts, tz=TZ_TUNIS).hour


def _local_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=TZ_TUNIS).strftime("%Y-%m-%d")


def _hour_window(events) -> list:
    """Tranches horaires à afficher : la plage par défaut, ÉLARGIE aux heures
    réellement observées.

    Avant, tout événement hors 9h–20h était replié sur l'heure limite : une PEC à
    21h30 était comptée à 20h. C'était faux, et cela masquait justement le fait
    que la boutique ferme plus tard. On ne replie plus rien — la fenêtre s'étend
    pour accueillir l'heure réelle de chaque événement.

    Conséquence assumée : un événement isolé à 3h du matin étire l'axe jusqu'à 3h.
    C'est voulu — cela rend l'anomalie visible au lieu de la diluer dans la
    première tranche.

    Les heures viennent donc de la base, pas d'une constante : si la boutique
    change ses horaires, les graphes suivent sans qu'on touche au code.
    """
    # Seuls les types RÉELLEMENT tracés élargissent l'axe. Une base qui contient
    # encore des lignes PEC* d'avant le passage à INTERACTION ne doit pas ajouter
    # de colonnes vides : ces PEC_START s'étalent de 02h à 23h alors que les
    # clients tiennent dans 09h–21h, soit 9 tranches vides sur tous les graphes.
    heures = [
        _local_hour(e["ts"])
        for e in events
        if e["event_type"] in (ENTRY_TYPE, PEC_TYPE)
    ]
    debut = min([DEFAULT_OPEN_HOUR, *heures])
    fin = max([DEFAULT_CLOSE_HOUR, *heures])
    return list(range(debut, fin + 1))


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise BadRequest(f"{field} must be an ISO date (YYYY-MM-DD)")


def parse_range(du: str, au: str):
    """(first_day, last_day, day_count) — reversed inputs are swapped."""
    d1 = _parse_date(du, "du")
    d2 = _parse_date(au, "au")
    if d2 < d1:
        d1, d2 = d2, d1
    n = (d2 - d1).days + 1
    if n > MAX_RANGE_DAYS:
        raise BadRequest(f"range too long ({n} days, max {MAX_RANGE_DAYS})")
    return d1, d2, n


def _iso(d: date) -> str:
    return d.isoformat()


def _short_label(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}"


# ------------------------------------------------------- identité des personnes

def _unique_tracks(events, event_type: str) -> dict:
    """{(track_id, jour local): ts le plus ancien} — une entrée par personne réelle.

    ENTRY et INTERACTION portent la même et unique identité : le track_id que le
    tracker attribue à la personne suivie. Ce numéro n'est unique ni dans le
    temps ni dans la journée, d'où la clé composite (track_id, jour) :

    - DANS la journée, le même track réapparaît quand le tracker perd puis
      retrouve la personne. Mesuré sur MANAR CITY : 54 répétitions pour 658
      entrées, écart médian 10,7 s, 50 des 54 à moins de 60 s. Ce sont des
      re-détections d'une seule personne, pas de secondes entrées — les compter
      séparément gonflait le total de 8,2 %. Le jour dans la clé les fusionne.
    - D'UN JOUR À L'AUTRE, le numéro est réattribué : le compteur du tracker
      repart bas à chaque redémarrage du boîtier, et un identifiant est réapparu
      jusqu'à 90 h plus tard. Le jour dans la clé les sépare, là où un track_id
      seul les aurait fusionnés à tort (-8,4 % sur l'historique).

    Corollaire utile : un lot renvoyé reproduit exactement les mêmes clés, il ne
    peut donc jamais gonfler un total.

    Un événement sans track_id ne peut pas être dédoublonné : il garde une clé
    qui lui est propre, pour être compté une fois plutôt que perdu.

    Le ts retenu est le plus ancien vu, afin que la personne soit rattachée à
    l'heure où elle est apparue et non à sa dernière re-détection.
    """
    first = {}
    for index, e in enumerate(events):
        if e["event_type"] != event_type:
            continue
        track_id = e["track_id"]
        key = (track_id, _local_day(e["ts"])) if track_id is not None else ("?", index)
        if key not in first or e["ts"] < first[key]:
            first[key] = e["ts"]
    return first


# ----------------------------------------------------------------------- KPIs

def compute_kpis(events, nb_jours: int) -> dict:
    # Les deux indicateurs comptent des personnes distinctes, jamais des lignes :
    # une re-détection ne crée ni un client ni une PEC de plus.
    clients = len(_unique_tracks(events, ENTRY_TYPE))
    pec_count = len(_unique_tracks(events, PEC_TYPE))

    return {
        "clients_entres": clients,
        "clients_par_jour": round(clients / nb_jours, 1) if nb_jours else None,
        "pec_count": pec_count,
        "taux_pec": round(pec_count / clients * 100, 1) if clients else None,
        "evenements": len(events),
    }


# -------------------------------------------------- KPI ventes & potentiel
# Spécification : CRK_Dashboard_Sales_Potential_KPIs.pdf (WiseVision AI).
#
#   V = visiteurs (Jetson)          A = visiteurs pris en charge (Jetson)
#   T = tickets (caisse)            R = chiffre d'affaires (caisse)
#
#   1. Conversion Rate (%)          = T / V × 100
#   2. Average Basket (TND)         = R / T
#   3. Prise en Charge Rate (%)     = A / V × 100
#   4. Sales Potential (TND)        = V × CR_target × AB_reference
#   5. Opportunity Gap (TND)        = max(Sales Potential − R, 0)
#   6. Opportunity Capture Rate (%) = R / Sales Potential × 100
#
# Les cas indéfinis de la spec (§7) renvoient None, jamais 0 : V=0 pour la
# conversion, T=0 pour le panier, potentiel=0 pour la captation.

# Repères de performance fournis par CRK. Ce ne sont PAS des valeurs simulées :
# ce sont des paramètres métier, réglables par variable d'environnement sans
# toucher au code. Ils vivent ici, à côté de la formule qui les consomme, et non
# dans pos.py — pos.py est le fichier provisoire qui disparaîtra avec la
# simulation, ces repères doivent lui survivre.
#
# CR_target est saisi en POURCENTAGE et converti en décimal au calcul, comme
# l'exige la spec (« 30 % = 0.30 »).
#
# La spec (§3) prévoit qu'ils deviennent plus tard dynamiques — par magasin, jour
# de semaine ou saison. C'est le seul endroit à faire évoluer pour cela.
CR_TARGET_PCT = float(os.environ.get("CRK_CR_TARGET_PCT", "20"))
AB_REFERENCE = float(os.environ.get("CRK_AB_REFERENCE", "290"))


def parse_objectif(value) -> float:
    """Objectif de conversion en %, borné à [0, 100]. None => défaut.

    Le dashboard laisse la direction CRK déplacer cet objectif à la volée : ce
    n'est pas une mesure mais une hypothèse de travail, et voir le potentiel
    bouger avec elle est justement l'intérêt. CRK_CR_TARGET_PCT reste le défaut
    pour tout appel qui ne précise rien (comparaison, rapports).
    """
    if value is None:
        return CR_TARGET_PCT
    try:
        pct = float(value)
    except (TypeError, ValueError):
        raise BadRequest("objectif doit être un nombre entre 0 et 100")
    if not 0 <= pct <= 100:
        raise BadRequest("objectif doit être compris entre 0 et 100")
    return pct


def _potentiel(visiteurs: int, cr_target_pct: float) -> float:
    """Sales Potential = V x CR_target x AB_reference (spec §3).

    Une seule définition, utilisée pour la période comme pour chaque tranche
    horaire : le total horaire somme donc exactement au potentiel de la période.
    """
    return visiteurs * (cr_target_pct / 100) * AB_REFERENCE


def compute_ventes(store_id: str, du: str, au: str, visiteurs: int, pec: int,
                   visiteurs_par_jour: dict | None = None,
                   visiteurs_par_heure: dict | None = None,
                   hours: list | None = None,
                   cr_target_pct: float | None = None) -> dict:
    """Les 6 indicateurs de la spec, plus leur ventilation par tranche horaire."""
    cible = CR_TARGET_PCT if cr_target_pct is None else cr_target_pct
    caisse = pos.fetch_pos_data(
        store_id, du, au, visiteurs, visiteurs_par_jour, visiteurs_par_heure
    )
    tickets = caisse["tickets"]
    revenue = caisse["revenue"]
    potentiel = _potentiel(visiteurs, cible)

    return {
        # Potentiel / manque à gagner / captation, heure par heure.
        "parHeure": _ventes_par_heure(
            caisse["par_heure"], visiteurs_par_heure or {}, hours or [], cible
        ),
        # provenance : le dashboard affiche un bandeau tant que c'est simulé
        "simule": caisse["simule"],
        "source": caisse["source"],
        # jours que la caisse n'a pas pu fournir : à signaler plutôt qu'à
        # laisser passer pour un chiffre d'affaires nul
        "joursManquants": caisse["jours_manquants"],
        # repères utilisés, renvoyés pour que le calcul soit lisible côté UI
        "cr_target_pct": cible,
        "ab_reference": AB_REFERENCE,
        # valeurs brutes
        "visiteurs": visiteurs,
        "pris_en_charge": pec,
        "tickets": tickets,
        "revenue": round(revenue, 2),
        # 1. conversion
        "conversion_rate": round(tickets / visiteurs * 100, 1) if visiteurs else None,
        # 2. panier moyen — indéfini si aucun ticket
        "average_basket": round(revenue / tickets, 2) if tickets else None,
        # 3. taux de prise en charge
        "pec_rate": round(pec / visiteurs * 100, 1) if visiteurs else None,
        # 4. potentiel
        "sales_potential": round(potentiel, 2),
        # 5. manque à gagner
        "opportunity_gap": round(max(potentiel - revenue, 0), 2),
        # 6. taux de captation — indéfini si le potentiel est nul
        "opportunity_capture_rate": round(revenue / potentiel * 100, 1) if potentiel else None,
    }


def _ventes_par_heure(caisse_par_heure: dict, visiteurs_par_heure: dict, hours: list,
                      cr_target_pct: float) -> list:
    """Une ligne par tranche horaire de la fenêtre affichée.

    Le potentiel d'une heure se calcule sur les visiteurs de CETTE heure, avec la
    même formule que la période. Le CA vient de la caisse, ventilé par l'heure de
    l'entête.

    Les deux mesures ne viennent pas de la même source : une heure peut avoir des
    ventes sans visiteur compté (caméra en défaut) ou l'inverse. On ne corrige
    rien — c'est justement ce qu'il faut voir.
    """
    # visiteurs_par_heure est {jour: {heure: nb}} : on cumule sur la période
    cumul_visiteurs = {}
    for par_heure in visiteurs_par_heure.values():
        for h, n in par_heure.items():
            cumul_visiteurs[h] = cumul_visiteurs.get(h, 0) + n

    lignes = []
    for h in hours:
        v = cumul_visiteurs.get(h, 0)
        vente = caisse_par_heure.get(h, {"tickets": 0, "revenue": 0.0})
        ca = vente["revenue"]
        pot = _potentiel(v, cr_target_pct)
        lignes.append({
            "h": f"{h:02d}h",
            "visiteurs": v,
            "tickets": vente["tickets"],
            "revenue": round(ca, 2),
            "potentiel": round(pot, 2),
            "manque": round(max(pot - ca, 0), 2),
            # None plutôt que 0 : sans visiteur il n'y a pas de potentiel, donc
            # pas de taux de captation à afficher.
            "captation": round(ca / pot * 100, 1) if pot else None,
            # Taux de conversion de la tranche : tickets / visiteurs. Même règle,
            # None sans visiteur — 0 % se lirait comme « personne n'a acheté »
            # alors que personne n'est entré.
            "conversion": round(vente["tickets"] / v * 100, 1) if v else None,
        })
    return lignes


# --------------------------------------------------------------- distributions

def _hourly(events, hours):
    entry_counts = {h: 0 for h in hours}
    pec_counts = {h: 0 for h in hours}

    # On répartit les MÊMES ensembles dédoublonnés que compute_kpis, sinon les
    # barres ne sommeraient pas aux KPI de la période. Chaque personne tombe dans
    # sa vraie heure : la fenêtre a été calculée pour les contenir toutes, donc
    # aucune clé ne peut manquer.
    for ts in _unique_tracks(events, ENTRY_TYPE).values():
        entry_counts[_local_hour(ts)] += 1

    for ts in _unique_tracks(events, PEC_TYPE).values():
        pec_counts[_local_hour(ts)] += 1

    heure_de_pointe = [
        {"h": f"{h:02d}h", "clients": entry_counts[h]} for h in hours
    ]
    pec_par_heure = [{"h": f"{h:02d}h", "pec": pec_counts[h]} for h in hours]
    taux_par_heure = [
        {
            "h": f"{h:02d}h",
            "taux": round(pec_counts[h] / entry_counts[h] * 100, 1)
            if entry_counts[h]
            else None,
        }
        for h in hours
    ]
    return heure_de_pointe, pec_par_heure, taux_par_heure


def _bucket_by_day(events, day_start_ts: float, nb_jours: int):
    """events grouped into local-day buckets, index 0 = first day of the range."""
    buckets = [[] for _ in range(nb_jours)]
    for e in events:
        offset = int((e["ts"] - day_start_ts) // 86400)
        if 0 <= offset < nb_jours:
            buckets[offset].append(e)
    return buckets


def _heatmap(day_buckets, first_day: date, hours):
    """Comptage des ENTRY par heure × jour de semaine, cumulé sur la période."""
    base = hours[0]
    matrix = [[0] * 7 for _ in hours]
    for offset, events in enumerate(day_buckets):
        weekday = (first_day + timedelta(days=offset)).weekday()
        # Personnes distinctes, comme partout ailleurs : la heatmap cumule donc
        # exactement les mêmes clients que la courbe horaire.
        for ts in _unique_tracks(events, ENTRY_TYPE).values():
            matrix[_local_hour(ts) - base][weekday] += 1

    return {
        "heures": [f"{h:02d}h" for h in hours],
        "jours": JOUR_LABELS,
        "data": matrix,
        "max": max((v for row in matrix for v in row), default=0),
    }


# ------------------------------------------------------------------- responses

def build_range_response(store_id: str, du: str, au: str, objectif=None) -> dict:
    """Everything the "Vue d'ensemble" page draws, for one store over one range.

    `objectif` est l'objectif de conversion en % choisi dans l'interface. Il ne
    change QUE le potentiel de vente et ce qui en dérive (manque à gagner, taux
    de captation) — jamais une mesure.
    """
    d1, d2, nb_jours = parse_range(du, au)
    cible = parse_objectif(objectif)

    start_ts, _ = _day_bounds(d1)
    _, end_ts = _day_bounds(d2)
    events = db.get_events_in_range(store_id, start_ts, end_ts)

    # Preceding window of the same length, for the "vs période préc." deltas.
    prev_first = d1 - timedelta(days=nb_jours)
    prev_start_ts, _ = _day_bounds(prev_first)
    _, prev_end_ts = _day_bounds(d1 - timedelta(days=1))
    prev_events = db.get_events_in_range(store_id, prev_start_ts, prev_end_ts)

    # None plutôt que des zéros quand la fenêtre précédente est vide : le
    # dashboard masque alors l'écart au lieu d'annoncer un bond de +100 %.
    kpis_prec = compute_kpis(prev_events, nb_jours) if prev_events else None
    ventes_prec = (
        compute_ventes(
            store_id,
            _iso(prev_first),
            _iso(d1 - timedelta(days=1)),
            kpis_prec["clients_entres"],
            kpis_prec["pec_count"],
            # Même objectif que la période courante, sinon l'écart « vs période
            # précédente » comparerait deux hypothèses différentes.
            cr_target_pct=cible,
        )
        if kpis_prec
        else None
    )

    hours = _hour_window(events)
    heure_de_pointe, pec_par_heure, taux_par_heure = _hourly(events, hours)
    day_buckets = _bucket_by_day(events, start_ts, nb_jours)

    kpis = compute_kpis(events, nb_jours)

    # Visiteurs par jour, et par (jour, heure). Le détail horaire sert à deux
    # choses : calculer le potentiel de CHAQUE tranche, et garder la simulation
    # cohérente avec la fréquentation réellement mesurée.
    visiteurs_jour = {}
    visiteurs_heure = {}
    for i, bucket in enumerate(day_buckets):
        jour = _iso(d1 + timedelta(days=i))
        visiteurs_jour[jour] = compute_kpis(bucket, 1)["clients_entres"]
        par_heure = {}
        for ts in _unique_tracks(bucket, ENTRY_TYPE).values():
            h = _local_hour(ts)
            par_heure[h] = par_heure.get(h, 0) + 1
        visiteurs_heure[jour] = par_heure

    ventes = compute_ventes(
        store_id, _iso(d1), _iso(d2), kpis["clients_entres"], kpis["pec_count"],
        visiteurs_jour, visiteurs_heure, hours, cible,
    )

    evolution_jours = []
    for offset, day_events in enumerate(day_buckets):
        d = d1 + timedelta(days=offset)
        k = compute_kpis(day_events, 1)
        evolution_jours.append(
            {
                "date": _iso(d),
                "label": _short_label(d),
                "jour": JOUR_LABELS[d.weekday()],
                "clients": k["clients_entres"],
                "pec": k["pec_count"],
                "taux": k["taux_pec"],
            }
        )

    return {
        "magasin": store_id,
        "periode": {"du": _iso(d1), "au": _iso(d2), "nbJours": nb_jours},
        "kpis": compute_kpis(events, nb_jours),
        "ventes": ventes,
        # None rather than zeroed KPIs when the preceding window is empty, so the
        # UI can hide the delta badge instead of claiming a +100% jump.
        "kpisPrecedent": kpis_prec,
        "ventesPrecedent": ventes_prec,
        "heureDePointe": heure_de_pointe,
        "pecParHeure": pec_par_heure,
        "tauxParHeure": taux_par_heure,
        "evolutionJours": evolution_jours,
        "heatmap": _heatmap(day_buckets, d1, hours),
    }


def build_comparison_response(du: str, au: str) -> dict:
    """One row per store over the range, for the "Comparaison" page."""
    d1, d2, nb_jours = parse_range(du, au)
    start_ts, _ = _day_bounds(d1)
    _, end_ts = _day_bounds(d2)

    magasins = []
    daily_taux = {}
    for name in db.STORE_NAMES:
        events = db.get_events_in_range(name, start_ts, end_ts)
        k = compute_kpis(events, nb_jours)
        v = compute_ventes(name, _iso(d1), _iso(d2), k["clients_entres"], k["pec_count"])
        magasins.append(
            {
                "nom": name,
                "aDonnees": len(events) > 0,
                **k,
                "revenue": v["revenue"],
                "sales_potential": v["sales_potential"],
                "opportunity_gap": v["opportunity_gap"],
                "opportunity_capture_rate": v["opportunity_capture_rate"],
                "ventesSimulees": v["simule"],
            }
        )
        buckets = _bucket_by_day(events, start_ts, nb_jours)
        daily_taux[name] = [compute_kpis(b, 1)["taux_pec"] for b in buckets]

    jours = [d1 + timedelta(days=i) for i in range(nb_jours)]
    evolution_jours = [
        {
            "label": _short_label(d),
            "date": _iso(d),
            **{name: daily_taux[name][i] for name in db.STORE_NAMES},
        }
        for i, d in enumerate(jours)
    ]

    return {
        "periode": {"du": _iso(d1), "au": _iso(d2), "nbJours": nb_jours},
        "magasins": magasins,
        "evolutionJours": evolution_jours,
    }


def _series_buckets(periode: str, fin: date):
    """[(label, first_day, last_day)] for the requested granularity."""
    if periode == "jour":
        # 7 jours : la semaine écoulée, `fin` inclus. Au-delà, les étiquettes se
        # chevauchent et la comparaison « même jour la semaine dernière » se perd.
        return [
            (_short_label(d), d, d)
            for d in (fin - timedelta(days=i) for i in range(6, -1, -1))
        ]

    if periode == "semaine":
        monday = fin - timedelta(days=fin.weekday())
        buckets = []
        for w in range(7, -1, -1):
            start = monday - timedelta(days=w * 7)
            buckets.append((_short_label(start), start, min(start + timedelta(days=6), fin)))
        return buckets

    # mois : the 6 calendar months ending with fin's own month
    buckets = []
    for back in range(5, -1, -1):
        month_index = fin.year * 12 + (fin.month - 1) - back
        first = date(month_index // 12, month_index % 12 + 1, 1)
        next_index = month_index + 1
        next_first = date(next_index // 12, next_index % 12 + 1, 1)
        buckets.append(
            (MOIS_LABELS[first.month - 1], first, min(next_first - timedelta(days=1), fin))
        )
    return buckets


def build_series_response(store_id: str, periode: str, fin: str) -> dict:
    """Clients / PEC / taux PEC over time, at day, week or month granularity."""
    if periode not in SERIES_PERIODS:
        raise BadRequest(f"periode must be one of {', '.join(SERIES_PERIODS)}")
    fin_date = _parse_date(fin, "fin")

    buckets = _series_buckets(periode, fin_date)
    span_start, _ = _day_bounds(buckets[0][1])
    _, span_end = _day_bounds(buckets[-1][2])
    events = db.get_events_in_range(store_id, span_start, span_end)

    points = []
    for label, first, last in buckets:
        b_start, _ = _day_bounds(first)
        _, b_end = _day_bounds(last)
        window = [e for e in events if b_start <= e["ts"] < b_end]
        nb_jours = (last - first).days + 1
        k = compute_kpis(window, nb_jours)
        points.append(
            {
                "label": label,
                "du": _iso(first),
                "au": _iso(last),
                "clients": k["clients_entres"],
                "pec": k["pec_count"],
                "taux": k["taux_pec"],
            }
        )

    return {"magasin": store_id, "periode": periode, "fin": _iso(fin_date), "points": points}
