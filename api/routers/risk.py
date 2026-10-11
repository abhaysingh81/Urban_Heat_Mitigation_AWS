"""Ward-level risk endpoints (real-data cities only)."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api import aws
from api.deps import get_city_id
from api.data_source import is_real
from models.risk import alert_level, ward_table, risk_today
from pipeline.config import REAL_CITIES

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])

METHOD = {
    "formula": "risk = hazard × exposure × vulnerability (each a 0–1 percentile rank across wards); rescaled to 0–100",
    "hazard": "0.6·pct(mean surface temperature) + 0.4·pct(90th-percentile surface temperature), Landsat composite",
    "exposure": "pct(total population)",
    "vulnerability": "0.5·pct(population density) + 0.3·pct(green deficit) + 0.2·pct(building density)",
    "not_included": ["age structure", "informal settlements", "income", "day/night population switch"],
    "note": "A relative ranking for prioritisation, not an absolute harm estimate.",
}


def require_real(city_id: str = Depends(get_city_id)) -> str:
    if not is_real(city_id):
        raise HTTPException(404, f"'{city_id}' is a synthetic preview city. Risk scoring is available for: "
                                 f"{', '.join(REAL_CITIES)} (once their real data has been built).")
    return city_id


@router.get("/wards")
async def wards(city_id: str = Depends(require_real)):
    from pipeline.config import city_processed_dir
    import json
    
    w = ward_table(city_id)
    
    card_file = city_processed_dir(city_id) / "data_card.json"
    ward_kind = "2km_analysis_zones"
    if card_file.exists():
        try:
            ward_kind = json.loads(card_file.read_text()).get("ward_kind", ward_kind)
        except Exception:
            pass
            
    method_info = dict(METHOD)
    method_info["boundary_type"] = ward_kind
    
    return {"city_id": city_id, "n_wards": len(w), "method": method_info,
            "wards": w.to_dict("records")}


@router.get("/wards.csv")
async def wards_csv(city_id: str = Depends(require_real)):
    """Ward ranking as CSV (for spreadsheets / GIS)."""
    from fastapi.responses import Response
    csv = ward_table(city_id).to_csv(index=False)
    return Response(csv, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{city_id}_ward_risk.csv"'})


def _cache_file(city_id: str):
    d = aws.RUNTIME_DIR / "risk_today"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{city_id}.json"


def _read_cached(city_id: str):
    if aws.DATA_BUCKET:
        try:
            body = aws.client("s3").get_object(Bucket=aws.DATA_BUCKET, Key=f"risk_today/{city_id}.json")["Body"].read()
            return json.loads(body)
        except Exception:
            pass
    f = _cache_file(city_id)
    return json.loads(f.read_text()) if f.exists() else None


from fastapi import APIRouter, Depends, HTTPException, Query

@router.get("/today")
async def today(city_id: str = Depends(require_real), simulate: str = Query(None, pattern="^(yellow|orange|red)$")):
    """Today's forecast applied to the ward ranking. Falls back to the last good
    result (stale=true), then to hot-season climatology, if the forecast fails."""
    try:
        from models.forecast import get_forecast
        fc = get_forecast(city_id, 3)
        t = fc["today"]
        res = risk_today(city_id, t["tmax_c"], t["heat_index_c"])
        res.update({"stale": False, "source": "open-meteo forecast", "forecast_days": fc["days"],
                    "generated_at": datetime.now(timezone.utc).isoformat()})
        _cache_file(city_id).write_text(json.dumps(res))
        if simulate:
            res.update({"alert_level": simulate, "simulated": True})
        return res
    except Exception as e:
        cached = _read_cached(city_id)
        if cached:
            cached.update({"stale": True, "source": "cached", "error": type(e).__name__})
            if simulate:
                cached.update({"alert_level": simulate, "simulated": True})
            return cached
        import pandas as pd
        from pipeline.config import city_real_features_file
        clim = float(pd.read_parquet(city_real_features_file(city_id))["air_temp_max"].iloc[0])
        res = risk_today(city_id, clim)
        res.update({"stale": True, "source": "hot-season climatology", "error": type(e).__name__})
        if simulate:
            res.update({"alert_level": simulate, "simulated": True})
        return res
