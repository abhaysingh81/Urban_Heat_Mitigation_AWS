"""Model card, cooling spots and the citizen 'what do I do today?' payload."""

from fastapi import APIRouter, Depends, HTTPException, Query

from api import aws, shelters, translate
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
async def citizen(lat: float = Query(...), lon: float = Query(...), city_id: str = Depends(require_real),
                  simulate: str = Query(None, pattern="^(yellow|orange|red)$"),
                  lang: str = Query(None, pattern="^[a-z]{2}$")):
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
    today = await risk_today_endpoint(city_id, simulate=simulate)
    level = today["alert_level"]
    advisory_url = advisory_url_en = None
    if aws.DATA_BUCKET:  # Polly advisories (Hindi, Indian English) written by the daily forecast job
        from datetime import date

        def audio(suffix: str):
            try:
                key = f"advisories/{city_id}/{date.today().isoformat()}{suffix}.mp3"
                aws.client("s3").head_object(Bucket=aws.DATA_BUCKET, Key=key)
                return aws.presign_get(key, 3600)
            except Exception:
                return None
        advisory_url, advisory_url_en = audio(""), audio("-en")
    places, skipped = shelters.recommend(city_id, nearest_cooling_spots(city_id, lat, lon, 8), 3)
    en, hi = LEVEL_TEXT[level]
    # regional language (Amazon Translate): None when it is off, unsupported or the call fails
    local = translate.translate(en, lang) if lang else None
    return {
        "city_id": city_id, "grid_id": gid, "alert_level": level, "stale": today.get("stale", False),
        "simulated": today.get("simulated", False),
        "message_en": en, "message_hi": hi,
        "message_local": local, "message_local_lang": lang if local else None,
        "machine_translated": bool(local),
        "ward": None if ward is None else {"ward_id": ward["ward_id"], "ward_name": ward["ward_name"],
                                            "rank": int(ward["rank"]), "of_wards": int(len(w)),
                                            "risk_score": float(ward["risk_score"])},
        "forecast_tmax_c": today.get("forecast_tmax_c"),
        "advisory_audio_url": advisory_url, "advisory_audio_url_en": advisory_url_en,
        # full or closed refuges (live status from ward officers) are moved out of the way
        "nearest_cooling_spots": places,
        "refuges_skipped_full_or_closed": skipped,
    }
