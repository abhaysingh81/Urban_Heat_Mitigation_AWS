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
    is_real_city, load_city_mask, city_boundary_file, data_version, HOTSPOT_TIERS,
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


def _tiers(lst: np.ndarray, mean: float, std: float) -> np.ndarray:
    z = (lst - mean) / std
    return np.select([z > HOTSPOT_TIERS["critical"], z > HOTSPOT_TIERS["high"], z > HOTSPOT_TIERS["moderate"],
                      z > HOTSPOT_TIERS["normal"]], ["critical", "high", "moderate", "normal"], default="cool")


@lru_cache(maxsize=8)
def _city_table(city_id: str, version: tuple) -> pd.DataFrame:
    """Real-data cells inside the city boundary, with no gaps:
    observed Landsat temperature where it exists, the model's prediction elsewhere
    (lst_source = "observed" | "predicted"). Tiers are relative to the city's own
    observed cells, so a predicted cell never shifts the thresholds."""
    df = pd.read_parquet(city_real_features_file(city_id))
    pred_f = city_processed_dir(city_id) / "predictions_real.parquet"
    if pred_f.exists():
        df = df.merge(pd.read_parquet(pred_f), on="grid_id", how="left")
    mask = load_city_mask(city_id)
    if mask:
        df = df[df["grid_id"].isin(mask["inside"])]
    observed = df["lst_c"].notna() if "lst_c" in df else df["lst_mean"].notna()
    df["lst_source"] = np.where(observed, "observed", "predicted")
    if "lst_pred" in df:
        df["lst_mean"] = df["lst_mean"].where(observed, df["lst_pred"])
        df["lst_max"] = df["lst_max"].where(observed, df.get("lst_q90", df["lst_pred"]))
    df = df[df["lst_mean"].notna()].reset_index(drop=True)
    obs = df.loc[df["lst_source"] == "observed", "lst_mean"]
    mean, std = float(obs.mean()), float(obs.std()) or 1.0
    df["tier"] = _tiers(df["lst_mean"].to_numpy(), mean, std)
    df["delta_above_mean"] = (df["lst_mean"] - mean).round(2)
    return df


def read_features(city_id: str) -> pd.DataFrame:
    if is_real(city_id):
        return _city_table(city_id, data_version(city_id)).copy()
    return pd.read_parquet(features_path(city_id))


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


@lru_cache(maxsize=8)
def _real_grid(city_id: str, version: tuple) -> dict:
    with open(city_grid_file(city_id)) as f:
        geo = json.load(f)
    df = _city_table(city_id, version).set_index("grid_id")
    cols = [c for c in GRID_PROPS + ["lst_std", "n_scenes", "lst_pred", "lst_q10", "lst_q90",
                                     "ward_id", "ward_name"] if c in df.columns]
    mask = load_city_mask(city_id)
    feats = []
    for feat in geo["features"]:
        gid = feat["properties"]["grid_id"]
        if gid not in df.index:
            continue  # outside the city boundary
        geometry = mask["clipped"].get(gid, feat["geometry"]) if mask else feat["geometry"]
        row = df.loc[gid]
        props = {"grid_id": gid, "lst_mean": _clean(row["lst_mean"]),
                 "lst_max": _clean(row["lst_max"]), "tier": row["tier"], "lst_source": row["lst_source"],
                 "delta_above_mean": _clean(row["delta_above_mean"]),
                 "priority_score": _clean(row["priority_score"]),
                 "data_kind": "real"}
        props.update({c: _clean(row[c]) if c not in ("ward_id", "ward_name") else row[c]
                      for c in cols})
        feats.append({"type": "Feature", "geometry": geometry, "properties": props})
    out = {"type": "FeatureCollection", "features": feats}
    bf = city_boundary_file(city_id)
    if bf.exists():
        out["boundary"] = json.loads(bf.read_text())
    return out


def grid_geojson(city_id: str) -> dict:
    if is_real(city_id):
        return _real_grid(city_id, data_version(city_id))
    with open(city_grid_file(city_id)) as f:
        return json.load(f)
