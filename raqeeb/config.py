"""Central configuration for the Raqeeb agent.

Anything an operator might tune lives here. The demo runs fully offline using
synthetic imagery; flip OFFLINE to False (and provide credentials) to wire in
Google Earth Engine + the Anthropic API in your own environment.
"""
from __future__ import annotations
import os
from pathlib import Path

# --- runtime mode -----------------------------------------------------------
# Offline = synthetic imagery + heuristic classifier (no network, no keys).
# Online  = Sentinel-2 via Earth Engine + Claude vision/orchestration.
OFFLINE = os.getenv("RAQEEB_OFFLINE", "1") != "0"

# --- model ------------------------------------------------------------------
# Verify the current model string at https://docs.claude.com/en/api/overview
CLAUDE_MODEL = os.getenv("RAQEEB_MODEL", "claude-sonnet-4-6")

# Which LLM backs the vision classifier + tool-use orchestrator: "claude" | "gemini".
# Claude is the default. Auto-detects Gemini only when a Gemini/Google key is set and
# no Anthropic key is present. Override explicitly with RAQEEB_LLM.
LLM_PROVIDER = (os.getenv("RAQEEB_LLM")
                or ("gemini" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
                    and not os.getenv("ANTHROPIC_API_KEY") else "claude")).lower()
# Gemini free tier (Google AI Studio). gemini-3.5-flash also works if available.
GEMINI_MODEL = os.getenv("RAQEEB_GEMINI_MODEL", "gemini-2.5-flash")

# --- reviewer handoff (human-in-the-loop; alerts are NEVER auto-sent) --------
# A drafted alert is routed to a human reviewer only on an explicit human action.
# Transport: "outbox" (default, writes to OUTPUT_DIR/outbox, no creds) | "email" | "webhook".
REVIEW_TRANSPORT = os.getenv("RAQEEB_REVIEW_TRANSPORT", "outbox").lower()
REVIEWER_EMAIL = os.getenv("RAQEEB_REVIEWER_EMAIL")
REVIEW_WEBHOOK = os.getenv("RAQEEB_REVIEW_WEBHOOK")
SMTP_HOST = os.getenv("RAQEEB_SMTP_HOST")
SMTP_PORT = int(os.getenv("RAQEEB_SMTP_PORT", "587"))
SMTP_USER = os.getenv("RAQEEB_SMTP_USER")
SMTP_PASSWORD = os.getenv("RAQEEB_SMTP_PASSWORD")

# --- earth engine (online imagery) ------------------------------------------
# Run `earthengine authenticate` once; modern Earth Engine also requires a
# Google Cloud project id passed to ee.Initialize(project=...).
EE_PROJECT = os.getenv("EARTHENGINE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
# Collection ids confirmed current in the GEE data catalog (2026-06).
S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"             # harmonized L2A surface reflectance
CLOUD_SCORE_COLLECTION = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
CLOUD_SCORE_BAND = "cs_cdf"        # cumulative clear-pixel score
CLOUD_SCORE_CLEAR_MIN = 0.60       # keep pixels with score >= this (0.50-0.65 typical)
SCENE_CLOUD_MAX = 60               # drop very cloudy scenes before compositing
SR_SCALE = 10000.0                 # Sentinel-2 SR is scaled by 10000 -> divide for 0..1

# --- paths ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "data" / "reference"
OUTPUT_DIR = ROOT / "outputs"

# --- geospatial -------------------------------------------------------------
METRIC_CRS = "EPSG:32636"      # UTM zone 36N — correct for Lebanon
COASTAL_SETBACK_M = 150        # proxy for the public maritime domain
PIXEL_M = 10                   # Sentinel-2 ground sample distance

# Ad-hoc scans (drawn zone / NL "scan …") must stay near PIXEL_M resolution so detection
# quality + area math hold and the fetch stays fast. Cap the side, and derive the grid to
# keep ~PIXEL_M ground sampling instead of a fixed grid over an arbitrarily large area.
SCAN_MAX_KM = 5.0              # reject zones wider than this (≈ 500 px at 10 m)
SCAN_GRID_MIN = 96
SCAN_GRID_MAX = 512

# --- detection thresholds ---------------------------------------------------
NDVI_DROP_MIN = 0.25           # vegetation loss
BSI_RISE_MIN = 0.10            # bare-soil / bare-rock / built-up gain
NDWI_DROP_MIN = 0.15           # water loss (sea/beach -> land), coastal mode
MIN_AREA_HA = 0.5              # ignore specks below this

# --- demo scenario ----------------------------------------------------------
# A synthetic quarry case, positioned to straddle the eastern edge of the real
# Al-Shouf Cedar Nature Reserve (WDPA), so the legality check is grounded in a real
# protected boundary: the reserve covers ~75% of the AOI (where the synthetic quarry
# lands) and its edge crosses the scene. Imagery is synthetic; the boundary is real.
DEMO_SCENARIO = {
    "name": "Al-Shouf Cedar Reserve edge — quarry (synthetic demo)",
    "mode": "quarry",
    "bbox": (35.7245, 33.6908, 35.7461, 33.7089),   # (min_lon, min_lat, max_lon, max_lat)
    "before_window": "2019-05-01..2019-09-30",
    "after_window": "2024-05-01..2024-09-30",
    "grid": 200,                              # pixels per side (200 * 10 m = 2 km)
    "nearest_place": "Barouk, Chouf (Mount Lebanon)",
}

# A synthetic coastal-encroachment case. The bbox straddles the reference coastline
# near the Jounieh vertex (~35.62, 33.98) so the synthetic shoreline build lands
# inside the public-domain setback.
COASTAL_DEMO_SCENARIO = {
    "name": "Lebanese coast (synthetic demo)",
    "mode": "coastal",
    "bbox": (35.6105, 33.97, 35.6305, 33.99),
    "before_window": "2019-05-01..2019-09-30",
    "after_window": "2024-05-01..2024-09-30",
    "grid": 200,
    "nearest_place": "Jounieh coast (demo)",
}
