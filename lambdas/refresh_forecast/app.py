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

from api import aws, email_alerts, static_map, translate, voice_calls, whatsapp
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


def advisory_text_en(city_name: str, res: dict) -> str:
    wards = ", ".join(w["ward_name"] for w in res["top_wards"][:3])
    return (f"Heat alert for {city_name}. Today's high is expected to reach {res['forecast_tmax_c']} degrees. "
            f"{LEVEL_TEXT[res['alert_level']][0]} Highest-risk areas: {wards}.")


def _speak(city_id: str, text: str, language: str, key: str) -> str | None:
    """Polly neural voice (Kajal speaks Hindi and Indian English) -> S3 -> week-long link."""
    try:
        speech = aws.client("polly").synthesize_speech(
            Text=text, OutputFormat="mp3", VoiceId="Kajal", Engine="neural", LanguageCode=language)
        aws.client("s3").put_object(Bucket=aws.DATA_BUCKET, Key=key,
                                    Body=speech["AudioStream"].read(), ContentType="audio/mpeg")
        return aws.presign_get(key, 7 * 24 * 3600)
    except Exception as e:  # audio is a bonus; the alert must still go out
        print(f"polly failed for {city_id} ({language}): {type(e).__name__}: {e}")
        return None


def write_risk_history(city_id: str, date: str, tmax: float, heat_index: float | None) -> None:
    """One JSON line per analysis zone per day under analytics/risk_daily/, the table Amazon Athena
    reads for trends over time (Feature J). risk_today/<city>.json keeps only the latest day."""
    full = risk_today(city_id, tmax, heat_index, top_n=100_000)
    rows = "\n".join(json.dumps({
        "ward_id": w["ward_id"], "ward_name": w["ward_name"], "rank": int(w["rank"]),
        "risk_score": float(w["risk_score"]), "risk_today": float(w["risk_today"]),
        "population": int(w["population"]), "lst_mean": float(w["lst_mean"]),
        "alert_level": full["alert_level"], "forecast_tmax_c": full["forecast_tmax_c"],
        "forecast_heat_index_c": full["forecast_heat_index_c"]}) for w in full["top_wards"])
    aws.client("s3").put_object(
        Bucket=aws.DATA_BUCKET, Key=f"analytics/risk_daily/city={city_id}/dt={date}/risk.json",
        Body=rows.encode(), ContentType="application/x-ndjson")


