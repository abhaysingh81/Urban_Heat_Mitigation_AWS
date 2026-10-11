from fastapi import APIRouter, Response
from pydantic import BaseModel
import os
import json
import time
from datetime import datetime, timezone
from api import auth, aws, email_alerts, live, net, translate

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
        "model": model_card or 'unavailable'
    }
