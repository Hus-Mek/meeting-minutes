# =============================================================================
# build_windows.ps1 - One-shot local Windows build for MeetingMinutes.
# =============================================================================
#
# Produces the per-user Inno Setup installer:
#     dist\installer\MeetingMinutes-Setup.exe
#
# What it does, end to end:
#   1. Builds the React frontend (frontend\dist).
#   2. Creates/refreshes an isolated build venv (.buildvenv) and installs the
#      runtime + desktop deps plus PyInstaller (a build-only tool).
#   3. Pre-builds the synthetic .docx template so the frozen app never has to
#      write into read-only Program Files.
#   4. Generates the app icon (packaging\app.ico).
#   5. Freezes the app with PyInstaller (ONEDIR -> dist\MeetingMinutes\).
#   6. Compiles the installer with Inno Setup (ISCC).
#
# PREREQUISITES (install these on the build machine first):
#   - Node.js + npm           (to build the frontend)
#   - Python 3.12             (launched via the "py" launcher, with a python
#                              fallback; used to create the build venv)
#   - Inno Setup 6            (provides ISCC.exe - the installer compiler;
#                              get it from https://jrsoftware.org/isdl.php)
#
# USAGE:
#   Open PowerShell and run the script from anywhere, e.g.:
#       powershell -ExecutionPolicy Bypass -File C:\path\to\packaging\build_windows.ps1
#   or, from within an interactive PowerShell session:
#       .\packaging\build_windows.ps1
#
#   The script resolves the repo root itself, so the working directory does
#   not matter.
# =============================================================================

# Stop on the first error so a failed step never silently cascades.
$ErrorActionPreference = "Stop"

# -----------------------------------------------------------------------------
# Step 1: Resolve the repo root (parent of this script's folder) and go there.
# -----------------------------------------------------------------------------
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host "==> Repo root: $repoRoot" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# Step 2: Build the React frontend.
#         web.py serves frontend\dist, and the spec bundles it into the app.
# -----------------------------------------------------------------------------
Write-Host "==> Building frontend (npm ci && npm run build)..." -ForegroundColor Cyan
Set-Location (Join-Path $repoRoot "frontend")
npm ci
npm run build
Set-Location $repoRoot

# -----------------------------------------------------------------------------
# Step 3: Create/refresh the isolated build venv and install dependencies.
#         Prefer Python 3.12 via the "py" launcher; fall back to "python".
# -----------------------------------------------------------------------------
$venvDir = Join-Path $repoRoot ".buildvenv"
Write-Host "==> Creating build venv at $venvDir ..." -ForegroundColor Cyan

# Resolve which interpreter can create the venv. "py -3.12" is preferred; if
# the launcher or that version is missing, fall back to plain "python".
$pyExe = $null
$pyArgs = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    # Probe that "py -3.12" actually resolves to an installed interpreter.
    & py -3.12 -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pyExe = "py"
        $pyArgs = @("-3.12")
    }
}
if (-not $pyExe) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Host "    py -3.12 unavailable; falling back to 'python'." -ForegroundColor Yellow
        $pyExe = "python"
        $pyArgs = @()
    }
    else {
        Write-Error "No suitable Python found. Install Python 3.12 (the 'py' launcher or 'python' must be on PATH)."
    }
}

# Build the venv with the chosen interpreter.
& $pyExe @pyArgs -m venv $venvDir

# Activate it for the rest of this session.
$activate = Join-Path $venvDir "Scripts\Activate.ps1"
. $activate

# Install deps. From here on, "python" / "pip" are the venv's.
Write-Host "==> Installing build dependencies into the venv..." -ForegroundColor Cyan
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-desktop.txt pyinstaller

# -----------------------------------------------------------------------------
# Step 4: Pre-build the synthetic .docx template (packaging-time artifact).
#         The frozen app ships this prebuilt so it never writes into a
#         read-only install directory at runtime.
# -----------------------------------------------------------------------------
Write-Host "==> Pre-building the synthetic .docx template..." -ForegroundColor Cyan
python -c "from meeting_minutes.sample_template import build; print(build())"

# -----------------------------------------------------------------------------
# Step 5: Generate the app icon (packaging\app.ico).
# -----------------------------------------------------------------------------
Write-Host "==> Generating app icon..." -ForegroundColor Cyan
python packaging\make_icon.py

# -----------------------------------------------------------------------------
# Step 5b: Vendor a portable Node.js + the Claude Code CLI into vendor\node so the
#          installer ships everything the app needs except a one-time Claude login.
#          (The launcher prefers a claude the user already has and falls back to this.)
# -----------------------------------------------------------------------------
Write-Host "==> Vendoring Node.js + Claude Code CLI..." -ForegroundColor Cyan
$nodeVer = "v20.18.1"
$nodeUrl = "https://nodejs.org/dist/$nodeVer/node-$nodeVer-win-x64.zip"
$nodeZip = Join-Path $repoRoot "node.zip"
$nodeTmp = Join-Path $repoRoot "node_tmp"
$vendorNode = Join-Path $repoRoot "vendor\node"
Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeZip
if (Test-Path $nodeTmp) { Remove-Item -Recurse -Force $nodeTmp }
Expand-Archive $nodeZip -DestinationPath $nodeTmp -Force
if (Test-Path $vendorNode) { Remove-Item -Recurse -Force $vendorNode }
New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot "vendor") | Out-Null
Move-Item (Join-Path $nodeTmp "node-$nodeVer-win-x64") $vendorNode
& (Join-Path $vendorNode "npm.cmd") install -g "@anthropic-ai/claude-code" --prefix $vendorNode
if (-not (Test-Path (Join-Path $vendorNode "claude.cmd"))) { Write-Error "claude.cmd missing after npm install" }
Remove-Item -Force $nodeZip
Remove-Item -Recurse -Force $nodeTmp

# -----------------------------------------------------------------------------
# Step 6: Freeze the app with PyInstaller (ONEDIR -> dist\MeetingMinutes\).
# -----------------------------------------------------------------------------
Write-Host "==> Freezing the app with PyInstaller..." -ForegroundColor Cyan
pyinstaller --noconfirm --clean packaging\meeting_minutes.spec

# -----------------------------------------------------------------------------
# Step 7: Build the installer with Inno Setup (ISCC).
#         Prefer ISCC on PATH; otherwise fall back to the default install path.
# -----------------------------------------------------------------------------
Write-Host "==> Compiling the installer with Inno Setup..." -ForegroundColor Cyan
$isccCmd = Get-Command ISCC -ErrorAction SilentlyContinue
if ($isccCmd) {
    $iscc = $isccCmd.Source
}
else {
    $isccFallback = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $isccFallback) {
        $iscc = $isccFallback
    }
    else {
        Write-Error "Inno Setup compiler (ISCC.exe) not found on PATH or at '$isccFallback'. Install Inno Setup 6 from https://jrsoftware.org/isdl.php and retry."
    }
}
& $iscc "packaging\installer.iss"

# -----------------------------------------------------------------------------
# Done. Report the final installer path.
# -----------------------------------------------------------------------------
$installerPath = Join-Path $repoRoot "dist\installer\MeetingMinutes-Setup.exe"
Write-Host ""
Write-Host "==> Build complete." -ForegroundColor Green
Write-Host "    Installer: $installerPath" -ForegroundColor Green
