# Agent IA — Rapports hebdomadaires CRK

Génère automatiquement un rapport d'analyse hebdomadaire par magasin
(constats chiffrés + recommandations actionnables) à partir des KPI,
via l'API Gemini (free tier).

## Installation (une seule fois)

Aucune librairie à installer : le script n'utilise que la bibliothèque
standard de Python (3.8+). Il suffit de configurer la clé :

```bash
cp agent/.env.example agent/.env
# puis éditer agent/.env et coller ta clé (https://aistudio.google.com)
```

(Sous Windows : copie manuellement le fichier `.env.example`, renomme la
copie en `.env`, et colle ta clé dedans.)

## Utilisation

```bash
# 1. Exporter les KPI de la semaine depuis le mockdata du dashboard
node agent/export_data.mjs               # semaine se terminant aujourd'hui
node agent/export_data.mjs 2026-07-12    # ou à une date précise

# 2. Générer les rapports
python agent/agent.py                        # les 8 magasins
python agent/agent.py --magasin "Tunisia Mall"   # un seul
```

Les rapports sont écrits dans `agent/reports/*.md`.

## Comment ça marche

```
mockData.js ──export_data.mjs──▶ agent/data/*.json ──agent.py──▶ Gemini ──▶ agent/reports/*.md
```

- `export_data.mjs` réutilise le générateur du dashboard : l'agent analyse
  exactement les mêmes chiffres que ceux affichés à l'écran (7 jours de
  détail + agrégats de la semaine + semaine précédente pour comparaison).
- `agent.py` envoie ces données à Gemini avec un prompt d'analyste retail
  strict (chiffres obligatoires, pas de recommandations génériques,
  structure imposée) et sauvegarde le rapport en markdown.

## Branchement futur sur les données réelles

Seul `export_data.mjs` est à remplacer : au lieu de lire le mockdata, il
interrogera la base (Supabase) alimentée par les Jetson et les caisses.
Le format JSON produit reste le même, `agent.py` ne change pas.

## Notes

- ⚠️ Ne jamais commiter `agent/.env` (la clé). Le `.gitignore` l'exclut.
- Free tier Gemini : le script attend 5 s entre deux magasins pour rester
  sous les limites de requêtes/minute.
- Données de démonstration : les recommandations seront à recalibrer sur
  les données réelles une fois la pipeline en production.