def process_city(city_id: str, simulate: str = None) -> dict:
    fc = get_forecast(city_id, 3)
    t = fc["today"]
    res = risk_today(city_id, t["tmax_c"], t["heat_index_c"])
    res.update({"stale": False, "source": "open-meteo forecast", "forecast_days": fc["days"],
                "generated_at": datetime.now(timezone.utc).isoformat()})
    
    # The real result is what the API serves as its fallback, so write it before any simulation
    if aws.DATA_BUCKET:
        aws.client("s3").put_object(Bucket=aws.DATA_BUCKET, Key=f"risk_today/{city_id}.json",
                                    Body=json.dumps(res), ContentType="application/json")

        if os.environ.get("ANALYTICS_ENABLED") == "true":
            try:
                write_risk_history(city_id, t["date"], t["tmax_c"], t["heat_index_c"])
            except Exception as e:  # the history table is a by-product; never fail the alert for it
                print(f"risk history failed for {city_id}: {type(e).__name__}: {e}")

    if simulate:
        res["alert_level"] = simulate

    out = {"city": city_id, "alert_level": res["alert_level"], "alert_sent": False,
           "simulated": bool(simulate)}

    if ALERT_LEVELS.index(res["alert_level"]) >= ALERT_LEVELS.index(MIN_ALERT):
        name = CITIES[city_id]["name"]
        level = res["alert_level"]
        audio_url = None
        if aws.DATA_BUCKET:
            # a simulated advisory must not replace the one the citizen page plays today
            stem = f"advisories/{city_id}/{'simulated-' if simulate else ''}{t['date']}"
            audio_url = _speak(city_id, advisory_text_hi(name, res), "hi-IN", f"{stem}.mp3")
            if audio_url:
                out["advisory_key"] = f"{stem}.mp3"
            _speak(city_id, advisory_text_en(name, res), "en-IN", f"{stem}-en.mp3")

        # the city's main regional language, when Amazon Translate is on (text only: Polly has no voice for it)
        regional = None
        lang = translate.CITY_LANGUAGE.get(city_id)
        if lang:
            local = translate.translate(LEVEL_TEXT[level][0], lang)
            if local:
                regional = (translate.ENGLISH_NAMES[lang], local)
                out["regional_language"] = lang

        if TOPIC_ARN:
            top = "\n".join(f"  {w['rank']}. {w['ward_name']} (risk {w['risk_score']})" for w in res["top_wards"][:5])
            msg = (("*** SIMULATION — this is a test, not a real alert ***\n\n" if simulate else "") +
                   f"HEAT ALERT — {name}: {level.upper()}\n"
                   f"Forecast high {res['forecast_tmax_c']} °C, heat index {res['forecast_heat_index_c']} °C.\n"
                   f"Highest-risk zones today:\n{top}\n\n{LEVEL_TEXT[level][0]}\n"
                   f"{LEVEL_TEXT[level][1]}\n"
                   + (f"{regional[1]} ({regional[0]}, machine translated)\n" if regional else "")
                   + (f"\nHindi audio advisory: {audio_url}\n" if audio_url else ""))

            subject_prefix = "[SIMULATION] " if simulate else ""
            aws.client("sns").publish(
                TopicArn=TOPIC_ARN,
                Subject=f"{subject_prefix}Heat alert: {name} ({level})",
                Message=msg,
                MessageAttributes={
                    'city': {'DataType': 'String', 'StringValue': city_id},
                    'level_num': {'DataType': 'Number', 'StringValue': str(ALERT_LEVELS.index(level))}
                }
            )
            out["alert_sent"] = True

        # citizens who signed up through Amazon SES get the HTML card
        if email_alerts.enabled():
            site = email_alerts.site_url()
            # Amazon Location static map of today's zones and refuges (None when off or failing);
            # a simulation gets its own file so it never replaces the real day's map
            map_url = static_map.render(city_id, res["top_wards"],
                                        day=f"{t['date']}-simulated" if simulate else t["date"])
            out["map"] = bool(map_url)
            subject, html_body, text_body = email_alerts.build_card(
                name, res, LEVEL_TEXT[level], audio_url=audio_url, regional=regional, simulated=bool(simulate),
                citizen_url=f"{site}/citizen?city={city_id}" if site else None, map_url=map_url)
            out["ses"] = email_alerts.send_city_alert(city_id, level, subject, html_body, text_body)
            out["alert_sent"] = out["alert_sent"] or out["ses"]["sent"] > 0

        # WhatsApp (End User Messaging Social) and phone calls (Amazon Connect) reach real
        # people's phones, so a simulation never uses them
        if simulate:
            out["whatsapp"] = out["voice"] = "skipped (simulation)"
        else:
            site = email_alerts.site_url()
            if whatsapp.enabled():
                out["whatsapp"] = whatsapp.send_city_alert(
                    city_id, name, level, res["forecast_tmax_c"], [w["ward_name"] for w in res["top_wards"]],
                    LEVEL_TEXT[level][0], site)
                out["alert_sent"] = out["alert_sent"] or out["whatsapp"]["sent"] > 0
            if voice_calls.enabled():
                en, hi = advisory_text_en(name, res), advisory_text_hi(name, res)
                out["voice"] = voice_calls.call_city(city_id, level, {"en": en, "hi": hi}, t["date"])
    emf(city_id, AlertsFired=int(out["alert_sent"]), RefreshOk=1, RefreshFailed=0)
    return out


def handler(event=None, context=None):
    results = []
    simulate = (event or {}).get("simulate") or None
    if simulate is not None and simulate not in ALERT_LEVELS:
        raise ValueError(f"simulate must be one of {ALERT_LEVELS}")
    for city_id in (event or {}).get("cities") or REAL_CITIES:
        try:
            results.append(process_city(city_id, simulate=simulate))
        except Exception as e:
            print(f"refresh failed for {city_id}: {type(e).__name__}: {e}")
            emf(city_id, AlertsFired=0, RefreshOk=0, RefreshFailed=1)
            results.append({"city": city_id, "error": f"{type(e).__name__}: {e}"})
    purged = email_alerts.purge_expired_signups()   # SES signups never confirmed within 48 hours
    return {"results": results, **({"expired_signups_removed": purged} if purged else {})}
