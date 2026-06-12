#!/usr/bin/env python
r"""Run the LIVE Claude-orchestrated agent end-to-end on a real AOI.

Exercises step 1 + step 2 together: live Sentinel-2 fetch -> Claude vision
classification -> legality -> dossier -> drafted (not sent) alert, with Claude
sequencing the tools itself.

    ./.venv/Scripts/earthengine.exe authenticate     # once
    # one LLM key (don't commit it): GEMINI_API_KEY (free, AI Studio) or ANTHROPIC_API_KEY
    ./.venv/Scripts/python.exe scripts/run_live_agent.py `
        --bbox 35.708 33.758 35.724 33.773 `
        --before 2018-05-01..2018-09-30 --after 2024-05-01..2024-09-30 `
        --project raqeeb-498718 --name "Ain Dara"
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _env import load_env  # noqa: E402

load_env()  # populate os.environ from .env before raqeeb.config reads it


def main():
    ap = argparse.ArgumentParser(description="Run the live Claude-orchestrated Raqeeb agent.")
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--before", required=True, help="before window, e.g. 2018-05-01..2018-09-30")
    ap.add_argument("--after", required=True, help="after window, e.g. 2024-05-01..2024-09-30")
    ap.add_argument("--grid", type=int, default=256)
    ap.add_argument("--mode", default="quarry", choices=["quarry", "coastal"])
    ap.add_argument("--project", default=None, help="Google Cloud project id for Earth Engine")
    ap.add_argument("--name", default="Live AOI")
    ap.add_argument("--deterministic", action="store_true",
                    help="use run_agent (deterministic) instead of the Claude orchestrator")
    args = ap.parse_args()

    has_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not has_key:
        sys.exit("No LLM key found. Set ANTHROPIC_API_KEY or GEMINI_API_KEY, then retry.")

    os.environ["RAQEEB_OFFLINE"] = "0"
    if args.project:
        os.environ["EARTHENGINE_PROJECT"] = args.project

    from raqeeb import config  # noqa: E402
    from raqeeb.agent import run_agent, run_agent_with_llm  # noqa: E402

    scenario = {
        "name": args.name, "mode": args.mode, "bbox": tuple(args.bbox),
        "before_window": args.before, "after_window": args.after,
        "grid": args.grid, "nearest_place": args.name,
    }

    runner = run_agent if args.deterministic else run_agent_with_llm
    mode = "deterministic" if args.deterministic else f"{config.LLM_PROVIDER}-orchestrated"
    print(f"Running {mode} agent on {args.name} {tuple(args.bbox)} (LIVE) …\n")
    narration, finding = runner(scenario)

    print("=== AGENT NARRATION ===")
    for i, line in enumerate(narration, 1):
        print(f"[{i}] {line}\n")

    print("=== FINDING ===")
    if finding is None:
        print("No finding produced.")
        return
    print(f"  area:      {finding.region.area_ha} ha")
    print(f"  centroid:  {finding.region.centroid[1]:.5f} N, {finding.region.centroid[0]:.5f} E")
    print(f"  class:     {finding.classification.label} "
          f"({finding.classification.confidence}; {finding.classification.source})")
    print(f"  candidate violation: {finding.is_violation}")
    print(f"  flags:     {finding.flags}")
    print(f"  dossier:   {finding.dossier_path}")


if __name__ == "__main__":
    main()
