#!/usr/bin/env bash
# Start the web system: the server and the background worker. Every assessment is a new paid Gemini request.
# Applications, uploads, results and the mask cache live in data_prod/. Prices: data/materials.db.
#
#   scripts/run_production.sh            # http://localhost:8001, Ctrl+C stops the server and the worker
#   PORT=8002 scripts/run_production.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${PORT:-8001}"

if ! grep -q '^GEMINI_API_KEY=.\+' .env 2>/dev/null; then
  echo "GEMINI_API_KEY is not set in .env: the production mode needs it." >&2
  exit 1
fi
if ! ls weights/*.pt >/dev/null 2>&1; then
  echo "No segmentation weights in weights/: the production mode needs them." >&2
  exit 1
fi

export DAMAGE_WEB_DATA="$ROOT/data_prod"
export DAMAGE_CACHE_DIR="$ROOT/data_prod/cache"
mkdir -p "$DAMAGE_WEB_DATA"

uv run python -m web.worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null; wait $WORKER 2>/dev/null' EXIT INT TERM

echo
echo "  Оцінка пошкоджень: http://localhost:$PORT"
echo "  Кожна нова заявка і кожен перерахунок - платні запити до Gemini."
echo "  Облік запитів: output/gemini_usage.csv. Зупинити: Ctrl+C."
echo
uv run uvicorn web.server:app --port "$PORT"
