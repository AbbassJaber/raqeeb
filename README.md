# Raqeeb

An AI agent that watches Lebanon from satellite imagery, detects environmental
violations (illegal **quarrying** and **coastal encroachment**), reasons about whether
each change breaks a rule, and produces a ready-to-file evidence dossier —
autonomously, from one instruction. Built for the AI-agents hackathon.

Every output is a **candidate for human verification**, never an accusation, and alerts
are **drafted only, never sent**.

## What it does

Pipeline (one swappable detector per mode → shared downstream):

1. **Imagery** — same-season, cloud-masked before/after composites (synthetic offline; live Sentinel-2 via Google Earth Engine).
2. **Detect** — spectral-index change detection → regions with area + centroid (real numpy).
   - *quarry:* vegetation loss (NDVI↓) **and** bare-rock gain (BSI↑).
   - *coastal:* new built-up/bare (BSI↑) replacing water **or** vegetation (NDWI↓ or NDVI↓).
3. **Classify** — heuristic offline; an LLM vision model online looks at the before/after crop.
4. **Check legality** — shapely/pyproj intersection (metric CRS) vs protected areas, the
   coastal public-domain setback, and permitted-quarry zones. The coastal setback is
   measured from the **imagery's own NDWI shoreline** when running live (locally accurate),
   with a static coastline layer as the offline proxy.
5. **Dossier** — a one-page PDF (reportlab) with before/after, coords, area, evidence.
6. **Alert** — a drafted message for human review (never auto-sent).

The agent narrates each step. Offline it runs a deterministic orchestration
(`run_agent`); online an LLM selects and sequences the same tools via tool use
(`run_agent_with_llm`).

## LLM provider — Claude *or* Gemini (pluggable)

The vision classifier and the tool-use orchestrator run on either provider, auto-detected
from which key is set (`config.LLM_PROVIDER`, override with `RAQEEB_LLM`):

- **Claude** (Anthropic — `ANTHROPIC_API_KEY`) — the **default**; `claude-sonnet-4-6`.
- **Gemini** (free, Google AI Studio — `GEMINI_API_KEY`) — used only when no Anthropic
  key is set; `gemini-2.5-flash` by default.

Both providers drive the same paths — vision classify, an adversarial second opinion, and a
streaming tool-use agent run. A free-tier 429 backoff is built in for Gemini's per-minute limit.

Keys live in a gitignored `.env` (copy `.env.example`); `scripts/run_server.py` and
`scripts/run_live_agent.py` load it at startup (stdlib loader, no extra dependency).

## Setup

Windows, Python 3.12 in a local venv:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

`requirements.txt` covers offline + live + UI (numpy/scipy/shapely/pyproj/matplotlib/
reportlab/pillow, `earthengine-api`, `anthropic`, `google-genai`, `streamlit` +
`streamlit-folium`).

## Run it

```powershell
# Offline (no keys, no network) — synthetic imagery, real pipeline:
./.venv/Scripts/python.exe scripts/run_demo.py          # quarry demo + dossier PDF
./.venv/Scripts/python.exe -m pytest -q                 # 10 tests (detection, legality, modes, harness)
./.venv/Scripts/streamlit run app/streamlit_app.py      # jury UI: draw a zone on the map, pick mode, run

# Accuracy harness — precision/recall per mode:
./.venv/Scripts/python.exe scripts/eval_accuracy.py                       # offline synthetic sanity set
./.venv/Scripts/python.exe scripts/eval_accuracy.py --live --project <P>  # real sites (heuristic; add --llm for vision)
```

### Cinematic demo (web player)

A polished, unbreakable stage demo that plays a pre-generated run:

```powershell
# 1. Build run bundles (offline synthetic; or --live --project <P> for real imagery)
./.venv/Scripts/python.exe scripts/build_demo_run.py
# 2. Serve and open http://localhost:8000
./.venv/Scripts/python.exe scripts/serve_demo.py
```

Orbital-Command UI: press ▶ Run for the auto-played perceive→reason→act sequence
(space = pause, ←/→ = step, Replay = restart). Switch sites with the picker.

## Run with Docker

