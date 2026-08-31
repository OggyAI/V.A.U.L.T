#!/usr/bin/env bash
# V.A.U.L.T. setup — Linux / macOS
set -e

echo "── V.A.U.L.T. Setup ──"

# Python venv
if [ ! -d ".venv" ]; then
  echo "[1/4] Creating Python venv..."
  python3 -m venv .venv
else
  echo "[1/4] Venv already exists."
fi

source .venv/bin/activate

# Dependencies
echo "[2/4] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Vault
if [ ! -d "vault" ]; then
  echo "[3/4] Copying vault template..."
  cp -r vault.example vault
else
  echo "[3/4] Vault already exists, skipping copy."
fi

# .env
if [ ! -f ".env" ]; then
  echo "[4/4] Creating .env from template..."
  cp .env.example .env
  echo "     ⚠  Fill in your API keys in .env before running."
else
  echo "[4/4] .env already exists."
fi

echo ""
echo "── Setup complete ──"
echo "Activate:   source .venv/bin/activate"
echo "Voice:      python -m voice.loop --text"
echo "HUD:        uvicorn hud.server:app --port 8550"
echo ""
echo "See HANDOFF.md for remaining manual steps."
