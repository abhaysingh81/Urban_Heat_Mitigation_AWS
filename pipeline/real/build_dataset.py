"""
Build features_real.parquet for a city from real data.

    python -m pipeline.real.build_dataset new_delhi
    python -m pipeline.real.build_dataset mumbai --refresh landsat
    python -m pipeline.real.build_dataset jaipur --skip osm,population

Each stage caches its result under data/raw/real/<city>/ (git-ignored), so
re-runs after a network failure resume instead of starting over.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from pipeline.config import (
    HOTSPOT_TIERS, REAL_CITIES, REAL_RAW_DIR, city_cooling_spots_file,
    city_data_card_file, city_real_features_file,
)
from pipeline.real import (
    context_features, landcover, landsat_composite, osm_features, population,
    sentinel2, terrain, wards, weather,
)
from pipeline.real.gridspec import GridSpec

STAGES = ["landsat", "sentinel2", "landcover", "terrain", "osm", "population", "weather"]
LICENCES = {
    "landsat": "Landsat Collection 2 Level-2 — USGS, public domain",
    "sentinel2": "Copernicus Sentinel-2 L2A — free and open (Copernicus licence)",
    "landcover": "ESA WorldCover 2021 — CC BY 4.0",
    "terrain": "Copernicus DEM GLO-30 — Copernicus licence (free use)",
    "osm": "© OpenStreetMap contributors — ODbL",
    "population": "Meta High Resolution Population Density Maps (HRSL) — CC BY 4.0",
    "weather": "Open-Meteo archive (ERA5-based) — CC BY 4.0",
}


def _cached(city_id: str, stage: str, fn, refresh: set[str]):
    path = REAL_RAW_DIR / city_id / f"stage_{stage}.pkl"
    if path.exists() and stage not in refresh and "all" not in refresh:
        print(f"  [{stage}] cached")
        return pickle.loads(path.read_bytes())
    print(f"  [{stage}] building…")
    result = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(result))
    return result


def assign_tiers(lst: np.ndarray) -> np.ndarray:
    """Observed-LST tiers using the same mean/std thresholds as the app."""
    mean, std = np.nanmean(lst), np.nanstd(lst)
    z = (lst - mean) / std
    out = np.full(lst.shape, "unknown", dtype=object)
    ok = ~np.isnan(z)
    out[ok & (z > HOTSPOT_TIERS["critical"])] = "critical"
    out[ok & (z <= HOTSPOT_TIERS["critical"]) & (z > HOTSPOT_TIERS["high"])] = "high"
    out[ok & (z <= HOTSPOT_TIERS["high"]) & (z > HOTSPOT_TIERS["moderate"])] = "moderate"
    out[ok & (z <= HOTSPOT_TIERS["moderate"]) & (z > HOTSPOT_TIERS["normal"])] = "normal"
    out[ok & (z <= HOTSPOT_TIERS["normal"])] = "cool"
    return out


def build_city(city_id: str, skip: set[str] = frozenset(), refresh: set[str] = frozenset()):
    spec = GridSpec.for_city(city_id)
    print(f"\n=== {city_id}: {spec.rows}x{spec.cols} = {spec.n_cells} cells ===")
    arrays: dict[str, np.ndarray] = {}
    card = {"city_id": city_id, "built_at": datetime.now(timezone.utc).isoformat(),
            "sources": {}, "skipped": sorted(skip), "notes": []}

    land = _cached(city_id, "landsat", lambda: landsat_composite.build(spec), refresh)
    arrays.update(land["arrays"])
    scene_dates = sorted({s["date"] for s in land["scenes"]})
    card["sources"]["landsat"] = {"licence": LICENCES["landsat"], "scenes": land["scenes"]}

    simple = [("sentinel2", sentinel2), ("landcover", landcover), ("terrain", terrain)]
    for name, mod in simple:
        if name in skip:
            continue
        res = _cached(city_id, name, lambda m=mod: m.build(spec), refresh)
        arrays.update(res["arrays"])
        card["sources"][name] = {"licence": LICENCES[name],
                                 **{k: v for k, v in res.items() if k != "arrays"}}

    cooling_spots = []
    if "osm" not in skip:
        osm = _cached(city_id, "osm", lambda: osm_features.build(spec), refresh)
        arrays.update(osm["arrays"])
        cooling_spots = osm["cooling_spots"]
        card["sources"]["osm"] = {"licence": LICENCES["osm"],
                                  "tile_coverage": osm["osm_tile_coverage"],
                                  "n_buildings": osm["n_buildings"]}
        if np.isnan(osm["arrays"]["building_density"]).all():
            card["notes"].append("OSM building features not collected (opt-in); the model does not use them.")

    if "population" not in skip:
        pop = _cached(city_id, "population",
                      lambda: population.build(spec, arrays.get("building_density")), refresh)
        arrays.update(pop["arrays"])
        card["sources"]["population"] = {"licence": LICENCES["population"],
                                         "source": pop["source"]}
        if pop["source"] != "meta_hrsl_30m":
            card["notes"].append("Population is a building-count proxy, not HRSL.")

    weather_scalars = {}
    if "weather" not in skip:
        w = _cached(city_id, "weather", lambda: weather.build(city_id, scene_dates), refresh)
        weather_scalars = w["scalars"]
        card["sources"]["weather"] = {"licence": LICENCES["weather"], **w}

    arrays.update(context_features.build(arrays))

    # ── assemble per-cell table ──
    lon, lat = spec.cell_centers_lonlat()
    idx = np.arange(spec.n_cells)
    row, col = spec.idx_to_rowcol(idx)
    df = pd.DataFrame({"grid_id": spec.grid_ids(), "row": row, "col": col,
                       "centroid_lon": lon, "centroid_lat": lat})
    for name, arr in arrays.items():
        df[name] = spec.array_to_cells(arr)
    for k, v in weather_scalars.items():
        df[k] = v

    # derived, physically meaningful features
    veg = df.get("frac_vegetation")
    if veg is not None:
        df["green_deficit"] = (1.0 - df["frac_vegetation"].fillna(0)).clip(0, 1)
        df["veg_imperv_ratio"] = df["frac_vegetation"] / (df["frac_impervious"] + 0.01)

    wd = wards.assign(spec)
    df["ward_id"], df["ward_name"] = wd["ward_id"], wd["ward_name"]
    df["tier"] = assign_tiers(df["lst_c"].to_numpy())
    df["lst_mean"] = df["lst_c"]  # legacy column name used by existing API code
    df["lst_max"] = df["lst_c"] + df["lst_std"].fillna(0)
    df["delta_above_mean"] = (df["lst_mean"] - df["lst_mean"].mean()).round(2)
    ps = np.clip(df["delta_above_mean"], 0, None) / (df["frac_vegetation"].fillna(0.1) + 0.01)
    df["priority_score"] = (ps / ps.max() * 10).round(1) if ps.max() > 0 else 0.0

    out = city_real_features_file(city_id)
    df.to_parquet(out, index=False)
    city_cooling_spots_file(city_id).write_text(json.dumps(cooling_spots))
    card.update({
        "n_cells": int(len(df)),
        "target_valid_cells": int(df["lst_c"].notna().sum()),
        "ward_kind": wd["kind"],
        "lst_c": {"mean": round(float(df["lst_c"].mean()), 2),
                  "std": round(float(df["lst_c"].std()), 2)},
        "features": [c for c in df.columns],
    })
    city_data_card_file(city_id).write_text(json.dumps(card, indent=2, default=str))
    print(f"  wrote {out}  (target valid {card['target_valid_cells']}/{len(df)})")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=REAL_CITIES)
    ap.add_argument("--skip", default="", help="comma list of stages to skip")
    ap.add_argument("--refresh", default="", help="comma list of stages to rebuild (or 'all')")
    a = ap.parse_args()
    skip = {s for s in a.skip.split(",") if s}
    refresh = {s for s in a.refresh.split(",") if s}
    for bad in (skip | refresh) - set(STAGES) - {"all"}:
        raise SystemExit(f"unknown stage '{bad}'; stages: {STAGES}")
    for c in a.cities:
        build_city(c, skip, refresh)


if __name__ == "__main__":
    main()
