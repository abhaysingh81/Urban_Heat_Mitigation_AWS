"""
Daily early-warning job (EventBridge Scheduler -> this Lambda).

For each real-data city: pull the forecast, recompute today's ward risk,
write it to S3, and — when the alert level is high enough — publish an SNS
alert and a Hindi Polly advisory. Each city is isolated: a failure in one
(e.g. forecast outage) is logged, counted, and does not stop the others; the
last good risk_today.json in S3 keeps being served, flagged stale by the API.

Metrics are emitted as CloudWatch Embedded Metric Format log lines (no extra
API calls or IAM needed).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from api import aws
from api.routers.meta import LEVEL_TEXT
from models.forecast import get_forecast
from models.risk import risk_today
from pipeline.config import CITIES, REAL_CITIES

ALERT_LEVELS = ["green", "yellow", "orange", "red"]
MIN_ALERT = os.environ.get("ALERT_MIN_LEVEL", "orange")
TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN")


def emf(city: str, **metrics):
    print(json.dumps({
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": "HeatRelief", "Dimensions": [["City"]],
            "Metrics": [{"Name": k, "Unit": "Count"} for k in metrics]}]},
        "City": city, **metrics}))


def advisory_text_hi(city_name: str, res: dict) -> str:
    wards = ", ".join(w["ward_name"] for w in res["top_wards"][:3])
    return (f"{city_name} के लिए गर्मी की चेतावनी। आज अधिकतम तापमान {res['forecast_tmax_c']} डिग्री रहने का अनुमान है। "
            f"{LEVEL_TEXT[res['alert_level']][1]} सबसे ज़्यादा जोखिम वाले इलाके: {wards}।")


def process_city(city_id: str) -> dict:
    fc = get_forecast(city_id, 3)
    t = fc["today"]
    res = risk_today(city_id, t["tmax_c"], t["heat_index_c"])
    res.update({"stale": False, "source": "open-meteo forecast", "forecast_days": fc["days"],
                "generated_at": datetime.now(timezone.utc).isoformat()})
    out = {"city": city_id, "alert_level": res["alert_level"], "alert_sent": False}

    if aws.DATA_BUCKET:
        aws.client("s3").put_object(Bucket=aws.DATA_BUCKET, Key=f"risk_today/{city_id}.json",
                                    Body=json.dumps(res), ContentType="application/json")

    if ALERT_LEVELS.index(res["alert_level"]) >= ALERT_LEVELS.index(MIN_ALERT):
        name = CITIES[city_id]["name"]
        audio_url = None
        if aws.DATA_BUCKET:
            try:
                speech = aws.client("polly").synthesize_speech(
                    Text=advisory_text_hi(name, res), OutputFormat="mp3",
                    VoiceId="Kajal", Engine="neural", LanguageCode="hi-IN")
                key = f"advisories/{city_id}/{t['date']}.mp3"
                aws.client("s3").put_object(Bucket=aws.DATA_BUCKET, Key=key,
                                            Body=speech["AudioStream"].read(), ContentType="audio/mpeg")
                audio_url = aws.presign_get(key, 7 * 24 * 3600)
                out["advisory_key"] = key
            except Exception as e:  # audio is a bonus; the alert must still go out
                print(f"polly failed for {city_id}: {type(e).__name__}: {e}")
        if TOPIC_ARN:
            top = "\n".join(f"  {w['rank']}. {w['ward_name']} (risk {w['risk_score']})" for w in res["top_wards"][:5])
            msg = (f"HEAT ALERT — {name}: {res['alert_level'].upper()}\n"
                   f"Forecast high {res['forecast_tmax_c']} °C, heat index {res['forecast_heat_index_c']} °C.\n"
                   f"Highest-risk zones today:\n{top}\n\n{LEVEL_TEXT[res['alert_level']][0]}\n"
                   f"{LEVEL_TEXT[res['alert_level']][1]}\n" + (f"\nHindi audio advisory: {audio_url}\n" if audio_url else ""))
            aws.client("sns").publish(TopicArn=TOPIC_ARN, Subject=f"Heat alert: {name} ({res['alert_level']})", Message=msg)
            out["alert_sent"] = True
    emf(city_id, AlertsFired=int(out["alert_sent"]), RefreshOk=1, RefreshFailed=0)
    return out


def handler(event=None, context=None):
    results = []
    for city_id in (event or {}).get("cities") or REAL_CITIES:
        try:
            results.append(process_city(city_id))
        except Exception as e:
            print(f"refresh failed for {city_id}: {type(e).__name__}: {e}")
            emf(city_id, AlertsFired=0, RefreshOk=0, RefreshFailed=1)
            results.append({"city": city_id, "error": f"{type(e).__name__}: {e}"})
    return {"results": results}
