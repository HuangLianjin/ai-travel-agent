#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[start] generated .env (demo mode by default)"
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[start] creating .venv..."
  if command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  else
    PY_BIN="python"
  fi
  "$PY_BIN" -m venv .venv
  echo "[start] installing dependencies..."
  .venv/bin/python -m pip install -r requirements.txt
fi

PYTHON=".venv/bin/python"

if [ ! -f "data/travel.db" ]; then
  echo "[start] seeding demo data..."
  "$PYTHON" -m app.seed
fi

echo "[start] serving at http://127.0.0.1:8000"
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

