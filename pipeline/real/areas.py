"""
Area names for the map: each grid cell gets the name of its nearest OpenStreetMap
locality (neighbourhood, suburb, quarter, village, town).

This is a nearest-named-place label, not an official boundary: it tells an officer
roughly where a cell is ("Bani Park"), nothing more. Cells with no named place within
MAX_DISTANCE_M get no label. One Overpass request per city; the result is written to
data/processed/<city>/area_names.json and served with the grid, so the browser never
calls a geocoder.

    python -m pipeline.real.areas                  # every city that has a grid
    python -m pipeline.real.areas jaipur mumbai

© OpenStreetMap contributors (ODbL).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import numpy as np
import requests

from pipeline.config import CITIES, city_area_names_file, city_grid_file

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
HEADERS = {"User-Agent": "HeatRelief-hackathon/0.1 (urban heat research; github.com/adityafilesx)"}
PLACE_TYPES = ("neighbourhood", "quarter", "suburb", "village", "town", "hamlet")
MAX_DISTANCE_M = 3000.0
BBOX_PAD_DEG = 0.02  # a place just outside the grid can still be the nearest one


def fetch_places(bbox: tuple, retries: int = 4) -> list[dict]:
    """Named locality nodes in (west, south, east, north), padded slightly."""
    w, s, e, n = bbox
    q = (f'[out:json][timeout:120];node["place"~"^({"|".join(PLACE_TYPES)})$"]["name"]'
         f'({s - BBOX_PAD_DEG},{w - BBOX_PAD_DEG},{n + BBOX_PAD_DEG},{e + BBOX_PAD_DEG});out body;')
    last = None
    for i in range(retries):
        try:
            r = requests.post(ENDPOINTS[i % len(ENDPOINTS)], data={"data": q}, timeout=180, headers=HEADERS)
            if r.status_code == 200:
                out = []
                for el in r.json().get("elements", []):
                    tags = el.get("tags", {})
                    name = (tags.get("name:en") or tags.get("name") or "").strip()
                    if name and "lat" in el and "lon" in el:
                        out.append({"name": name, "place": tags.get("place"),
                                    "lat": float(el["lat"]), "lon": float(el["lon"])})
                return out
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"Overpass place query failed after {retries} tries: {last}")


def nearest_names(lon: np.ndarray, lat: np.ndarray, places: list[dict],
                  max_distance_m: float = MAX_DISTANCE_M) -> list[str | None]:
    """Name of the nearest place for each point, or None beyond max_distance_m."""
    if not places:
        return [None] * len(lon)
    p_lat = np.radians([p["lat"] for p in places])
    p_lon = np.radians([p["lon"] for p in places])
    out: list[str | None] = []
    for i in range(0, len(lon), 2000):  # chunked: cells x places stays small in memory
        la, lo = np.radians(lat[i:i + 2000])[:, None], np.radians(lon[i:i + 2000])[:, None]
        a = np.sin((p_lat - la) / 2) ** 2 + np.cos(la) * np.cos(p_lat) * np.sin((p_lon - lo) / 2) ** 2
        dist = 2 * 6371000 * np.arcsin(np.sqrt(a))
        j = dist.argmin(axis=1)
        d = dist[np.arange(len(j)), j]
        out += [places[k]["name"] if m <= max_distance_m else None for k, m in zip(j, d)]
    return out


def grid_centroids(city_id: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    geo = json.loads(city_grid_file(city_id).read_text())
    ids, lon, lat = [], [], []
    for f in geo["features"]:
        g = f["geometry"]
        ring = g["coordinates"][0][0] if g["type"] == "MultiPolygon" else g["coordinates"][0]
        pts = np.asarray(ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring, dtype=float)
        ids.append(f["properties"]["grid_id"])
        lon.append(pts[:, 0].mean()); lat.append(pts[:, 1].mean())
    return ids, np.asarray(lon), np.asarray(lat)


def build(city_id: str) -> dict:
    ids, lon, lat = grid_centroids(city_id)
    bbox = (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
    places = fetch_places(bbox)
    names = nearest_names(lon, lat, places)
    # store each distinct name once: {"names": [...], "cells": {grid_id: index}}
    table = sorted({n for n in names if n})
    index = {n: i for i, n in enumerate(table)}
    out = {
        "city_id": city_id, "built_at": datetime.now(timezone.utc).isoformat(),
        "method": f"nearest OpenStreetMap place node ({', '.join(PLACE_TYPES)}) within {int(MAX_DISTANCE_M)} m",
        "licence": "OpenStreetMap contributors — ODbL",
        "n_places": len(places), "n_cells": len(ids), "n_named": sum(n is not None for n in names),
        "names": table, "cells": {g: index[n] for g, n in zip(ids, names) if n},
    }
    city_area_names_file(city_id).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*")
    a = ap.parse_args()
    cities = a.cities or [c for c in CITIES if city_grid_file(c).exists()]
    for i, c in enumerate(cities):
        if i:
            time.sleep(3)  # be polite to the public Overpass server
        try:
            r = build(c)
            print(f"{c}: {r['n_named']}/{r['n_cells']} cells named from {r['n_places']} places")
        except Exception as e:
            print(f"{c}: FAILED ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
