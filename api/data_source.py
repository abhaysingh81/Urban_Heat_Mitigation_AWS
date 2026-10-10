"""
Single place that decides where a city's data comes from.

Real-data cities (pipeline.config.REAL_CITIES) are served from
features_real.parquet (+ predictions); every other city is the legacy
synthetic preview. Routers call these helpers instead of hard-coding paths.
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import pandas as pd

from pipeline.config import (
    city_features_file, city_grid_file, city_processed_dir, city_real_features_file,
    is_real_city,
)

GRID_PROPS = [
    "frac_impervious", "frac_vegetation", "frac_bare_soil", "frac_water", "ndvi_mean",
    "ndbi_mean", "building_density", "building_height_mean", "air_temp_max",
    "wind_speed_mean", "solar_radiation", "pop_density", "elev_mean",
]


def data_kind(city_id: str) -> str:
    return "real" if is_real_city(city_id) and city_real_features_file(city_id).exists() \
        else "synthetic_preview"


def is_real(city_id: str) -> bool:
    return data_kind(city_id) == "real"


def features_path(city_id: str):
    return city_real_features_file(city_id) if is_real(city_id) else city_features_file(city_id)


def read_features(city_id: str) -> pd.DataFrame:
    df = pd.read_parquet(features_path(city_id))
    if is_real(city_id):
        df = df[df["lst_mean"].notna()].reset_index(drop=True)
    return df


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


@lru_cache(maxsize=8)
def _real_grid(city_id: str, mtime: float) -> dict:
    with open(city_grid_file(city_id)) as f:
        geo = json.load(f)
    df = pd.read_parquet(city_real_features_file(city_id)).set_index("grid_id")
    pred_f = city_processed_dir(city_id) / "predictions_real.parquet"
    if pred_f.exists():
        df = df.join(pd.read_parquet(pred_f).set_index("grid_id"))
    cols = [c for c in GRID_PROPS + ["lst_std", "n_scenes", "lst_pred", "lst_q10", "lst_q90",
                                     "ward_id", "ward_name"] if c in df.columns]
    feats = []
    for feat in geo["features"]:
        gid = feat["properties"]["grid_id"]
        if gid not in df.index:
            continue
        row = df.loc[gid]
        if pd.isna(row["lst_mean"]):
            continue  # no satellite observation for this cell
        props = {"grid_id": gid, "lst_mean": _clean(row["lst_mean"]),
                 "lst_max": _clean(row["lst_max"]), "tier": row["tier"],
                 "delta_above_mean": _clean(row["delta_above_mean"]),
                 "priority_score": _clean(row["priority_score"]),
                 "data_kind": "real"}
        props.update({c: _clean(row[c]) if c not in ("ward_id", "ward_name") else row[c]
                      for c in cols})
        feats.append({"type": "Feature", "geometry": feat["geometry"], "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def grid_geojson(city_id: str) -> dict:
    if is_real(city_id):
        return _real_grid(city_id, city_real_features_file(city_id).stat().st_mtime)
    with open(city_grid_file(city_id)) as f:
        return json.load(f)
