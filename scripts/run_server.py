#!/usr/bin/env python
"""Launch the live cinematic player (FastAPI + SSE).

    ./.venv/Scripts/python.exe scripts/run_server.py        # http://127.0.0.1:8000

This is the single demo surface: the national map, the cinematic single-site player,
and a live 'Run'/'Draw a zone' path that streams a real agent run into the beats.
Set RAQEEB_OFFLINE=0 (plus GEE auth + an LLM key) for real Sentinel-2 + Claude;
left at the default it streams the synthetic pipeline live (never fails on stage).
Configuration is read from a local .env (see .env.example) at startup.
"""
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import raqeeb + app

from _env import load_env  # noqa: E402

load_env()  # populate os.environ from .env BEFORE raqeeb.config reads it

PORT = int(os.getenv("RAQEEB_DEMO_PORT", "8000"))


def _free_port(start: int) -> int:
    """First open port at/after `start` — so a lingering instance doesn't block startup."""
    for p in range(start, start + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                print(f"port {p} busy, trying {p + 1} ...", flush=True)
    raise SystemExit(f"No free port found in {start}..{start + 9}.")


if __name__ == "__main__":
    from app.server import app
    port = _free_port(PORT)
    print(f"Raqeeb live player -> http://127.0.0.1:{port}   (Ctrl+C to stop)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
