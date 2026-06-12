"""Classify a detected change.

Offline: a transparent spectral + geometric heuristic.
Online: Claude reasons over before/after image crops (the demo's "the AI looked
at it and figured it out" moment), with the heuristic as a deterministic fallback.
"""
from __future__ import annotations
import base64
import json
from io import BytesIO

import numpy as np

from . import config
from .models import ChangeRegion, Classification


def classify_heuristic(region: ChangeRegion, distance_to_coast_m: float,
                       mode: str | None = None) -> Classification:
    # coastal-mode runs already detect against the shoreline (imagery-derived sea mask),
    # so treat them as near-coast even when the reference coastline is coarse/synthetic.
    near_coast = distance_to_coast_m < 300 or mode == "coastal"
    strong = region.ndvi_drop > 0.4 and region.bsi_rise > 0.15

    if near_coast:
        label = "coastal_construction"
        reason = "New non-vegetated surface adjacent to the shoreline."
    elif strong:
        label = "quarry_expansion"
        reason = "Vegetation replaced by an expanding bare-rock signature, inland."
    else:
        label = "building" if region.area_ha < 1 else "agriculture"
        reason = "Moderate land-cover change without a strong bare-rock signature."

    confidence = max(0.4, min(0.95, 0.55 + region.ndvi_drop * 0.35 + region.bsi_rise * 0.4))
    return Classification(label=label, confidence=round(confidence, 2),
                          reasoning=reason, source="heuristic")


def _img_block(b: bytes) -> dict:
    """A base64 PNG image content block for the Anthropic Messages API."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(b).decode()}}


_VISION_PROMPT = (
    "Classify the change as one of: quarry_expansion, coastal_construction, "
    "building, agriculture, natural. Reply with ONLY JSON: "
    '{"label": "...", "confidence": 0.0-1.0, "reasoning": "..."}'
)


def classify_with_claude(before_png: bytes, after_png: bytes,
                         model: str = config.CLAUDE_MODEL) -> Classification:  # pragma: no cover
    """Real multimodal classification. Requires ANTHROPIC_API_KEY in the environment."""
    from . import llm
    raw = llm.claude_generate(
        model=model, max_tokens=400,
        contents=[
            {"type": "text", "text": "Two satellite crops of the SAME place in Lebanon, BEFORE then AFTER."},
            _img_block(before_png), _img_block(after_png),
            {"type": "text", "text": _VISION_PROMPT},
        ],
    ).text
    return _parse_classification(raw, source="claude")


def classify_with_gemini(before_png: bytes, after_png: bytes,
                         model: str = config.GEMINI_MODEL) -> Classification:  # pragma: no cover
    """Vision classification via Google Gemini (free tier). Requires GEMINI_API_KEY."""
    from google.genai import types
    from . import llm

    resp = llm.gemini_generate(
        model=model,
        contents=[
            "Two satellite crops of the SAME place in Lebanon, BEFORE then AFTER.",
            types.Part.from_bytes(data=before_png, mime_type="image/png"),
            types.Part.from_bytes(data=after_png, mime_type="image/png"),
            _VISION_PROMPT,
        ],
    )
    return _parse_classification(resp.text, source="gemini")


_CRITIQUE_PROMPT = (
    "You are independently double-checking a satellite change-detection result for Lebanon, to "
    "avoid false alarms. The system proposed: label='{label}', confidence={conf}. Look again at "
    "the BEFORE then AFTER crops. Could this be a seasonal or tidal water change, cloud/shadow, "
    "harvest/ploughing, or otherwise NOT a real new built / bare / sea-reclaimed surface? "
    "Be skeptical but fair. Reply with ONLY JSON: "
    '{{"verdict": "confirm|downgrade|reject", "confidence": 0.0-1.0, "reason": "one sentence"}}.'
)


def second_opinion(cls: Classification, before: dict, after: dict, region: ChangeRegion):
    """Adversarial second look at a proposed classification (online only). Returns a dict
    {verdict, confidence, reason} or None offline / on any error. Advisory — the caller
    decides what to do with a 'downgrade'/'reject'. Routes to the configured provider."""
    if config.OFFLINE or config.LLM_PROVIDER not in ("gemini", "claude"):
        return None
    try:
        before_png = region_crop_png(before, region.pixel_bbox)
        after_png = region_crop_png(after, region.pixel_bbox)
        prompt = _CRITIQUE_PROMPT.format(label=cls.label, conf=cls.confidence)
        intro = "Two satellite crops of the SAME place in Lebanon, BEFORE then AFTER."
        from . import llm
        if config.LLM_PROVIDER == "claude":
            raw = llm.claude_generate(contents=[
                {"type": "text", "text": intro},
                _img_block(before_png), _img_block(after_png),
                {"type": "text", "text": prompt},
            ], max_tokens=300).text
        else:
            from google.genai import types
            raw = llm.gemini_generate(contents=[
                intro,
                types.Part.from_bytes(data=before_png, mime_type="image/png"),
                types.Part.from_bytes(data=after_png, mime_type="image/png"),
                prompt,
            ]).text
        s, e = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[s:e + 1])
        verdict = str(data.get("verdict", "confirm")).lower()
        if verdict not in ("confirm", "downgrade", "reject"):
            verdict = "confirm"
        return {"verdict": verdict, "confidence": float(data.get("confidence", cls.confidence)),
                "reason": str(data.get("reason", "")).strip()}
    except Exception:  # noqa: BLE001 - never let the critique crash the pipeline
        return None


def _parse_classification(raw: str, source: str) -> Classification:
    """Extract the JSON object from a model reply even if wrapped in ``` fences/prose."""
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1] if start != -1 and end != -1 else raw)
    return Classification(label=data["label"], confidence=float(data["confidence"]),
                          reasoning=data["reasoning"], source=source)


def region_crop_png(bands: dict[str, np.ndarray], pixel_bbox, pad: int = 8) -> bytes:
    """True-colour PNG (bytes) of the change region (+padding) for Claude vision."""
    from PIL import Image
    from .imagery import to_rgb

    r0, c0, r1, c1 = pixel_bbox
    h, w = next(iter(bands.values())).shape
    r0, c0 = max(0, r0 - pad), max(0, c0 - pad)
    r1, c1 = min(h, r1 + pad + 1), min(w, c1 + pad + 1)
    crop = {b: arr[r0:r1, c0:c1] for b, arr in bands.items()}
    rgb = (np.clip(to_rgb(crop), 0, 1) * 255).astype("uint8")
    buf = BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def classify(region: ChangeRegion, before: dict, after: dict,
             distance_to_coast_m: float, mode: str | None = None) -> Classification:
    """Dispatcher used by the agent. Offline -> heuristic; online -> the configured
    vision LLM (config.LLM_PROVIDER) on before/after region crops, falling back to
    the heuristic on any error so classification never crashes the pipeline."""
    if config.OFFLINE:
        return classify_heuristic(region, distance_to_coast_m, mode)
    try:
        before_png = region_crop_png(before, region.pixel_bbox)
        after_png = region_crop_png(after, region.pixel_bbox)
        if config.LLM_PROVIDER == "gemini":
            return classify_with_gemini(before_png, after_png)
        return classify_with_claude(before_png, after_png)
    except Exception:  # noqa: BLE001 - never let classification crash the pipeline
        return classify_heuristic(region, distance_to_coast_m, mode)
