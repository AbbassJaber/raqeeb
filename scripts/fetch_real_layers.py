"""Fetch REAL Lebanese reference layers from public datasets via Google Earth Engine,
replacing the synthetic proxies in data/reference/.

  protected_areas.geojson  <- WCMC/WDPA/current/polygons  (World Database on Protected
                              Areas), filtered ISO3 = LBN. 69 real, legally-designated
                              areas: nature reserves, protected forests, biosphere
                              reserves, Ramsar wetlands, himas.
  coastline.geojson         <- western coastal arc derived from the real Lebanon national
                              boundary (FAO/GAUL_SIMPLIFIED_500m/2015/level0).

The synthetic originals are backed up once as *.synthetic.geojson so the demo can be
reverted. Run:

    EARTHENGINE_PROJECT=raqeeb-498718 ./.venv/Scripts/python.exe scripts/fetch_real_layers.py
"""
from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raqeeb import config  # noqa: E402

PROJECT = os.getenv("EARTHENGINE_PROJECT") or config.EE_PROJECT or "raqeeb-498718"
REF = Path(config.REFERENCE_DIR)

# Romanised English names for Lebanon's WDPA reserves (WDPA NAME is Arabic for most of
# them). Keyed on the Arabic NAME (whitespace-stripped). Unmapped areas fall back to
# their (English) designation, so the legal verdict still reads cleanly.
NAME_EN = {
    "محمية أرز الشوف الطبيعية": "Al-Shouf Cedar Nature Reserve",
    "محمية حرج اهدن الطبيعية": "Horsh Ehden Nature Reserve",
    "محمية غابة أرز تنورين الطبيعية": "Tannourine Cedars Nature Reserve",
    "محمية بنتاعل الطبيعية": "Bentael Nature Reserve",
    "محمية اليمونة الطبيعية": "Yammouneh Nature Reserve",
    "محمية كرم شباط الطبيعية": "Karm Shbat Nature Reserve",
    "محمية جبل حرمون الطبيعية": "Mount Hermon Nature Reserve",
    "محمية وادي الحجير الطبيعية": "Wadi El Hujeir Nature Reserve",
    "محمية النميرية الطبيعية": "Nmairieh Nature Reserve",
    "محمية أرز جاج الطبيعية": "Jaj Cedars Nature Reserve",
    "محمية جزيرة النخل وجزيرة سنني وجزيرة رامكين الطبيعية": "Palm Islands Nature Reserve",
    "محمية شاطئ العباسية الطبيعية": "Abbassieh Beach Nature Reserve",
    "محمية شاطئ صور الطبيعية": "Tyre Beach Nature Reserve",
    "محمية مشاع شننعير الطبيعية": "Chnaniir Nature Reserve",
    "محمية بيت ليف الطبيعية": "Beit Lif Nature Reserve",
}


def _ee():
    import ee
    ee.Initialize(project=PROJECT)
    return ee


def _backup(p: Path):
    b = p.with_name(p.stem + ".synthetic.geojson")
    if p.exists() and not b.exists():
        shutil.copy2(p, b)
        print(f"  backed up {p.name} -> {b.name}")


