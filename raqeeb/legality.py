"""Legality assessment.

Turns "a change" into "a candidate violation" by intersecting the change polygon
with reference layers. All geometry is done in a metric CRS. Protected areas are the
real WDPA layer and the coastline is the real national boundary; the permit layer is
still a proxy and the 150 m setback is a proxy width — so every result is a CANDIDATE
for human review, never a verdict.
"""
from __future__ import annotations
import json
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.geometry.base import BaseGeometry

from . import config
from .geo import to_metric, distance_m, to_wgs84


def _load(path: Path) -> BaseGeometry | None:
    if not path.exists():
        return None
    gj = json.loads(path.read_text(encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in gj.get("features", []) if f.get("geometry")]
    return unary_union(geoms) if geoms else None


def _load_named(path: Path) -> list[dict]:
    """Load features individually so a candidate can be named (e.g. the specific
    reserve it overlaps), not just tested against a merged geometry."""
    if not path.exists():
        return []
    gj = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for f in gj.get("features", []):
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if g.is_empty:
            continue
        out.append({"geom": g, "props": f.get("properties", {})})
    return out


def load_layers(reference_dir: Path | None = None) -> dict:
    d = Path(reference_dir or config.REFERENCE_DIR)
    named = _load_named(d / "protected_areas.geojson")
    protected = unary_union([n["geom"] for n in named]) if named else None
    return {
        "protected": protected,
        "protected_named": named,
        "coastline": _load(d / "coastline.geojson"),
        "permitted": _load(d / "permitted_quarries.geojson"),
    }


def _protected_flag(rp_metric, named: list[dict]) -> str | None:
    """If the (metric) region overlaps any protected area, return a named, human-readable
    flag — preferring a specific reserve name over a generic designation."""
    hits: list[tuple[int, str]] = []
    for n in named:
        if rp_metric.intersects(to_metric(n["geom"])):
            props = n["props"]
            name_en = props.get("name_en")
            desig = props.get("desig") or "protected area"
            if name_en:
                hits.append((0, f"overlaps {name_en} (protected area)"))
            else:
                hits.append((1, f"overlaps a protected area ({desig})"))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])   # specific reserve names first
    return hits[0][1]


def setback_polygon(layers: dict, setback_m: float | None = None):
    """The coastal public-domain setback as a lon/lat polygon (the buffered coastline),
    for display overlays. Returns None if there's no coastline layer."""
    coast = layers.get("coastline")
    if coast is None:
        return None
    m = config.COASTAL_SETBACK_M if setback_m is None else setback_m
    return to_wgs84(to_metric(coast).buffer(m))


def distance_to_coast_m(centroid_geom, layers: dict) -> float:
    coast = layers.get("coastline")
    if coast is None:
        return float("inf")
    return distance_m(centroid_geom, coast)


def check_legality(region_polygon, looks_like_quarry: bool, layers: dict) -> list[str]:
    """Return a list of named, human-readable candidate-violation flags."""
    flags: list[str] = []
    rp = to_metric(region_polygon)

    named = layers.get("protected_named")
    if named:
        pf = _protected_flag(rp, named)
        if pf:
            flags.append(pf)
    else:
        protected = layers.get("protected")
        if protected is not None and rp.intersects(to_metric(protected)):
            flags.append("overlaps a protected area")

    coast = layers.get("coastline")
    if coast is not None:
        setback = to_metric(coast).buffer(config.COASTAL_SETBACK_M)
        if rp.intersects(setback):
            flags.append("within the coastal public-domain setback")

    permitted = layers.get("permitted")
    if looks_like_quarry:
        if permitted is None or not rp.intersects(to_metric(permitted)):
            flags.append("quarry-like change outside any permitted zone")

    return flags


def assess_flags(region, after: dict, scenario: dict,
                 looks_like_quarry: bool, layers: dict) -> list[str]:
    """Full candidate-violation flag set for a region: the geometry-based rules plus,
    for coastal mode, an imagery-derived setback check (the actual NDWI shoreline),
    which is more accurate than the coarse static coastline proxy on real imagery."""
    from shapely.geometry import box as _box
    from . import detect

    flags = check_legality(_box(*region.geo_bbox), looks_like_quarry, layers)
    if scenario.get("mode") == "coastal" and not any("setback" in f for f in flags):
        if detect.within_sea_setback(region, after, scenario):
            flags.append("within the coastal public-domain setback")
    return flags
