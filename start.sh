#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python"
fi

if [ ! -f "data/travel.db" ]; then
  "$PYTHON" -m app.seed
fi

"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

