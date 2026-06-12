# CLAUDE.md — Raqeeb

AI agent that watches Lebanon from satellite imagery, flags likely environmental
violations (illegal quarrying; coastal encroachment), reasons about whether each
change breaks a rule, and produces an evidence dossier. Hackathon project.

This file is the standing brief. Read it every session before working.

## Non-negotiable constraints

- **Candidate, not accusation.** Every output is a *candidate for human
  verification*, never a legal verdict and never a named accusation. Boundaries
  (coastline buffer, permit zones) are proxies — say so.
- **Never auto-send alerts.** Alerts are *drafted* for a human to review and send.
- **Metric CRS for all geometry.** Do area/distance/intersection math in
  `EPSG:32636` (UTM 36N, correct for Lebanon). Lon/lat is for display + the
  imagery sampling grid only.
- **Same-season, cloud-masked composites.** Compare before/after windows in the
  same season; per-pixel cloud-mask before compositing (not just a scene-level
  cloud-% filter).
- **Ask before:** installing heavy dependencies, or changing the public interface
  of an existing module. Additive helpers are fine; signature changes need a heads-up.
- **Don't guess credentials.** Tell the user what you need (API key, Earth Engine
  auth + GCP project id) instead of inventing values.

## Build order (strict — do not advance until the current step runs on a REAL example)

0. **Scout / zone selection** — one real AOI + same-season before/after dates with
   clearly visible change; plus a draw-zone-on-map selector in the Streamlit UI.
1. **Live Sentinel-2 fetch** — `imagery._fetch_gee` returns real before/after
   composites as numpy arrays for a bbox via Google Earth Engine. *First confirm
   the current Sentinel-2 collection id against the GEE data catalog.*
2. **Live Claude** — turn on `classify.classify_with_claude` (vision) and
   `agent.run_agent_with_claude` (tool-use orchestrator). *First confirm the
   current model id at https://docs.claude.com.*
3. **Coastal encroachment mode** — only after 1+2 work end-to-end on one real
   site. Add a detector returning `ChangeRegion`s + a legality rule, reusing the
   existing pipeline.
4. **Accuracy harness** — precision/recall on a small set of known sites.

## Architecture (don't rebuild — extend)

Pipeline: `imagery → detect → classify → legality → dossier → alert`, orchestrated
by `raqeeb/agent.py` (`run_agent` offline-deterministic; `run_agent_with_claude`
online tool-use). Detection is a swappable step keyed by `scenario["mode"]`.

**The data contract IS the interface.** `imagery.get_composites(scenario)` returns
`(before, after)` where each is `dict[str, np.ndarray]` of `grid×grid` float
reflectance (0..1) for bands `B2, B3, B4, B8, B11`. The online and offline paths
must return this same shape so `detect.py` / `geo.py` stay unchanged.

Geometry helpers in `raqeeb/geo.py` already reproject to `EPSG:32636`. Legality
intersections in `raqeeb/legality.py` already run in metric CRS.

## Going live

- `RAQEEB_OFFLINE=0`, set an LLM key, run `earthengine authenticate`.
- **LLM provider is pluggable** (`config.LLM_PROVIDER`, auto-detected): `claude`
  (`ANTHROPIC_API_KEY`, the default) or `gemini` (free, Google AI Studio —
  `GEMINI_API_KEY`). Same pipeline; `classify.classify()`,
  `classify.second_opinion()`, `agent.run_agent_with_llm()`, and the streaming
  `agent.run_agent_stream()` all route by provider. The live path now uses
  **Claude Sonnet** (`claude-sonnet-4-6`). Keys load from a gitignored `.env` via a
  tiny stdlib loader (`scripts/_env.py`) in `run_server.py` / `run_live_agent.py`.
- Earth Engine now requires a project: use `ee.Initialize(project="<gcp-project>")`.
- Current config: `LLM_PROVIDER` auto (claude when ANTHROPIC_API_KEY set),
  `CLAUDE_MODEL=claude-sonnet-4-6`, `GEMINI_MODEL=gemini-2.5-flash`,
  `METRIC_CRS=EPSG:32636`, `COASTAL_SETBACK_M=150`, `PIXEL_M=10`.
- Reference layers in `data/reference/`: **protected areas (real WDPA/WCMC, via Earth
  Engine) and the coastline are now real**; only the permitted-quarry zone is still a
  synthetic proxy. (The old synthetic placeholders are kept as `*.synthetic.geojson`.)
  WDPA polygons are still a *triage* proxy — confirm exact boundaries against the
  official cadastre / Ministry of Environment.

## Environment

- Windows. Project uses an isolated venv at `.venv` (standalone Python — the only
  other interpreter on this box is pgAdmin's private one; do not use it).
- Run: `./.venv/Scripts/python.exe scripts/run_demo.py` ·
  `./.venv/Scripts/python.exe -m pytest -q` ·
  `./.venv/Scripts/streamlit run app/streamlit_app.py`.
