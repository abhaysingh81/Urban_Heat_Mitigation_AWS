"""
OpenStreetMap features via Overpass (CSV output keeps payloads small):
building density / height and cooling-relevant amenities.

Overpass is a shared public service, so requests are tiled, cached on disk
and retried. Failed tiles leave NaN (XGBoost handles missing values) and
are reported in the data card rather than silently imputed.
"""

from __future__ import annotations

import csv
import io
import os
import time

import numpy as np
import requests

from pipeline.config import REAL_RAW_DIR
from pipeline.real.gridspec import GridSpec

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
# Building footprints are a heavy Overpass download (minutes per tile in dense cities),
# so they are opt-in:  HEATRELIEF_OSM_BUILDINGS=1 python -m pipeline.real.build_dataset ...
# Without them building_density/height are NaN and the model simply does not use them.
FETCH_BUILDINGS = os.environ.get("HEATRELIEF_OSM_BUILDINGS", "0") == "1"
# HEATRELIEF_OSM_OFFLINE=1 uses only tiles already cached on disk (no network).
OFFLINE = os.environ.get("HEATRELIEF_OSM_OFFLINE", "0") == "1"
TILE_DEG = 0.1
HEADERS = {"User-Agent": "HeatRelief-hackathon/0.1 (urban heat research; github.com/adityafilesx)"}
MAX_CONSECUTIVE_FAILS = 6  # circuit breaker: stop hammering a throttled server
_FAILS = 0
LEVEL_M = 3.0  # metres per building level when only levels are tagged

AMENITY_QUERY = (
    'nwr["amenity"~"^(hospital|clinic|community_centre|library|shelter|drinking_water)$"]'
    "({bbox});nwr[\"leisure\"=\"park\"]({bbox});node[\"highway\"=\"bus_stop\"]({bbox});"
)


def _tiles(spec: GridSpec):
    w, s, e, n = spec.bbox_wgs84()
    xs = np.arange(w, e, TILE_DEG)
    ys = np.arange(s, n, TILE_DEG)
    for x in xs:
        for y in ys:
            yield (round(y, 5), round(x, 5), round(min(y + TILE_DEG, n), 5), round(min(x + TILE_DEG, e), 5))


def _overpass(query: str, cache_file, retries: int = 5) -> str | None:
    """POST an Overpass query with disk caching. 429 (busy) waits and retries on the
    primary server; 5xx/network errors fall over to the mirror."""
    global _FAILS
    if cache_file.exists():
        return cache_file.read_text()
    if OFFLINE:
        return None
    last, url_i = None, 0
    for i in range(retries):
        url = ENDPOINTS[url_i % len(ENDPOINTS)]
        try:
            r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=240)
            if r.status_code == 200:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(r.text)
                _FAILS = 0
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code != 429:
                url_i += 1               # server error: try the other mirror next
        except requests.RequestException as e:
            last = str(e)
            url_i += 1
        time.sleep(20 if last == "HTTP 429" else 8 * (i + 1))
    _FAILS += 1
    print(f"    [osm] gave up on {cache_file.name}: {last}")
    return None


def _height_m(levels: str, height: str) -> float:
    for raw, mult in ((height, 1.0), (levels, LEVEL_M)):
        try:
            v = float(str(raw).split()[0].replace(",", "."))
            if v > 0:
                return v * mult
        except (ValueError, IndexError):
            continue
    return np.nan


