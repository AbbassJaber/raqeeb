"""Small geospatial helpers shared across tools."""
from __future__ import annotations
from functools import lru_cache

from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform as shp_transform

from . import config


@lru_cache(maxsize=4)
def _to_metric_transformer():
    return Transformer.from_crs("EPSG:4326", config.METRIC_CRS, always_xy=True)


def to_metric(geom):
    """Reproject a lon/lat shapely geometry into the metric CRS for distance/area math."""
    t = _to_metric_transformer()
    return shp_transform(lambda x, y, z=None: t.transform(x, y), geom)


@lru_cache(maxsize=4)
def _to_wgs84_transformer():
    return Transformer.from_crs(config.METRIC_CRS, "EPSG:4326", always_xy=True)


def to_wgs84(geom):
    """Reproject a metric-CRS shapely geometry back to lon/lat (for display overlays)."""
    t = _to_wgs84_transformer()
    return shp_transform(lambda x, y, z=None: t.transform(x, y), geom)


def pixel_to_lonlat(row: float, col: float, grid: int, bbox) -> tuple[float, float]:
    """Map a pixel (row, col) to (lon, lat). Row 0 is the top (max latitude)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    lon = min_lon + (col + 0.5) / grid * (max_lon - min_lon)
    lat = max_lat - (row + 0.5) / grid * (max_lat - min_lat)
    return lon, lat


def pixel_bbox_to_geo(pixel_bbox, grid: int, bbox):
    """Convert a (row0, col0, row1, col1) pixel box into a lon/lat shapely box."""
    r0, c0, r1, c1 = pixel_bbox
    lon0, lat1 = pixel_to_lonlat(r0, c0, grid, bbox)   # top-left
    lon1, lat0 = pixel_to_lonlat(r1, c1, grid, bbox)   # bottom-right
    min_lon, max_lon = sorted((lon0, lon1))
    min_lat, max_lat = sorted((lat0, lat1))
    return box(min_lon, min_lat, max_lon, max_lat)


def distance_m(geom_a, geom_b) -> float:
    """Metric distance (metres) between two lon/lat geometries."""
    return to_metric(geom_a).distance(to_metric(geom_b))