The watchroom runs in a container — **offline by default** (cached real cases + the
synthetic pipeline, no keys, no network), with an opt-in **live** profile for real
Sentinel-2 + Claude.

```powershell
# Offline (no keys, no network):
docker compose --profile offline up --build      # http://localhost:8000

# Live (real Sentinel-2 + Claude): copy .env.example -> .env and fill in
# ANTHROPIC_API_KEY, EARTHENGINE_PROJECT and EARTHENGINE_CREDS, then:
docker compose --profile live up --build
```

Both profiles serve http://localhost:8000 and bind the same port, so run one at a time —
a bare `docker compose up` starts nothing on purpose; pick a profile. Or use the image
directly:

```powershell
docker build -t raqeeb .
docker run --rm -p 8000:8000 raqeeb               # offline
```

The offline image is lean; the live profile builds with `INSTALL_LIVE=1`, which adds
`google-genai` + `earthengine-api` (deliberately not in `requirements.txt`) and mounts the
credentials from `earthengine authenticate` read-only. See the `Dockerfile` header and
`.env.example` for the full live setup.

## Going live

1. **Earth Engine**: `./.venv/Scripts/earthengine.exe authenticate`, then a Google Cloud
   project with the Earth Engine API enabled + the project registered (set `EARTHENGINE_PROJECT`).
2. **LLM key**: `setx ANTHROPIC_API_KEY "..."` (the live default) or `setx GEMINI_API_KEY "..."` (free fallback).
3. `RAQEEB_OFFLINE=0`. See `.env.example`.

Scout / verify on real imagery:

```powershell
# Save before/after RGB + detection summary for an AOI (no LLM needed):
./.venv/Scripts/python.exe scripts/scout_aoi.py --bbox <minlon minlat maxlon maxlat> `
  --before 2018-05-01..2018-09-30 --after 2024-05-01..2024-09-30 --mode quarry --project <P>

# Full LLM-orchestrated run on a real AOI:
./.venv/Scripts/python.exe scripts/run_live_agent.py --bbox ... --mode coastal --project <P>
```

### Verified live (Claude)

- **Quarry** — Ain Dara, Mount Lebanon (`35.708,33.758,35.724,33.773`, 2018→2024): 1.82 ha
  bare-rock expansion → `quarry_expansion` → "outside any permitted zone".
- **Coastal** — Jounieh waterfront (`35.60,33.96,35.64,34.00`, 2018→2024): 2.4 ha shoreline
  change extending into the water → `coastal_construction` → "within the coastal public-domain setback".
- **Accuracy (10 real sites):** precision 1.0 · recall 0.8 · F1 0.89 (quarry + coastal).
  *Labels are imagery-derived, not yet field-verified — the onsite-verdict loop supplies that
  ground truth. Expand `data/eval_sites.json` to strengthen.*

## Project layout

```
raqeeb/
  config.py    models.py    geo.py        llm.py
  imagery.py   detect.py    classify.py   evaluate.py
  legality.py  dossier.py   alert.py      agent.py
data/reference/  protected_areas / coastline / permitted_quarries (GeoJSON)
data/eval_sites.json   labelled validation set for the accuracy harness
scripts/  run_demo.py  scout_aoi.py  run_live_agent.py  eval_accuracy.py
app/streamlit_app.py     tests/test_pipeline.py     CLAUDE.md
```

## Responsible use & honest limits

- Every output is a **candidate for human verification**, never a legal verdict; the agent
  never names individuals and never sends an alert automatically.
- The legal boundaries are **proxies** — the coastline is an approximate hand-traced layer
  (live coastal uses the NDWI shoreline instead), permitted-quarry zones are seeded, and
  zoning is unavailable. Confirm against official cadastral records.
- 10 m imagery resolves quarries and large coastal structures, not single small buildings.
- The offline heuristic classifier can mislabel a coastal change's *type* (the setback rule
  still flags it); the LLM vision path labels it correctly.

## Extending to more modes

A detector is a function returning `ChangeRegion`s; register it in `detect._DETECTORS`
keyed by mode. The rest of the pipeline (classify → legality → dossier → alert → agent)
is unchanged. See `raqeeb-feature-spec.md` §4 for the mode catalogue
(deforestation, burn-then-build, illegal dumping, river encroachment).
