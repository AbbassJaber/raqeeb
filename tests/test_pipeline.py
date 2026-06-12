"""Tests for the detection and legality logic (run: pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shapely.geometry import box, Point
from raqeeb import config, imagery, detect, legality
from raqeeb.classify import classify_heuristic


def _run_detection():
    before, after = imagery.synthesize_quarry(config.DEMO_SCENARIO["grid"])
    return detect.detect_changes(before, after, config.DEMO_SCENARIO)


def test_detects_one_region():
    regions = _run_detection()
    assert len(regions) >= 1
    r = regions[0]
    assert r.area_ha > config.MIN_AREA_HA
    assert r.ndvi_drop > config.NDVI_DROP_MIN
    assert r.bsi_rise > config.BSI_RISE_MIN


def test_centroid_inside_aoi():
    r = _run_detection()[0]
    w, s, e, n = config.DEMO_SCENARIO["bbox"]
    lon, lat = r.centroid
    assert w <= lon <= e and s <= lat <= n


def test_legality_flags_quarry_violation():
    r = _run_detection()[0]
    layers = legality.load_layers()
    flags = legality.check_legality(box(*r.geo_bbox), looks_like_quarry=True, layers=layers)
    assert any("permitted" in f for f in flags)
    assert any("protected" in f for f in flags)


def test_far_from_coast():
    r = _run_detection()[0]
    layers = legality.load_layers()
    assert legality.distance_to_coast_m(Point(r.centroid), layers) > 1000


def test_classifier_labels_quarry():
    r = _run_detection()[0]
    cls = classify_heuristic(r, distance_to_coast_m=13000)
    assert cls.label == "quarry_expansion"
    assert 0 <= cls.confidence <= 1


# --- coastal encroachment mode ----------------------------------------------

def _run_coastal():
    before, after = imagery.synthesize_coastal(config.COASTAL_DEMO_SCENARIO["grid"])
    return detect.detect_coastal_changes(before, after, config.COASTAL_DEMO_SCENARIO)


def test_coastal_detects_region():
    regions = _run_coastal()
    assert len(regions) >= 1
    assert regions[0].area_ha > config.MIN_AREA_HA


def test_coastal_within_setback():
    r = _run_coastal()[0]
    layers = legality.load_layers()
    # Coastal construction is not a quarry, so only the setback rule should trigger.
    flags = legality.check_legality(box(*r.geo_bbox), looks_like_quarry=False, layers=layers)
    assert any("setback" in f for f in flags)


def test_coastal_near_coast():
    r = _run_coastal()[0]
    layers = legality.load_layers()
    assert legality.distance_to_coast_m(Point(r.centroid), layers) < 300


def test_mode_dispatch_routes_coastal():
    before, after = imagery.synthesize_coastal(config.COASTAL_DEMO_SCENARIO["grid"])
    assert detect.detect(before, after, config.COASTAL_DEMO_SCENARIO)  # non-empty


# --- accuracy harness -------------------------------------------------------

def test_accuracy_harness_offline_perfect_on_synthetic():
    from raqeeb import evaluate
    sites = evaluate.load_sites()
    results = evaluate.evaluate(sites, live=False)
    scored = [r for r in results if not r.skipped]
    assert len(scored) >= 4
    m = evaluate.metrics(results)
    # Synthetic sanity set is separable by construction: no false positives/negatives.
    assert m["overall"]["fp"] == 0 and m["overall"]["fn"] == 0
    assert m["overall"]["precision"] == 1.0 and m["overall"]["recall"] == 1.0


# --- cinematic demo bundle --------------------------------------------------

def test_democache_build_offline(tmp_path):
    from raqeeb import democache
    scenario = democache.SCENARIOS["quarry-demo"]
    run = democache.build_run(scenario, out_root=tmp_path)

    # required keys present
    for key in ("id", "title", "mode", "windows", "images", "region",
                "classification", "flags", "narration", "dossier", "generated_at"):
        assert key in run, f"missing {key}"

    grid = run["images"]["grid"]
    r0, c0, r1, c1 = run["region"]["pixel_bbox"]
    assert 0 <= r0 <= r1 <= grid and 0 <= c0 <= c1 <= grid
    assert isinstance(run["flags"], list) and run["flags"]          # quarry demo flags
    assert run["classification"]["label"] == "quarry_expansion"

    run_dir = tmp_path / "quarry-demo"
    assert (run_dir / "run.json").exists()
    assert (run_dir / "before.png").exists()
    assert (run_dir / "after.png").exists()
    assert list(run_dir.glob("dossier_*.pdf")), "dossier PDF not written"

    import json
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert any(r["id"] == "quarry-demo" for r in manifest["runs"])
    assert manifest["default"] == "quarry-demo"


# --- live progress + reviewer handoff ---------------------------------------

def test_run_agent_emits_steps_in_order(tmp_path):
    from raqeeb.agent import run_agent
    stages = []
    narration, finding = run_agent(config.DEMO_SCENARIO, out_dir=tmp_path,
                                   on_step=lambda stage, line, data: stages.append(stage))
    assert finding is not None
    assert stages == ["start", "imagery", "detect", "classify", "legality", "dossier", "alert"]


def test_send_to_reviewer_outbox_and_gate(tmp_path):
    import pytest
    from raqeeb import alert
    from raqeeb.agent import run_agent
    _, finding = run_agent(config.DEMO_SCENARIO, out_dir=tmp_path)
    # human-approval gate: refuses without reviewed=True
    with pytest.raises(PermissionError):
        alert.send_to_reviewer(finding, out_root=tmp_path / "outbox")
    msg = alert.send_to_reviewer(finding, reviewed=True, transport="outbox",
                                 out_root=tmp_path / "outbox")
    box = tmp_path / "outbox" / finding.region.id
    assert (box / "alert.txt").exists()
    assert (box / "finding.json").exists()
    assert "reviewer" in msg.lower()


def test_severity_score_ranks_and_explains(tmp_path):
    from raqeeb import severity
    from raqeeb.agent import run_agent
    _, finding = run_agent(config.DEMO_SCENARIO, out_dir=tmp_path)  # quarry: protected + permit flags
    s = severity.score(finding)
    assert 0 <= s["score"] <= 100
    assert s["tier"] in ("low", "medium", "high", "critical")
    assert s["factors"] and all("label" in f and "points" in f for f in s["factors"])
    # the flagged quarry violation (protected + outside-permit + large) should rank high
    assert s["score"] >= 55 and s["tier"] in ("high", "critical")


def test_timeseries_onset_in_bundle(tmp_path):
    from raqeeb import democache
    run = democache.build_run(democache.SCENARIOS["quarry-demo"], out_root=tmp_path)
    ts = run.get("timeseries")
    assert ts and ts["onset"] == 2021            # the configured/detected onset year
    areas = [s["area_ha"] for s in ts["series"]]
    assert areas[0] < 0.5 and areas[-1] > areas[0]   # stable, then grows
    assert (tmp_path / "quarry-demo" / "year_2024.png").exists()


def test_bundle_has_reference_overlays(tmp_path):
    from raqeeb import democache
    run = democache.build_run(democache.SCENARIOS["quarry-demo"], out_root=tmp_path)
    assert "overlays" in run
    # the quarry demo AOI overlaps the (synthetic) protected polygon
    assert any(o["type"] == "protected" for o in run["overlays"])
    # clipped to the AOI, every point is a stage percentage within ~[0, 100]
    for o in run["overlays"]:
        assert o["kind"] in ("polygon", "line") and len(o["points"]) >= 2
        for x, y in o["points"]:
            assert -1 <= x <= 101 and -1 <= y <= 101
