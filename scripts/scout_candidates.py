#!/usr/bin/env python
"""Scout several candidate 'dramatic' real AOIs at once with live Sentinel-2.

Saves outputs/scout_<slug>_before.png / _after.png for eyeballing, and prints
clear-pixel coverage + a detection summary per site. Edit CANDIDATES and re-run
to home in on the most visually striking before/after.
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.environ["RAQEEB_OFFLINE"] = "0"
os.environ.setdefault("EARTHENGINE_PROJECT", "raqeeb-498718")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BEFORE = "2017-04-01..2017-10-31"   # earlier baseline catches more expansion
AFTER = "2024-05-01..2024-09-30"

# Quarry candidates: vegetated Mount-Lebanon hillsides that may have been carved out.
CANDIDATES = [
    ("kfardebian", "Kfardebian belt", "quarry", (35.742, 33.998, 35.772, 34.024)),
    ("mayrouba", "Mayrouba / Kesrouan", "quarry", (35.770, 34.010, 35.795, 34.035)),
    ("aley", "Aley / Btekhnay", "quarry", (35.610, 33.770, 35.640, 33.795)),
    ("jbeil-hills", "Jbeil hinterland", "quarry", (35.665, 34.095, 35.695, 34.120)),
]


def main():
    from raqeeb import config, imagery, detect  # noqa: E402
    out = config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    for slug, name, mode, bbox in CANDIDATES:
        scenario = {"name": name, "mode": mode, "bbox": tuple(bbox),
                    "before_window": BEFORE, "after_window": AFTER,
                    "grid": 256, "nearest_place": name}
        print(f"\n=== {name} {bbox} [{mode}] ===")
        try:
            before, after = imagery.get_composites(scenario)
        except Exception as e:
            print("  fetch failed:", repr(e)[:200])
            continue
        for tag, comp in (("before", before), ("after", after)):
            cov = float((comp["B8"] > 0).mean())
            plt.imsave(out / f"scout_{slug}_{tag}.png", imagery.to_rgb(comp))
            print(f"  {tag}: clear {cov:.0%} -> outputs/scout_{slug}_{tag}.png")
        try:
            regions = detect.detect(before, after, scenario)
            print(f"  detected {len(regions)} region(s):", end=" ")
            print("; ".join(f"{r.area_ha}ha (NDVI-{r.ndvi_drop}, BSI+{r.bsi_rise})"
                            for r in regions[:3]) or "none above thresholds")
        except Exception as e:
            print("  detect failed:", repr(e)[:160])


if __name__ == "__main__":
    main()
