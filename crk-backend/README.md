# crk-backend

Service d'ingestion et d'agrégation CRK. Il reçoit les événements des boîtiers
caméra en boutique, les stocke dans SQLite, interroge l'API caisse Joolan, et
sert au [dashboard](../Dashboard) des agrégats déjà calculés.

FastAPI + SQLite (mode WAL). Trois dépendances, versions figées.

> 📘 Explication détaillée de chaque décision de conception :
> [`../DOCUMENT.md`](../DOCUMENT.md).

---

## Démarrer

```bash
pip install -r requirements.txt
cp .env.example .env        # renseigner CRK_API_KEY
py main.py                  # http://localhost:8000
```

> **Port occupé ?** Sur la machine de développement, `127.0.0.1:8080` est déjà
> pris par le listener Oracle (TNSLSNR). Uvicorn peut se lier à `0.0.0.0:8080`
> sans erreur tout en restant inatteignable depuis `localhost` : la liaison la
> plus spécifique gagne. Si les requêtes renvoient un 404 HTML au lieu de JSON,
> changer `CRK_PORT`.

Documentation interactive : <http://localhost:8000/docs>.

Au démarrage, le service affiche trois lignes qui répondent d'avance aux trois
questions de dépannage :

```
[crk] base       : C:\...\crk_analytics.db
[crk] evenements : 7601
[crk] dashboard  : C:\...\Dashboard\dist
```

---

## Flux de données

```
Boîtier caméra (Jetson)                         API caisse Joolan
   │  POST /ingest/batch   (X-API-Key)                ▲  export-tickets.do
   ▼                                                  │
 events (SQLite)  ── store_id, event_type, ts,        │
   │                 track_id, received_at            │
   │                                            pos_hourly (cache)
   │  agrégation à la lecture (analytics.py)  ◄───────┘
   ▼
 GET /api/range · /api/comparison · /api/series  ──►  Dashboard React
```

Rien n'est pré-calculé : chaque requête agrège les événements bruts de la
fenêtre demandée. À ce volume (quelques milliers d'événements par magasin et par
semaine, index sur `(store_id, ts)`) c'est instantané, et changer une règle de
calcul ne demande **aucune reprise de données**.

---

## Les fichiers

| Fichier | Rôle |
|---|---|
| [`main.py`](main.py) | routes FastAPI, authentification, service du dashboard statique |
| [`models.py`](models.py) | contrat d'événements accepté à l'ingestion (Pydantic) |
| [`db.py`](db.py) | schéma, connexions, écriture, lectures brutes, cache caisse |
| [`analytics.py`](analytics.py) | **toutes** les règles de calcul et les réponses agrégées |
| [`pos.py`](pos.py) | aiguillage Joolan / simulation, gestion du cache journalier |
| [`joolan.py`](joolan.py) | client HTTP de l'API caisse |

---

## Endpoints

### Ingestion — `X-API-Key` requis

| Méthode | Route | Corps | Réponse |
|---|---|---|---|
| POST | `/ingest/event` | un événement | `{ok, stored}` |
| POST | `/ingest/batch` | `{ "events": [...] }`, 1000 max | `{received, inserted}` |

L'API **accepte** les trois types que le boîtier a le droit d'envoyer — refuser
un événement renverrait un 422 et ferait perdre **tout le lot**, jusqu'à 1000
événements.

Elle n'en **stocke que deux** :

| Événement | Stocké | Colonnes conservées |
|---|---|---|
| `ENTRY` | oui | `store_id`, `ts`, `track_id` |
| `INTERACTION` | oui | `store_id`, `ts`, `track_id` |
| `HEARTBEAT` | non | servait au KPI « vendeurs actifs », retiré |

`duration_s` et `seller_count` sont acceptés puis ignorés : le boîtier applique
lui-même sa règle de durée minimale avant d'émettre une `INTERACTION`, le
backend compte ce qui arrive et ne rejuge pas.

`inserted` plus petit que `received` est **normal**, pas une erreur : ce sont les
`HEARTBEAT`.

Les anciens types `PEC` / `PEC_START` / `PEC_END` ne sont plus envoyés par le
boîtier, plus stockés, et plus comptés. Les lignes déjà en base sont ignorées ;
[`migrate_db.py`](migrate_db.py) et [`purge_db.py`](purge_db.py) permettent de
nettoyer.

### Lecture — publique (CORS restreint à `CRK_ALLOWED_ORIGINS` en dev)

