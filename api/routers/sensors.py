"""Street-level temperature sensors (Feature G: AWS IoT Core): latest reading per sensor."""

import time

from fastapi import APIRouter, Depends

from api import store
from api.routers.risk import require_real
from models.risk import alert_level
from pipeline.real.weather import heat_index_c

router = APIRouter(prefix="/api/v1/sensors", tags=["sensors"])
STALE_AFTER_S = 15 * 60   # sensors report every 60 s; a quarter of an hour of silence means offline


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def clean(item: dict, now: float | None = None) -> dict | None:
    """One reading as the map needs it, or None if it has no usable temperature or position."""
    temp, lat, lon = _num(item.get("temp_c")), _num(item.get("lat")), _num(item.get("lon"))
    if temp is None or lat is None or lon is None or not -30 <= temp <= 70:
        return None
    rh = _num(item.get("humidity"))
    hi = round(heat_index_c(temp, rh), 1) if rh is not None and 0 <= rh <= 100 else None
    received = _num(item.get("received_at"))   # milliseconds, set by the IoT rule
    age = None if received is None else max(0, int((now or time.time()) - received / 1000))
    return {"sensor_id": str(item.get("sensor_id")), "lat": lat, "lon": lon, "temp_c": round(temp, 1),
            "humidity_pct": None if rh is None else round(rh), "heat_index_c": hi,
            "alert_level": alert_level(temp, hi), "age_s": age,
            "stale": age is None or age > STALE_AFTER_S}


@router.get("")
async def sensors(city_id: str = Depends(require_real)):
    """Latest reading from each street sensor in the city. Empty when no sensors are connected."""
    readings = [r for r in (clean(i) for i in store.list_sensor_readings(city_id)) if r]
    live = [r for r in readings if not r["stale"]]
    return {"city_id": city_id, "count": len(readings), "live": len(live),
            "max_temp_c": max((r["temp_c"] for r in live), default=None),
            "sensors": sorted(readings, key=lambda r: r["sensor_id"])}
