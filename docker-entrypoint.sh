#!/bin/sh
# Container start. Two jobs:
#   1. If a Render Secret File with the Earth Engine credentials is mounted, copy it into
#      the path the earthengine-api expects (so live Sentinel-2 works, no code change).
#   2. Serve the watchroom on $PORT — Render injects it; defaults to 8000 locally/compose.
set -e

if [ -f /etc/secrets/earthengine-credentials ]; then
  mkdir -p /root/.config/earthengine
  cp /etc/secrets/earthengine-credentials /root/.config/earthengine/credentials
fi

exec uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-8000}"
