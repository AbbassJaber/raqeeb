# Raqeeb — satellite monitoring agent. Containerised demo server (the FastAPI + SSE watchroom).
#
# Builds an OFFLINE-by-default image: the cached real cases (Bourj Hammoud, Costa Brava,
# Jounieh) and the synthetic pipeline run with no keys and no network, so the demo can't
# die. For the LIVE path (real Sentinel-2 + Claude) see the notes at the bottom.
FROM python:3.12-slim

# Unbuffered stdout so SSE/agent logs stream out immediately; no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RAQEEB_OFFLINE=1

WORKDIR /app

# Install deps first so this layer is cached unless requirements.txt changes. numpy/
# scipy/shapely/pyproj/matplotlib/pillow all ship manylinux wheels, so no system
# GEOS/PROJ or build toolchain is needed on slim.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optionally bake in the LIVE-only deps: Earth Engine (real Sentinel-2) + the Gemini SDK.
# The Claude SDK (anthropic) is already in requirements.txt, so the live Claude path needs no
# build flag. Off by default to keep the offline image lean; the compose `live` profile and
# render.yaml build with INSTALL_LIVE=1. These are intentionally NOT in requirements.txt.
ARG INSTALL_LIVE=0
RUN if [ "$INSTALL_LIVE" = "1" ]; then pip install --no-cache-dir google-genai earthengine-api; fi

# App code. The .dockerignore keeps .venv/, outputs/, caches and scratch out of the image,
# while the cached demo bundles under web/runs/ are included so the demo works offline.
COPY . .

EXPOSE 8000

# Serve the watchroom via the entrypoint script: it serves app.server:app on $PORT (Render
# injects it; defaults to 8000 locally/compose) and, if a Render Secret File is mounted,
# places the Earth Engine credentials first. We avoid scripts/run_server.py (it binds
# 127.0.0.1 + hunts for a free port). Run via `sh` so no executable bit is needed.
CMD ["sh", "/app/docker-entrypoint.sh"]

# --- Going live (optional) --------------------------------------------------------------
# The base image is offline. For real imagery + AI, build with INSTALL_LIVE=1 (installs
# earthengine-api; the anthropic SDK is already present) and pass credentials at runtime:
#   docker build --build-arg INSTALL_LIVE=1 -t raqeeb:live .
#   docker run -p 8000:8000 \
#     -e RAQEEB_OFFLINE=0 -e RAQEEB_LLM=claude -e ANTHROPIC_API_KEY=... \
#     -e EARTHENGINE_PROJECT=<gcp-project> \
#     -v "$HOME/.config/earthengine:/root/.config/earthengine:ro" raqeeb:live
