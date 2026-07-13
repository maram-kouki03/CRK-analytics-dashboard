# CRK — Plateforme d'Analyse Retail

Tableau de bord d'analyse des performances des points de vente **CRK Maroquinier** (8 magasins en Tunisie).
La plateforme visualise les indicateurs issus de la pipeline de vision par ordinateur :
clients entrés, prises en charge (PEC), taux PEC, vendeurs actifs et temps moyen avant PEC.

![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-5-646CFF?logo=vite&logoColor=white)
![Recharts](https://img.shields.io/badge/Recharts-2-96402e)

---

## 📸 Aperçu

La plateforme contient **deux pages** :

| Page | URL | Contenu |
|---|---|---|
| **Vue d'ensemble** | `/` | KPI du jour + 4 visualisations pour un magasin et une date donnés |
| **Comparaison** | `/comparaison` | Classement et comparaison des 8 magasins sur 7 jours |

### Vue d'ensemble
- 5 cartes KPI avec variation vs la veille (clients entrés, nombre de PEC, taux PEC, vendeurs actifs, temps moyen avant PEC)
- Courbe d'affluence par heure (heure de pointe)
- Taux PEC par heure
- Évolution hebdomadaire du taux PEC (cette semaine vs semaine dernière)
- Heatmap de présence clients (heure × jour)
- **Sélecteur de date** (calendrier, dates futures bloquées) et **sélecteur de magasin** (les 8 points de vente)

### Comparaison
- Cartes "meilleur magasin" par indicateur
- Tableau de performances des 8 magasins
- Graphes comparatifs (taux PEC, clients entrés, temps moyen avant PEC)
- Évolution hebdomadaire multi-magasins
- Conclusion générée automatiquement à partir des données

### Les 8 points de vente
Mall of Sousse · Tunisia Mall · Mall of Sfax · Sfax 1 · La Marsa · Azur City · MANAR CITY · Menzah 5

---

## 🚀 Accéder au projet et le lancer

### Prérequis
- [Node.js](https://nodejs.org/) version 18 ou plus (vérifier avec `node -v`)
- npm (installé automatiquement avec Node.js)

### Installation

```bash
# 1. Cloner le dépôt (ou télécharger et décompresser le zip)
git clone https://github.com/<votre-compte>/crk-dashboard.git
cd crk-dashboard

# 2. Installer les dépendances
npm install

# 3. Lancer le serveur de développement
npm run dev
```

Puis ouvrir **http://localhost:5173** dans le navigateur.

### Construire pour la production

```bash
npm run build      # génère le dossier dist/
npm run preview    # tester la version de production en local
```

Le dossier `dist/` généré peut être déployé sur n'importe quel hébergeur statique
(Vercel, Netlify, GitHub Pages, ou un serveur nginx/Apache).

---

## 📁 Structure du projet

```
crk-dashboard/
├── index.html                    # Point d'entrée HTML (fonts, titre)
├── package.json                  # Dépendances et scripts
├── vite.config.js                # Configuration Vite
└── src/
    ├── main.jsx                  # Bootstrap React
    ├── App.jsx                   # Routing + état du sidebar
    ├── index.css                 # Tous les styles (palette CRK)
    ├── assets/
    │   └── logo-crk.png          # Logo CRK (remplaçable)
    ├── components/
    │   ├── Sidebar.jsx           # Menu latéral rétractable
    │   ├── Topbar.jsx            # Barre du haut (sélecteurs date + magasin)
    │   └── Calendar.jsx          # Calendrier custom (sans librairie)
    ├── pages/
    │   ├── Dashboard.jsx         # Page vue d'ensemble
    │   └── Comparaison.jsx       # Page comparaison des 8 magasins
    └── data/
        └── mockData.js           # ⚠️ Données de démonstration
```

---

## 📊 Données : mode démonstration

**Important : les chiffres affichés sont des données de démonstration générées, pas des données réelles.**

Tout est centralisé dans `src/data/mockData.js` :

- Chaque magasin a un **profil** (nombre moyen de clients, taux PEC, etc.) dans l'objet `profiles`
- Les données sont générées de façon **déterministe** par combinaison magasin + date :
  la même sélection redonne toujours les mêmes chiffres
- Les variations "vs hier" sont réellement calculées en comparant avec les données générées de la veille
- Les dates futures ne sont pas sélectionnables dans le calendrier

### Brancher les données réelles

Quand l'API de la pipeline sera disponible, remplacer dans `src/pages/Dashboard.jsx` :

```js
const data = useMemo(
  () => getDashboardData(selectedStore, selectedDate),
  [selectedStore, selectedDate]
);
```

par un appel API qui retourne un objet de la même forme :

```js
// GET /api/dashboard?magasin=Tunisia%20Mall&date=2026-07-07
{
  kpis: [...],           // 5 cartes KPI
  heureDePointe: [...],  // { h, clients } × 12
  tauxParHeure: [...],   // { h, taux } × 12
  evolutionHebdo: [...], // { jour, cette, derniere } × 6
  heatmapData: [[...]]   // matrice 12 × 7 de valeurs 0 → 1
}
```

Aucun autre fichier n'a besoin d'être modifié.

---

## 🛠️ Technologies

| Librairie | Usage |
|---|---|
| [React 18](https://react.dev/) + [Vite](https://vitejs.dev/) | Framework et build |
| [react-router-dom](https://reactrouter.com/) | Navigation entre les pages |
| [Recharts](https://recharts.org/) | Tous les graphes |
| [lucide-react](https://lucide.dev/) | Icônes |

Le calendrier et la heatmap sont des composants custom sans dépendance supplémentaire.

---

## 🎨 Personnalisation

- **Logo** : remplacer `src/assets/logo-crk.png` (même nom de fichier)
- **Couleurs** : variables CSS en haut de `src/index.css` (`--crk-brick`, `--crk-cream`, ...)
- **Magasins** : liste `storeNames` et profils dans `src/data/mockData.js`
