"""Minimal .env loader (stdlib only — no python-dotenv dependency).

The app reads configuration from real environment variables at import time (see
``raqeeb/config.py``), so entry points call ``load_env()`` BEFORE importing anything
under ``raqeeb`` / ``app``. Existing environment variables always win over the file,
so an explicitly exported var is never clobbered.
"""
from __future__ import annotations
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (without overriding existing vars)."""
    env_path = path or (_ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
