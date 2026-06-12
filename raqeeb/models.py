"""Typed data structures passed between the agent's tools."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ChangeRegion:
    id: str
    area_ha: float
    centroid: tuple[float, float]        # (lon, lat)
    geo_bbox: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    pixel_bbox: tuple[int, int, int, int]        # (row0, col0, row1, col1)
    ndvi_drop: float
    bsi_rise: float


@dataclass
class Classification:
    label: str            # quarry_expansion | coastal_construction | building | agriculture | natural
    confidence: float     # 0..1
    reasoning: str
    source: str = "heuristic"   # or "claude"


@dataclass
class Finding:
    region: ChangeRegion
    classification: Classification
    flags: list[str] = field(default_factory=list)
    nearest_place: str = ""
    mode: str = "quarry"
    detected_window: str = ""
    dossier_path: Optional[str] = None

    @property
    def is_violation(self) -> bool:
        return len(self.flags) > 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_violation"] = self.is_violation
        return d
