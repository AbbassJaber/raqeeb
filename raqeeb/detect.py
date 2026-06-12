"""Change detection via spectral index differencing.

Quarry signature: vegetation loss (NDVI drop) AND bare-soil/rock gain (BSI rise).
Real numpy maths — identical whether the arrays come from synthetic imagery or
from Sentinel-2.
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage

from . import config
from .geo import pixel_to_lonlat, pixel_bbox_to_geo
from .models import ChangeRegion


def ndvi(bands: dict[str, np.ndarray]) -> np.ndarray:
    nir, red = bands["B8"], bands["B4"]
    return (nir - red) / (nir + red + 1e-6)


def bsi(bands: dict[str, np.ndarray]) -> np.ndarray:
    swir, red, nir, blue = bands["B11"], bands["B4"], bands["B8"], bands["B2"]
    return ((swir + red) - (nir + blue)) / ((swir + red) + (nir + blue) + 1e-6)


def ndwi(bands: dict[str, np.ndarray]) -> np.ndarray:
    """Normalised Difference Water Index — high over water, low over land/built."""
    green, nir = bands["B3"], bands["B8"]
    return (green - nir) / (green + nir + 1e-6)


def _extract_regions(mask: np.ndarray, ndvi_drop: np.ndarray,
                     bsi_rise: np.ndarray, scenario: dict) -> list[ChangeRegion]:
    """Label a boolean change mask into ChangeRegions (shared by all detection modes)."""
    grid, bbox = scenario["grid"], scenario["bbox"]
    labels, n = ndimage.label(mask)
    pixel_area_ha = (config.PIXEL_M ** 2) / 10_000.0

    regions: list[ChangeRegion] = []
    for lab in range(1, n + 1):
        sel = labels == lab
        area_ha = float(sel.sum()) * pixel_area_ha
        if area_ha < config.MIN_AREA_HA:
            continue
        rows, cols = np.where(sel)
        r0, r1, c0, c1 = int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())
        cr, cc = float(rows.mean()), float(cols.mean())
        regions.append(ChangeRegion(
            id=f"R{lab:03d}",
            area_ha=round(area_ha, 2),
            centroid=tuple(round(v, 6) for v in pixel_to_lonlat(cr, cc, grid, bbox)),
            geo_bbox=tuple(round(v, 6) for v in pixel_bbox_to_geo((r0, c0, r1, c1), grid, bbox).bounds),
            pixel_bbox=(r0, c0, r1, c1),
            ndvi_drop=round(float(ndvi_drop[sel].mean()), 3),
            bsi_rise=round(float(bsi_rise[sel].mean()), 3),
        ))
    regions.sort(key=lambda r: r.area_ha, reverse=True)
    return regions


def detect_changes(before: dict, after: dict, scenario: dict) -> list[ChangeRegion]:
    """Quarry signal: vegetation loss AND bare-rock/bare-soil gain."""
    ndvi_drop = ndvi(before) - ndvi(after)
    bsi_rise = bsi(after) - bsi(before)
    mask = (ndvi_drop > config.NDVI_DROP_MIN) & (bsi_rise > config.BSI_RISE_MIN)
    return _extract_regions(mask, ndvi_drop, bsi_rise, scenario)


def detect_coastal_changes(before: dict, after: dict, scenario: dict) -> list[ChangeRegion]:
    """Coastal-encroachment signal: new built-up/bare surface (BSI rise) replacing
    water OR vegetation (NDWI drop OR NDVI drop) — i.e. sea-reclamation or
    beach/vegetation built over. Legality (the coastal setback) is applied downstream."""
    ndvi_drop = ndvi(before) - ndvi(after)
    bsi_rise = bsi(after) - bsi(before)
    ndwi_drop = ndwi(before) - ndwi(after)
    built_gain = bsi_rise > config.BSI_RISE_MIN
    lost_natural = (ndwi_drop > config.NDWI_DROP_MIN) | (ndvi_drop > config.NDVI_DROP_MIN)
    return _extract_regions(built_gain & lost_natural, ndvi_drop, bsi_rise, scenario)


def _sea_mask(after: dict) -> np.ndarray:
    """Largest connected open-water body in the scene (NDWI > 0) — i.e. the sea."""
    water = ndwi(after) > 0.0
    labels, n = ndimage.label(water)
    if n == 0:
        return water
    counts = np.bincount(labels.ravel())
    counts[0] = 0  # background
    return labels == int(counts.argmax())


def within_sea_setback(region: ChangeRegion, after: dict, scenario: dict,
                       setback_m: float | None = None) -> bool:
    """True if the region lies within the coastal setback of open water detected in
    the imagery itself (NDWI land/water boundary). Locally accurate and self-contained
    — no external coastline layer needed. Returns False when the scene has no real sea."""
    setback_m = config.COASTAL_SETBACK_M if setback_m is None else setback_m
    sea = _sea_mask(after)
    if sea.mean() < 0.01:                       # essentially no water in view
        return False
    px = max(1, round(setback_m / config.PIXEL_M))
    near_shore = ndimage.binary_dilation(sea, iterations=px) & ~sea
    r0, c0, r1, c1 = region.pixel_bbox
    zone = np.zeros(sea.shape, dtype=bool)
    zone[r0:r1 + 1, c0:c1 + 1] = True
    return bool((near_shore & zone).any())


# Mode registry — add a detector here to make it available to the agent.
_DETECTORS = {"quarry": detect_changes, "coastal": detect_coastal_changes}


def detect(before: dict, after: dict, scenario: dict) -> list[ChangeRegion]:
    """Dispatch to the detector for scenario['mode'] (defaults to quarry)."""
    return _DETECTORS.get(scenario.get("mode", "quarry"), detect_changes)(before, after, scenario)
