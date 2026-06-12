"""Imagery acquisition.

Offline: synthesise two Sentinel-2-like band stacks (before/after) in which a
bare-rock quarry patch expands — enough to exercise the real detection maths.

Online: fetch cloud-free Sentinel-2 composites from Google Earth Engine. The
code is included and guarded; it runs only where `earthengine-api` is installed
and authenticated.
"""
from __future__ import annotations
import numpy as np

from . import config

# Reflectance signatures (B2 blue, B3 green, B4 red, B8 NIR, B11 SWIR)
_VEG = {"B2": 0.04, "B3": 0.07, "B4": 0.06, "B8": 0.36, "B11": 0.20}
_BARE = {"B2": 0.14, "B3": 0.18, "B4": 0.22, "B8": 0.26, "B11": 0.34}
_WATER = {"B2": 0.06, "B3": 0.07, "B4": 0.05, "B8": 0.02, "B11": 0.01}   # low NIR/SWIR -> high NDWI
_BANDS = ("B2", "B3", "B4", "B8", "B11")


def _disc(grid: int, radius: float) -> np.ndarray:
    yy, xx = np.ogrid[:grid, :grid]
    c = grid / 2.0
    return (yy - c) ** 2 + (xx - c) ** 2 <= radius ** 2


def _compose(grid: int, bare_mask: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    bands = {}
    for b in _BANDS:
        arr = np.where(bare_mask, _BARE[b], _VEG[b]).astype("float32")
        arr += rng.normal(0, 0.01, size=arr.shape).astype("float32")
        bands[b] = np.clip(arr, 0, 1)
    return bands


def synthesize_quarry(grid: int, r_before: float = 8, r_after: float = 22):
    """Return (before_bands, after_bands) dicts of HxW float arrays."""
    before = _compose(grid, _disc(grid, r_before), seed=1)
    after = _compose(grid, _disc(grid, r_after), seed=2)
    return before, after


def synthesize_quarry_series(grid: int, years: list[int], onset: int,
                             r0: float = 8, r1: float = 22) -> dict:
    """A yearly stack {year: bands}: a quarry stable at r0 until `onset`, then growing
    to r1 by the last year — so onset dating + an area-per-year trend are detectable."""
    last = years[-1]
    stack = {}
    for i, y in enumerate(years):
        if y < onset:
            r = r0
        else:
            frac = (y - onset) / max(1, last - onset)   # 0 at onset .. 1 at last year
            r = 11 + (r1 - 11) * frac                    # a clear jump at onset, then growth
        stack[y] = _compose(grid, _disc(grid, r), seed=20 + i)
    return stack


def _compose_coastal(grid: int, water_mask: np.ndarray, built_mask: np.ndarray,
                     seed: int) -> dict[str, np.ndarray]:
    """Compose bands from three materials: water, built (bare), else vegetation."""
    rng = np.random.default_rng(seed)
    bands = {}
    for b in _BANDS:
        arr = np.full((grid, grid), _VEG[b], dtype="float32")
        arr = np.where(water_mask, _WATER[b], arr)
        arr = np.where(built_mask, _BARE[b], arr)
        arr += rng.normal(0, 0.01, size=arr.shape).astype("float32")
        bands[b] = np.clip(arr, 0, 1)
    return bands


def synthesize_coastal(grid: int):
    """Synthesise a coastal scene where new construction appears at the shoreline.

    West (~left 45%) is sea; the rest is vegetated coast. In the AFTER image a
    built-up block appears straddling the shoreline — replacing both water
    (sea-reclamation) and vegetation — so NDWI and NDVI both drop while BSI rises.
    """
    sea = np.zeros((grid, grid), dtype=bool)
    sea[:, : int(grid * 0.45)] = True
    built = np.zeros((grid, grid), dtype=bool)
    built[int(grid * 0.40): int(grid * 0.62), int(grid * 0.40): int(grid * 0.55)] = True
    before = _compose_coastal(grid, sea, np.zeros_like(sea), seed=3)
    after = _compose_coastal(grid, sea & ~built, built, seed=4)
    return before, after


def synthesize_stable(grid: int):
    """A stable scene: vegetation in both epochs (only sensor noise differs) — a true
    negative for the accuracy harness (no change should be detected)."""
    empty = np.zeros((grid, grid), dtype=bool)
    return _compose(grid, empty, seed=5), _compose(grid, empty, seed=6)


def get_composites(scenario: dict):
    """Top-level entry point used by the agent. Returns (before_bands, after_bands)."""
    if config.OFFLINE:
        if scenario.get("mode") == "coastal":
            return synthesize_coastal(scenario["grid"])
        return synthesize_quarry(scenario["grid"])
    return _fetch_gee(scenario)


def _ee_init():  # pragma: no cover - requires GEE auth + network
    """Initialise Earth Engine, surfacing a clear, actionable error if unconfigured."""
    import ee
    try:
        if config.EE_PROJECT:
            ee.Initialize(project=config.EE_PROJECT)
        else:
            ee.Initialize()
    except Exception as exc:  # noqa: BLE001 - re-raise with guidance
        raise RuntimeError(
            "Earth Engine initialisation failed. Run `earthengine authenticate` "
            "once, then set EARTHENGINE_PROJECT to your Google Cloud project id "
            f"(ee.Initialize requires a project). Underlying error: {exc}"
        ) from exc
    return ee


def _window_sampler(scenario: dict):  # pragma: no cover - requires GEE auth + network
    """Build a ``sample(window) -> dict[band] -> grid x grid float32`` closure for one AOI.

    Shared by the before/after fetch and the per-year timeseries fetch so the GEE
    setup (init, AOI, cloud-score link, grid affine) is done once.

    Pixels are sampled on an EPSG:4326 grid aligned to the bbox, which makes the
    array map linearly to lon/lat (geo.pixel_to_lonlat stays exactly correct).
    All *geometry* (area, distance, intersection) is still done in EPSG:32636 by
    geo.py / legality.py — the sampling-grid CRS is a separate concern.

    Clouds are removed per-pixel via Cloud Score+ (linkCollection + updateMask)
    before the median, rather than relying only on a scene-level cloud-% filter.
    """
    ee = _ee_init()
    min_lon, min_lat, max_lon, max_lat = scenario["bbox"]
    grid = int(scenario["grid"])
    aoi = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
    cs = ee.ImageCollection(config.CLOUD_SCORE_COLLECTION)
    bands = list(_BANDS)

    def composite(window: str):
        start, end = window.split("..")
        col = (ee.ImageCollection(config.S2_COLLECTION)
               .filterBounds(aoi).filterDate(start, end)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", config.SCENE_CLOUD_MAX))
               .linkCollection(cs, [config.CLOUD_SCORE_BAND]))
        clear = col.map(lambda img: img.updateMask(
            img.select(config.CLOUD_SCORE_BAND).gte(config.CLOUD_SCORE_CLEAR_MIN)))
        return clear.select(bands).median().clip(aoi)

    # Affine for a grid x grid raster spanning the bbox; row 0 is the top (max lat).
    grid_spec = {
        "dimensions": {"width": grid, "height": grid},
        "affineTransform": {
            "scaleX": (max_lon - min_lon) / grid, "shearX": 0.0, "translateX": min_lon,
            "shearY": 0.0, "scaleY": -(max_lat - min_lat) / grid, "translateY": max_lat,
        },
        "crsCode": "EPSG:4326",
    }

    def sample(window: str) -> dict[str, np.ndarray]:
        rec = ee.data.computePixels({
            "expression": composite(window),
            "fileFormat": "NUMPY_NDARRAY",
            "bandIds": bands,
            "grid": grid_spec,
        })
        out = {}
        for b in bands:
            a = np.nan_to_num(np.asarray(rec[b], dtype="float32"), nan=0.0)
            out[b] = np.clip(a / config.SR_SCALE, 0.0, 1.0)
        return out

    return sample


def _fetch_gee(scenario: dict):  # pragma: no cover - requires GEE auth + network
    """Real Sentinel-2 path: same-season, cloud-masked median composites -> numpy.

    Returns (before_bands, after_bands), each a dict[band] -> grid x grid float32
    array of 0..1 reflectance — the SAME data contract as ``synthesize_quarry`` so
    detect.py / geo.py are unchanged.
    """
    sample = _window_sampler(scenario)
    before = sample(scenario["before_window"])
    after = sample(scenario["after_window"])

    # Guard against an AOI/date pair that yielded no clear imagery (all-masked
    # composites come back as zeros) — fail loudly rather than "detecting" noise.
    for label, comp in (("before", before), ("after", after)):
        valid = float((comp["B8"] > 0).mean())
        if valid < 0.1:
            raise RuntimeError(
                f"The {label} composite for {scenario['name']} has almost no clear "
                f"pixels ({valid:.0%}). Try a wider or different date window / season."
            )
    return before, after


def _season_from_window(window: str) -> tuple[str, str]:
    """The month-day season span of a 'YYYY-MM-DD..YYYY-MM-DD' window, e.g. ('05-01','09-30')."""
    start, end = window.split("..")
    return start[5:], end[5:]


def years_between(before_window: str, after_window: str) -> list[int]:
    """Inclusive list of years spanned by the before/after windows (for the timeseries)."""
    y0 = int(before_window[:4])
    y1 = int(after_window[:4])
    return list(range(min(y0, y1), max(y0, y1) + 1))


def fetch_year_stack(scenario: dict, years: list[int] | None = None) -> dict[int, dict]:  # pragma: no cover - GEE
    """Same-season composite per year -> {year: bands}, reusing the before-window's season.

    Lets the live player build a real 'change over time' series (per-year area vs the
    baseline year). Years default to every year spanned by before/after. Years that yield
    no clear imagery are skipped (not fatal — the series just omits them)."""
    years = years or years_between(scenario["before_window"], scenario["after_window"])
    mm_start, mm_end = _season_from_window(scenario["before_window"])
    sample = _window_sampler(scenario)   # one GEE setup; one fetch per year
    stack: dict[int, dict] = {}
    for y in years:
        bands = sample(f"{y}-{mm_start}..{y}-{mm_end}")
        if float((bands["B8"] > 0).mean()) >= 0.1:   # skip years with no clear imagery
            stack[y] = bands
    return stack


def to_rgb(bands: dict[str, np.ndarray]) -> np.ndarray:
    """A display-friendly true-colour image (HxWx3) from B4/B3/B2."""
    rgb = np.dstack([bands["B4"], bands["B3"], bands["B2"]]).astype("float32")
    hi = np.percentile(rgb, 99) or 1.0
    return np.clip(rgb / hi, 0, 1)
