#!/usr/bin/env python
"""Re-render every cached case's evidence dossier with the current layout — from the
saved finding.json + run.json (second opinion) + existing before/after viz. No LLM/GEE.

    ./.venv/Scripts/python.exe scripts/refresh_dossiers.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raqeeb import dossier, config  # noqa: E402
from raqeeb.models import ChangeRegion, Classification, Finding  # noqa: E402

RUNS = config.ROOT / "web" / "runs"


def _finding(d: dict) -> Finding:
    r, c = d["region"], d["classification"]
    region = ChangeRegion(id=r["id"], area_ha=r["area_ha"], centroid=tuple(r["centroid"]),
                          geo_bbox=tuple(r["geo_bbox"]), pixel_bbox=tuple(r["pixel_bbox"]),
                          ndvi_drop=r["ndvi_drop"], bsi_rise=r["bsi_rise"])
    cls = Classification(label=c["label"], confidence=c["confidence"],
                         reasoning=c.get("reasoning", ""), source=c.get("source", "heuristic"))
    return Finding(region=region, classification=cls, flags=d.get("flags", []),
                   nearest_place=d.get("nearest_place", ""), mode=d.get("mode", "quarry"),
                   detected_window=d.get("detected_window", ""), dossier_path=d.get("dossier_path"))


if __name__ == "__main__":
    for dd in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        fj, rj = dd / "finding.json", dd / "run.json"
        if not (fj.exists() and rj.exists()):
            continue
        fnd = _finding(json.loads(fj.read_text(encoding="utf-8")))
        second = json.loads(rj.read_text(encoding="utf-8")).get("second_opinion")
        viz = dd / f"{fnd.region.id}_before_after.png"
        if not viz.exists():
            print("skip (no viz):", dd.name); continue
        p = dossier.build_dossier(fnd, viz, dd, second)
        print(f"refreshed {dd.name} -> {p.name} | 2nd opinion: {bool(second)}")
