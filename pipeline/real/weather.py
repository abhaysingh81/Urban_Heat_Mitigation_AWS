"""
Weather for the dates the Landsat composite was actually observed
(Open-Meteo archive, free, no key). Values are city-level means, so they
carry between-city climate differences only; the model card says so.
"""

from __future__ import annotations

import math

import numpy as np
import requests

from pipeline.config import CITIES

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY = ["temperature_2m_max", "relative_humidity_2m_mean", "wind_speed_10m_mean",
         "shortwave_radiation_sum"]


def heat_index_c(t_c: float, rh: float) -> float:
    """NWS Rothfusz heat index (input/output °C). Below 27 °C it is just T."""
    if t_c < 27:
        return t_c
    t = t_c * 9 / 5 + 32
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
          - 6.83783e-3 * t * t - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh
          + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    return (hi - 32) * 5 / 9


def wet_bulb_c(t_c: float, rh: float) -> float:
    """Stull (2011) wet-bulb approximation, valid for RH 5–99 %."""
    return (t_c * math.atan(0.151977 * math.sqrt(rh + 8.313659))
            + math.atan(t_c + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


def build(city_id: str, scene_dates: list[str]) -> dict:
    lon, lat = CITIES[city_id]["center"]
    start, end = min(scene_dates), max(scene_dates)
    r = requests.get(ARCHIVE_URL, timeout=60, params={
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": ",".join(DAILY), "timezone": "auto"})
    r.raise_for_status()
    daily = r.json()["daily"]
    keep = [i for i, d in enumerate(daily["time"]) if d in set(scene_dates)]
    if not keep:
        raise RuntimeError(f"Open-Meteo returned none of the scene dates for {city_id}")

    def mean(key):
        vals = [daily[key][i] for i in keep if daily[key][i] is not None]
        return float(np.mean(vals))

    tmax, rh = mean("temperature_2m_max"), mean("relative_humidity_2m_mean")
    return {"scalars": {
        "air_temp_max": round(tmax, 2),
        "humidity_mean": round(rh, 1),
        "wind_speed_mean": round(mean("wind_speed_10m_mean") / 3.6, 2),  # km/h -> m/s
        "solar_radiation": round(mean("shortwave_radiation_sum"), 2),     # MJ/m2/day
        "heat_index_c": round(heat_index_c(tmax, rh), 2),
        "wet_bulb_c": round(wet_bulb_c(tmax, rh), 2),
    }, "n_days": len(keep)}
