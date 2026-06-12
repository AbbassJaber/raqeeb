"""Build a cached 'run bundle' for the cinematic web demo (web/runs/<id>/).

Reuses the live pipeline (imagery -> detect -> classify -> legality -> dossier) on a
single fetched before/after pair and serialises exactly what the static player needs:
run.json + before.png + after.png + the dossier PDF. No interface changes to the
pipeline — this module only consumes it.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import Point, box as _box

from . import config, imagery, detect, classify, legality, dossier, severity
from .models import Finding

WEB_RUNS = config.ROOT / "web" / "runs"


class NoChangeDetected(ValueError):
    """Raised when detection finds no change. A valid negative result, not a failure —
    build_run has already emitted the before/after imagery and a 'nochange' stage, so
    callers should treat this as 'done with no finding', NOT surface it as an error."""

# Named demo scenarios. Synthetic ones build offline with no keys; ain-dara/jounieh
# need --live (real Sentinel-2). Each carries id/title/name for the bundle + narration.
SCENARIOS = {
    "quarry-demo": {**config.DEMO_SCENARIO, "id": "quarry-demo",
                    "title": "Al-Shouf reserve edge · quarry (synthetic)",
                    "timeseries": {"years": [2018, 2019, 2020, 2021, 2022, 2023, 2024],
                                   "onset": 2021}},
    "coastal-demo": {**config.COASTAL_DEMO_SCENARIO, "id": "coastal-demo",
                     "title": "Lebanese coast (synthetic)"},
    "ain-dara": {"id": "ain-dara", "name": "Ain Dara, Mount Lebanon",
                 "title": "Ain Dara · Mount Lebanon", "mode": "quarry",
                 "bbox": (35.708, 33.758, 35.724, 33.773),
                 "before_window": "2018-05-01..2018-09-30",
                 "after_window": "2024-05-01..2024-09-30",
                 "grid": 256, "nearest_place": "Ain Dara, Mount Lebanon"},
    "jounieh": {"id": "jounieh", "name": "Jounieh waterfront",
                "title": "Jounieh waterfront · Mount Lebanon", "mode": "coastal",
                "bbox": (35.600, 33.960, 35.640, 34.000),
                "before_window": "2018-05-01..2018-09-30",
                "after_window": "2024-05-01..2024-09-30",
                "grid": 400, "nearest_place": "Jounieh coast"},
    # Real, recognizable coastal sea-reclamation (Lebanon's 2015 waste crisis). 2017
    # baseline catches the fill growing into the sea; needs --live (real Sentinel-2).
    "bourj-hammoud": {"id": "bourj-hammoud", "name": "Bourj Hammoud sea landfill",
                      "title": "Bourj Hammoud · sea landfill", "mode": "coastal",
                      "bbox": (35.540, 33.894, 35.564, 33.914),
                      "before_window": "2017-04-01..2017-10-31",
                      "after_window": "2024-05-01..2024-09-30",
                      "grid": 256, "nearest_place": "Bourj Hammoud, Beirut"},
    "costa-brava": {"id": "costa-brava", "name": "Costa Brava coastal landfill",
                    "title": "Costa Brava · coastal landfill", "mode": "coastal",
                    "bbox": (35.468, 33.806, 35.490, 33.824),
                    "before_window": "2017-04-01..2017-10-31",
                    "after_window": "2024-05-01..2024-09-30",
                    "grid": 256, "nearest_place": "Costa Brava, south Beirut"},
    "jbeil-hills": {"id": "jbeil-hills", "name": "Jbeil hinterland quarries",
                    "title": "Jbeil hinterland · quarrying", "mode": "quarry",
                    "bbox": (35.665, 34.095, 35.695, 34.120),
                    "before_window": "2017-04-01..2017-10-31",
                    "after_window": "2024-05-01..2024-09-30",
                    "grid": 256, "nearest_place": "Jbeil (Byblos) hinterland"},
}


def _save_png(bands: dict, path: Path) -> None:
    rgb = (np.clip(imagery.to_rgb(bands), 0, 1) * 255).astype("uint8")
    img = Image.fromarray(rgb)
    # display only: smoothly upscale small composites (e.g. a small drawn zone) so the
    # hero image never looks blocky. Detection/area use the raw arrays, so they're unaffected.
    if min(img.size) < 512:
        scale = 512 / min(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.BICUBIC)
    img.save(path)


def _pt(lon: float, lat: float, bbox) -> list:
    """Map a lon/lat to [x%, y%] of the stage (row 0 = top = max latitude)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return [round((lon - min_lon) / (max_lon - min_lon) * 100, 2),
            round((max_lat - lat) / (max_lat - min_lat) * 100, 2)]


