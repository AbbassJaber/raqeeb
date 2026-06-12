#!/usr/bin/env python
r"""Scout / verify a real AOI with LIVE Sentinel-2 imagery.

Fetches cloud-masked before/after composites for a bounding box, saves true-colour
RGB PNGs so you can eyeball whether the change is visible, and prints clear-pixel
coverage plus a detection summary. Use it to confirm step 1 works on a real site
and to scout candidate AOIs.

    ./.venv/Scripts/earthengine.exe authenticate         # once
    ./.venv/Scripts/python.exe scripts/scout_aoi.py `
        --bbox 35.655 33.735 35.675 33.755 `
        --before 2018-05-01..2018-09-30 --after 2024-05-01..2024-09-30 `
        --project YOUR_GCP_PROJECT --name "Ain Dara"

Outputs: outputs/scout_before.png, outputs/scout_after.png
"""
import argparse
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser(description="Scout/verify a real AOI with live Sentinel-2.")
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--before", required=True, help="before window, e.g. 2018-05-01..2018-09-30")
    ap.add_argument("--after", required=True, help="after window, e.g. 2024-05-01..2024-09-30")
    ap.add_argument("--grid", type=int, default=256, help="pixels per side (~10 m each)")
    ap.add_argument("--mode", default="quarry", choices=["quarry", "coastal"])
    ap.add_argument("--project", default=None, help="Google Cloud project id for Earth Engine")
    ap.add_argument("--name", default="Scouted AOI")
    args = ap.parse_args()

    # Force the online path before importing config (it reads env at import time).
    os.environ["RAQEEB_OFFLINE"] = "0"
    if args.project:
        os.environ["EARTHENGINE_PROJECT"] = args.project

    from raqeeb import config, imagery, detect  # noqa: E402

    scenario = {
        "name": args.name, "mode": args.mode, "bbox": tuple(args.bbox),
        "before_window": args.before, "after_window": args.after,
        "grid": args.grid, "nearest_place": args.name,
    }

    print(f"Fetching live Sentinel-2 for {args.name} {tuple(args.bbox)} "
          f"({args.before}  vs  {args.after}) …")
    before, after = imagery.get_composites(scenario)

    out = config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    for tag, comp in (("before", before), ("after", after)):
        cov = float((comp["B8"] > 0).mean())
        plt.imsave(out / f"scout_{tag}.png", imagery.to_rgb(comp))
        print(f"  {tag}: clear-pixel coverage {cov:.0%}  ->  outputs/scout_{tag}.png")

    regions = detect.detect(before, after, scenario)
    print(f"\nDetected {len(regions)} change region(s):")
    for r in regions[:5]:
        print(f"  {r.id}: {r.area_ha} ha @ {r.centroid[1]:.4f} N, {r.centroid[0]:.4f} E "
              f"(NDVI drop {r.ndvi_drop}, BSI rise {r.bsi_rise})")
    if not regions:
        print("  (none above thresholds — try a different window/season or a larger zone)")


if __name__ == "__main__":
    main()
