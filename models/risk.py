"""
Ward-level heat risk = hazard x exposure x vulnerability.

Each component is a 0-1 percentile rank across the city's wards (so the
score is a *relative* ranking for prioritisation, not an absolute harm
estimate), and every component is returned so a ranking can be explained.

  hazard         0.6 * pct(ward mean LST) + 0.4 * pct(ward p90 LST)
                 (observed Landsat composite; model prediction fills cells
                 outside the satellite footprint)
  exposure       pct(ward total population)
  vulnerability  0.5 * pct(pop density) + 0.3 * pct(green deficit)
                 + 0.2 * pct(building density)   [crowding proxy]

Age structure and informal-settlement data are not in v1; the model card
and API say so. Day/night population switching is likewise not in v1.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from pipeline.config import (
    CITIES, city_cooling_spots_file, city_processed_dir, city_real_features_file,
    is_real_city, load_city_mask, data_version,
)

# City-level alert level from the forecast, on two separate scales (never mixed):
#  * dry-bulb daily max (°C): a simplification of IMD's plains heatwave criteria
#  * heat index / "feels like" (°C): NWS danger bands (caution <32, extreme caution 32–41,
#    danger 41–54, extreme danger >=54), which capture humid heat that Tmax misses
# The alert is the higher of the two, but heat index only escalates the alert on days that are
# already hot (Tmax >= HEAT_INDEX_MIN_TMAX), so a humid-but-mild day does not raise an alarm.
HEAT_INDEX_MIN_TMAX = 35.0
TMAX_LEVELS = [(45.0, "red"), (42.0, "orange"), (40.0, "yellow")]
HEAT_INDEX_LEVELS = [(54.0, "red"), (41.0, "orange"), (32.0, "yellow")]
LEVEL_ORDER = ["green", "yellow", "orange", "red"]
ALERT_MULTIPLIER = {"green": 1.0, "yellow": 1.2, "orange": 1.5, "red": 2.0}


def pct(s: pd.Series) -> pd.Series:
    """Percentile rank in (0, 1]; NaN stays NaN."""
    return s.rank(pct=True, method="average")


def _file_key(city_id: str):
    return data_version(city_id)


@lru_cache(maxsize=8)
def _load(key) -> pd.DataFrame:
    city_id = key[0]
    f = city_real_features_file(city_id)
    if not f.exists():
        raise FileNotFoundError(f"No real-data features for '{city_id}'")
    df = pd.read_parquet(f)
    mask = load_city_mask(city_id)  # keep only cells inside the city's administrative boundary
    if mask:
        df = df[df["grid_id"].isin(mask["inside"])].reset_index(drop=True)
    pred_f = city_processed_dir(city_id) / "predictions_real.parquet"
    if pred_f.exists():
        df = df.merge(pd.read_parquet(pred_f), on="grid_id", how="left")
    else:
        df["lst_pred"] = np.nan
    df["lst_hazard"] = df["lst_c"].fillna(df["lst_pred"])
    df["hazard_source"] = np.where(df["lst_c"].notna(), "observed", "predicted")
    df["pop_total"] = df.get("pop_total", pd.Series(0.0, index=df.index)).fillna(0.0)
    return df


def load_cells(city_id: str) -> pd.DataFrame:
    if not is_real_city(city_id):
        raise ValueError(f"'{city_id}' is a synthetic preview city; risk scoring needs real data")
    return _load(_file_key(city_id)).copy()


def cell_components(city_id: str) -> pd.DataFrame:
    """Per-cell hazard/exposure/vulnerability percentiles (used by the optimizer)."""
    df = load_cells(city_id)
    df["hazard_pct"] = pct(df["lst_hazard"]).fillna(0.0)
    df["pop_density"] = df.get("pop_density", pd.Series(0.0, index=df.index)).fillna(0.0)
    df["green_deficit"] = df.get("green_deficit", pd.Series(0.5, index=df.index)).fillna(0.5)
    bd = df.get("building_density", pd.Series(np.nan, index=df.index))
    df["vuln_pct"] = (0.5 * pct(df["pop_density"]).fillna(0)
                      + 0.3 * pct(df["green_deficit"]).fillna(0)
                      + 0.2 * pct(bd).fillna(pct(df["pop_density"]).fillna(0)))
    return df


def ward_table(city_id: str) -> pd.DataFrame:
    df = cell_components(city_id)
    g = df.groupby(["ward_id", "ward_name"], sort=False)
    w = g.agg(
        n_cells=("grid_id", "size"),
        lon=("centroid_lon", "mean"), lat=("centroid_lat", "mean"),
        population=("pop_total", "sum"),
        lst_mean=("lst_hazard", "mean"),
        lst_p90=("lst_hazard", lambda s: float(np.nanpercentile(s, 90)) if s.notna().any() else np.nan),
        green_deficit=("green_deficit", "mean"),
        pop_density=("pop_density", "mean"),
        building_density=("building_density", "mean") if "building_density" in df else ("pop_density", "mean"),
        observed_share=("hazard_source", lambda s: float((s == "observed").mean())),
    ).reset_index()
    w = w[w["n_cells"] >= 3].reset_index(drop=True)  # drop slivers at the edge

    w["hazard"] = (0.6 * pct(w["lst_mean"]) + 0.4 * pct(w["lst_p90"])).fillna(0)
    w["exposure"] = pct(w["population"]).fillna(0)
    w["vulnerability"] = (0.5 * pct(w["pop_density"]).fillna(0)
                          + 0.3 * pct(w["green_deficit"]).fillna(0)
                          + 0.2 * pct(w["building_density"]).fillna(pct(w["pop_density"]).fillna(0)))
    raw = w["hazard"] * w["exposure"] * w["vulnerability"]
    w["risk_score"] = (100 * raw / raw.max()).round(1) if raw.max() > 0 else 0.0
    w["rank"] = w["risk_score"].rank(ascending=False, method="first").astype(int)
    for c in ("hazard", "exposure", "vulnerability", "lst_mean", "lst_p90", "lon", "lat",
              "green_deficit", "observed_share"):
        w[c] = w[c].round(3)
    w["population"] = w["population"].round(0).astype(int)
    w = w.drop(columns=["pop_density", "building_density"])
    return w.sort_values("rank").reset_index(drop=True)


def _level(value: float | None, bands) -> str:
    if value is None:
        return "green"
    for threshold, level in bands:
        if value >= threshold:
            return level
    return "green"


def alert_level(tmax_c: float, heat_index_c: float | None = None) -> str:
    a = _level(tmax_c, TMAX_LEVELS)
    b = _level(heat_index_c if tmax_c >= HEAT_INDEX_MIN_TMAX else None, HEAT_INDEX_LEVELS)
    return max(a, b, key=LEVEL_ORDER.index)


def risk_today(city_id: str, forecast_tmax_c: float, forecast_heat_index_c: float | None = None,
               top_n: int = 10) -> dict:
    """Apply a forecast to the ward ranking. Ranking comes from the ward table;
    the forecast sets the city-level alert level that scales the score."""
    level = alert_level(forecast_tmax_c, forecast_heat_index_c)
    w = ward_table(city_id)
    mult = ALERT_MULTIPLIER[level]
    w["risk_today"] = (w["risk_score"] * mult).round(1)
    top = w.head(top_n)
    return {"city": city_id, "alert_level": level, "forecast_tmax_c": round(forecast_tmax_c, 1),
            "forecast_heat_index_c": None if forecast_heat_index_c is None else round(forecast_heat_index_c, 1),
            "multiplier": mult,
            "top_wards": top[["ward_id", "ward_name", "rank", "risk_score", "risk_today",
                              "population", "lst_mean", "lat", "lon"]].to_dict("records")}


def nearest_cooling_spots(city_id: str, lat: float, lon: float, k: int = 3) -> list[dict]:
    import json
    f = city_cooling_spots_file(city_id)
    if not f.exists():
        return []
    spots = json.loads(f.read_text())
    if not spots:
        return []
    # straight-line (haversine) distance; a routing service is out of scope for v1
    la, lo = np.radians(lat), np.radians(lon)
    arr = np.array([[s["lat"], s["lon"]] for s in spots])
    dlat, dlon = np.radians(arr[:, 0]) - la, np.radians(arr[:, 1]) - lo
    a = np.sin(dlat / 2) ** 2 + np.cos(la) * np.cos(np.radians(arr[:, 0])) * np.sin(dlon / 2) ** 2
    dist = 2 * 6371000 * np.arcsin(np.sqrt(a))
    order = np.argsort(dist)[:k]

    def format_spot(i):
        s = spots[i].copy()
        if s["name"] in ("Node", "Way", "Water point", "Cooling center") or s["name"].isdigit():
            s["name"] = s["type"].replace("_", " ").title()
        return {**s, "distance_m": int(dist[i])}

    return [format_spot(i) for i in order]
