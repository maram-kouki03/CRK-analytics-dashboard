<#
.SYNOPSIS
    Installe la plateforme CRK Analytics sur une VM Windows Server, en un service.

.DESCRIPTION
    Un seul processus sert le dashboard ET l'API sur le même port : pas de CORS,
    pas de reverse proxy, rien à configurer côté frontend.

    Le script est idempotent — le relancer après un `git pull` reconstruit le
    dashboard et redémarre le service sans toucher au .env ni à la base.

    À lancer depuis une console PowerShell EN ADMINISTRATEUR :
        .\deploy\windows\install.ps1
        .\deploy\windows\install.ps1 -Port 8000

.PARAMETER Port
    Port d'écoute. Défaut 8000. Évite 8080 si un listener Oracle tourne déjà.

.PARAMETER SkipBuild
    Ne reconstruit pas le dashboard (Node absent, ou dist/ déjà copié à la main).

.PARAMETER NoFirewall
    N'ajoute pas la règle de pare-feu entrante.
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipBuild,
    [switch]$NoFirewall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'CRK Analytics'

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !   $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "`nÉCHEC : $msg" -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- pré-requis

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Die "à lancer dans une console PowerShell ouverte en administrateur." }

$root     = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$backend  = Join-Path $root 'crk-backend'
$frontend = Join-Path $root 'Dashboard'
$dist     = Join-Path $frontend 'dist'

if (-not (Test-Path $backend))  { Die "crk-backend introuvable sous $root" }
if (-not (Test-Path $frontend)) { Die "Dashboard introuvable sous $root" }

Step "Vérification des outils"

$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { Die "Python introuvable. Installer Python 3.10+ depuis python.org en cochant « Add to PATH »." }
# `py` peut exister sans qu'aucun interpréteur ne soit installé : le lanceur
# répond alors en erreur sans lever d'exception PowerShell. On teste la sortie.
$pyVersion = & $py.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $pyVersion) {
    Die "$($py.Source) ne pointe vers aucun interpréteur utilisable. Installer Python 3.10+ depuis python.org."
}
if ([version]$pyVersion -lt [version]'3.10') {
    Die "Python $pyVersion trop ancien : le backend utilise la syntaxe `str | None` (3.10+)."
}
Ok "Python $pyVersion ($($py.Source))"

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm -and -not $SkipBuild) {
    if (Test-Path (Join-Path $dist 'index.html')) {
        Warn "Node absent, mais dist/ existe déjà : on garde ce build (-SkipBuild implicite)."
        $SkipBuild = $true
    } else {
        Die "Node.js introuvable et aucun dist/ présent. Installer Node 18+, ou construire le dashboard ailleurs et copier Dashboard\dist sur la VM puis relancer avec -SkipBuild."
    }
} elseif ($npm) {
    Ok "npm $(& npm --version)"
}

# ------------------------------------------------------------------ backend

Step "Environnement Python (venv)"

$venv       = Join-Path $backend 'venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

# Un venv dont l'interpréteur de base a disparu (Python mis à jour, déplacé) reste
# présent sur le disque mais échoue à chaque appel : on le recrée plutôt que de
# laisser un service qui ne démarrera jamais.
if ((Test-Path $venv) -and -not (Test-Path $venvPython)) {
    Warn "venv incomplet, recréation"
    Remove-Item $venv -Recurse -Force
} elseif (Test-Path $venvPython) {
    & $venvPython -c "import sys" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Warn "venv cassé (interpréteur de base absent), recréation"
        Remove-Item $venv -Recurse -Force
    }
}

if (-not (Test-Path $venvPython)) {
    & $py.Source -m venv $venv
    if ($LASTEXITCODE -ne 0) { Die "création du venv impossible" }
}
Ok "venv prêt"

& $venvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPython -m pip install -r (Join-Path $backend 'requirements.txt') --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Die "pip install a échoué" }
Ok "dépendances installées (versions figées)"

# --------------------------------------------------------------------- .env

Step "Configuration (.env)"

