#!/usr/bin/env python
"""Run the full Raqeeb agent on the demo scenario and print its reasoning trace.

    python scripts/run_demo.py

Offline by default (synthetic imagery, no API key). Produces a dossier PDF in outputs/.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raqeeb import config  # noqa: E402
from raqeeb.agent import run_agent  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Run the Raqeeb agent on a demo scenario.")
    ap.add_argument("--coastal", action="store_true",
                    help="run the coastal-encroachment demo instead of quarry")
    args = ap.parse_args()
    scenario = config.COASTAL_DEMO_SCENARIO if args.coastal else config.DEMO_SCENARIO
    narration, finding = run_agent(scenario)
    print("\n=== AGENT REASONING TRACE ===")
    for i, line in enumerate(narration, 1):
        print(f"\n[{i}] {line}")
    print("\n=== FINDING ===")
    if finding is None:
        print("No change detected.")
        return
    print(f"  area:        {finding.region.area_ha} ha")
    print(f"  centroid:    {finding.region.centroid[1]:.5f} N, {finding.region.centroid[0]:.5f} E")
    print(f"  class:       {finding.classification.label} ({finding.classification.confidence})")
    print(f"  violation:   {finding.is_violation}")
    print(f"  flags:       {finding.flags}")
    print(f"  dossier:     {finding.dossier_path}")


if __name__ == "__main__":
    main()