def _rings(geom, bbox) -> list:
    """Clip a lon/lat geometry to the AOI and return polylines as %-of-stage point lists."""
    clipped = geom.intersection(_box(*bbox))
    rings: list = []

    def walk(g):
        gt = g.geom_type
        if gt == "Polygon":
            rings.append([_pt(x, y, bbox) for x, y in g.exterior.coords])
        elif gt == "LineString":
            rings.append([_pt(x, y, bbox) for x, y in g.coords])
        elif gt in ("MultiPolygon", "MultiLineString", "GeometryCollection"):
            for sub in g.geoms:
                walk(sub)

    if not clipped.is_empty:
        walk(clipped)
    return rings


def _overlays(scenario: dict, layers: dict) -> list:
    """Reference-layer boundaries that fall inside the AOI, as stage-% polygons/lines, so
    the player can draw the protected area / setback / permit zone the change crosses."""
    bbox = scenario["bbox"]
    out = []
    for key in ("protected", "permitted"):
        g = layers.get(key)
        if g is not None:
            out += [{"type": key, "kind": "polygon", "points": ring} for ring in _rings(g, bbox)]
    if layers.get("coastline") is not None:
        band = legality.setback_polygon(layers)
        if band is not None:
            out += [{"type": "setback", "kind": "polygon", "points": ring}
                    for ring in _rings(band, bbox)]
        out += [{"type": "coast", "kind": "line", "points": ring}
                for ring in _rings(layers["coastline"], bbox)]
    return out


