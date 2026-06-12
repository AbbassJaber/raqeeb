#!/usr/bin/env python
"""Build the real coastal-landfill bundles (live Sentinel-2). Run with RAQEEB_OFFLINE=0.

    RAQEEB_OFFLINE=0 EARTHENGINE_PROJECT=<proj> ./.venv/Scripts/python.exe scripts/build_real_coastal.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("EARTHENGINE_PROJECT", "raqeeb-498718")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raqeeb import democache, config  # noqa: E402

USE_LLM = "--llm" in sys.argv

if __name__ == "__main__":
    print("OFFLINE =", config.OFFLINE, "| provider =", config.LLM_PROVIDER, "| use_llm =", USE_LLM)
    for sid in ("bourj-hammoud", "costa-brava"):
        run = democache.build_run(democache.SCENARIOS[sid], use_llm=USE_LLM)
        s = run["severity"]
        print(f"{sid}: {run['classification']['label']} | {run['region']['area_ha']} ha "
              f"| flags={run['flags']} | severity {s['tier']} {s['score']} | src {run['provider']}")
