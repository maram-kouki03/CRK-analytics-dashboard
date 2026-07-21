# Agent de rapports hebdomadaires CRK

Génère, pour chaque boutique CRK, un rapport hebdomadaire en français
(constats chiffrés + recommandations actionnables) à partir des KPI du
dashboard, via l'API Gemini.

Le pipeline a deux étapes indépendantes :

```
src/data/mockData.js (getWeekRaw)
        │  node
        ▼
agent/export_data.mjs  ──────►  agent/data/<Magasin>.json   (1 fichier / boutique, 7j + 7j précédents)
                                        │  python
                                        ▼
                                 agent/agent.py  ──► API Gemini (generativelanguage.googleapis.com)
                                        │
                                        ▼
                                 agent/reports/<Magasin>.md  (1 rapport / boutique)
```

## Installation

1. Node.js 18+ (déjà requis par le dashboard) et Python 3.9+ — aucune
   dépendance externe à installer, ni côté Node (réutilise le code du
   dashboard) ni côté Python (bibliothèque standard uniquement).
2. Créer votre fichier d'environnement :
   ```bash
   cp agent/.env.example agent/.env
   ```
3. Renseigner `GEMINI_API_KEY` dans `agent/.env` (clé obtenue sur
   [Google AI Studio](https://aistudio.google.com/apikey)). `GEMINI_MODEL`
   est optionnel (défaut : `gemini-2.5-flash`).

## Usage

```bash
# 1. Exporter les données brutes des 8 magasins (semaine se terminant aujourd'hui)
node agent/export_data.mjs

# ... ou pour une semaine se terminant à une date précise :
node agent/export_data.mjs 2026-07-14

# 2. Générer les rapports (tous les magasins présents dans agent/data/)
python agent/agent.py

# ... ou un seul magasin (nom exact, voir storeNames dans src/data/mockData.js) :
python agent/agent.py --magasin "Tunisia Mall"
```

`agent/agent.py` marque une pause de 5 secondes entre deux appels à l'API
pour rester dans les limites du palier gratuit (free tier) de Gemini.

## Données utilisées

`agent/export_data.mjs` réutilise le générateur déterministe existant du
dashboard (`getWeekRaw` dans `src/data/mockData.js`, qui s'appuie sur
`rawDayStats`) — **ce sont donc toujours des données de démonstration**,
pas des chiffres réels de boutique, tant que la pipeline de vision par
ordinateur n'est pas branchée (voir la section correspondante dans le
[README principal](../README.md)).

Chaque fichier `agent/data/<Magasin>.json` contient : le détail des 7
jours de la semaine analysée et des 7 jours de la semaine précédente
(valeurs numériques brutes : clients, PEC, taux PEC, vendeurs actifs,
temps avant PEC, tickets, panier moyen, taux de transformation,
potentiel de revenu), ainsi que les totaux agrégés des deux semaines.

## Prompt système

Le rôle et les règles de rédaction du rapport (analyste retail senior,
constats chiffrés obligatoires, croisement d'indicateurs, recommandations
actionnables avec enjeu chiffré en DT, interdiction des conseils
génériques, structure markdown imposée) sont définis dans la constante
`SYSTEM_PROMPT` en tête de `agent/agent.py`.

## Prochaine étape : branchement Supabase

Ce pipeline fonctionne aujourd'hui entièrement en local avec des fichiers
JSON/Markdown. Quand la pipeline de vision par ordinateur écrira ses
résultats dans Supabase :

- `agent/export_data.mjs` serait remplacé par une requête Supabase
  (via `@supabase/supabase-js` ou l'API REST/PostgREST) qui reconstituerait
  la même forme de données que `getWeekRaw` (7 jours + semaine précédente),
  au lieu de générer des données de démonstration.
- `agent/agent.py` pourrait écrire les rapports générés dans une table
  Supabase (ou dans Supabase Storage) en plus — ou à la place — des
  fichiers locaux de `agent/reports/`, pour que le dashboard puisse les
  afficher directement.
- L'ensemble pourrait tourner sur un déclencheur planifié (cron) plutôt
  qu'en exécution manuelle, par exemple via une Supabase Edge Function
  ou une tâche planifiée externe qui invoque les deux scripts en séquence.

Aucun changement de structure des fichiers `agent/data/*.json` ne serait
nécessaire côté `agent.py` tant que la forme des données reste identique
à celle produite par `getWeekRaw`.
