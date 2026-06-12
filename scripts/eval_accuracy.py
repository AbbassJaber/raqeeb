#!/usr/bin/env python
r"""Report Raqeeb's precision/recall per detection mode over a labelled site set.

Offline (default) runs the deterministic synthetic sanity sites — no keys, no network:

    ./.venv/Scripts/python.exe scripts/eval_accuracy.py

Live runs the real sites in the manifest (those without 'truth_imagery'); needs Earth
Engine auth + a project, and an LLM key for vision classification:

    ./.venv/Scripts/python.exe scripts/eval_accuracy.py --live --project raqeeb-498718
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fmt(x):
    return "  n/a" if x is None else f"{x:5.2f}"


def main():
    ap = argparse.ArgumentParser(description="Accuracy harness for Raqeeb.")
    ap.add_argument("--sites", default=None, help="path to a sites manifest JSON")
    ap.add_argument("--live", action="store_true", help="fetch real Sentinel-2 imagery")
    ap.add_argument("--llm", action="store_true",
                    help="classify with the vision LLM (default: fast heuristic, no rate limits)")
    ap.add_argument("--project", default=None, help="Earth Engine Google Cloud project id")
    args = ap.parse_args()

    if args.live:
        os.environ["RAQEEB_OFFLINE"] = "0"
        if args.project:
            os.environ["EARTHENGINE_PROJECT"] = args.project

    from raqeeb import evaluate  # noqa: E402  (import after env is set)

    sites = evaluate.load_sites(args.sites)
    results = evaluate.evaluate(sites, live=args.live, use_llm=args.llm)

    print(f"\n=== Per-site ({'LIVE' if args.live else 'OFFLINE synthetic'}) ===")
    print(f"{'site':<46} {'mode':<8} {'truth':<6} {'pred':<6} {'label':<20} ok")
    for r in results:
        if r.skipped:
            print(f"{r.name:<46} {r.mode:<8} {'-':<6} {'-':<6} {'(skipped: live-only)':<20}  -")
            continue
        truth = "VIOL" if r.expected else "clean"
        pred = "VIOL" if r.predicted else "clean"
        ok = "Y" if r.expected == r.predicted else "N"
        print(f"{r.name:<46} {r.mode:<8} {truth:<6} {pred:<6} {str(r.label):<20}  {ok}")

    m = evaluate.metrics(results)
    print("\n=== Scores ===")
    print(f"{'group':<10} {'n':>3} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3}  "
          f"{'prec':>6} {'recall':>6} {'f1':>6} {'acc':>6}")
    for group in ["overall"] + [g for g in m if g != "overall"]:
        s = m[group]
        print(f"{group:<10} {s['n']:>3} {s['tp']:>3} {s['fp']:>3} {s['fn']:>3} {s['tn']:>3}  "
              f"{_fmt(s['precision'])} {_fmt(s['recall'])} {_fmt(s['f1'])} {_fmt(s['accuracy'])}")

    if not args.live:
        print("\nNote: OFFLINE numbers validate the harness + pipeline logic on synthetic "
              "sites (perfect by construction). Real-world accuracy requires real labelled "
              "sites in the manifest, run with --live.")


if __name__ == "__main__":
    main()
