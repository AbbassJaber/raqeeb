"""Severity / triage scoring for a Finding.

A transparent 0..100 score so candidates can be ranked for a human reviewer (higher =
more urgent). Every contributing factor is returned, so the score is explainable — never
a black box — consistent with "candidate for verification, not a verdict".
"""
from __future__ import annotations

from .models import Finding

# Legal triggers dominate — they are *why* a change is a candidate at all. Matched by
# substring so named variants still score (e.g. "overlaps Al-Shouf Cedar Nature Reserve
# (protected area)" still earns the protected-area points).
_TIERS = [(80, "critical"), (55, "high"), (30, "medium"), (0, "low")]


def _flag_points(flag: str) -> float:
    f = flag.lower()
    if "protected area" in f:
        return 35
    if "setback" in f:
        return 30
    if "permitted zone" in f or "permit" in f:
        return 25
    return 15


def score(finding: Finding) -> dict:
    """Return {"score": 0..100, "tier": str, "factors": [{"label","points"}, ...]}."""
    r = finding.region
    factors: list[dict] = []

    for flag in finding.flags:
        factors.append({"label": flag, "points": _flag_points(flag)})

    # Size of the change (caps at 5 ha -> full 20 points).
    area_pts = round(min(r.area_ha / 5.0, 1.0) * 20, 1)
    factors.append({"label": f"change area {r.area_ha} ha", "points": area_pts})

    # Spectral signal strength (vegetation loss + bare/built gain).
    sig = max(0.0, r.ndvi_drop) + max(0.0, r.bsi_rise)
    factors.append({"label": f"signal strength (NDVI {r.ndvi_drop}, BSI {r.bsi_rise})",
                    "points": round(min(sig / 0.8, 1.0) * 15, 1)})

    # Classifier confidence.
    factors.append({"label": f"classifier confidence {finding.classification.confidence}",
                    "points": round(finding.classification.confidence * 10, 1)})

    total = round(min(100.0, sum(f["points"] for f in factors)), 1)
    tier = next(name for cut, name in _TIERS if total >= cut)
    return {"score": total, "tier": tier, "factors": factors}
