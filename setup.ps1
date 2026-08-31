# V.A.U.L.T. setup — Windows (PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "── V.A.U.L.T. Setup ──" -ForegroundColor Cyan

# Python venv
if (-not (Test-Path ".venv")) {
    Write-Host "[1/4] Creating Python venv..."
    python -m venv .venv
} else {
    Write-Host "[1/4] Venv already exists."
}

& .\.venv\Scripts\Activate.ps1

# Dependencies
Write-Host "[2/4] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Vault
if (-not (Test-Path "vault")) {
    Write-Host "[3/4] Copying vault template..."
    Copy-Item -Recurse vault.example vault
} else {
    Write-Host "[3/4] Vault already exists, skipping copy."
}

# .env
if (-not (Test-Path ".env")) {
    Write-Host "[4/4] Creating .env from template..."
    Copy-Item .env.example .env
    Write-Host "     WARNING: Fill in your API keys in .env before running." -ForegroundColor Yellow
} else {
    Write-Host "[4/4] .env already exists."
}

Write-Host ""
Write-Host "── Setup complete ──" -ForegroundColor Green
Write-Host "Activate:   .\.venv\Scripts\Activate.ps1"
Write-Host "Voice:      python -m voice.loop --text"
Write-Host "HUD:        uvicorn hud.server:app --port 8550"
Write-Host ""
Write-Host "See HANDOFF.md for remaining manual steps."
