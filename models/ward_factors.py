"""
Ward heat-risk profile with 12 factors in four groups, adjustable weights.

  hazard       mean surface temperature, hottest-decile surface temperature,
               share of hotspot cells
  exposure     population, crowd points (hospitals + bus stops)
  sensitivity  population density, green deficit, sealed-surface share
  coping       distance to the nearest indoor cool refuge, distance to the
               nearest drinking-water point, tree cover, parks within 500 m
               (lower coping capacity = higher risk)

Every factor becomes a 0–1 percentile against a *reference* ward table
(by default the city as it is today), so a projected "after" table can be
scored on the same scale and risk can actually go down. A group score is the
mean of its factors; risk = 100 × Σ weight_g × group_g. All inputs come
from data already in the repo; distances are straight-line.
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import pandas as pd

from models.risk import cell_components, _file_key
from pipeline.config import city_cooling_spots_file

REFUGE_TYPES = {"hospital", "clinic", "shelter", "community_centre", "library"}
WATER_TYPES = {"drinking_water"}
PARK_TYPES = {"park"}
DIST_CAP_M = 5000.0
TREE_CANOPY_M2 = 30.0

# factor -> (group, direction): +1 = higher value is riskier, -1 = higher value is safer
FACTORS = {
    "lst_mean": ("hazard", 1, "Mean surface temperature (°C)"),
    "lst_p90": ("hazard", 1, "Hottest 10% surface temperature (°C)"),
    "hotspot_share": ("hazard", 1, "Share of hotspot cells"),
    "population": ("exposure", 1, "People living here"),
    "crowd_points": ("exposure", 1, "Hospitals and bus stops (crowd points)"),
    "pop_density": ("sensitivity", 1, "Population density (people/km²)"),
    "green_deficit": ("sensitivity", 1, "Green deficit (0–1)"),
    "sealed_share": ("sensitivity", 1, "Sealed (impervious) surface share"),
    "dist_refuge_m": ("coping", 1, "Distance to nearest cool refuge (m)"),
    "dist_water_m": ("coping", 1, "Distance to nearest drinking water (m)"),
    "tree_cover": ("coping", -1, "Tree cover share"),
    "parks_500m": ("coping", -1, "Parks within 500 m"),
}
GROUPS = ("hazard", "exposure", "sensitivity", "coping")
WEIGHT_PRESETS = {
    "balanced": {"hazard": 0.35, "exposure": 0.25, "sensitivity": 0.20, "coping": 0.20},
    "heat_first": {"hazard": 0.50, "exposure": 0.20, "sensitivity": 0.15, "coping": 0.15},
    "equity_first": {"hazard": 0.25, "exposure": 0.20, "sensitivity": 0.30, "coping": 0.25},
    "access_first": {"hazard": 0.25, "exposure": 0.20, "sensitivity": 0.20, "coping": 0.35},
}


def _xy_m(lat, lon, lat0):
    lat = np.asarray(lat, float); lon = np.asarray(lon, float)
    return np.c_[(lon - 0) * 111_320 * np.cos(np.radians(lat0)), lat * 110_540]


def _spots(city_id: str) -> list[dict]:
    f = city_cooling_spots_file(city_id)
    return json.loads(f.read_text()) if f.exists() else []


def nearest_distance(cells: pd.DataFrame, points: list[tuple[float, float]]) -> np.ndarray:
    if not points:
        return np.full(len(cells), DIST_CAP_M)
    from scipy.spatial import cKDTree
    lat0 = float(cells["centroid_lat"].mean())
    tree = cKDTree(_xy_m([p[0] for p in points], [p[1] for p in points], lat0))
    d, _ = tree.query(_xy_m(cells["centroid_lat"], cells["centroid_lon"], lat0))
    return np.minimum(d, DIST_CAP_M)


def count_within(cells: pd.DataFrame, points: list[tuple[float, float]], radius_m: float) -> np.ndarray:
    if not points:
        return np.zeros(len(cells))
    from scipy.spatial import cKDTree
    lat0 = float(cells["centroid_lat"].mean())
    tree = cKDTree(_xy_m([p[0] for p in points], [p[1] for p in points], lat0))
    xy = _xy_m(cells["centroid_lat"], cells["centroid_lon"], lat0)
    return np.array([len(x) for x in tree.query_ball_point(xy, radius_m)], dtype=float)


@lru_cache(maxsize=8)
def _base_cells(key) -> pd.DataFrame:
    city_id = key[0]
    df = cell_components(city_id).reset_index(drop=True)
    spots = _spots(city_id)
    pts = lambda types: [(s["lat"], s["lon"]) for s in spots if s.get("type") in types]
    df["dist_refuge_m"] = nearest_distance(df, pts(REFUGE_TYPES))
    df["dist_water_m"] = nearest_distance(df, pts(WATER_TYPES))
    df["parks_500m"] = count_within(df, pts(PARK_TYPES), 500)
    z = (df["lst_hazard"] - df["lst_hazard"].mean()) / df["lst_hazard"].std()
    df["is_hotspot"] = (z > 1).astype(float)
    return df


def base_cells(city_id: str) -> pd.DataFrame:
    return _base_cells(_file_key(city_id)).copy()


def _col(df, name, default=0.0):
    return df[name].fillna(default).astype(float) if name in df else pd.Series(default, index=df.index)


def aggregate(cells: pd.DataFrame, water_shortage: bool = False) -> pd.DataFrame:
    c = cells.copy()
    c["pop_total"] = _col(c, "pop_total")
    c["crowd"] = _col(c, "hospital_count") + _col(c, "bus_stop_count")
    w8 = c["pop_total"] + 1.0
    dist_water = pd.Series(DIST_CAP_M, index=c.index) if water_shortage else c["dist_water_m"]
    c["_wr"] = c["dist_refuge_m"] * w8
    c["_ww"] = dist_water * w8
    g = c.groupby(["ward_id", "ward_name"], sort=False)
    w = g.agg(
        n_cells=("grid_id", "size"), lat=("centroid_lat", "mean"), lon=("centroid_lon", "mean"),
        lst_mean=("lst_hazard", "mean"),
        lst_p90=("lst_hazard", lambda s: float(np.nanpercentile(s, 90)) if s.notna().any() else np.nan),
        hotspot_share=("is_hotspot", "mean"), population=("pop_total", "sum"),
        crowd_points=("crowd", "sum"), pop_density=("pop_density", "mean"),
        green_deficit=("green_deficit", "mean"), sealed_share=("frac_impervious", "mean"),
        tree_cover=("frac_tree", "mean"), parks_500m=("parks_500m", "mean"),
        _wr=("_wr", "sum"), _ww=("_ww", "sum"), _w=("pop_total", lambda s: float((s + 1.0).sum())),
    ).reset_index()
    w["dist_refuge_m"] = w["_wr"] / w["_w"]
    w["dist_water_m"] = w["_ww"] / w["_w"]
    w = w.drop(columns=["_wr", "_ww", "_w"])
    return w[w["n_cells"] >= 3].reset_index(drop=True)


def _pct_against(ref: pd.Series, vals: pd.Series) -> np.ndarray:
    r = np.sort(ref.dropna().to_numpy())
    if len(r) == 0:
        return np.zeros(len(vals))
    v = vals.fillna(np.nanmedian(r)).to_numpy()
    lo = np.searchsorted(r, v, side="left"); hi = np.searchsorted(r, v, side="right")
    return (lo + hi) / 2.0 / len(r)


def resolve_weights(weights: dict | None = None, preset: str = "balanced", power_cut: bool = False) -> dict:
    if preset not in WEIGHT_PRESETS:
        raise ValueError(f"preset must be one of {list(WEIGHT_PRESETS)}")
    w = dict(WEIGHT_PRESETS[preset])
    if weights:
        for k, v in weights.items():
            if k not in GROUPS:
                raise ValueError(f"unknown weight group '{k}'")
            if v < 0:
                raise ValueError("weights must be non-negative")
            w[k] = float(v)
    if power_cut:
        w["sensitivity"] *= 1.5
    s = sum(w.values())
    if s <= 0:
        raise ValueError("weights must not all be zero")
    return {k: round(v / s, 4) for k, v in w.items()}


def score(wards: pd.DataFrame, ref: pd.DataFrame, weights: dict) -> pd.DataFrame:
    out = wards.copy()
    for f, (grp, sign, _) in FACTORS.items():
        p = _pct_against(ref[f], out[f])
        out[f"p_{f}"] = p if sign > 0 else 1 - p
    for grp in GROUPS:
        fs = [f for f, (g, _, _) in FACTORS.items() if g == grp]
        out[grp] = out[[f"p_{f}" for f in fs]].mean(axis=1)
    out["risk_score"] = (100 * sum(weights[g] * out[g] for g in GROUPS)).round(1)
    out["rank"] = out["risk_score"].rank(ascending=False, method="first").astype(int)
    out["band"] = pd.cut(out["risk_score"], [-1, 40, 55, 70, 101], labels=["low", "moderate", "high", "severe"]).astype(str)
    return out


def drivers(row: pd.Series, weights: dict, n: int = 3) -> list[dict]:
    items = []
    for f, (grp, _, label) in FACTORS.items():
        items.append({"factor": f, "label": label, "group": grp, "percentile": round(float(row[f"p_{f}"]), 2),
                      "value": None if pd.isna(row[f]) else round(float(row[f]), 2),
                      "weight": weights[grp] * row[f"p_{f}"]})
    items.sort(key=lambda d: -d["weight"])
    for d in items:
        d.pop("weight")
    return items[:n]


def ward_profile(city_id: str, preset: str = "balanced", weights: dict | None = None,
                 power_cut: bool = False, water_shortage: bool = False) -> dict:
    cells = base_cells(city_id)
    ref = aggregate(cells)
    wards = aggregate(cells, water_shortage=water_shortage)
    wts = resolve_weights(weights, preset, power_cut)
    s = score(wards, ref, wts).sort_values("rank").reset_index(drop=True)
    rows = []
    for _, r in s.iterrows():
        rows.append({
            "ward_id": r["ward_id"], "ward_name": r["ward_name"], "rank": int(r["rank"]),
            "risk_score": float(r["risk_score"]), "band": r["band"],
            "lat": round(float(r["lat"]), 5), "lon": round(float(r["lon"]), 5),
            "groups": {g: round(float(r[g]), 3) for g in GROUPS},
            "factors": {f: (None if pd.isna(r[f]) else round(float(r[f]), 3)) for f in FACTORS},
            "percentiles": {f: round(float(r[f"p_{f}"]), 3) for f in FACTORS},  # 1 = riskiest
            "drivers": drivers(r, wts),
        })
    return {
        "city_id": city_id, "n_wards": len(rows), "weights": wts, "preset": preset,
        "factors": [{"key": f, "group": g, "label": lbl, "higher_is_riskier": sign > 0}
                    for f, (g, sign, lbl) in FACTORS.items()],
        "bands": {b: int((s["band"] == b).sum()) for b in ("severe", "high", "moderate", "low")},
        "wards": rows,
        "method": "Each factor is a percentile rank among this city's wards today; group score = mean of its "
                  "factors; risk = 100 × weighted sum of groups. A relative ranking, not a harm prediction. "
                  "Not included: age, income, informal settlements, night-time temperature.",
    }