def build(spec: GridSpec) -> dict:
    cache = REAL_RAW_DIR / spec.city_id / "osm"
    n_tiles = ok_tiles = 0
    b_lat, b_lon, b_h = [], [], []
    amenities = []

    for (s, w, n, e) in _tiles(spec):
        n_tiles += 1
        if _FAILS >= MAX_CONSECUTIVE_FAILS:
            continue  # server is throttling us; leave remaining tiles as missing
        bbox = f"{s},{w},{n},{e}"
        tag = f"{s}_{w}"
        bq = ('[out:csv(::lat,::lon,"building:levels","height";false)][timeout:200];'
              f'way["building"]({bbox});out center;')
        btxt = _overpass(bq, cache / f"b_{tag}.tsv") if FETCH_BUILDINGS else None
        aq = ('[out:csv(::lat,::lon,name,amenity,leisure,highway;false)][timeout:120];('
              + AMENITY_QUERY.format(bbox=bbox) + ");out center;")
        atxt = _overpass(aq, cache / f"a_{tag}.tsv")
        if atxt is not None:
            for row in csv.reader(io.StringIO(atxt), delimiter="\t"):
                if len(row) >= 6 and row[0]:
                    try:
                        amenities.append({"lat": float(row[0]), "lon": float(row[1]),
                                          "name": row[2], "amenity": row[3],
                                          "leisure": row[4], "highway": row[5]})
                    except ValueError:
                        pass
        if btxt is not None:
            ok_tiles += 1
            for row in csv.reader(io.StringIO(btxt), delimiter="\t"):
                if len(row) >= 4 and row[0]:
                    try:
                        b_lat.append(float(row[0])); b_lon.append(float(row[1]))
                        b_h.append(_height_m(row[2], row[3]))
                    except ValueError:
                        pass
        time.sleep(3.0)  # be polite to the public Overpass servers

    coverage = ok_tiles / max(n_tiles, 1)
    arrays: dict[str, np.ndarray] = {}
    nan = np.full((spec.rows, spec.cols), np.nan)
    if not FETCH_BUILDINGS:
        print("    [osm] building footprints skipped (opt-in) -> NaN building features")
        arrays.update(building_density=nan.copy(), building_height_mean=nan.copy())
    elif coverage < 0.7 or not b_lat:
        print(f"    [osm] building coverage {coverage:.0%} too low -> NaN features")
        arrays.update(building_density=nan.copy(), building_height_mean=nan.copy())
    else:
        r, c, ok = spec.lonlat_to_cell_rc(np.array(b_lon), np.array(b_lat))
        r, c, h = r[ok], c[ok], np.array(b_h)[ok]
        count = np.zeros((spec.rows, spec.cols))
        np.add.at(count, (r, c), 1)
        hsum = np.zeros_like(count); hn = np.zeros_like(count)
        known = ~np.isnan(h)
        np.add.at(hsum, (r[known], c[known]), h[known])
        np.add.at(hn, (r[known], c[known]), 1)
        with np.errstate(all="ignore"):
            hmean = hsum / hn
        city_med = np.nanmedian(h[known]) if known.any() else np.nan
        hmean = np.where(count > 0, np.where(hn > 0, hmean, city_med), np.nan)
        arrays["building_density"] = count / (spec.cell ** 2 / 1e6)  # per km²
        arrays["building_height_mean"] = hmean

    # amenity counts per cell + cooling-spot table
    spots = []
    for key, name in (("hospital_count", "hospital"), ("bus_stop_count", "bus_stop"),
                      ("drinking_water_count", "drinking_water")):
        arrays[key] = np.zeros((spec.rows, spec.cols))
    kind_of = lambda a: (a["amenity"] or a["leisure"] or a["highway"])
    for a in amenities:
        kind = kind_of(a)
        r, c, ok = spec.lonlat_to_cell_rc(np.array([a["lon"]]), np.array([a["lat"]]))
        if not ok[0]:
            continue
        key = {"hospital": "hospital_count", "clinic": "hospital_count",
               "bus_stop": "bus_stop_count", "drinking_water": "drinking_water_count"}.get(kind)
        if key:
            arrays[key][r[0], c[0]] += 1
        if kind in ("hospital", "clinic", "community_centre", "library", "shelter", "park",
                    "drinking_water"):
            spots.append({"name": a["name"] or kind.replace("_", " ").title(),
                          "type": kind, "lat": round(a["lat"], 5), "lon": round(a["lon"], 5)})

    return {"arrays": arrays, "cooling_spots": spots,
            "osm_tile_coverage": round(coverage, 3), "n_buildings": len(b_lat)}
