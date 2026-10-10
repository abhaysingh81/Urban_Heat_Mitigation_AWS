"""
Planning conditions: "what day are we planning for?"

  mode="today"       live Open-Meteo forecast (falls back to the hot-season
                     average if the forecast is unreachable, flagged)
  mode="hot_season"  average of the Landsat composite scene dates (Apr–Jun)
  mode="custom"      officer-entered max temperature and humidity

On top of any mode: a climate shift (+°C added to the max temperature),
and two stress overlays that change who is at risk, not the temperature:
  power_cut       no fans/AC: crowding and density weigh more
  water_shortage  existing drinking-water points treated as unavailable
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from models.risk import alert_level
from pipeline.config import city_real_features_file
from pipeline.real.weather import heat_index_c

MODES = ("today", "hot_season", "custom")


@dataclass
class ConditionsRequest:
    mode: str = "hot_season"
    climate_shift_c: float = 0.0
    tmax_c: float | None = None        # custom mode
    humidity_pct: float | None = None  # custom mode, or override
    power_cut: bool = False
    water_shortage: bool = False


def _hot_season(city_id: str) -> tuple[float, float]:
    df = pd.read_parquet(city_real_features_file(city_id), columns=["air_temp_max", "humidity_mean"])
    return float(df["air_temp_max"].iloc[0]), float(df["humidity_mean"].iloc[0])


def resolve(city_id: str, req: ConditionsRequest) -> dict:
    if req.mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not -1.0 <= req.climate_shift_c <= 4.0:
        raise ValueError("climate_shift_c must be between -1 and 4 °C")
    notes = []
    source = req.mode
    if req.mode == "custom":
        if req.tmax_c is None:
            raise ValueError("custom mode needs tmax_c")
        tmax, rh = float(req.tmax_c), float(req.humidity_pct if req.humidity_pct is not None else 40.0)
    elif req.mode == "today":
        try:
            from models.forecast import get_forecast
            t = get_forecast(city_id, 1)["today"]
            tmax, rh = float(t["tmax_c"]), float(t["humidity_pct"] if t["humidity_pct"] is not None else 40)
            source = "open-meteo forecast"
        except Exception as e:  # network outage must not block planning
            tmax, rh = _hot_season(city_id)
            source = "hot-season average (forecast unavailable)"
            notes.append(f"Forecast unavailable ({type(e).__name__}); using the hot-season average.")
    else:
        tmax, rh = _hot_season(city_id)
        source = "hot-season average of the satellite scene dates (Apr–Jun)"
    if req.humidity_pct is not None and req.mode != "custom":
        rh = float(req.humidity_pct)

    base_t = tmax
    tmax = tmax + req.climate_shift_c
    hi = heat_index_c(tmax, rh)
    if req.climate_shift_c:
        notes.append(f"Climate shift of {req.climate_shift_c:+.1f} °C applied to the daily maximum.")
    if req.power_cut:
        notes.append("Power cut: density and crowding weigh more in vulnerability (no fans or AC).")
    if req.water_shortage:
        notes.append("Water shortage: existing drinking-water points are treated as unavailable.")
    return {
        "request": asdict(req), "source": source,
        "base_tmax_c": round(base_t, 1), "tmax_c": round(tmax, 1), "humidity_pct": round(rh),
        "heat_index_c": round(hi, 1), "alert_level": alert_level(tmax, hi),
        "power_cut": req.power_cut, "water_shortage": req.water_shortage, "notes": notes,
    }


def feels_like(tmax_c: float, humidity_pct: float, air_delta_c: float) -> float:
    return round(heat_index_c(tmax_c + air_delta_c, humidity_pct), 1)
