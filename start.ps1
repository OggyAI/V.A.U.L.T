# V.A.U.L.T. launcher — starts the HUD in a background window,
# opens the dashboard, and runs the voice loop in this window.
#
# Usage:
#   .\start.ps1              # timed mode, 3s per turn (default)
#   .\start.ps1 -Mode text   # type instead of speak
#   .\start.ps1 -Mode ptt    # push-to-talk (needs: pip install keyboard)
#   .\start.ps1 -NoHud       # voice loop only

param(
    [ValidateSet("timed", "text", "ptt")]
    [string]$Mode = "timed",

    [int]$Port = 8550,
    [switch]$NoHud
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "No venv found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

& .\.venv\Scripts\Activate.ps1

if (-not $NoHud) {
    Write-Host "Starting HUD on port $Port..." -ForegroundColor Cyan

    # Separate window so its logs don't interleave with the voice loop's.
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "Set-Location '$root'; .\.venv\Scripts\Activate.ps1; uvicorn hud.server:app --port $Port"
    )

    # Give uvicorn a moment to bind before opening the browser.
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:$Port"
}

$modeArg = switch ($Mode) {
    "text"  { "--text" }
    "ptt"   { "--ptt" }
    default { "--timed 3" }
}

Write-Host "Starting voice loop ($Mode mode). Ctrl+C to stop." -ForegroundColor Green
Write-Host ""

Invoke-Expression "python -m voice.loop $modeArg"
