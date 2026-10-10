"""
Check that a city's heat grid has no gaps inside its administrative boundary.

    python scripts/check_coverage.py new_delhi [--base http://localhost:8000]

Reads the grid exactly as the frontend does (/api/v1/grid), then reports the
boundary area not covered by any served cell, the largest uncovered patches, and
whether a set of named places (looked up once on OpenStreetMap) fall inside a cell.
"""

from __future__ import annotations

import argparse
import sys
import time

import requests
from pyproj import Geod
from shapely.geometry import Point, shape
from shapely.ops import unary_union

GEOD = Geod(ellps="WGS84")
PLACES = {
    "new_delhi": ["Dhansa, Delhi", "Issapur, Delhi", "Raota, Delhi", "Jharoda Kalan, Delhi", "Najafgarh, Delhi",
                  "Kair, Delhi", "Mitraon, Delhi", "Connaught Place, New Delhi", "Narela, Delhi", "Alipur, Delhi"],
    "jaipur": ["Jhotwara, Jaipur", "Sanganer, Jaipur", "Amer, Jaipur", "Malviya Nagar, Jaipur"],
    "bengaluru": ["Yelahanka, Bengaluru", "Electronic City, Bengaluru", "Whitefield, Bengaluru", "Kengeri, Bengaluru"],
    "mumbai": ["Colaba, Mumbai", "Dahisar, Mumbai", "Mulund, Mumbai"],
}


def km2(geom) -> float:
    return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


def geocode(q: str):
    r = requests.get("https://nominatim.openstreetmap.org/search", timeout=30,
                     headers={"User-Agent": "HeatRelief/1.0 (coverage check)"},
                     params={"q": q, "format": "jsonv2", "limit": 1})
    hits = r.json()
    return (float(hits[0]["lon"]), float(hits[0]["lat"])) if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    g = requests.get(f"{a.base}/api/v1/grid", params={"city": a.city}, timeout=120).json()
    if not g.get("boundary"):
        sys.exit("no boundary in the grid response — run pipeline.real.boundary first")
    boundary = unary_union([shape(f["geometry"]) for f in g["boundary"]["features"]]).buffer(0)
    cells = unary_union([shape(f["geometry"]) for f in g["features"]]).buffer(1e-7)
    gap = boundary.difference(cells)
    pieces = sorted(getattr(gap, "geoms", [gap]), key=km2, reverse=True)
    pieces = [p for p in pieces if not p.is_empty]
    b_km2, gap_km2 = km2(boundary), km2(gap) if not gap.is_empty else 0.0
    print(f"{a.city}: {len(g['features'])} cells · boundary {b_km2:.1f} km² · uncovered {gap_km2:.2f} km² "
          f"({100 * gap_km2 / b_km2:.2f}%)")
    for p in pieces[:5]:
        c = p.representative_point()
        print(f"   uncovered patch {km2(p):.3f} km² near {c.y:.4f}N {c.x:.4f}E")
    predicted = sum(1 for f in g["features"] if f["properties"].get("lst_source") == "predicted")
    print(f"   cells using the model estimate (no clear satellite pass): {predicted}")
    for i, q in enumerate(PLACES.get(a.city, [])):
        if i:
            time.sleep(1.2)  # Nominatim usage policy
        ll = geocode(q)
        if not ll:
            print(f"   {q:32s} not found on OSM")
            continue
        pt = Point(ll)
        state = "covered" if cells.contains(pt) else ("OUTSIDE boundary" if not boundary.contains(pt) else "GAP")
        print(f"   {q:32s} {ll[1]:.4f}N {ll[0]:.4f}E  {state}")
    sys.exit(1 if gap_km2 > 0.005 * b_km2 else 0)  # fail when more than 0.5% of the city is uncovered


if __name__ == "__main__":
    main()