| Route | Paramètres | Usage |
|---|---|---|
| `GET /api/stores` | — | `[{ nom, aDonnees, dernierEvenementTs }]` |
| `GET /api/range` | `magasin`, `du`, `au`, `objectif?` | page Vue d'ensemble |
| `GET /api/dashboard` | `magasin`, `date`, `objectif?` | raccourci un jour (même forme que `/api/range`) |
| `GET /api/comparison` | `du`, `au` | page Comparaison |
| `GET /api/series` | `magasin`, `periode`, `fin` | séries `jour` / `semaine` / `mois` |
| `GET /api/health` | — | état + total d'événements |
| `GET /api/last-seen` | `magasin` | dernier événement reçu (`seconds_ago`) |

Dates au format ISO `YYYY-MM-DD`. Magasin inconnu → 404, paramètre invalide →
400 avec le motif. Une plage inversée est remise à l'endroit ; au-delà de 400
jours elle est refusée.

Structure complète des réponses :
[`../DOCUMENT.md` §8](../DOCUMENT.md#8-full-reference-of-crk-endpoints).

### Dashboard statique

Tout ce qui ne commence pas par `/api/` ou `/ingest/` est servi depuis
`CRK_DASHBOARD_DIST` (défaut `../Dashboard/dist`) : les fichiers réels sont
renvoyés tels quels, le reste retombe sur `index.html` pour laisser React Router
gérer `/comparaison` et `/rapports`.

Conséquence : **un seul service à déployer**, le dashboard est same-origin, donc
ni CORS ni reverse proxy. Une route `/api/*` inconnue reste un 404 JSON, jamais
la page HTML — sinon une URL mal orthographiée renverrait 200 + du HTML et le
client échouerait au parsing plutôt que de dire ce qui manque. Les remontées
`../` sont bloquées (`is_relative_to`).

Si `dist/` n'existe pas, l'API continue de répondre et l'interface renvoie un 503
qui explique comment construire le dashboard.

---

## Règles de calcul

Fuseau **Africa/Tunis fixé à +01:00** (pas de DST) : `zoneinfo` s'appuie sur la
base IANA que Windows ne fournit pas, et sans DST un jour local fait exactement
86 400 s — ce dont dépend le découpage journalier.

### Comptage : des personnes, jamais des lignes

`ENTRY` et `INTERACTION` portent la même identité : le **`track_id`** de la
personne suivie. Ce numéro n'est unique **ni dans le temps ni dans la journée**,
d'où la clé composite **(`track_id`, jour local)** :

- **Dans la journée**, le même track réapparaît quand le tracker perd puis
  retrouve la personne. Mesuré sur MANAR CITY : 54 répétitions pour 658 entrées,
  écart médian 10,7 s, 50 des 54 à moins de 60 s. Les compter séparément
  gonflait le total de **+8,2 %**.
- **D'un jour à l'autre**, le numéro est réattribué (le compteur repart bas à
  chaque redémarrage du boîtier ; un identifiant est réapparu jusqu'à 90 h plus
  tard). Un `track_id` seul les aurait fusionnés à tort : **−8,4 %**.

Corollaire : un lot renvoyé reproduit exactement les mêmes clés, il ne peut donc
**jamais** gonfler un total. Un événement sans `track_id` garde une clé qui lui
est propre — compté une fois plutôt que perdu.

| Indicateur | Règle |
|---|---|
| `clients_entres` | `(track_id, jour)` distincts sur les `ENTRY` |
| `pec_count` | `(track_id, jour)` distincts sur les `INTERACTION` |
| `taux_pec` | `pec_count / clients_entres × 100`, `null` si aucun client |
| `clients_par_jour` | `clients_entres` / nombre de jours de la période |

### Plage horaire déduite des données

`CRK_OPEN_HOUR` / `CRK_CLOSE_HOUR` (9h-20h par défaut, 10h-22h en production) ne
sont qu'un **minimum d'affichage**, pour garder une échelle stable d'une période
à l'autre. La fenêtre s'élargit à toute heure réellement observée : une
interaction à 21h30 apparaît en 21h. **Aucun événement n'est replié** sur une
heure limite — un total horaire est donc toujours égal au KPI correspondant.

Corollaire assumé : un événement isolé à 3 h du matin étire l'axe jusqu'à 3 h.
C'est voulu, l'anomalie doit se voir plutôt que se diluer dans la première
tranche.

### KPI ventes & potentiel

Spécification : `CRK_Dashboard_Sales_Potential_KPIs.pdf`. Renvoyés sous la clé
`ventes` de `/api/range`, avec leur ventilation horaire dans `ventes.parHeure`.

V = visiteurs, A = pris en charge (boîtier) ; T = tickets, R = chiffre
d'affaires (caisse Joolan).

| Indicateur | Formule | `null` si |
|---|---|---|
| `conversion_rate` | T / V × 100 | V = 0 |
| `average_basket` | R / T | T = 0 |
| `pec_rate` | A / V × 100 | V = 0 |
| `sales_potential` | V × `CRK_CR_TARGET_PCT`/100 × `CRK_AB_REFERENCE` | — |
| `opportunity_gap` | max(potentiel − R, 0) | — |
| `opportunity_capture_rate` | R / potentiel × 100 | potentiel = 0 |

Repères par défaut : objectif de conversion **20 %**, panier de référence
**290 DT**, tous deux réglables par variable d'environnement. Le paramètre
`objectif` de `/api/range` permet à l'interface de déplacer l'objectif à la
volée — il ne change **que** le potentiel et ce qui en dérive, jamais une mesure.

Le potentiel utilisant la même formule pour la période et pour chaque tranche
horaire, la somme des potentiels horaires **est** le potentiel de la période.

> ⚠️ La spec définit A comme le nombre de **visiteurs** pris en charge, alors que
> `pec_count` compte les **interactions distinctes**. Un visiteur abordé deux
> fois compte donc 2. C'est une piste sérieuse pour expliquer le taux PEC > 100 %.

**Un indicateur non mesurable vaut `null`, jamais 0.** Le dashboard l'affiche
« — ». C'est la seule façon de distinguer « personne n'est entré » de « la caméra
n'a rien envoyé ».

### Horodatage

Les boîtiers envoient de préférence du temps Unix, respecté tel quel — un lot
tamponné puis vidé en retard garde les instants réels. Un boîtier qui envoie des
secondes depuis son démarrage est détecté (valeurs très inférieures à une époque
plausible) et son lot est recalé sur l'instant de réception en conservant les
écarts internes. C'est une **reconstruction, pas une mesure** : voir `db.py`.

Le recalage est fait **avant** le filtrage des types, car l'ancre est
« l'événement le plus récent du lot » et un `HEARTBEAT` — jeté ensuite — peut
très bien être le plus récent.

---

## Base de données

SQLite en mode **WAL**, fichier désigné par `CRK_DB_PATH`. Deux tables :

- **`events`** — six colonnes, les faits bruts. Index `(store_id, ts)`, qui
  correspond exactement à la question du dashboard : « ce magasin, entre ces
  deux dates ».
- **`pos_hourly`** — cache des données de caisse, une ligne par
  (magasin, date, heure). L'API Joolan ne répond que **par date** : sans ce
  cache, afficher 30 jours déclencherait 30 requêtes HTTP à **chaque**
  rafraîchissement.

Le mode WAL permet de lire pendant qu'on écrit : `watch_events.py` ne perturbe
pas le service, et le backend peut lire une base qu'un autre processus alimente.

**Sauvegarde :** copier `.db`, `.db-wal` et `.db-shm` ensemble, ou arrêter le
service d'abord.

Une base au **schéma ancien** (colonnes `pec_id`, `duration_s`, `seller_count`,
`zone_id`) reste lisible : le service le signale au démarrage mais ne migre
jamais tout seul — une opération destructrice ne doit pas être un effet de bord.

Pourquoi SQLite et pas PostgreSQL, et quand il faudra changer :
[`../DOCUMENT.md` §4](../DOCUMENT.md#4-layer-3--the-database-yes-there-is-one).

---

## API caisse Joolan

Endpoint utilisé : `GET https://{domaine}/api/v2/export-tickets.do?enseigne=…&api-key=…&Date=AAAA-MM-JJ`

Trois propriétés de cette API dictent toute la conception :

1. **Un seul jour par appel** — pas de plage de dates. D'où le cache
   `pos_hourly`.
2. **Un appel renvoie tous les magasins** — le champ `Magasin` permet de
   ventiler. On appelle donc une fois **par date**, jamais par magasin : 7
   requêtes pour la semaine des 8 boutiques, pas 56.
3. **L'heure est bien renvoyée** — le swagger ne documente aucun champ de
   réponse, mais l'appel réel montre un champ `Heure` (`"20:28:22"`) sur 332
   entêtes sur 332. Le CA **par heure** est donc mesuré, pas reconstitué.

Tant que `CRK_JOOLAN_DOMAIN` / `_ENSEIGNE` / `_API_KEY` ne sont pas renseignés,
[`pos.py`](pos.py) simule tickets et CA et remonte `simule: true` — le dashboard
affiche alors un bandeau orange.

Un jour que Joolan n'a pas pu fournir n'est **jamais** mis en cache comme un
zéro : il part dans `joursManquants`, et le dashboard explique que le CA de la
période est sous-évalué.

Détail complet et points restant à confirmer avec CRK :
[`JOOLAN_INTEGRATION.md`](JOOLAN_INTEGRATION.md).

---

## Outils

Tous documentés par un docstring en tête de fichier, et tous précisent s'ils
écrivent ou non.

```bash
# --- lecture seule, sûrs contre le service en cours ---
py watch_events.py                    # suivre les événements en direct
py watch_events.py --since 30         # les 30 derniers, puis suivre
py watch_events.py --store "Manar city" --once

py test_joolan.py                     # diagnostiquer la connexion caisse
py test_joolan.py --date 2026-08-20   # sur une date précise
py inspect_joolan.py                  # voir les champs réellement renvoyés

py diagnostic.py                      # quelle base le service utilise-t-il ?
py retrouver_base.py                  # retrouver une base perdue sur les disques

# --- écrivent : ARRÊTER LE SERVICE d'abord ---
py migrate_db.py --dry-run            # ancien schéma -> schéma minimal
py migrate_db.py                      # sauvegarde puis migre

py purge_db.py --depuis 2026-08-24 --dry-run   # supprimer l'historique ancien
py restaurer.py --source "<chemin>"            # fusionner une base récupérée
```

Les trois scripts destructeurs partagent les mêmes garde-fous : `--dry-run`,
sauvegarde horodatée automatique, annonce du coût avant d'écrire, et
vérification que le service est arrêté.

---

## Configuration

Toutes les variables sont documentées dans [`.env.example`](.env.example) et
récapitulées dans
[`../DOCUMENT.md` annexe A](../DOCUMENT.md#appendix-a--all-environment-variables).

Les essentielles :

| Variable | Rôle |
|---|---|
| `CRK_API_KEY` | **obligatoire** — secret partagé avec les boîtiers Jetson |
| `CRK_DB_PATH` | chemin de la base SQLite |
| `CRK_PORT` | port d'écoute (éviter 8080) |
| `CRK_JOOLAN_DOMAIN` / `_ENSEIGNE` / `_API_KEY` | l'interrupteur simulation ↔ réel |
| `CRK_JOOLAN_MAGASINS` | correspondance nom CRK → code `Magasin` Joolan |
| `CRK_CR_TARGET_PCT` / `CRK_AB_REFERENCE` | repères métier du potentiel de vente |

⚠️ **`CRK_API_KEY` doit changer des deux côtés à la fois** (serveur *et* chaque
boîtier). Ne changer que le serveur arrête **silencieusement** l'ingestion : les
boîtiers reçoivent 401 et les données de la période sont perdues. Vérifier avec
`/api/last-seen`.

---

## Limites connues

- **Magasins** : la liste fait autorité dans `STORE_NAMES` ([`db.py`](db.py)) et
  alimente le sélecteur du dashboard. Les noms sont résolus sans tenir compte de
  la casse (les boîtiers envoient `Manar city`, la liste dit `MANAR CITY`).
- **Codes `Magasin` Joolan** : seul **MANAR CITY** est confirmé. Les 7 autres
  boutiques affichent 0 ticket et 0 DT tant que leur code n'est pas ajouté à
  `CRK_JOOLAN_MAGASINS`.
- **Nature des tickets** : seules les entêtes de nature `VENTE` sont comptées.
  Le traitement des retours et avoirs reste à confirmer avec CRK — cela
  changerait R, le panier moyen et le taux de captation.
- **Qualité des mesures** : sur les données actuelles de MANAR CITY, le taux PEC
  dépasse 100 % (plus d'interactions comptées que de clients entrés). C'est un
  problème de pipeline vision, pas d'agrégation ; l'API renvoie la valeur mesurée
  sans la corriger ni la borner.
- **Pas de tests automatisés.** `_unique_tracks`, `_with_wall_clock` et les six
  formules KPI sont des fonctions pures, testables sans serveur ni base : c'est
  le meilleur retour sur investissement disponible.
- **Tables mortes** : `store_config` et `pos_daily` sont des vestiges d'anciennes
  versions. Aucun code ne les lit ; elles peuvent être supprimées.
