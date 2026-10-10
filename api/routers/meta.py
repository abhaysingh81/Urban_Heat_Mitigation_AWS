"""Model card, cooling spots and the citizen 'what do I do today?' payload."""

from fastapi import APIRouter, Depends, HTTPException, Query

from api import aws
from api.routers.risk import require_real, today as risk_today_endpoint
from api.data_source import read_features
from models.risk import nearest_cooling_spots, ward_table
from pipeline.real.gridspec import GridSpec

router = APIRouter(prefix="/api/v1", tags=["meta"])

LEVEL_TEXT = {
    "green": ("Normal day. Stay hydrated.", "सामान्य दिन। पानी पीते रहें।"),
    "yellow": ("Hot day. Avoid long time in the sun, drink water often.",
               "गर्म दिन। धूप में ज़्यादा समय न रहें, बार-बार पानी पिएँ।"),
    "orange": ("Very hot. Avoid going out at midday; check on older people and children.",
               "बहुत गर्मी। दोपहर में बाहर न निकलें; बुज़ुर्गों और बच्चों का ध्यान रखें।"),
    "red": ("Extreme heat. Stay indoors in the day; seek a cool place if you feel unwell; call 112 or 108 in an emergency.",
            "अत्यधिक गर्मी। दिन में घर के अंदर रहें; तबीयत बिगड़े तो ठंडी जगह जाएँ; आपात स्थिति में 112 या 108 पर कॉल करें।"),
}


@router.get("/model-card")
async def model_card():
    card = aws.model_card()
    if not card:
        raise HTTPException(404, "No real-data model has been trained yet (python -m models.train_real).")
    return card


@router.get("/cooling-spots")
async def cooling_spots(lat: float = Query(...), lon: float = Query(...), k: int = Query(3, ge=1, le=10),
                        city_id: str = Depends(require_real)):
    return {"city_id": city_id, "spots": nearest_cooling_spots(city_id, lat, lon, k)}


@router.get("/citizen")
async def citizen(lat: float = Query(...), lon: float = Query(...), city_id: str = Depends(require_real)):
    spec = GridSpec.for_city(city_id)
    r, c, ok = spec.lonlat_to_cell_rc([lon], [lat])
    if not ok[0]:
        raise HTTPException(400, "Location is outside this city's analysis area")
    row = spec.rows - 1 - int(r[0])
    gid = f"cell_{int(c[0]) * spec.rows + row:04d}"
    df = read_features(city_id)
    cell = df[df["grid_id"] == gid]
    w = ward_table(city_id)
    ward = None
    if not cell.empty:
        m = w[w["ward_id"] == cell.iloc[0]["ward_id"]]
        ward = None if m.empty else m.iloc[0]
    today = await risk_today_endpoint(city_id)
    level = today["alert_level"]
    advisory_url = None
    if aws.DATA_BUCKET:  # Hindi Polly advisory written by the daily forecast job
        try:
            from datetime import date
            key = f"advisories/{city_id}/{date.today().isoformat()}.mp3"
            aws.client("s3").head_object(Bucket=aws.DATA_BUCKET, Key=key)
            advisory_url = aws.presign_get(key, 3600)
        except Exception:
            advisory_url = None
    en, hi = LEVEL_TEXT[level]
    return {
        "city_id": city_id, "grid_id": gid, "alert_level": level, "stale": today.get("stale", False),
        "message_en": en, "message_hi": hi,
        "ward": None if ward is None else {"ward_id": ward["ward_id"], "ward_name": ward["ward_name"],
                                            "rank": int(ward["rank"]), "of_wards": int(len(w)),
                                            "risk_score": float(ward["risk_score"])},
        "forecast_tmax_c": today.get("forecast_tmax_c"),
        "advisory_audio_url": advisory_url,
        "nearest_cooling_spots": nearest_cooling_spots(city_id, lat, lon, 3),
    }
