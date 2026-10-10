"""
City boundary and the cells inside it.

    python -m pipeline.real.boundary new_delhi mumbai jaipur bengaluru

Fetches the administrative boundary from OpenStreetMap (Nominatim, ODbL),
then writes for each city:
  data/processed/<city>/boundary.geojson   the boundary polygon
  data/processed/<city>/city_mask.json     {"inside": [grid_id, ...],
                                            "clipped": {grid_id: geometry}}
A cell is "inside" when at least MIN_SHARE (1%) of its area lies within the
boundary; edge cells get their polygon clipped to the boundary so maps follow
the city outline. Precomputed here so the API needs no geometry library.
"""

from __future__ import annotations

import argparse
import json
import time

import requests
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from pipeline.config import CITIES, city_grid_file, city_processed_dir

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "HeatRelief/1.0 (urban heat research; github.com/adityafilesx)"
MIN_SHARE = 0.01  # keep any cell that really overlaps the city (clipped to the line), so edges have no slivers
# Query that returns the municipal / administrative area each grid was built for.
# Several queries are merged (Greater Mumbai = Mumbai City + Mumbai Suburban districts).
QUERIES = {
    "new_delhi": ["National Capital Territory of Delhi"],
    "mumbai": ["Mumbai City district, Maharashtra", "Mumbai Suburban district, Maharashtra"],
    "jaipur": ["Jaipur Municipal Corporation, Rajasthan"],
    "bengaluru": ["Bengaluru, Karnataka, India"],
}


def _one(q: str):
    r = requests.get(NOMINATIM, timeout=60, headers={"User-Agent": USER_AGENT}, params={
        "q": q, "format": "jsonv2", "polygon_geojson": 1, "limit": 5})
    r.raise_for_status()
    for hit in r.json():  # administrative areas first, any polygon as a fallback
        if hit.get("osm_type") == "relation" and hit.get("type") == "administrative" \
                and hit.get("geojson", {}).get("type") in ("Polygon", "MultiPolygon"):
            return shape(hit["geojson"]), hit
    for hit in r.json():
        if hit.get("geojson", {}).get("type") in ("Polygon", "MultiPolygon"):
            return shape(hit["geojson"]), hit
    raise RuntimeError(f"no polygon boundary found for '{q}'")


def fetch_boundary(city_id: str):
    parts, hits = [], []
    for i, q in enumerate(QUERIES.get(city_id, [CITIES[city_id]["name"]])):
        if i:
            time.sleep(1.5)
        g, h = _one(q)
        parts.append(g.buffer(0)); hits.append(h)
    hit = dict(hits[0])
    hit["display_name"] = " + ".join(h["display_name"].split(",")[0] for h in hits) if len(hits) > 1 else hits[0]["display_name"]
    hit["osm_id"] = ",".join(str(h["osm_id"]) for h in hits)
    return unary_union(parts), hit


def build(city_id: str) -> dict:
    boundary, hit = fetch_boundary(city_id)
    # simplify once (~2 m) and use the same line for clipping and for the saved outline,
    # so clipped edge cells meet the drawn boundary exactly (no slivers)
    boundary = boundary.buffer(0).simplify(2e-5).buffer(0)
    grid = json.loads(city_grid_file(city_id).read_text())
    inside, clipped = [], {}
    for f in grid["features"]:
        cell = shape(f["geometry"])
        part = cell.intersection(boundary)
        if part.is_empty or part.area < MIN_SHARE * cell.area:
            continue
        gid = f["properties"]["grid_id"]
        inside.append(gid)
        if part.area < 0.999 * cell.area:
            clipped[gid] = mapping(part)
    out_dir = city_processed_dir(city_id)
    (out_dir / "boundary.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(boundary),
                                                   "properties": {"name": hit.get("display_name"),
                                                                  "osm_type": hit.get("osm_type"),
                                                                  "osm_id": hit.get("osm_id"),
                                                                  "source": "OpenStreetMap via Nominatim (ODbL)"}}]}))
    (out_dir / "city_mask.json").write_text(json.dumps({"inside": inside, "clipped": clipped,
                                                        "boundary_name": hit.get("display_name")}))
    grid_union = unary_union([shape(f["geometry"]) for f in grid["features"]])
    return {"city": city_id, "boundary": hit.get("display_name"), "cells_total": len(grid["features"]),
            "cells_inside": len(inside), "edge_cells_clipped": len(clipped),
            "boundary_share_covered_by_grid": round(boundary.intersection(grid_union).area / boundary.area, 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="+")
    for i, c in enumerate(ap.parse_args().cities):
        if i:
            time.sleep(1.5)  # Nominatim usage policy: at most 1 request per second
        print(build(c))
