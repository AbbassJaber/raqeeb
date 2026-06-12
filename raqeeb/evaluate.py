"""Accuracy harness.

Runs the detection → classification → legality pipeline over a labelled set of sites
and reports precision / recall / F1 per detection mode. Per the spec (D1), measured
accuracy on real sites is the single biggest credibility signal.

Offline sites carry a ``truth_imagery`` key (quarry | coastal | stable) and run
deterministically with no network/keys. Real sites omit it and are fetched live
(``live=True``) so the harness reports genuine accuracy once a real labelled set exists.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from shapely.geometry import Point, box

from . import config, imagery, detect, classify, legality

_SYNTH = {
    "quarry": imagery.synthesize_quarry,
    "coastal": imagery.synthesize_coastal,
    "stable": imagery.synthesize_stable,
}


@dataclass
class SiteResult:
    name: str
    mode: str
    expected: bool          # ground truth: should a candidate violation be flagged?
    predicted: bool         # did the pipeline flag one?
    label: Optional[str]    # classification label (or None if no change detected)
    skipped: bool = False   # offline run skips live-only sites (no truth_imagery)


def _scenario(site: dict) -> dict:
    return {
        "name": site["name"], "mode": site.get("mode", "quarry"),
        "bbox": tuple(site["bbox"]),
        "before_window": site["before_window"], "after_window": site["after_window"],
        "grid": int(site.get("grid", 200)), "nearest_place": site.get("nearest_place", ""),
    }


def predict(site: dict, live: bool = False, use_llm: bool = False):
    """Return (predicted_violation: bool, label: str|None), or None to skip the site.

    Classification defaults to the deterministic heuristic (fast, no rate limits) so a
    live multi-site run isn't throttled by the LLM free tier; pass use_llm=True to
    classify with the configured vision model instead.
    """
    scenario = _scenario(site)
    synth = site.get("truth_imagery")
    if live:
        if synth is not None:
            return None  # synthetic site; skipped in live runs
        before, after = imagery.get_composites(scenario)
    else:
        if synth is None:
            return None  # real/live-only site; skipped in offline runs
        before, after = _SYNTH[synth](scenario["grid"])

    regions = detect.detect(before, after, scenario)
    if not regions:
        return False, None
    region = regions[0]
    layers = legality.load_layers()
    dist = legality.distance_to_coast_m(Point(region.centroid), layers)
    if use_llm and not config.OFFLINE:
        cls = classify.classify(region, before, after, dist)
    else:
        cls = classify.classify_heuristic(region, dist)
    flags = legality.assess_flags(region, after, scenario, cls.label == "quarry_expansion", layers)
    return bool(flags), cls.label


def evaluate(sites: list[dict], live: bool = False, use_llm: bool = False) -> list[SiteResult]:
    results: list[SiteResult] = []
    for site in sites:
        expected = bool(site.get("expect_violation", False))
        out = predict(site, live=live, use_llm=use_llm)
        if out is None:
            results.append(SiteResult(site["name"], site.get("mode", "quarry"),
                                      expected, False, None, skipped=True))
            continue
        predicted, label = out
        results.append(SiteResult(site["name"], site.get("mode", "quarry"),
                                   expected, predicted, label))
    return results


def _scores(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs of (expected, predicted) -> confusion counts + precision/recall/F1/accuracy."""
    tp = sum(1 for e, p in pairs if e and p)
    fp = sum(1 for e, p in pairs if not e and p)
    fn = sum(1 for e, p in pairs if e and not p)
    tn = sum(1 for e, p in pairs if not e and not p)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    accuracy = (tp + tn) / len(pairs) if pairs else None
    return {"n": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy}


def metrics(results: list[SiteResult]) -> dict:
    """Per-mode and overall scores over the non-skipped results."""
    scored = [r for r in results if not r.skipped]
    out = {"overall": _scores([(r.expected, r.predicted) for r in scored])}
    for mode in sorted({r.mode for r in scored}):
        pairs = [(r.expected, r.predicted) for r in scored if r.mode == mode]
        out[mode] = _scores(pairs)
    return out


def load_sites(path: Path | None = None) -> list[dict]:
    path = Path(path or (config.ROOT / "data" / "eval_sites.json"))
    return json.loads(path.read_text()).get("sites", [])
