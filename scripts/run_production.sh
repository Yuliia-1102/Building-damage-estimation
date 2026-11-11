#!/usr/bin/env bash
# The working product: the web system with Gemini only. Every assessment is a new paid request:
# no answer cache, no stub answers, no development pack. Its applications, uploads, results and mask cache
# live in data_prod/, apart from the development system in data/. Prices: the shared data/materials.db.
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

export DAMAGE_ENGINE=production
export DAMAGE_WEB_DATA="$ROOT/data_prod"
export DAMAGE_CACHE_DIR="$ROOT/data_prod/cache"
unset DAMAGE_LLM DAMAGE_LLM_MODE DAMAGE_PACK
mkdir -p "$DAMAGE_WEB_DATA"

uv run python -m web.worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null; wait $WORKER 2>/dev/null' EXIT INT TERM

echo
echo "  Робочий режим: http://localhost:$PORT"
echo "  Кожна нова заявка і кожен перерахунок - платні запити до Gemini."
echo "  Облік запитів: output/gemini_usage.csv. Зупинити: Ctrl+C."
echo
uv run uvicorn web.server:app --port "$PORT"
