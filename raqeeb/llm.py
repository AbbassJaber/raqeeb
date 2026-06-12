"""Shared LLM helpers.

Two thin text-generation wrappers so the rest of the codebase can ask for a reply
without caring which provider is configured:

- ``claude_generate`` — Anthropic Messages API (default provider). The SDK already
  retries 429 / 5xx / overload with exponential backoff, so this is a small wrapper
  that returns an object with a ``.text`` attribute (mirroring Gemini's shape) and
  caches one client.
- ``gemini_generate`` — Google AI Studio ``generate_content`` with backoff on 429,
  since the free tier caps requests-per-minute (e.g. ~5/min for gemini-2.5-flash) and
  the tool-use orchestrator makes several calls in quick succession.
"""
from __future__ import annotations
import re
import time
from dataclasses import dataclass

from . import config

# Fallback escalating waits if the API doesn't supply a retry hint.
_BACKOFF = (8, 20, 35, 50, 60)


# --- Claude (default provider) ----------------------------------------------

@dataclass
class _Reply:
    """Tiny result wrapper so call sites read like the Gemini path (``resp.text``)."""
    text: str


_claude_client = None


def claude_client():  # pragma: no cover - needs ANTHROPIC_API_KEY
    """One cached Anthropic client. Reads ANTHROPIC_API_KEY from the environment."""
    global _claude_client
    if _claude_client is None:
        import anthropic
        _claude_client = anthropic.Anthropic()
    return _claude_client


def claude_generate(contents, model: str | None = None, system: str | None = None,
                    max_tokens: int = 1000):  # pragma: no cover - needs key
    """Plain-text Claude completion. ``contents`` is a string or a Messages ``content``
    list (e.g. text + image blocks). Returns ``_Reply`` with ``.text`` — the concatenated
    text blocks of the reply. The SDK handles 429 / overload retries; let other errors
    surface so callers can fall back."""
    content = contents if isinstance(contents, list) else [{"type": "text", "text": contents}]
    kwargs = {"model": model or config.CLAUDE_MODEL, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": content}]}
    if system:
        kwargs["system"] = system
    msg = claude_client().messages.create(**kwargs)
    return _Reply(text="".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))


def _retry_after(exc) -> float | None:
    """Seconds the API asked us to wait, parsed from a 429 ('Please retry in 43.6s')."""
    m = re.search(r"retry in ([\d.]+)s", str(exc))
    return float(m.group(1)) if m else None


def gemini_generate(contents, gen_config=None, model: str | None = None):  # pragma: no cover - needs key
    """Call Gemini generate_content, retrying on 429 RESOURCE_EXHAUSTED.

    The free tier is ~20 requests/min and the 429 tells us exactly how long to wait
    ('retry in ~44s'); we honour that hint so a throttled call recovers with a REAL
    answer instead of wasting early retries (and falling back). A fresh client per call
    picks up GEMINI_API_KEY / GOOGLE_API_KEY from the current environment.
    """
    from google import genai
    from google.genai import errors

    client = genai.Client()
    mdl = model or config.GEMINI_MODEL
    last_exc = None
    for attempt in range(5):
        try:
            return client.models.generate_content(model=mdl, contents=contents, config=gen_config)
        except errors.ClientError as exc:
            if getattr(exc, "code", None) != 429:
                raise
            last_exc = exc
            hint = _retry_after(exc)
            time.sleep(min(65.0, hint + 1.5 if hint else _BACKOFF[min(attempt, len(_BACKOFF) - 1)]))
    raise last_exc
