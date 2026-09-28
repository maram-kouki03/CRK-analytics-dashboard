# Lancé par la tâche planifiée « CRK Analytics ».
# Rôle : se placer dans crk-backend, démarrer uvicorn avec le Python du venv, et
# rediriger toutes les sorties vers un fichier — sous Task Scheduler, stdout est
# perdu, donc sans cette redirection un crash au démarrage serait invisible.

# SURTOUT PAS 'Stop' ici. PowerShell 5.1 enrobe chaque ligne qu'un exe écrit sur
# stderr dans un ErrorRecord ; avec 'Stop' cela devient une erreur bloquante.
# uvicorn journalise sur stderr, donc le script mourait sur sa toute première
# ligne de log et emportait le backend avec lui : la tâche démarrait, rien
# n'écoutait, et le journal ne contenait que « démarrage » sans la suite.
$ErrorActionPreference = 'Continue'

# deploy\windows -> deploy -> racine du dépôt
$root    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$backend = Join-Path $root 'crk-backend'
$python  = Join-Path $backend 'venv\Scripts\python.exe'

$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$log = Join-Path $logDir ('crk-{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))

if (-not (Test-Path $python)) {
    "[$(Get-Date -Format s)] venv introuvable : $python - relancer install.ps1" |
        Out-File $log -Append -Encoding utf8
    exit 1
}

"[$(Get-Date -Format s)] demarrage de crk-backend" | Out-File $log -Append -Encoding utf8

Set-Location $backend

# Sans PYTHONUNBUFFERED, la sortie reste dans le tampon tant que le processus
# tourne : un service qui ne s'arrête jamais n'écrirait donc jamais son journal.
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

# La redirection est confiée à cmd.exe, qui écrit les deux flux tels quels, sans
# l'enrobage ErrorRecord de PowerShell décrit plus haut.
& cmd.exe /c "`"$python`" main.py >> `"$log`" 2>&1"
$code = $LASTEXITCODE

"[$(Get-Date -Format s)] arret (code $code)" | Out-File $log -Append -Encoding utf8
exit $code
