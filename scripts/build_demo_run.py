#!/usr/bin/env python
r"""Build cinematic-demo run bundles into web/runs/.

Offline (no keys) — synthetic demo sites:
    ./.venv/Scripts/python.exe scripts/build_demo_run.py

Live (real Sentinel-2; needs EE auth + project, optional --llm for Gemini labels):
    ./.venv/Scripts/python.exe scripts/build_demo_run.py ain-dara jounieh --live --project raqeeb-498718
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser(description="Build cinematic-demo run bundles.")
    ap.add_argument("scenarios", nargs="*", help="named scenarios (see --list)")
    ap.add_argument("--live", action="store_true", help="fetch real Sentinel-2")
    ap.add_argument("--llm", action="store_true", help="classify with the vision LLM")
    ap.add_argument("--project", default=None, help="Earth Engine project id")
    ap.add_argument("--list", action="store_true", help="list scenario names and exit")
    args = ap.parse_args()

    if args.live:
        os.environ["RAQEEB_OFFLINE"] = "0"
        if args.project:
            os.environ["EARTHENGINE_PROJECT"] = args.project

    from raqeeb import democache  # import after env is set

    if args.list:
        print("scenarios:", ", ".join(democache.SCENARIOS))
        return

    names = args.scenarios or (["ain-dara", "jounieh"] if args.live
                               else ["quarry-demo", "coastal-demo"])
    for name in names:
        if name not in democache.SCENARIOS:
            sys.exit(f"unknown scenario '{name}'. Try --list.")
        print(f"Building '{name}' ({'live' if args.live else 'offline'}) …")
        try:
            run = democache.build_run(democache.SCENARIOS[name], use_llm=args.llm)
        except ValueError as exc:
            print(f"  SKIPPED: {exc}")
            continue
        print(f"  {run['region']['area_ha']} ha · {run['classification']['label']} "
              f"({run['classification']['source']}) · flags={run['flags']}")
    print("Done. Serve with:  ./.venv/Scripts/python.exe scripts/serve_demo.py")


if __name__ == "__main__":
    main()