$envFile = Join-Path $backend '.env'
if (Test-Path $envFile) {
    Ok ".env existant conservé (clé API et base inchangées)"
    $existingPort = (Select-String -Path $envFile -Pattern '^CRK_PORT=(\d+)' | Select-Object -First 1)
    if ($existingPort) {
        $found = [int]$existingPort.Matches[0].Groups[1].Value
        if ($found -ne $Port) {
            Warn ".env impose CRK_PORT=$found — c'est lui qui gagne, pas -Port $Port."
            $Port = $found
        }
    }
} else {
    # Clé partagée avec les boîtiers caméra. Générée ici, jamais commitée.
    $bytes = [byte[]]::new(16)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $apiKey = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''

    @(
        "CRK_API_KEY=$apiKey",
        "CRK_DB_PATH=./crk_analytics.db",
        "CRK_HOST=0.0.0.0",
        "CRK_PORT=$Port"
    ) | Set-Content -Path $envFile -Encoding utf8

    Ok ".env créé, nouvelle clé API générée"
    $script:newKey = $apiKey
}

# ----------------------------------------------------------------- frontend

if ($SkipBuild) {
    Step "Dashboard (build ignoré)"
    if (Test-Path (Join-Path $dist 'index.html')) { Ok "dist/ présent" }
    else { Warn "dist/ absent : l'API répondra, mais l'interface renverra 503." }
} else {
    Step "Construction du dashboard"
    Push-Location $frontend
    try {
        if (Test-Path (Join-Path $frontend 'package-lock.json')) { & npm ci --no-audit --no-fund }
        else { & npm install --no-audit --no-fund }
        if ($LASTEXITCODE -ne 0) { Die "npm install a échoué" }

        # Aucune variable VITE_API_URL : le dashboard appelle /api en relatif et
        # c'est ce même service qui répond. Rien à figer au build.
        & npm run build
        if ($LASTEXITCODE -ne 0) { Die "npm run build a échoué" }
    } finally { Pop-Location }
    Ok "dist/ reconstruit"
}

# ------------------------------------------------------------------ service

Step "Service Windows (tâche planifiée « $TaskName »)"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Ok "service existant arrêté"
}

$runner = Join-Path $PSScriptRoot 'run-service.ps1'
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $backend

$trigger = New-ScheduledTaskTrigger -AtStartup

# SYSTEM : le service doit tourner sans session ouverte et survivre à la déconnexion.
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Ok "tâche enregistrée (démarrage automatique, redémarrage auto en cas d'échec)"

Start-ScheduledTask -TaskName $TaskName
Ok "service démarré"

# ------------------------------------------------------------------ firewall

if (-not $NoFirewall) {
    Step "Pare-feu"
    $ruleName = "CRK Analytics ($Port)"
    if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
        Ok "règle déjà présente"
    } else {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
            -LocalPort $Port -Action Allow -Profile Any | Out-Null
        Ok "port $Port ouvert en entrée"
    }
}

# ----------------------------------------------------------------- contrôle

Step "Vérification"

$health = $null
foreach ($attempt in 1..20) {
    Start-Sleep -Milliseconds 750
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
        break
    } catch { }
}

if (-not $health) {
    Warn "l'API ne répond pas encore sur le port $Port."
    Warn "Journal : $(Join-Path $root 'logs')"
    Warn "Cause fréquente : port déjà pris. Vérifier avec"
    Warn "  Get-NetTCPConnection -LocalPort $Port -State Listen"
    exit 1
}

Ok "API en ligne — $($health.events_total) événement(s) en base"

try {
    $page = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
    if ($page.Content -match '<div id="root">') { Ok "dashboard servi sur le même port" }
    else { Warn "réponse inattendue sur / (build manquant ?)" }
} catch { Warn "le dashboard ne répond pas : $($_.Exception.Message)" }

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
       Select-Object -First 1).IPAddress

Write-Host "`n────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host " Dashboard : http://$ip`:$Port/"
Write-Host " Ingestion : http://$ip`:$Port/ingest/batch   (en-tête X-API-Key)"
Write-Host " Journaux  : $(Join-Path $root 'logs')"
if ($script:newKey) {
    Write-Host "`n CLÉ API générée (à configurer sur chaque boîtier caméra) :" -ForegroundColor Yellow
    Write-Host "   $($script:newKey)" -ForegroundColor Yellow
    Write-Host " Elle est stockée dans crk-backend\.env et n'est plus réaffichée."
}
Write-Host "────────────────────────────────────────────────────`n" -ForegroundColor Cyan
