"""
Phone contacts for WhatsApp alerts and voice calls — the only place phone numbers are handled.

Privacy rules (plan section 7, India DPDP Act 2023):
  * numbers are stored only to send the alerts the person consented to, in PHONE_ALERTS_TABLE
    (DynamoDB, encrypted at rest) with an expiry: every contact disappears after a year
    (EXPIRES_DAYS) unless renewed, and unconfirmed WhatsApp signups after 48 hours;
  * logs and API answers never carry a full number: logs get a keyed hash, officer screens a
    masked number (+91 98•••••210);
  * confirm / unsubscribe links are signed (HMAC with a key from AWS Secrets Manager), so no
    tokens are stored and a link cannot be forged or reused for another number.
Without the table (local development) contacts are JSON files under RUNTIME_DIR.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time

from api import aws

EXPIRES_DAYS = 365
PENDING_TTL_S = 48 * 3600
_IN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")
_key_cache: dict = {"value": None, "at": 0.0}


def normalize(raw: str) -> str | None:
    """Indian mobile number in E.164 (+91XXXXXXXXXX), or None if it is not one."""
    digits = re.sub(r"[^\d]", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    phone = "+" + digits
    return phone if _IN_MOBILE.match(phone) else None


def mask(phone: str) -> str:
    return f"{phone[:3]} {phone[3:5]}•••••{phone[-3:]}"


def _key() -> bytes:
    """HMAC key: PHONE_KEY_SECRET_ARN (Secrets Manager, cached 5 min) or PHONE_KEY; a fixed key
    only when neither is set and no AWS deployment is configured (local development)."""
    arn = os.environ.get("PHONE_KEY_SECRET_ARN")
    if arn:
        if _key_cache["value"] and time.time() - _key_cache["at"] < 300:
            return _key_cache["value"]
        value = aws.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"].strip().encode()
        _key_cache.update(value=value, at=time.time())
        return value
    if os.environ.get("PHONE_KEY"):
        return os.environ["PHONE_KEY"].encode()
    if table_name():
        raise RuntimeError("PHONE_KEY_SECRET_ARN is required with a phone-alerts table")
    return b"local-development-only"


def phone_id(channel: str, phone: str) -> str:
    """Stable, non-reversible id for a contact (also what logs show)."""
    return f"{channel}#" + hmac.new(_key(), phone.encode(), hashlib.sha256).hexdigest()[:24]


def sign(purpose: str, contact_id: str, created_at: str) -> str:
    return hmac.new(_key(), f"{purpose}|{contact_id}|{created_at}".encode(), hashlib.sha256).hexdigest()[:32]


def verify(purpose: str, contact: dict | None, sig: str) -> bool:
    return bool(contact) and hmac.compare_digest(sign(purpose, contact["id"], contact["created_at"]), sig or "")


# ── storage ──────────────────────────────────────────────────
def table_name() -> str:
    return os.environ.get("PHONE_ALERTS_TABLE", "")


def _dir():
    d = aws.RUNTIME_DIR / "phone_alerts"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _fname(contact_id: str):
    return _dir() / (contact_id.replace("#", "__") + ".json")


def put(doc: dict) -> None:
    if table_name():
        aws.table(table_name()).put_item(Item={"id": doc["id"], "channel": doc["channel"], "city_id": doc["city_id"],
                                               "expires_at": int(doc["expires_at"]), "body": json.dumps(doc)})
    else:
        _fname(doc["id"]).write_text(json.dumps(doc))


def get(contact_id: str) -> dict | None:
    if table_name():
        item = aws.table(table_name()).get_item(Key={"id": contact_id}).get("Item")
        doc = json.loads(item["body"]) if item else None
    else:
        f = _fname(contact_id)
        doc = json.loads(f.read_text()) if f.exists() else None
    return doc if doc and doc["expires_at"] > time.time() else None    # TTL deletion can lag by hours


def delete(contact_id: str) -> None:
    if table_name():
        aws.table(table_name()).delete_item(Key={"id": contact_id})
    else:
        _fname(contact_id).unlink(missing_ok=True)


def list_contacts(channel: str, city_id: str) -> list[dict]:
    if table_name():
        from boto3.dynamodb.conditions import Attr
        table, items = aws.table(table_name()), []
        kwargs = {"FilterExpression": Attr("channel").eq(channel) & Attr("city_id").eq(city_id)}
        while True:
            page = table.scan(**kwargs)
            items += page.get("Items", [])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        docs = [json.loads(i["body"]) for i in items]
    else:
        docs = [json.loads(f.read_text()) for f in _dir().glob(f"{channel}__*.json")]
        docs = [d for d in docs if d["city_id"] == city_id]
    now = time.time()
    return [d for d in docs if d["expires_at"] > now]
