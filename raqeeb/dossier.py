"""Evidence dossier: a before/after visual plus a one-page PDF."""
from __future__ import annotations
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from . import config
from .imagery import to_rgb
from .models import Finding

_INK = colors.HexColor("#13243A")
_CORAL = colors.HexColor("#D85A30")
_MUTED = colors.HexColor("#5B6B7B")


def render_before_after(before: dict, after: dict, finding: Finding, out_dir: Path) -> Path:
    r0, c0, r1, c1 = finding.region.pixel_bbox
    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    for ax, bands, title in ((axes[0], before, "Before"), (axes[1], after, "After")):
        ax.imshow(to_rgb(bands))
        ax.set_title(title, fontsize=11)
        ax.set_xticks([]); ax.set_yticks([])
    axes[1].add_patch(Rectangle((c0, r0), c1 - c0, r1 - r0,
                                fill=False, edgecolor="#D85A30", lw=2, linestyle="--"))
    fig.tight_layout()
    out = Path(out_dir) / f"{finding.region.id}_before_after.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


_TIER_HEX = {"critical": "#e5484d", "high": "#ef8b3c", "medium": "#e0a83a", "low": "#57c59a"}


def _legal_basis(flags: list[str]) -> str:
    t = " ".join(flags).lower()
    if any(w in t for w in ("setback", "public-domain", "public domain", "maritime", "coastal")):
        return "Maritime public domain - 150 m setback from the coastline (proxy width)"
    if "protected" in t:
        return "Protected area - WDPA-designated (confirm exact boundary with the Ministry of Environment)"
    if "permit" in t:
        return "Outside any permitted quarry zone (permit layer is a proxy)"
    return "-"


def _field(c, label, value, y, width=78, max_lines=6):
    """Draw a label + (wrapped) value; return the new y."""
    lines = textwrap.wrap(str(value), width) or ["-"]
    c.setFillColor(_MUTED); c.setFont("Helvetica-Bold", 9)
    c.drawString(2 * cm, y, label)
    c.setFillColor(_INK); c.setFont("Helvetica", 9)
    for ln in lines[:max_lines]:
        c.drawString(5.2 * cm, y, ln)
        y -= 0.52 * cm
    return y - 0.12 * cm


def build_dossier(finding: Finding, viz_png: Path, out_dir: Path, second_opinion=None) -> Path:
    from . import severity
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"dossier_{finding.region.id}.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    W, H = A4
    sev = severity.score(finding)

    c.setFillColor(_CORAL); c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, H - 2 * cm, "RAQEEB · EVIDENCE DOSSIER")
    c.setFillColor(_INK); c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, H - 2.8 * cm,
                 "Candidate violation" if finding.is_violation else "Detected change")
    c.setFillColor(colors.HexColor(_TIER_HEX.get(sev["tier"], "#5B6B7B")))
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(W - 2 * cm, H - 2.7 * cm, f"SEVERITY {sev['tier'].upper()} · {sev['score']}/100")

    c.drawImage(str(viz_png), 2 * cm, H - 11 * cm, width=W - 4 * cm,
                height=7.2 * cm, preserveAspectRatio=True, anchor="n")

    a = finding.region.area_ha
    factors = ", ".join(f"{f['label']} +{f['points']}" for f in sev.get("factors", [])[:3])
    y = H - 11.8 * cm
    y = _field(c, "Location", finding.nearest_place or "-", y)
    y = _field(c, "Coordinates",
               f"{finding.region.centroid[1]:.5f} N, {finding.region.centroid[0]:.5f} E", y)
    y = _field(c, "Change area", f"{a} ha  ({round(a * 10000):,} m2)", y)
    y = _field(c, "Window", finding.detected_window, y)
    y = _field(c, "Type", f"{finding.classification.label} (confidence "
               f"{finding.classification.confidence:.2f}; {finding.classification.source})", y)
    y = _field(c, "Evidence", f"NDVI drop {finding.region.ndvi_drop}, "
               f"BSI rise {finding.region.bsi_rise}", y)
    y = _field(c, "Severity", f"{sev['tier']} {sev['score']}/100 - {factors}", y)
    y = _field(c, "Flags", "; ".join(finding.flags) or "none", y)
    y = _field(c, "Legal basis", _legal_basis(finding.flags), y)
    if second_opinion:
        y = _field(c, "2nd opinion",
                   f"{second_opinion.get('verdict', '')} - {second_opinion.get('reason', '')}", y)
    y = _field(c, "Reasoning", finding.classification.reasoning, y)

    c.setFillColor(_MUTED); c.setFont("Helvetica-Oblique", 8)
    c.drawString(2 * cm, 1.6 * cm,
                 "Candidate for human verification. Not a legal determination. "
                 "Boundaries are proxies; confirm against official records.")
    c.showPage(); c.save()
    return pdf_path
