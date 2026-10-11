"""Citizen heat-alert signup.

Default: an SNS email subscription filtered by city and level (SNS sends the confirmation).
With Amazon SES configured (api/email_alerts.py): a double opt-in into the SES contact list,
and alerts arrive as HTML cards. The answer to the browser is identical in every case."""

import hashlib
import json
import os
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from api import aws, email_alerts
from api.net import client_ip, edge_secret
from pipeline.config import REAL_CITIES

router = APIRouter(prefix="/api/v1", tags=["alerts"])

# The daily job will pass these numerical values in SNS MessageAttributes
LEVEL_NUM = {'green': 0, 'yellow': 1, 'orange': 2, 'red': 3}

MAX_SIGNUPS_PER_HOUR = 5
ACCEPTED = {"detail": "If this address is valid, a confirmation email is on its way."}

# Fallback counter when RATE_LIMIT_TABLE is not set (local dev). It lives in one process,
# so on Lambda the DynamoDB counter below is the one that actually holds across instances.
_ip_signups: dict[str, list[float]] = {}


class SubscribeRequest(BaseModel):
    email: str = Field(max_length=254, pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
    city: Literal[*REAL_CITIES]  # only real cities are supported
    min_level: Literal['yellow', 'orange', 'red']
    consent: bool
    website: str = Field(default="", max_length=100)  # honeypot


def _over_limit(client_ip: str) -> bool:
    """True once this (hashed) IP has used its signups for the current hour."""
    now = time.time()
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    table = os.environ.get("RATE_LIMIT_TABLE")
    if table:
        try:
            hour = int(now // 3600)
            res = aws.client("dynamodb").update_item(
                TableName=table,
                Key={"id": {"S": f"signup#{ip_hash}#{hour}"}},
                UpdateExpression="ADD hits :one SET expires_at = :exp",
                ExpressionAttributeValues={":one": {"N": "1"}, ":exp": {"N": str((hour + 2) * 3600)}},
                ReturnValues="UPDATED_NEW",
            )
            return int(res["Attributes"]["hits"]["N"]) > MAX_SIGNUPS_PER_HOUR
        except Exception as e:  # a counter outage must not block signups; use the local counter
            print(f"rate-limit table unavailable: {type(e).__name__}")
    if len(_ip_signups) > 10_000:
        _ip_signups.clear()
    recent = [t for t in _ip_signups.get(ip_hash, []) if now - t < 3600]
    over = len(recent) >= MAX_SIGNUPS_PER_HOUR
    if not over:
        recent.append(now)
    _ip_signups[ip_hash] = recent
    return over


@router.post("/alerts/subscribe", status_code=202)
def subscribe(req: SubscribeRequest, request: Request):
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent is required")
    if req.website:
        # Honeypot filled, ignore silently
        return ACCEPTED

    # Same answer when throttled, so the response never reveals anything
    if _over_limit(client_ip(request)):
        return ACCEPTED

    email_hash = hashlib.sha256(req.email.lower().encode()).hexdigest()[:12]

    if email_alerts.enabled():
        # behind CloudFront + WAF the link must use the site address; the API's own address is closed
        base = email_alerts.site_url() if edge_secret() else ""
        try:
            email_alerts.start_signup(req.email, req.city, req.min_level,
                                      base or str(request.base_url))
            print(f"SES signup started for {email_hash} ({req.city}, {req.min_level})")
        except Exception as e:
            print(f"SES signup failed for {email_hash}: {type(e).__name__}")
        return ACCEPTED

    topic_arn = os.environ.get("ALERT_TOPIC_ARN")
    if not topic_arn:
        # Works locally without failing
        return ACCEPTED

    policy = {
        'city': [req.city],
        'level_num': [{'numeric': ['>=', LEVEL_NUM[req.min_level]]}]
    }

    try:
        aws.client("sns").subscribe(
            TopicArn=topic_arn,
            Protocol='email',
            Endpoint=req.email,
            Attributes={'FilterPolicy': json.dumps(policy)},
            ReturnSubscriptionArn=True
        )
        print(f"Subscribed {email_hash} for {req.city} at {req.min_level}")
    except Exception as e:
        # Log the error type only: SNS error text can contain the address
        print(f"Failed to subscribe {email_hash}: {type(e).__name__}")
        # Still return 202 to avoid leaking state

    return ACCEPTED


_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
         'content="width=device-width,initial-scale=1"><title>HeatRelief alerts</title></head>'
         '<body style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:48px auto;padding:0 16px;'
         'color:#1d2230"><h2>HeatRelief</h2><p style="font-size:18px">{en}</p><p lang="hi" style="font-size:18px">{hi}</p>'
         '</body></html>')


@router.get("/alerts/confirm", response_class=HTMLResponse)
def confirm(email: str = Query(..., max_length=254), token: str = Query(..., min_length=10, max_length=200)):
    """Second step of the SES double opt-in: the link from the confirmation email."""
    topic = email_alerts.confirm(email, token) if email_alerts.enabled() else None
    if not topic:
        return HTMLResponse(_PAGE.format(
            en="This link is not valid any more. Please sign up again from the HeatRelief page.",
            hi="यह लिंक अब मान्य नहीं है। कृपया HeatRelief पेज से दोबारा साइन अप करें।"), status_code=400)
    city, level = topic.rsplit("-", 1)
    return HTMLResponse(_PAGE.format(
        en=f"Confirmed. You will get heat alerts for {city.replace('_', ' ').title()} at {level} level and above. "
           "Every email has an unsubscribe link.",
        hi="पुष्टि हो गई। अब आपको इस शहर की गर्मी की चेतावनी ईमेल से मिलेगी। हर ईमेल में सदस्यता समाप्त करने का लिंक है।"))
