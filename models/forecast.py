"""Daily forecast via Open-Meteo (free, no key) -> heat index and alert level."""

from __future__ import annotations

import requests

from models.risk import alert_level
from pipeline.config import CITIES
from pipeline.real.weather import heat_index_c

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def get_forecast(city_id: str, days: int = 3) -> dict:
    lon, lat = CITIES[city_id]["center"]
    r = requests.get(FORECAST_URL, timeout=30, params={
        "latitude": lat, "longitude": lon, "forecast_days": days, "timezone": "auto",
        "daily": "temperature_2m_max,relative_humidity_2m_mean"})
    r.raise_for_status()
    d = r.json()["daily"]
    out = []
    for date, tmax, rh in zip(d["time"], d["temperature_2m_max"], d["relative_humidity_2m_mean"]):
        if tmax is None:
            continue
        hi = heat_index_c(tmax, rh if rh is not None else 40.0)
        out.append({"date": date, "tmax_c": round(tmax, 1), "humidity_pct": None if rh is None else round(rh),
                    "heat_index_c": round(hi, 1), "alert_level": alert_level(tmax, hi)})
    if not out:
        raise RuntimeError("empty forecast")
    return {"city_id": city_id, "days": out, "today": out[0]}