def _round_geom(geom, nd=5):
    """Round coordinates in-place to nd decimals (~1 m) to shrink the file. Handles
    GeometryCollection (which has 'geometries', not 'coordinates')."""
    def r(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    if "geometries" in geom:
        for g in geom["geometries"]:
            _round_geom(g, nd)
    elif "coordinates" in geom:
        geom["coordinates"] = r(geom["coordinates"])
    return geom


def fetch_protected(ee):
    print("Fetching WDPA protected areas (ISO3 = LBN)...")
    fc = ee.FeatureCollection("WCMC/WDPA/current/polygons").filter(ee.Filter.eq("ISO3", "LBN"))

    def slim(f):
        return ee.Feature(f.geometry().simplify(60), {
            "NAME": f.get("NAME"), "DESIG_ENG": f.get("DESIG_ENG"),
            "IUCN_CAT": f.get("IUCN_CAT"), "REP_AREA": f.get("REP_AREA")})

    gj = fc.map(slim).getInfo()
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union

    def _polygonal(geom_json):
        """Coerce to clean Polygon/MultiPolygon (simplify can leave stray lines/points
        in a GeometryCollection, which break boundary/overlay ops downstream)."""
        g = shape(geom_json)
        if g.geom_type == "GeometryCollection":
            parts = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
            g = unary_union(parts) if parts else g
        return g.buffer(0)

    feats = []
    for ft in gj["features"]:
        p = ft.get("properties", {})
        name = (p.get("NAME") or "").strip()
        desig = p.get("DESIG_ENG") or "Protected area"
        name_en = NAME_EN.get(name) or (name if name and name.isascii() else None)
        g = _polygonal(ft["geometry"])
        if g.is_empty:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "name": name, "name_en": name_en, "desig": desig,
                "iucn": p.get("IUCN_CAT"), "rep_area_km2": p.get("REP_AREA"),
                "source": "WDPA (WCMC/WDPA/current/polygons), ISO3=LBN",
            },
            "geometry": _round_geom(mapping(g)),
        })
    out = {
        "type": "FeatureCollection",
        "properties": {
            "source": "World Database on Protected Areas (WDPA/WCMC) via Google Earth Engine",
            "country": "Lebanon (ISO3 LBN)", "count": len(feats),
            "note": "Real, legally-designated protected areas. Still a candidate-triage proxy: "
                    "confirm exact boundaries against the official cadastre / Ministry of Environment.",
        },
        "features": feats,
    }
    _backup(REF / "protected_areas.geojson")
    (REF / "protected_areas.geojson").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {len(feats)} real protected areas -> protected_areas.geojson")

    # Report named reserves + centroids so we can place the demo quarry on a real one.
    from shapely.geometry import shape
    print("  named reserves (centroid lon,lat | bbox):")
    rows = []
    for ft in feats:
        en = ft["properties"]["name_en"]
        if not en:
            continue
        g = shape(ft["geometry"])
        c = g.centroid
        rows.append((en, round(c.x, 4), round(c.y, 4), [round(v, 4) for v in g.bounds]))
    for en, cx, cy, b in sorted(rows, key=lambda r: r[0]):
        print(f"    {en:<40} ({cx},{cy})  bbox={b}")


def fetch_coastline(ee):
    print("Deriving real coastline from Lebanon national boundary (GAUL)...")
    from shapely.geometry import shape, mapping, LineString
    fc = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level0").filter(
        ee.Filter.eq("ADM0_NAME", "Lebanon"))
    n = fc.size().getInfo()
    if n == 0:
        print("  WARN: no GAUL feature for 'Lebanon'; leaving coastline unchanged.")
        return
    geom = shape(fc.geometry().simplify(120).getInfo())
    polys = list(getattr(geom, "geoms", [geom]))
    polys = [g for g in polys if g.geom_type == "Polygon"] or polys
    poly = max(polys, key=lambda g: g.area)
    ring = [(round(x, 5), round(y, 5)) for x, y in poly.exterior.coords]

    # Anchor the split at the two real coastal endpoints (south: Ras Naqoura; north: Arida),
    # then keep the arc with the smaller mean longitude — the western (Mediterranean) edge.
    def nearest(pt):
        return min(range(len(ring)), key=lambda i: (ring[i][0] - pt[0]) ** 2 + (ring[i][1] - pt[1]) ** 2)
    i_s, i_n = nearest((35.108, 33.090)), nearest((35.984, 34.640))
    a, b = sorted((i_s, i_n))
    arc1 = ring[a:b + 1]
    arc2 = ring[b:] + ring[:a + 1]
    coast = min((arc1, arc2), key=lambda arc: sum(c[0] for c in arc) / len(arc))
    if coast[0][1] > coast[-1][1]:
        coast = coast[::-1]  # order south -> north

    lons = [c[0] for c in coast]
    if len(coast) < 5 or min(lons) < 34.8 or max(lons) > 36.2:
        print(f"  WARN: derived coast looks off (n={len(coast)}, lon {min(lons):.2f}..{max(lons):.2f}); "
              "leaving coastline unchanged.")
        print("  coords:", coast)
        return

    out = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": "Lebanon Mediterranean coastline (real)",
                "source": "Derived from the Lebanon national boundary, FAO GAUL "
                          "(FAO/GAUL_SIMPLIFIED_500m/2015/level0) via Google Earth Engine. "
                          "Western coastal arc; proxy for the public maritime domain — "
                          "confirm against official cadastral data.",
            },
            "geometry": mapping(LineString(coast)),
        }],
    }
    _backup(REF / "coastline.geojson")
    (REF / "coastline.geojson").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote real coastline with {len(coast)} vertices -> coastline.geojson")
    print("  sample (S->N):", coast[:: max(1, len(coast) // 6)])


if __name__ == "__main__":
    print(f"Earth Engine project: {PROJECT}")
    ee = _ee()
    fetch_protected(ee)
    fetch_coastline(ee)
    print("Done.")
