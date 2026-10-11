from fastapi import APIRouter, Response
from pydantic import BaseModel
import os
import json
import time
from datetime import datetime, timezone
from api import auth, aws, email_alerts, live, net, translate, voice_calls, whatsapp

router = APIRouter(prefix="/api/v1/system", tags=["system"])

IS_COLD_START = True

_cache = {}
def get_dynamo_counts():
    global _cache
    now = time.time()
    if "counts" in _cache and now - _cache["counts_time"] < 60:
        return _cache["counts"]
        
    counts = {}
    dynamodb = aws.client('dynamodb')
    for table_env, name in [('PLANS_TABLE', 'plans'), ('REPORTS_TABLE', 'reports')]:
        table_name = os.environ.get(table_env)
        if not table_name:
            counts[name] = 'unavailable'
            continue
        try:
            total = 0
            kwargs = {'TableName': table_name, 'Select': 'COUNT'}
            while True:
                res = dynamodb.scan(**kwargs)
                total += res.get('Count', 0)
                if 'LastEvaluatedKey' not in res:
                    break
                kwargs['ExclusiveStartKey'] = res['LastEvaluatedKey']
            counts[name] = total
        except Exception:
            counts[name] = 'unavailable'
    _cache["counts"] = counts
    _cache["counts_time"] = now
    return counts

def get_sns_counts():
    topic_arn = os.environ.get("ALERT_TOPIC_ARN")
    if not topic_arn:
        return 'unavailable'
    try:
        res = aws.client('sns').get_topic_attributes(TopicArn=topic_arn)
        attrs = res.get('Attributes', {})
        return {
            "confirmed": int(attrs.get('SubscriptionsConfirmed', 0)),
            "pending": int(attrs.get('SubscriptionsPending', 0))
        }
    except Exception:
        return 'unavailable'

