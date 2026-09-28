# Déploiement sur VM Windows Server

Un **seul service** sert le dashboard et l'API sur le même port. Pas de nginx,
pas de CORS, aucune URL de backend à figer dans le frontend.

> 📘 Pourquoi ce choix (et non nginx + uvicorn), et comment fonctionne chaque
> pièce : [`../../DOCUMENT.md` §11-12](../../DOCUMENT.md#12-deployment-the-deploy-folder).

```
VM:8000
 ├─ /            -> Dashboard/dist/index.html
 ├─ /comparaison -> index.html   (routes React, repli SPA)
 ├─ /assets/*    -> fichiers statiques du build
 ├─ /api/*       -> agrégats lus dans SQLite (+ cache caisse Joolan)
 └─ /ingest/*    -> boîtiers caméra (en-tête X-API-Key)

sortant :
 └─ HTTPS -> {CRK_JOOLAN_DOMAIN}/api/v2/export-tickets.do   (données de caisse)
```

⚠️ La VM doit pouvoir **sortir en HTTPS** vers le domaine Joolan. Sans cet accès
sortant, le dashboard bascule en simulation ou affiche des journées manquantes.
Vérifier avec `py test_joolan.py`.

---

## Pré-requis sur la VM

| Outil | Version | Nécessaire pour |
|---|---|---|
| Python | 3.10 ou plus | le backend (`str \| None` exige 3.10) |
| Node.js | 18 ou plus | construire le dashboard — **optionnel** si vous copiez `Dashboard\dist` déjà construit |

Installer Python depuis python.org **en cochant « Add python.exe to PATH »**.

## Installation

Copier le dossier du projet sur la VM (ou `git clone`), puis, dans une console
PowerShell **ouverte en administrateur** :

```powershell
cd C:\chemin\vers\CRK-analytics-dashboard
.\deploy\windows\install.ps1 -Port 8000
```

Le script :

1. vérifie Python et Node ;
2. crée `crk-backend\venv` et installe les dépendances aux versions figées
   (il **recrée** le venv s'il est cassé — cas fréquent après une mise à jour de Python) ;
3. crée `crk-backend\.env` s'il n'existe pas et **génère une clé API aléatoire** ;
4. construit `Dashboard\dist` ;
5. enregistre la tâche planifiée « CRK Analytics » (démarrage automatique, redémarrage
   auto en cas d'échec, compte SYSTEM donc sans session ouverte) ;
6. ouvre le port en entrée dans le pare-feu ;
7. interroge `/api/health` et `/` pour confirmer que tout répond.

La clé API générée est **affichée une seule fois** en fin d'installation. Elle est
stockée dans `crk-backend\.env` — c'est elle qu'il faut configurer sur chaque
boîtier caméra.

### Sans Node sur la VM

Construire ailleurs, copier `Dashboard\dist` sur la VM, puis :

```powershell
.\deploy\windows\install.ps1 -Port 8000 -SkipBuild
```

---

## Exploitation

```powershell
# état
Get-ScheduledTask -TaskName 'CRK Analytics' | Get-ScheduledTaskInfo

# arrêter / démarrer / redémarrer
Stop-ScheduledTask  -TaskName 'CRK Analytics'
Start-ScheduledTask -TaskName 'CRK Analytics'

# journaux (un fichier par jour de démarrage)
Get-Content .\logs\crk-*.log -Tail 50 -Wait

# santé
Invoke-RestMethod http://localhost:8000/api/health

# qui a émis en dernier
Invoke-RestMethod 'http://localhost:8000/api/last-seen?magasin=MANAR%20CITY'

# flux d'événements en direct
.\crk-backend\venv\Scripts\python.exe .\crk-backend\watch_events.py --since 30

# connexion à la caisse Joolan (5 étapes de diagnostic)
.\crk-backend\venv\Scripts\python.exe .\crk-backend\test_joolan.py

# quelle base le service utilise-t-il réellement ?
.\crk-backend\venv\Scripts\python.exe .\crk-backend\diagnostic.py
```

## Mise à jour

```powershell
git pull
.\deploy\windows\install.ps1        # idempotent : .env et base préservés
```

## Sauvegarde

Tout l'état tient dans un fichier : `crk-backend\crk_analytics.db`.

```powershell
Stop-ScheduledTask -TaskName 'CRK Analytics'
Copy-Item .\crk-backend\crk_analytics.db "D:\backup\crk-$(Get-Date -f yyyyMMdd).db"
Start-ScheduledTask -TaskName 'CRK Analytics'
```

La base est en mode WAL : copier `.db`, `.db-wal` et `.db-shm` ensemble, ou
arrêter le service d'abord (comme ci-dessus) pour une copie sûre.

---

## Dépannage

| Symptôme | Cause probable | Vérification |
|---|---|---|
| L'API renvoie du **HTML 404** au lieu de JSON | Un autre service occupe le port. Uvicorn se lie à `0.0.0.0` sans erreur mais la liaison plus spécifique (`127.0.0.1`) d'un autre programme gagne. C'est le cas du listener Oracle sur 8080. | `Get-NetTCPConnection -LocalPort 8000 -State Listen` — s'il y a deux lignes, changer `CRK_PORT` dans `.env` |
| **503** avec « Dashboard non construit » | `Dashboard\dist` absent | relancer `install.ps1` sans `-SkipBuild` |
| Le service ne démarre pas | venv cassé, ou `.env` sans `CRK_API_KEY` | `Get-Content .\logs\crk-*.log -Tail 30` |
| Les boîtiers reçoivent **401** | clé API différente de celle du `.env` | comparer avec `Select-String CRK_API_KEY .\crk-backend\.env` |
| Page blanche depuis un autre poste | pare-feu | `Get-NetFirewallRule -DisplayName 'CRK Analytics*'` |
| Dashboard vide, aucun magasin actif | aucun boîtier n'émet encore | `Invoke-RestMethod http://localhost:8000/api/health` → `events_total` |
| Bandeau orange « données caisse simulées » | `CRK_JOOLAN_*` non renseigné dans `.env` | `py test_joolan.py` |
| Bandeau « caisse indisponible sur N jours » | Joolan injoignable ou en erreur ces jours-là | `Get-Content .\logs\crk-*.log \| Select-String 'caisse'` |
| CA à 0 DT pour un magasin qui vend | code `Magasin` Joolan non mappé | `py test_joolan.py` affiche les codes réels → compléter `CRK_JOOLAN_MAGASINS` |
| `seconds_ago` qui grimpe en heures d'ouverture | boîtier muet, ou clé API désynchronisée | `/api/last-seen`, puis comparer `CRK_API_KEY` des deux côtés |

### Encodage des scripts

`install.ps1` et `run-service.ps1` sont enregistrés en **UTF-8 avec BOM**.
PowerShell 5.1 — celui livré par défaut avec Windows Server — lit un fichier sans
BOM comme de l'ANSI : les accents deviennent alors des octets parasites qui
cassent l'analyse du script. Si vous éditez ces fichiers, conservez le BOM :

```powershell
$t = Get-Content -Raw -Encoding UTF8 .\deploy\windows\install.ps1
[System.IO.File]::WriteAllText((Resolve-Path .\deploy\windows\install.ps1), $t, (New-Object System.Text.UTF8Encoding $true))
```

Contrôle de syntaxe avant de déployer :

```powershell
$e = $null
[void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path .\deploy\windows\install.ps1), [ref]$null, [ref]$e)
$e
```

---

## Sécurité

- `/ingest/*` exige l'en-tête `X-API-Key`. Les routes de lecture `/api/*` sont
  **publiques** : quiconque atteint le port voit les chiffres des magasins.
  Sur un réseau non maîtrisé, restreindre la règle de pare-feu aux adresses des
  boutiques, ou placer le service derrière un VPN.
- Le trafic est en **HTTP**, sans chiffrement. Pour du HTTPS, mettre un reverse
  proxy (IIS ou nginx) devant et fermer le port applicatif à l'extérieur.
- La traversée de répertoire est bloquée : une URL du type `/../crk-backend/.env`
  renvoie la page du dashboard, jamais le fichier.
