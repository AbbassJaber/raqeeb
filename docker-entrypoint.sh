#!/bin/sh
# Container start. Two jobs:
#   1. If a Render Secret File with the Earth Engine credentials is mounted (under
#      /etc/secrets/), copy it where earthengine-api looks (~/.config/earthengine/
#      credentials) so live Sentinel-2 works — no code change. Accepts a few common
#      file names so a .json suffix or alternate name still works.
#   2. Serve the watchroom on $PORT — Render injects it; defaults to 8000 locally/compose.
set -e

EE_DIR="${HOME:-/root}/.config/earthengine"
for src in /etc/secrets/earthengine-credentials \
           /etc/secrets/earthengine-credentials.json \
           /etc/secrets/credentials; do
  if [ -f "$src" ]; then
    mkdir -p "$EE_DIR"
    cp "$src" "$EE_DIR/credentials"
    echo "earth engine: placed credentials from $src"
    break
  fi
done

exec uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-8000}"
