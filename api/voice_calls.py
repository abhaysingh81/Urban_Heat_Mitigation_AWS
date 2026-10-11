"""
Heat-alert phone calls for people without smartphones (Amazon Connect + Amazon Polly).

Ward officers register a person (an older resident, a household without a smartphone) after
asking for their consent, and record who gave it. On days at or above VOICE_MIN_LEVEL (default red)
the daily job calls each registered person once: StartOutboundVoiceContact with the advisory in
their language as contact attributes; the contact flow plays it with Amazon Polly text-to-speech.

The Amazon Connect instance, a claimed phone number and the contact flow are created by hand
(see AWS_INTEGRATION_HANDOVER.md): the flow sets the voice from $.Attributes.voice and plays
$.Attributes.message as text-to-speech, then disconnects. Concurrent calls are limited per
instance, so a run makes at most MAX_CALLS_PER_RUN calls and stops early when Connect throttles.
Enabled when CONNECT_INSTANCE_ID and CONNECT_CONTACT_FLOW_ID are set; otherwise a no-op.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from api import aws, phones

CHANNEL = "voice"
LEVELS = ["green", "yellow", "orange", "red"]
LANGUAGES = {"hi": "Kajal", "en": "Kajal"}   # Polly neural voice for Hindi and Indian English


def enabled() -> bool:
    return bool(os.environ.get("CONNECT_INSTANCE_ID") and os.environ.get("CONNECT_CONTACT_FLOW_ID"))


def max_calls() -> int:
    return int(os.environ.get("MAX_CALLS_PER_RUN", "10"))


def register(raw_phone: str, city_id: str, ward_id: str, language: str, officer: str, consent_note: str) -> dict:
    phone = phones.normalize(raw_phone)
    if not phone:
        raise ValueError("not an Indian mobile number")
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {sorted(LANGUAGES)}")
    doc = {"id": phones.phone_id(CHANNEL, phone), "channel": CHANNEL, "phone": phone, "city_id": city_id,
           "ward_id": ward_id, "language": language, "status": "active",
           "consent": {"recorded_by": officer[:60], "note": consent_note[:200],
                       "at": datetime.now(timezone.utc).isoformat()},
           "created_at": datetime.now(timezone.utc).isoformat(),
           "expires_at": int(time.time() + phones.EXPIRES_DAYS * 86400)}
    phones.put(doc)
    return doc


def public_view(doc: dict) -> dict:
    return {"id": doc["id"], "phone": phones.mask(doc["phone"]), "city_id": doc["city_id"], "ward_id": doc["ward_id"],
            "language": doc["language"], "consent_by": doc["consent"]["recorded_by"], "created_at": doc["created_at"],
            "expires_at": doc["expires_at"]}


def call_city(city_id: str, level: str, texts: dict[str, str], day: str) -> dict:
    """Call every registered person in the city when today's level is high enough. Never raises."""
    out = {"called": 0, "failed": 0, "not_called_limit": 0}
    min_level = os.environ.get("VOICE_MIN_LEVEL", "red")
    if not enabled() or LEVELS.index(level) < LEVELS.index(min_level):
        return out
    client = aws.client("connect")
    contacts = phones.list_contacts(CHANNEL, city_id)
    for i, doc in enumerate(contacts):
        if out["called"] >= max_calls():
            out["not_called_limit"] = len(contacts) - i
            break
        kwargs = {"DestinationPhoneNumber": doc["phone"], "InstanceId": os.environ["CONNECT_INSTANCE_ID"],
                  "ContactFlowId": os.environ["CONNECT_CONTACT_FLOW_ID"],
                  "ClientToken": f"{day}-{doc['id']}"[:500],   # one call per person per day, even on retries
                  "Attributes": {"message": texts.get(doc["language"], texts["en"])[:1000],
                                 "voice": LANGUAGES[doc["language"]], "language": doc["language"]}}
        if os.environ.get("CONNECT_SOURCE_PHONE_NUMBER"):
            kwargs["SourcePhoneNumber"] = os.environ["CONNECT_SOURCE_PHONE_NUMBER"]
        if os.environ.get("CONNECT_QUEUE_ID"):
            kwargs["QueueId"] = os.environ["CONNECT_QUEUE_ID"]
        try:
            client.start_outbound_voice_contact(**kwargs)
            out["called"] += 1
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            print(f"voice call failed for {doc['id']}: {code}")
            if code in ("LimitExceededException", "ThrottlingException", "TooManyRequestsException"):
                out["not_called_limit"] = len(contacts) - i
                break
            out["failed"] += 1
    return out
