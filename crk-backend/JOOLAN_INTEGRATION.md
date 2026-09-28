# Intégration caisse Joolan

**État : branchée et fonctionnelle.** Le backend interroge réellement l'API
Joolan (`caisse.oopos.fr`, enseigne `CRK`) et le dashboard affiche de vraies
données de caisse. Il reste des **correspondances de magasins** et des
**précisions métier** à obtenir de CRK pour que tous les chiffres soient justes.

- Client : [`joolan.py`](joolan.py) — endpoint `/export-tickets.do`
- Aiguillage réel / simulation + cache : [`pos.py`](pos.py)
- Vérification en une commande : [`test_joolan.py`](test_joolan.py)
- Découverte des champs réels : [`inspect_joolan.py`](inspect_joolan.py)
- Spécification : [`../swagger.yaml`](../swagger.yaml) (Joolan API v2)

> 📘 Le raisonnement complet derrière la conception du cache et de l'aiguillage :
> [`../DOCUMENT.md` §6](../DOCUMENT.md#6-the-joolan-pos-api).

---

## 1. Ce qui est en place

```
CRK_JOOLAN_DOMAIN=caisse.oopos.fr
CRK_JOOLAN_ENSEIGNE=CRK
CRK_JOOLAN_API_KEY=<dans .env, jamais commité>
CRK_JOOLAN_MAGASINS={"MANAR CITY":"CRK Manar City"}
CRK_JOOLAN_NATURES=VENTE
```

Vérification mesurée sur la base du dépôt (période 05/08 → 14/08/2026) :

| Magasin | Lignes en cache | Tickets | CA |
|---|---|---|---|
| **MANAR CITY** | 109 | **303** | **74 712,12 DT** |
| Les 7 autres | 10 chacun | 0 | 0 DT |

`source = 'joolan'` sur **100 %** des lignes : aucune simulation, le bandeau
orange ne s'affiche plus.

Les 7 boutiques à zéro ne sont pas des boutiques sans ventes : ce sont les
lignes-sentinelles écrites quand aucun code `Magasin` ne correspond (voir
[§4](#4-ce-que-lapi-impose-et-ce-que-nous-en-avons-fait)). **Leur correspondance
reste à obtenir.**

Panier moyen réel mesuré : **246,57 DT** — à confronter au panier de référence
configuré `CRK_AB_REFERENCE=290`.

---

## 2. Ce qui reste à demander à CRK

### Bloquant pour les 7 autres boutiques

| # | Information | Où elle va | Pourquoi ça compte |
|---|---|---|---|
| 1 | **Codes `Magasin`** des 7 boutiques restantes | `CRK_JOOLAN_MAGASINS` | Nos noms sont `Tunisia Mall`, `Menzah 5`… Joolan utilise `CRK Manar City` pour MANAR CITY, donc probablement `CRK …` pour les autres. Sans la correspondance, chaque boutique affiche **0 ticket et 0 DT**. |

`test_joolan.py` affiche les codes **réellement renvoyés** par Joolan — c'est la
façon la plus rapide d'obtenir la liste sans passer par CRK :

```powershell
.\venv\Scripts\python.exe test_joolan.py --date 2026-08-20
```

### Précisions métier — sans elles, les chiffres restent approximatifs

| # | Question | Impact |
|---|---|---|
| 2 | Valeurs possibles de **`Nature`**, et lesquelles comptent comme une vente | Aujourd'hui seul `VENTE` est compté. S'il existe `RETOUR`, `AVOIR`, `ECHANGE` : faut-il les compter, et en négatif ? Cela change R, le panier moyen et le taux de captation. |
| 3 | **`Total_TTC`** : TTC ou HT ? remises et avoirs inclus ? | Le panier moyen et le CA doivent porter la même définition que celle utilisée par la direction, sinon les chiffres ne se recoupent pas en réunion. |
| 4 | Comment apparaît un **ticket annulé** ? | Il existe un endpoint `/annulation-ticket.do`. L'entête annulé disparaît-il de l'export, ou reste-t-il avec une autre `Nature` ? |
| 5 | Le repère **panier de référence de 290 DT** | Le panier réel mesuré est de 246,57 DT. Le repère de 290 DT est-il une cible à atteindre, ou une valeur à corriger ? Il pilote directement le potentiel de vente et le manque à gagner. |

### Confort, non bloquant

- La permission **`api_query`** : l'endpoint `/query.do` accepte du SQL en
  lecture seule, ce qui permettrait d'agréger une période entière en **un seul
  appel** au lieu d'un par jour. Le cache rend cela facultatif ; c'est un
  privilège large, CRK ne voudra peut-être pas l'accorder.
- Une **enseigne de test** pour valider sans toucher à la production.

---

## 3. Message prêt à envoyer

> Bonjour,
>
> L'accès à l'API Joolan fonctionne : nous récupérons bien les tickets de
> **MANAR CITY** (code `CRK Manar City`) via `export-tickets.do`.
>
> Pour brancher les 7 autres boutiques, il nous manque leurs **codes `Magasin`**
> tels qu'ils apparaissent dans Joolan :
> Tunisia Mall, Mall of Sousse, Mall of Sfax, Sfax 1, La Marsa, Azur City,
> Menzah 5.
>
> Et trois précisions pour que les chiffres soient justes :
>
> 1. les valeurs possibles du champ **`Nature`** et celles qui comptent comme une
>    vente (que faire des retours et avoirs ?) ;
> 2. si **`Total_TTC`** est TTC ou HT, et s'il inclut remises et avoirs ;
> 3. comment apparaît un **ticket annulé** dans l'export.
>
> Enfin, le panier moyen que nous mesurons sur MANAR CITY est de **246,57 DT**,
> alors que le panier de référence utilisé pour le calcul du potentiel de vente
> est de 290 DT. Faut-il conserver 290 DT comme cible, ou l'ajuster ?
>
> Merci.

---

## 4. Ce que l'API impose, et ce que nous en avons fait

**Un seul jour par appel.** `export-tickets.do` prend un paramètre `Date`
obligatoire, pas de plage. Une période de 30 jours demanderait 30 requêtes à
chaque affichage — d'où le cache horaire (table **`pos_hourly`**). Les journées
passées ne sont demandées qu'une fois ; la journée en cours est rafraîchie
puisque des ventes s'y ajoutent encore.

Plus précisément, une journée est redemandée dans trois cas seulement : jamais
lue, lue depuis une autre source (bascule simulation → Joolan), ou **lue avant
la fin de la journée** donc forcément incomplète. Ce dernier cas est le piège :
sans lui, une journée consultée à 14 h restait figée à 14 h pour toujours et une
soirée entière de CA disparaissait en silence.

**Un appel renvoie tous les magasins.** Le champ `Magasin` des entêtes permet de
ventiler. On appelle donc une fois par date, jamais par magasin : la semaine des
8 boutiques coûte **7 requêtes, pas 56**. Et les 8 magasins sont mis en cache
d'un seul coup, ce qui rend la page Comparaison gratuite.

**L'heure EST renvoyée.** ⚠️ Correction d'une hypothèse antérieure : le swagger
ne documente **aucun** champ de réponse (le schéma dit seulement `type: object`)
et son exemple n'en montre que cinq, sans heure. L'appel réel, fait par
[`inspect_joolan.py`](inspect_joolan.py), montre un champ **`Heure`**
(`"20:28:22"`) présent sur **332 entêtes sur 332**.

Conséquence : le chiffre d'affaires **par heure** est *mesuré*, pas reconstitué.
C'est ce qui a permis de passer de `pos_daily` à `pos_hourly` et de tracer le
potentiel, le manque à gagner et la captation heure par heure. Une entête dont
l'heure serait illisible reçoit l'heure conventionnelle `-1` : elle compte dans
le total du jour sans être attribuée à une tranche.

> **Leçon** : une documentation d'API décrit ce que l'éditeur a pris le temps
> d'écrire, pas ce que le serveur renvoie. Avant de concevoir autour d'une
> contrainte supposée, faire un appel réel et regarder.

**Un jour indisponible n'est jamais mis en cache comme un zéro.** Il est renvoyé
dans `joursManquants`, et le dashboard affiche un bandeau expliquant que le CA
de la période est sous-évalué. Un zéro silencieux se lirait comme « aucune
vente ».

**Un magasin sans vente reçoit quand même une ligne à zéro.** Sans elle, le
cache resterait vide pour ce magasin et on rappellerait Joolan à **chaque**
affichage. Elle n'ajoute rien aux totaux et n'apparaît dans aucune tranche
horaire. C'est ce qui explique les 10 lignes des boutiques non mappées.

---

## 5. Procédures

### Ajouter une correspondance de magasin

**1. Obtenir les codes réels**

```powershell
cd crk-backend
.\venv\Scripts\python.exe test_joolan.py --date 2026-08-20
```

**2. Compléter `.env`**

```
CRK_JOOLAN_MAGASINS={"MANAR CITY":"CRK Manar City","Tunisia Mall":"CRK Tunisia Mall"}
```

**3. Purger le cache des jours concernés**, sinon les lignes à zéro déjà
mémorisées resteraient affichées :

```powershell
.\venv\Scripts\python.exe -c "import db; print(db.clear_pos_cache(), 'lignes purgees')"
```

**4. Redémarrer**

```powershell
Stop-ScheduledTask  -TaskName 'CRK Analytics'
Start-ScheduledTask -TaskName 'CRK Analytics'
```

### Revenir de la simulation vers Joolan

Si des journées simulées subsistent en base (héritage d'avant le branchement),
elles resteraient affichées à la place des vraies :

```powershell
.\venv\Scripts\python.exe -c "import db; print(db.clear_pos_cache('simulation'), 'lignes purgees')"
```

Puis redémarrer. Le bandeau orange disparaît, les marqueurs « simulé »
disparaissent, et `/api/range` renvoie `"source": "joolan"`.

### En cas de panne Joolan

Le service **ne s'arrête pas**. Les jours en échec sont journalisés :

```powershell
Get-Content .\logs\crk-*.log | Select-String 'caisse'
# [crk] caisse 2026-08-12 indisponible : HTTP 400 sur ... — invalid api key
```

Ils ne sont pas mis en cache, donc ils seront redemandés au prochain affichage.
Le dashboard signale la sous-évaluation du CA à l'écran. Les visiteurs et les
prises en charge ne sont pas concernés.

---

## 6. Rappel sur la clé Joolan

La spec associe chaque endpoint à une colonne `api_<permission>` de la table
`api_keys`. `export-tickets.do` exige **`api_export_tickets`**.

⚠️ Une clé **valide** mais sans cette permission renvoie `invalid api key` —
message trompeur, car la clé n'est pas invalide, elle est juste non autorisée
pour cet endpoint.

La clé circule dans l'URL (paramètre `api-key`). `joolan.py` la **masque** avant
toute journalisation :

```python
def _masque(url):
    return url.replace(API_KEY, "***") if API_KEY else url
```

Sans ça, la clé de production finirait en clair dans `logs\crk-*.log`.

---

## 7. Piste inverse : pousser l'affluence DANS Joolan

La même API expose `/import-compteurs-passages.do` (permission
`api_compteurs_passages`), qui accepte `Magasin`, `Date`, `Heure`, `Compteur`,
`Entrees`, `Sorties`.

Nous pourrions donc envoyer nos comptages caméra vers Joolan, où la direction
verrait affluence et ventes côte à côte dans l'outil qu'elle utilise déjà. Non
implémenté, mais l'API est là et le sens est le bon : c'est nous qui produisons
la donnée d'affluence.
