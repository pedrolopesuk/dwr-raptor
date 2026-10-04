<#
.SYNOPSIS
  Launch the DRW researcher workspace locally (Windows PowerShell).

.DESCRIPTION
  Checks prerequisites, picks a free port, points the web app at the local
  Python scientific core, and starts the Next.js server.

  It does NOT delete or reset anything: the experiment workspace is created if
  missing and otherwise left untouched. It never kills other processes.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-local.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-local.ps1 -Mode dev -Port 3847
#>
[CmdletBinding()]
param(
  [int]$Port = 3000,
  [ValidateSet("prod", "dev")]
  [string]$Mode = "prod",
  [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
  Write-Host ""
  Write-Host "ERROR: $Message" -ForegroundColor Red
  Write-Host ""
  exit 1
}

function Info([string]$Message) { Write-Host $Message }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- prerequisites ---------------------------------------------------------
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Fail "Node.js was not found on PATH (DRW needs Node >= 20)."
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
  Fail "pnpm was not found on PATH (DRW needs pnpm >= 9). Install: corepack enable"
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $pythonCmd) {
    Fail "No Python interpreter found. Create the venv first:`n  python -m venv .venv`n  .\.venv\Scripts\python.exe -m pip install -e `"packages/core[dev]`""
  }
  $venvPython = $pythonCmd.Source
}
& $venvPython -c "import drw" 2>$null
if ($LASTEXITCODE -ne 0) {
  Fail "The Python scientific core is not importable by:`n  $venvPython`nInstall it with:`n  `"$venvPython`" -m pip install -e `"packages/core[dev]`""
}

if (-not (Test-Path (Join-Path $root "node_modules"))) {
  Info "Installing workspace dependencies (pnpm install)..."
  pnpm install | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail "pnpm install failed." }
}

# --- pick a free port (never assume 3000 is free) --------------------------
function Test-FreePort([int]$Candidate) {
  $listeners = Get-NetTCPConnection -LocalPort $Candidate -State Listen -ErrorAction SilentlyContinue
  return -not $listeners
}
$requested = $Port
while (-not (Test-FreePort $Port)) {
  Info "Port $Port is in use; trying $($Port + 1)..."
  $Port++
  if ($Port -gt $requested + 50) { Fail "Could not find a free port near $requested." }
}

# --- environment -----------------------------------------------------------
$workspace = if ($env:DRW_WORKSPACE) { $env:DRW_WORKSPACE } else { Join-Path $root ".drw\web-workspace" }
if (-not (Test-Path $workspace)) { New-Item -ItemType Directory -Force -Path $workspace | Out-Null }
$env:DRW_WORKSPACE = $workspace
$env:DRW_PYTHON = $venvPython

Info ""
Info "Differential Research Workbench - local launch"
Info "  mode      : $Mode"
Info "  python    : $venvPython"
Info "  workspace : $workspace"
Info "  url       : http://localhost:$Port"
Info "  stop      : Ctrl+C in this window"
Info ""
Info "The AI planner is optional; without DRW_LLM_PROVIDER it uses the offline rule-based planner."
Info ""

if ($Mode -eq "prod") {
  $build = Join-Path $root "apps\web\.next"
  if ((-not $NoBuild) -or (-not (Test-Path $build))) {
    Info "Building the web app (next build)..."
    pnpm --filter @drw/web build | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "The production build failed." }
  }
  Info "Starting the production server on http://localhost:$Port ..."
  pnpm --filter @drw/web exec next start -p $Port | Out-Host
} else {
  Info "Starting the development server on http://localhost:$Port ..."
  pnpm --filter @drw/web exec next dev -p $Port | Out-Host
}

if ($LASTEXITCODE -ne 0) { Fail "The server exited with code $LASTEXITCODE." }