def _mask_contour_rings(mask, grid: int) -> list:
    """Trace a boolean mask's boundary into stage-% polylines (row 0 = top)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure()
    rings = []
    try:
        cs = plt.contour(mask.astype(float), levels=[0.5])
        segs = cs.allsegs[0] if cs.allsegs else []
        for seg in segs:
            if len(seg) >= 4:
                rings.append([[round(float(x) / (grid - 1) * 100, 2),
                               round(float(y) / (grid - 1) * 100, 2)] for x, y in seg])
    finally:
        plt.close(fig)
    return rings


def _coastal_overlays(before: dict, grid: int) -> list:
    """Shoreline + public-domain setback derived from the BEFORE image's sea (NDWI),
    so they align exactly with the displayed composite — and the setback band the
    landfill encroached past is the *earlier* (pre-reclamation) shore."""
    from scipy import ndimage
    from . import detect
    sea = detect._sea_mask(before)
    if sea.mean() < 0.01:
        return []
    px = max(1, round(config.COASTAL_SETBACK_M / config.PIXEL_M))
    setback = ndimage.binary_dilation(sea, iterations=px)
    out = [{"type": "coast", "kind": "line", "points": r} for r in _mask_contour_rings(sea, grid)]
    out += [{"type": "setback-line", "kind": "line", "points": r}
            for r in _mask_contour_rings(setback, grid)]
    return out


_VERDICT_WORD = {"confirm": "confirmed", "downgrade": "downgraded", "reject": "flagged as likely false"}


def _narration(scenario: dict, region, cls, flags: list[str], second: dict | None = None) -> list[str]:
    lat, lon = region.centroid[1], region.centroid[0]
    classify_line = f"Classified as {cls.label} (confidence {cls.confidence}; {cls.source})."
    if second:
        classify_line += (f" Second opinion: {_VERDICT_WORD.get(second['verdict'], second['verdict'])}"
                          + (f" — {second['reason']}" if second.get("reason") else "") + ".")
    return [
        f"Monitoring {scenario.get('name', scenario['title'])} — "
        f"{scenario['before_window']} vs {scenario['after_window']}.",
        "Pulled before/after composites and aligned them (same-season, cloud-masked).",
        f"Detected {region.area_ha} ha of change at {lat:.4f} N, {lon:.4f} E "
        f"(NDVI drop {region.ndvi_drop}, BSI rise {region.bsi_rise}).",
        classify_line,
        "Legality check: " + ("; ".join(flags) if flags else "no rule triggered") + ".",
        "Compiled the evidence dossier.",
        "Drafted an alert for human review — not sent.",
    ]


def build_run(scenario: dict, out_root: Path = WEB_RUNS, use_llm: bool = False,
              on_step=None) -> dict:
    """Run the pipeline on one before/after pair and write web/runs/<id>/. Returns the run dict.

    Offline vs live is controlled by config.OFFLINE (set RAQEEB_OFFLINE before import for live).

    ``on_step(stage, payload)`` — if given — is called as each pipeline stage completes
    ("start", "imagery", "detect", "classify", "legality", "dossier", "done") so the live
    player can stream the agent's real progress into its cinematic beats. Default None
    keeps the offline bundle builder and its tests behaviourally identical.
    """
    def emit(stage: str, **payload):
        if on_step:
            on_step(stage, payload)

    name = scenario.get("name", scenario.get("title", scenario["id"]))
    scenario = {**scenario, "name": name}
    run_dir = Path(out_root) / scenario["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    emit("start", id=scenario["id"], title=scenario.get("title", name),
         mode=scenario.get("mode", "quarry"),
         windows={"before": scenario["before_window"], "after": scenario["after_window"]})

    ts_cfg = scenario.get("timeseries")
    stack = None
    if ts_cfg and config.OFFLINE:
        stack = imagery.synthesize_quarry_series(int(scenario["grid"]),
                                                 ts_cfg["years"], ts_cfg["onset"])
        before, after = stack[ts_cfg["years"][0]], stack[ts_cfg["years"][-1]]
    else:
        before, after = imagery.get_composites(scenario)
    # write the display composites first so the stream can show them immediately
    _save_png(before, run_dir / "before.png")
    _save_png(after, run_dir / "after.png")
    emit("imagery", before="before.png", after="after.png", grid=int(scenario["grid"]),
         provider=("synthetic" if config.OFFLINE else "Sentinel-2 (GEE)"))

    regions = detect.detect(before, after, scenario)
    if not regions:
        # A clean negative is a valid result, not an error: the before/after composites
        # are already shown (emit("imagery") above). Signal "no change" without raising so
        # the player keeps the map visible instead of covering it with an error overlay.
        emit("nochange", message="No significant change detected in this zone/window.",
             windows={"before": scenario["before_window"], "after": scenario["after_window"]})
        raise NoChangeDetected(f"No change detected for '{scenario['id']}' — pick a clearer AOI/window.")
    region = regions[0]
    region_d = {"id": region.id, "pixel_bbox": list(region.pixel_bbox),
                "area_ha": region.area_ha, "ndvi_drop": region.ndvi_drop,
                "bsi_rise": region.bsi_rise}
    emit("detect", region=region_d, centroid=[round(v, 6) for v in region.centroid])

    layers = legality.load_layers()
    dist = legality.distance_to_coast_m(Point(region.centroid), layers)
    if use_llm and not config.OFFLINE:
        cls = classify.classify(region, before, after, dist, scenario.get("mode"))
    else:
        cls = classify.classify_heuristic(region, dist, scenario.get("mode"))
    # adversarial second opinion (online only) — advisory: downgrade lowers confidence,
    # but we never auto-drop a candidate; a human decides.
    second = classify.second_opinion(cls, before, after, region) if (use_llm and not config.OFFLINE) else None
    if second and second["verdict"] == "downgrade":
        cls.confidence = round(min(cls.confidence, second["confidence"]), 2)
    cls_d = {"label": cls.label, "confidence": cls.confidence,
             "source": cls.source, "reasoning": cls.reasoning}
    emit("classify", classification=cls_d, second_opinion=second)

    flags = legality.assess_flags(region, after, scenario,
                                  cls.label == "quarry_expansion", layers)
    finding = Finding(region=region, classification=cls, flags=flags,
                      nearest_place=scenario.get("nearest_place", ""),
                      mode=scenario.get("mode", "quarry"),
                      detected_window=f"{scenario['before_window']} -> {scenario['after_window']}")
    sev = severity.score(finding)
    # coastal: shoreline/setback straight from the imagery (perfectly aligned); else the
    # reference protected/permit layers the inland change crosses.
    if scenario.get("mode") == "coastal":
        overlays = _coastal_overlays(before, int(scenario["grid"]))
    else:
        overlays = _overlays(scenario, layers)
    emit("legality", flags=flags, severity=sev, distance_to_coast_m=round(dist, 1),
         overlays=overlays)

    viz = dossier.render_before_after(before, after, finding, run_dir)
    finding.dossier_path = str(dossier.build_dossier(finding, viz, run_dir, second))
    emit("dossier", dossier=Path(finding.dossier_path).name)

    # 'change over time': offline uses the synthetic yearly stack; live fetches one
    # same-season Sentinel-2 composite per year. Never fatal — a finding stands on its own.
    timeseries = None
    if stack is not None:
        timeseries = _build_timeseries(stack, scenario, run_dir)
    elif not config.OFFLINE:
        try:
            live_stack = imagery.fetch_year_stack(scenario)
            if len(live_stack) >= 2:
                timeseries = _build_timeseries(live_stack, scenario, run_dir)
        except Exception:  # noqa: BLE001 - timeseries is a bonus, not the finding
            timeseries = None

    run = {
        "id": scenario["id"], "title": scenario.get("title", name),
        "mode": scenario.get("mode", "quarry"),
        "nearest_place": scenario.get("nearest_place", ""),
        "centroid": [round(v, 6) for v in region.centroid],
        "windows": {"before": scenario["before_window"], "after": scenario["after_window"]},
        "images": {"before": "before.png", "after": "after.png", "grid": int(scenario["grid"])},
        "region": region_d,
        "classification": cls_d,
        "flags": flags, "distance_to_coast_m": round(dist, 1),
        "severity": sev,
        "second_opinion": second,
        "overlays": overlays,
        "narration": _narration(scenario, region, cls, flags, second),
        "dossier": Path(finding.dossier_path).name,
        "provider": cls.source,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if timeseries is not None:
        run["timeseries"] = timeseries
    (run_dir / "run.json").write_text(json.dumps(run, indent=2))
    # persist the Finding so the review gate can prepare a reviewer alert later
    (run_dir / "finding.json").write_text(
        json.dumps(finding.to_dict(), indent=2, default=str))
    update_manifest(out_root)
    emit("done", run=run)
    return run


def assemble_from_state(scenario: dict, before, after, region, cls, flags, dist,
                        layers, out_root: Path = WEB_RUNS, second=None) -> dict:
    """Write a web bundle (pngs + dossier + run.json) from already-computed pipeline
    state — used by the agentic orchestrator, which produces this state via tool calls.
    Mirrors build_run's artifacts (no timeseries)."""
    run_dir = Path(out_root) / scenario["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    _save_png(before, run_dir / "before.png")
    _save_png(after, run_dir / "after.png")
    finding = Finding(region=region, classification=cls, flags=flags,
                      nearest_place=scenario.get("nearest_place", ""),
                      mode=scenario.get("mode", "quarry"),
                      detected_window=f"{scenario['before_window']} -> {scenario['after_window']}")
    viz = dossier.render_before_after(before, after, finding, run_dir)
    finding.dossier_path = str(dossier.build_dossier(finding, viz, run_dir, second))
    sev = severity.score(finding)
    overlays = (_coastal_overlays(before, int(scenario["grid"]))
                if scenario.get("mode") == "coastal" else _overlays(scenario, layers))
    run = {
        "id": scenario["id"], "title": scenario.get("title", scenario.get("name", scenario["id"])),
        "mode": scenario.get("mode", "quarry"), "nearest_place": scenario.get("nearest_place", ""),
        "centroid": [round(v, 6) for v in region.centroid],
        "windows": {"before": scenario["before_window"], "after": scenario["after_window"]},
        "images": {"before": "before.png", "after": "after.png", "grid": int(scenario["grid"])},
        "region": {"id": region.id, "pixel_bbox": list(region.pixel_bbox), "area_ha": region.area_ha,
                   "ndvi_drop": region.ndvi_drop, "bsi_rise": region.bsi_rise},
        "classification": {"label": cls.label, "confidence": cls.confidence,
                           "source": cls.source, "reasoning": cls.reasoning},
        "flags": flags, "distance_to_coast_m": round(dist, 1), "severity": sev,
        "second_opinion": second, "overlays": overlays,
        "narration": _narration(scenario, region, cls, flags, second),
        "dossier": Path(finding.dossier_path).name, "provider": cls.source,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # 'change over time': live per-year Sentinel-2 series (bonus — never fatal).
    if not config.OFFLINE:
        try:
            live_stack = imagery.fetch_year_stack(scenario)
            if len(live_stack) >= 2:
                run["timeseries"] = _build_timeseries(live_stack, scenario, run_dir)
        except Exception:  # noqa: BLE001
            pass
    (run_dir / "run.json").write_text(json.dumps(run, indent=2))
    (run_dir / "finding.json").write_text(json.dumps(finding.to_dict(), indent=2, default=str))
    update_manifest(out_root)
    return run


def _build_timeseries(stack: dict, scenario: dict, run_dir: Path) -> dict:
    """Per-year composites + change-area-vs-baseline series + onset year, for the scrubber."""
    years = sorted(stack)
    baseline = stack[years[0]]
    series, images = [], {}
    for y in years:
        _save_png(stack[y], run_dir / f"year_{y}.png")
        images[str(y)] = f"year_{y}.png"
        regions = detect.detect(baseline, stack[y], scenario)
        series.append({"year": y, "area_ha": round(sum(r.area_ha for r in regions), 2)})
    onset = next((s["year"] for s in series if s["area_ha"] >= config.MIN_AREA_HA), None)
    return {"years": years, "series": series, "onset": onset, "images": images}


def update_manifest(out_root: Path = WEB_RUNS) -> dict:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    runs = []
    for d in sorted(p for p in out_root.iterdir() if p.is_dir() and (p / "run.json").exists()):
        r = json.loads((d / "run.json").read_text())
        sev = r.get("severity") or {}
        grid = (r.get("images") or {}).get("grid") or 0
        runs.append({"id": r["id"], "title": r["title"], "mode": r["mode"],
                     "centroid": r.get("centroid"),               # [lon, lat] for the map pin
                     "tier": sev.get("tier"), "score": sev.get("score"),
                     "flags": len(r.get("flags") or []),
                     "area_ha": (r.get("region") or {}).get("area_ha"),
                     "aoi_km2": round((grid * config.PIXEL_M / 1000.0) ** 2, 1),
                     "review": (r.get("field_review") or {}).get("status"),
                     "generated_at": r.get("generated_at")})
    # default to the highest-severity run so the overview opens on the worst case
    default = max(runs, key=lambda x: x.get("score") or -1)["id"] if runs else None
    manifest = {"runs": runs, "default": default}
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
