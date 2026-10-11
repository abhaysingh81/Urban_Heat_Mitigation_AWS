"""
Heat alerts on WhatsApp (AWS End User Messaging Social).

  signup   citizen enters a mobile number + city + level and ticks consent -> pending contact
           (48 h) -> an opt-in template message with a signed confirmation link
  confirm  the link -> contact active for a year; WhatsApp alerts start
  alert    the daily job sends the alert template to every active contact of the city whose
           chosen level is at or below today's level (MAX_SENDS_PER_RUN per run)
  stop     every alert carries a signed unsubscribe link; it deletes the contact

Business-initiated WhatsApp messages must use templates approved in the WhatsApp Business account.
Create two templates there and pass their names to the stack (see AWS_INTEGRATION_HANDOVER.md):
  WHATSAPP_OPTIN_TEMPLATE  body: {{1}} city name, {{2}} confirmation link
  WHATSAPP_ALERT_TEMPLATE  body: {{1}} city, {{2}} level, {{3}} forecast high °C, {{4}} highest-risk
                           zones, {{5}} advice, {{6}} link to the citizen page, {{7}} unsubscribe link
API: socialmessaging.send_whatsapp_message(originationPhoneNumberId, message=<Meta message JSON>,
metaApiVersion). Enabled when WHATSAPP_PHONE_NUMBER_ID is set; otherwise every function is a no-op.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from api import aws, phones

CHANNEL = "whatsapp"
LEVELS = ["green", "yellow", "orange", "red"]
MAX_SENDS_PER_RUN = 500


def enabled() -> bool:
    return bool(os.environ.get("WHATSAPP_PHONE_NUMBER_ID"))


def _send(phone: str, template: str, params: list[str]) -> None:
    message = {"messaging_product": "whatsapp", "to": phone, "type": "template",
               "template": {"name": template, "language": {"code": os.environ.get("WHATSAPP_LANGUAGE", "en")},
                            "components": [{"type": "body",
                                            "parameters": [{"type": "text", "text": str(p)[:1000]} for p in params]}]}}
    aws.client("socialmessaging").send_whatsapp_message(
        originationPhoneNumberId=os.environ["WHATSAPP_PHONE_NUMBER_ID"],
        message=json.dumps(message, ensure_ascii=False).encode(),
        metaApiVersion=os.environ.get("WHATSAPP_META_API_VERSION", "v20.0"))


def link(base_url: str, purpose: str, contact: dict) -> str:
    return (f"{base_url.rstrip('/')}/api/v1/phone-alerts/{purpose}?id={contact['id'].replace('#', '%23')}"
            f"&sig={phones.sign(purpose, contact['id'], contact['created_at'])}")


def start_signup(raw_phone: str, city_id: str, min_level: str, city_name: str, base_url: str) -> str:
    """Create (or refresh) a pending contact and send the opt-in message. Returns the contact id."""
    phone = phones.normalize(raw_phone)
    if not phone:
        raise ValueError("not an Indian mobile number")
    cid = phones.phone_id(CHANNEL, phone)
    existing = phones.get(cid)
    if existing and existing["status"] == "active":
        return cid                       # already subscribed: no second message to the same number
    now = time.time()
    doc = {"id": cid, "channel": CHANNEL, "phone": phone, "city_id": city_id, "min_level": min_level,
           "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
           "expires_at": int(now + phones.PENDING_TTL_S)}
    phones.put(doc)
    if enabled():
        _send(phone, os.environ.get("WHATSAPP_OPTIN_TEMPLATE", "heatrelief_optin"),
              [city_name, link(base_url, "confirm", doc)])
    return cid


def confirm(contact_id: str, sig: str) -> dict | None:
    doc = phones.get(contact_id)
    if not phones.verify("confirm", doc, sig) or doc["status"] != "pending":
        return None
    doc.update(status="active", confirmed_at=datetime.now(timezone.utc).isoformat(),
               expires_at=int(time.time() + phones.EXPIRES_DAYS * 86400))
    phones.put(doc)
    return doc


def unsubscribe(contact_id: str, sig: str) -> bool:
    doc = phones.get(contact_id)
    if not phones.verify("unsubscribe", doc, sig):
        return False
    phones.delete(contact_id)
    return True


def send_city_alert(city_id: str, city_name: str, level: str, tmax, zones: list[str], advice: str,
                    site_url: str) -> dict:
    """Alert template to every active contact for this city at `level` or lower. Never raises."""
    out = {"sent": 0, "failed": 0, "skipped_over_limit": 0}
    if not enabled() or level not in LEVELS[1:]:
        return out
    template = os.environ.get("WHATSAPP_ALERT_TEMPLATE", "heatrelief_alert")
    for doc in phones.list_contacts(CHANNEL, city_id):
        if doc["status"] != "active" or LEVELS.index(doc["min_level"]) > LEVELS.index(level):
            continue
        if out["sent"] + out["failed"] >= MAX_SENDS_PER_RUN:
            out["skipped_over_limit"] += 1
            continue
        try:
            _send(doc["phone"], template, [city_name, level.upper(), tmax, ", ".join(zones[:3]) or "-", advice,
                                           f"{site_url}/citizen?city={city_id}", link(site_url, "unsubscribe", doc)])
            out["sent"] += 1
        except Exception as e:
            out["failed"] += 1
            print(f"whatsapp send failed for {doc['id']}: {type(e).__name__}")
    return out