def _metric_query(qid: str, namespace: str, name: str, dims: dict, stat: str, period: int) -> dict:
    return {"Id": qid, "ReturnData": True, "MetricStat": {
        "Metric": {"Namespace": namespace, "MetricName": name,
                   "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]},
        "Period": period, "Stat": stat}}


def get_cloudwatch_activity() -> dict | str:
    """Recent activity from Amazon CloudWatch (cached 5 min): API requests, errors, p95 latency and
    throttles over 24 h, plus alerts sent and failed refreshes over 7 days for the default city.
    'unavailable' outside Lambda or when the call fails. Only numbers are returned."""
    fn = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    if not fn:
        return 'unavailable'
    now = time.time()
    if "cw" in _cache and now - _cache["cw_time"] < 300:
        return _cache["cw"]
    from datetime import timedelta
    from pipeline.config import DEFAULT_CITY
    end = datetime.now(timezone.utc)
    lam = {"FunctionName": fn}
    city = {"City": DEFAULT_CITY}

    def fetch(queries, days):
        res = aws.client("cloudwatch").get_metric_data(
            MetricDataQueries=queries, StartTime=end - timedelta(days=days), EndTime=end)
        return {r["Id"]: r.get("Values", []) for r in res.get("MetricDataResults", [])}

    try:
        day = fetch([_metric_query("requests", "AWS/Lambda", "Invocations", lam, "Sum", 3600),
                     _metric_query("errors", "AWS/Lambda", "Errors", lam, "Sum", 3600),
                     _metric_query("throttles", "AWS/Lambda", "Throttles", lam, "Sum", 3600),
                     _metric_query("p95", "AWS/Lambda", "Duration", lam, "p95", 86400)], 1)
        week = fetch([_metric_query("alerts", "HeatRelief", "AlertsFired", city, "Sum", 86400),
                      _metric_query("refresh_failed", "HeatRelief", "RefreshFailed", city, "Sum", 86400),
                      _metric_query("refresh_ok", "HeatRelief", "RefreshOk", city, "Sum", 86400)], 7)
        total = lambda vals: int(sum(vals))
        out = {
            "api_requests_24h": total(day.get("requests", [])),
            "api_errors_24h": total(day.get("errors", [])),
            "api_throttles_24h": total(day.get("throttles", [])),
            "api_p95_ms_24h": round(max(day.get("p95", []) or [0]), 1),
            "alerts_sent_7d": total(week.get("alerts", [])),
            "daily_refresh_ok_7d": total(week.get("refresh_ok", [])),
            "daily_refresh_failed_7d": total(week.get("refresh_failed", [])),
            "city": DEFAULT_CITY,
        }
    except Exception:
        out = 'unavailable'
    _cache["cw"], _cache["cw_time"] = out, now
    return out


def features() -> dict:
    """Which optional AWS services this deployment has switched on (names and counts only)."""
    return {
        "location_map": bool(os.environ.get("LOCATION_MAP_ENABLED") == "true"),
        "knowledge_base": bool(os.environ.get("KNOWLEDGE_BASE_ID")),
        "translate_languages": [l["english_name"] for l in translate.languages()],
        "email_channel": "Amazon SES (HTML cards)" if email_alerts.enabled() else "Amazon SNS (plain text)",
        "sign_in": {"cognito": "Amazon Cognito roles", "token": "shared officer token",
                    "open": "open (local development)"}[auth.mode()],
        "live_updates": live.enabled(),
        "street_sensors": bool(os.environ.get("SENSOR_LATEST_TABLE")),
        "waf": bool(net.edge_secret()),
        "analytics": bool(os.environ.get("ANALYTICS_ENABLED") == "true"),
        "cool_refuge_status": True,
        "static_alert_map": os.environ.get("STATIC_MAP_ENABLED") == "true",
        "batch_briefs": bool(os.environ.get("BATCH_ROLE_ARN")) or os.environ.get("BATCH_BRIEFS_ENABLED") == "true",
        "uptime_canary": os.environ.get("CANARY_ENABLED") == "true",
        "sensor_history": os.environ.get("SENSOR_HISTORY_ENABLED") == "true",
        "officer_token_in_secrets_manager": bool(os.environ.get("OFFICER_TOKEN_SECRET_ARN")),
        "whatsapp_alerts": whatsapp.enabled(),
        "phone_calls": voice_calls.enabled(),
    }


@router.get("/config")
async def client_config(response: Response):
    """What the browser needs to use the optional features. Only public identifiers: the Cognito
    app client id and the WebSocket address are meant to be known to browsers."""
    response.headers["Cache-Control"] = "max-age=60"
    return {
        "auth": {"mode": auth.mode(),
                 "region": auth.pool_id().split("_", 1)[0] if auth.mode() == "cognito" else None,
                 "client_id": auth.client_id() if auth.mode() == "cognito" else None,
                 "roles": list(auth.ROLES)},
        "live": {"ws_url": os.environ.get("WS_PUBLIC_URL") or None},
        "translate": {"languages": translate.languages()},
        "sensors": bool(os.environ.get("SENSOR_LATEST_TABLE")) or not aws.DATA_BUCKET,
        "whatsapp": whatsapp.enabled(),
        "voice_calls": voice_calls.enabled(),
    }


@router.get("/status")
async def system_status(response: Response):
    global IS_COLD_START
    
    # Compute
    compute = {
        "function_name": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "local"),
        "memory_mb": os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "unknown"),
        "region": os.environ.get("AWS_REGION", "local"),
        "timeout_s": os.environ.get("API_TIMEOUT_SECONDS", "unknown")
    }
    
    # Cold start
    cold_start = IS_COLD_START
    IS_COLD_START = False
    
    # AI
    ai = {
        "model_id": os.environ.get("BEDROCK_MODEL_ID", "template"),
        "guardrail_version": os.environ.get("BEDROCK_GUARDRAIL_VERSION", "none"),
        "knowledge_base": os.environ.get("KNOWLEDGE_BASE_ID", "none")
    }
    
    # Storage (DynamoDB)
    storage = get_dynamo_counts()
    
    # Alerts (SNS)
    alerts = get_sns_counts()
    
    # Daily Job
    daily_job = 'unavailable'
    try:
        from pipeline.config import DEFAULT_CITY
        import json
        if aws.DATA_BUCKET:
            res = aws.client('s3').get_object(Bucket=aws.DATA_BUCKET, Key=f"risk_today/{DEFAULT_CITY}.json")
            data = json.loads(res['Body'].read())
            daily_job = {
                "generated_at": data.get("generated_at"),
                "stale": data.get("stale", False)
            }
    except Exception:
        pass
        
    response.headers["Cache-Control"] = "max-age=30"
    
    # Ensure trace headers are also available in response headers for the browser
    model_card = aws.model_card()
    if model_card:
        response.headers["X-Model-Version"] = model_card.get("model_version", "unknown")
        response.headers["X-Data-Date"] = model_card.get("data_date", "unknown")
        
    return {
        "features": features(),
        "compute": compute,
        "cold_start": cold_start,
        "ai": ai,
        "storage": storage,
        "alerts": alerts,
        "daily_job": daily_job,
        "activity": get_cloudwatch_activity(),
        "model": model_card or 'unavailable'
    }
