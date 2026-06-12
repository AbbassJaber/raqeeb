#!/usr/bin/env bash
# Launch the Raqeeb Streamlit app in LIVE mode (real Sentinel-2 + Gemini).
#   bash scripts/run_app.sh
# For OFFLINE (synthetic, no keys) just run:
#   ./.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py
set -e
cd "$(dirname "$0")/.."
export RAQEEB_OFFLINE=0
export EARTHENGINE_PROJECT="${EARTHENGINE_PROJECT:-raqeeb-498718}"
if [ -z "${GEMINI_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "warning: no GEMINI_API_KEY / ANTHROPIC_API_KEY in env — live classification will fall back to the heuristic." >&2
fi
exec ./.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py
