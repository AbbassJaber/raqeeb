"""Best-effort reverse geocoding: turn a drawn zone's center into a place name.

Used to label an ad-hoc drawn/scanned zone after the real Lebanese town or
municipality it sits in (e.g. "Bourj Hammoud, Mount Lebanon") instead of bare
coordinates. Strictly best-effort — every failure path returns None so the
caller can fall back to coordinates; a no-network demo still works.

Stdlib only (urllib) — no new dependency. Talks to OSM Nominatim, whose usage
policy requires a descriptive User-Agent and discourages heavy traffic; this is
one call per interactive draw, which is well within bounds.
"""
from __future__ import annotations
import json
import urllib.parse
import urllib.request

from . import config

# Identify ourselves per Nominatim's usage policy (a generic UA gets blocked).
_USER_AGENT = "Raqeeb/1.0 (environmental-monitoring hackathon demo)"

# Address fields from most to least specific; we want the finest locality plus a
# region for context. Lebanon's Nominatim data uses these OSM/Nominatim keys.
_LOCALITY_KEYS = ("city", "town", "village", "municipality", "suburb",
                  "neighbourhood", "hamlet")
_REGION_KEYS = ("state", "region", "county", "state_district")


def reverse_place_name(lon: float, lat: float) -> str | None:
    """Return a human place name for (lon, lat), or None if it can't be resolved.

    None on any of: geocoding disabled, network/timeout error, or no usable name
    in the response. The caller is expected to fall back to coordinates.
    """
    if not config.GEOCODE:
        return None
    params = urllib.parse.urlencode({
        "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
        "format": "jsonv2", "zoom": "12",  # ~town/municipality granularity
        "addressdetails": "1", "accept-language": "en",
    })
    url = f"{config.NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=config.GEOCODE_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None  # offline, timeout, HTTP error, bad JSON — all just "no name"
    return _format_name(data)


def _format_name(data: dict) -> str | None:
    """Compose '<locality>, <region>' from a Nominatim reverse response."""
    addr = data.get("address") or {}
    locality = next((addr[k] for k in _LOCALITY_KEYS if addr.get(k)), None)
    region = next((addr[k] for k in _REGION_KEYS if addr.get(k)), None)
    if locality and region and locality != region:
        return f"{locality}, {region}"
    if locality:
        return locality
    if region:
        return region
    # No structured locality; fall back to the leading part of the display name.
    display = data.get("display_name")
    if display:
        return display.split(",")[0].strip() or None
    return None
