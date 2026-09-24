# CRK — Dashboard (frontend)

Interface d'analyse des points de vente **CRK Maroquinier**. Toutes les données
affichées viennent de [`crk-backend`](../crk-backend) via HTTP — ce dossier ne
calcule et ne génère aucun chiffre lui-même.

![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)
![Recharts](https://img.shields.io/badge/Recharts-2-96402e)

> 📘 Architecture détaillée, build et déploiement expliqués :
> [`../DOCUMENT.md` §9](../DOCUMENT.md#9-layer-5--the-react-frontend) et
> [§11](../DOCUMENT.md#11-the-build-what-dist-is-for).

---

## Lancer le projet

Le dashboard ne fonctionne pas seul : il lui faut le backend.

```bash
# 1. Terminal A — backend
cd ../crk-backend
pip install -r requirements.txt
py main.py

# 2. Terminal B — frontend
cd Dashboard
npm install
cp .env.example .env      # facultatif, seulement pour la page Rapports
npm run dev
```

Puis ouvrir <http://localhost:5173>.

En dev le client appelle `/api/...` en relatif et `vite.config.js` proxifie vers
`CRK_BACKEND_URL` (par défaut `http://localhost:8080`). Il n'y a donc **aucune URL
de backend codée en dur** dans le code, et pas de problème de CORS.

> ⚠️ Si le backend écoute sur un autre port que 8080 (c'est le cas : la config
> du projet est `CRK_PORT=8000`), définir `CRK_BACKEND_URL=http://localhost:8000`
> dans `Dashboard/.env`. Symptôme sinon : des réponses HTML 404 au lieu de JSON.

Pour viser un backend distant directement depuis le navigateur, renseigner
`VITE_API_URL` dans `.env` — et ajouter l'origine du dashboard à
`CRK_ALLOWED_ORIGINS` côté backend.

### Production

```bash
npm run build      # génère dist/
npm run preview    # test local de la version buildée
```

En production, **c'est crk-backend qui sert `dist/`**, sur son propre port : le
dashboard et l'API sont alors sur la même origine, donc les appels `/api`
relatifs fonctionnent sans proxy, sans CORS et sans `VITE_API_URL` figé au build.
Le **même** `dist/` fonctionne donc sur `localhost`, sur une IP, ou derrière un
nom de domaine — rien à reconstruire pour changer d'adresse.

Rien à configurer : il suffit que `dist/` existe. Voir
[`../deploy/windows/README.md`](../deploy/windows/README.md).

Ne définir `VITE_API_URL` **avant le build** que si le dashboard est hébergé
séparément du backend — auquel cas il faut aussi ajouter son origine à
`CRK_ALLOWED_ORIGINS` côté backend.

> `dist/` est dans `.gitignore` : c'est du code **généré**. Il est reconstruit à
> chaque déploiement par `install.ps1`. Le supprimer localement est sans risque.

---

## Pages

| Page | URL | Endpoints backend |
|---|---|---|
| **Vue d'ensemble** | `/` | `GET /api/range` + 2 × `GET /api/series` |
| **Comparaison** | `/comparaison` | `GET /api/comparison` |
| **Rapports** | `/rapports` | `GET /api/range` + API Gemini |

La période (calendrier du Topbar) est partagée entre Vue d'ensemble et
Comparaison ; elle est passée telle quelle au backend en `du` / `au`.

Le magasin d'ouverture est **le plus récemment actif**, pas le premier de la
liste : sinon le dashboard s'ouvrirait sur une boutique muette depuis des
semaines, et une page vide se lirait comme un bug.

---

## Indicateurs affichés

La Vue d'ensemble est découpée en trois sections, selon la **provenance** des
chiffres — c'est ce qui garde la page lisible malgré le nombre d'indicateurs.

### 1. Fréquentation & prise en charge — mesuré par le boîtier

| Indicateur | Source |
|---|---|
| Clients entrés | `ENTRY` dédoublonnés par (`track_id`, jour) |
| Clients / jour (moy.) | clients entrés ÷ nombre de jours de la période |
| Nombre de PEC | `INTERACTION` dédoublonnés par (`track_id`, jour) |

Le taux PEC n'est plus une carte : il figure dans l'entonnoir, sous le niveau
« Pris en charge » qu'il produit — un taux ne se lit qu'à côté des deux volumes
qu'il relie.

### 2. Ventes & potentiel — croise boîtier et caisse

Les 6 indicateurs de la spec `CRK_Dashboard_Sales_Potential_KPIs.pdf`, présentés
en **cartes** plutôt qu'en tuiles isolées :

- **Entonnoir de conversion** — Visiteurs → Pris en charge → Tickets → CA, avec
  le taux de prise en charge (A/V) et le taux de conversion (T/V) placés sous le
  niveau qu'ils produisent, et le panier moyen (R/T) en pied de carte.
  Le CA n'a pas de barre : comparer des dinars à des personnes sur la même
  échelle ne veut rien dire.
- **Potentiel de vente** — potentiel, CA réalisé et manque à gagner sur une seule
  barre, puisqu'ils forment une addition ; le taux de captation à côté ; et le
  calcul écrit en clair (`V × objectif × panier de référence`), sans quoi le
  chiffre n'est pas exploitable.
- **Quatre graphes horaires** — potentiel, manque à gagner, captation et
  conversion par tranche horaire. C'est là que se voit **à quelle heure** le
  potentiel n'est pas converti.

L'**objectif de conversion** est ajustable depuis l'interface (`ObjectifPicker`).
Ce n'est pas une mesure mais une hypothèse de travail : voir le potentiel bouger
avec elle est justement l'intérêt. Il ne déplace que le potentiel et ce qui en
dérive.

**Deux bandeaux d'avertissement possibles, jamais les deux à la fois :**

| Bandeau | Quand |
|---|---|
| « Données caisse simulées » | `CRK_JOOLAN_*` non renseigné côté backend — tickets et CA sont des valeurs de démonstration |
| « Caisse indisponible sur N jours » | Joolan branché mais des journées manquantes — le CA, le panier moyen et le taux de captation sont **sous-évalués** |

Dans les deux cas, les visiteurs et les prises en charge restent **mesurés** et
ne sont pas concernés.

### 3. Détail par heure et par jour — mesuré par le boîtier

Courbes horaires, séries temporelles (jour / semaine / mois) et heatmap
heure × jour de semaine.

La **plage horaire s'adapte aux données** : si la boutique reçoit du monde à
21h, la colonne 21h apparaît. Aucun événement n'est replié sur une heure limite,
donc un total horaire est toujours égal au KPI de la période.

### Règles d'affichage

Chacune évite une lecture fausse — ce ne sont pas des choix cosmétiques.

| Règle | Raison |
|---|---|
| **`—` jamais `0`** pour un indicateur `null` | distinguer « personne n'est entré » de « rien n'a été mesuré » |
| **Barres, pas d'aire**, pour les tranches horaires | une aire interpolerait entre 10h et 11h et suggérerait une arrivée progressive |
| **Pas de plafond à 100 %** sur l'axe du taux PEC | le taux mesuré dépasse réellement 100 % ; borner l'axe masquerait l'anomalie |
| **`connectNulls={false}`** | une heure sans mesure crée un trou, pas un segment inventé |
| **Infobulle `11h – 12h`** | l'axe affiche « 11h », mais la valeur couvre une tranche, pas un instant |
| **Magasin sans flux marqué** dans le sélecteur | un dashboard vide se lit « pas de flux », pas « bug » |
| **Message d'erreur réel affiché** | `States.jsx` montre le message du backend, jamais un « oups » |

---

## Structure

```
Dashboard/
├── index.html
├── vite.config.js                # proxy /api -> crk-backend (dev seulement)
├── .env.example
├── dist/                         # build de production (gitignoré)
└── src/
    ├── main.jsx / App.jsx        # bootstrap + routing + période partagée
    ├── index.css                 # tous les styles (palette CRK)
    ├── api/
    │   ├── client.js             # ⭐ SEULE porte d'entrée des données
    │   └── useApi.js             # hook chargement/erreur + useStores()
    ├── lib/format.js             # formatage fr-FR, « — » pour null, deltas
    ├── components/
    │   ├── Sidebar.jsx  Topbar.jsx  Calendar.jsx
    │   ├── SalesPotential.jsx    # entonnoir + potentiel + bandeaux
    │   └── States.jsx            # chargement / erreur / aucune donnée
    ├── pages/
    │   └── Dashboard.jsx  Comparaison.jsx  Rapports.jsx
    ├── data/
    │   └── storeColors.js        # palette des courbes
    └── report/generateReport.js  # payload backend -> Gemini -> markdown -> PDF
```

**Règle d'or : `src/api/client.js` est le seul fichier qui appelle `fetch()`.**
Aucun composant ne parle au backend directement, et aucun générateur de données
local n'existe. Changer d'URL de backend touche un fichier ; la gestion d'erreur
est unique et parlante.

Pour brancher un nouvel indicateur : l'ajouter au backend, puis à `KPI_DEFS` dans
[`src/pages/Dashboard.jsx`](src/pages/Dashboard.jsx). Aucun autre fichier à
toucher.

---

## Page Rapports (IA)

Le navigateur envoie les **vraies données** de `/api/range` à l'API Gemini, avec
un prompt système strict, et reçoit un rapport en markdown qu'il convertit en
PDF stylé CRK.

```
VITE_GEMINI_API_KEY=...            # clé gratuite : https://aistudio.google.com
VITE_GEMINI_MODEL=gemini-3.5-flash # optionnel
```

Sans clé, la page affiche une erreur explicite au lieu de générer.

Trois garde-fous côté code : réessai **sélectif** (503 et 429 seulement, jamais
une erreur permanente), rejet d'une réponse tronquée (`MAX_TOKENS`), et
**vérification que la structure demandée est bien présente** avant d'afficher.
Le format exact imposé par le prompt devient ainsi un test automatique.

L'historique des rapports est conservé dans `localStorage` (clé `crk-rapports`).

> ⚠️ Toute variable `VITE_*` est **incluse dans le bundle JavaScript** et donc
> visible par le navigateur. Acceptable pour une clé du palier gratuit sur un
> réseau interne ; à déplacer côté backend si le dashboard devient public.

> ⚠️ Le prompt système date d'avant le branchement de Joolan : il affirme encore
> qu'« il n'y a AUCUNE donnée de caisse ». À mettre à jour maintenant que le CA
> est réel — voir
> [`../DOCUMENT.md` §16.3](../DOCUMENT.md#163-identified-technical-debt).

---

## Personnalisation

- **Logo** : remplacer `src/assets/logo-crk.png` (même nom).
- **Couleurs** : variables CSS en haut de `src/index.css` (`--crk-brick`, …).
- **Magasins** : la liste vient de `GET /api/stores`, donc de `STORE_NAMES` dans
  `../crk-backend/db.py` — pas du frontend.
- **Couleurs des courbes par magasin** : `src/data/storeColors.js`.
