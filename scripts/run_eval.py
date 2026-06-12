"""Run the accuracy harness and report precision / recall / F1.

  Offline (synthetic sanity set):
      ./.venv/Scripts/python.exe scripts/run_eval.py
  Live (REAL labelled sites — needs Earth Engine auth + RAQEEB_OFFLINE=0):
      EARTHENGINE_PROJECT=raqeeb-498718 RAQEEB_OFFLINE=0 \
        ./.venv/Scripts/python.exe scripts/run_eval.py --live

Add --llm to classify with the configured vision model instead of the deterministic
heuristic (slower; uses the LLM free-tier quota). The deterministic run is the
reproducible headline number. Writes data/eval_report.json.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raqeeb import config, evaluate  # noqa: E402


def _fmt(x):
    return "—" if x is None else f"{x:.2f}"


def main() -> int:
    live = "--live" in sys.argv
    use_llm = "--llm" in sys.argv
    sites = evaluate.load_sites()
    mode_label = "LIVE (real Sentinel-2)" if live else "OFFLINE (synthetic)"
    clf = "vision LLM" if use_llm else "deterministic heuristic"
    print(f"Accuracy harness · {mode_label} · classifier: {clf}")
    print(f"{len(sites)} sites in the labelled set\n")

    results = evaluate.evaluate(sites, live=live, use_llm=use_llm)

    hdr = f"{'site':<46}{'mode':<9}{'truth':<7}{'pred':<7}{'label':<18}ok"
    print(hdr); print("-" * len(hdr))
    for r in results:
        if r.skipped:
            continue
        ok = "OK " if r.expected == r.predicted else "XX "
        print(f"{r.name[:45]:<46}{r.mode:<9}"
              f"{('viol' if r.expected else 'clean'):<7}"
              f"{('viol' if r.predicted else 'clean'):<7}"
              f"{str(r.label or '-')[:17]:<18}{ok}")

    m = evaluate.metrics(results)
    o = m["overall"]
    print(f"\nConfusion (n={o['n']}):  TP={o['tp']}  FP={o['fp']}  FN={o['fn']}  TN={o['tn']}")
    print(f"Precision={_fmt(o['precision'])}  Recall={_fmt(o['recall'])}  "
          f"F1={_fmt(o['f1'])}  Accuracy={_fmt(o['accuracy'])}")
    for mode in [k for k in m if k != "overall"]:
        s = m[mode]
        print(f"  [{mode}] n={s['n']} P={_fmt(s['precision'])} R={_fmt(s['recall'])} F1={_fmt(s['f1'])}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "live" if live else "offline",
        "classifier": clf,
        "offline_flag": config.OFFLINE,
        "metrics": m,
        "sites": [
            {"name": r.name, "mode": r.mode, "expected": r.expected,
             "predicted": r.predicted, "label": r.label, "skipped": r.skipped}
            for r in results
        ],
        "note": "Labels are expert assessment from visible Sentinel-2 change + known context, "
                "not field-verified. Deterministic detector+legality first-pass (no AI second "
                "opinion, no human review) unless --llm.",
    }
    out = config.ROOT / "data" / "eval_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
