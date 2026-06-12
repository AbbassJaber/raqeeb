#!/usr/bin/env python
"""(Re)build real-imagery bundles. Run with RAQEEB_OFFLINE=0 + EE project (+ a Gemini
key and --llm for real vision labels).

    RAQEEB_OFFLINE=0 EARTHENGINE_PROJECT=<proj> GEMINI_API_KEY=<key> \
        ./.venv/Scripts/python.exe scripts/build_real_sites.py --llm
    # or specific ids:  ... scripts/build_real_sites.py --llm bourj-hammoud costa-brava
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("EARTHENGINE_PROJECT", "raqeeb-498718")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raqeeb import democache, config  # noqa: E402

USE_LLM = "--llm" in sys.argv
IDS = [a for a in sys.argv[1:] if not a.startswith("--")] or \
      ["bourj-hammoud", "costa-brava", "jbeil-hills", "ain-dara", "jounieh"]

if __name__ == "__main__":
    print(f"OFFLINE={config.OFFLINE} provider={config.LLM_PROVIDER} llm={USE_LLM} ids={IDS}")
    for sid in IDS:
        run = democache.build_run(democache.SCENARIOS[sid], use_llm=USE_LLM)
        s, c = run["severity"], run["classification"]
        print(f"  {sid}: {c['label']} ({c['source']}) | {run['region']['area_ha']}ha "
              f"| sev {s['tier']} {s['score']} | overlays {len(run['overlays'])} | flags {run['flags']}")
