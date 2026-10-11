"""
Persistence for plans and citizen reports.

DynamoDB when PLANS_TABLE / REPORTS_TABLE are set (items keep the full
document as a JSON string, avoiding DynamoDB's float restrictions);
otherwise JSON files under RUNTIME_DIR so local dev and tests need no AWS.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from api import aws

STATUSES = ("draft", "approved", "implemented")
_ALLOWED_NEXT = {"draft": {"approved"}, "approved": {"implemented", "draft"}, "implemented": set()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dir(kind: str):
    d = aws.RUNTIME_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _put(table_name: str | None, kind: str, doc: dict):
    if table_name:
        aws.table(table_name).put_item(Item={"id": doc["id"], "city_id": doc.get("city_id", ""),
                                             "updated_at": _now(), "body": json.dumps(doc)})
    else:
        (_dir(kind) / f"{doc['id']}.json").write_text(json.dumps(doc))


def _get(table_name: str | None, kind: str, doc_id: str) -> dict | None:
    if table_name:
        item = aws.table(table_name).get_item(Key={"id": doc_id}).get("Item")
        return json.loads(item["body"]) if item else None
    f = _dir(kind) / f"{doc_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


# ── plans ────────────────────────────────────────────────────
def save_plan(city_id: str, plan: dict) -> dict:
    doc = {"id": uuid.uuid4().hex[:12], "city_id": city_id, "status": "draft",
           "created_at": _now(), "plan": plan,
           "audit": [{"at": _now(), "action": "created", "status": "draft", "actor": "officer"}]}
    _put(aws.PLANS_TABLE, "plans", doc)
    return doc


def get_plan(plan_id: str) -> dict | None:
    return _get(aws.PLANS_TABLE, "plans", plan_id)


def set_plan_status(plan_id: str, status: str, actor: str = "officer", note: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    doc = get_plan(plan_id)
    if doc is None:
        raise KeyError(plan_id)
    if status != doc["status"] and status not in _ALLOWED_NEXT[doc["status"]]:
        raise ValueError(f"cannot move a plan from '{doc['status']}' to '{status}'")
    doc["status"] = status
    doc["audit"].append({"at": _now(), "action": "status_change", "status": status,
                         "actor": actor[:60], "note": note[:300]})
    _put(aws.PLANS_TABLE, "plans", doc)
    return doc


# ── citizen reports ──────────────────────────────────────────
REPORT_STATUSES = ("new", "verified", "dispatched", "resolved", "rejected")


def save_report(city_id: str, grid_id: str, kind: str, note: str, photo_key: str | None) -> dict:
    doc = {"id": uuid.uuid4().hex[:12], "city_id": city_id, "grid_id": grid_id, "kind": kind,
           "note": note[:300], "photo_key": photo_key, "created_at": _now(), "ts": int(time.time()),
           "status": "new", "audit": []}
    _put(aws.REPORTS_TABLE, "reports", doc)
    return doc


def get_report(report_id: str) -> dict | None:
    return _get(aws.REPORTS_TABLE, "reports", report_id)


def set_report_status(report_id: str, status: str, actor: str = "officer", note: str = "") -> dict:
    """Field verification by a ward officer: new -> verified -> dispatched -> resolved (or rejected)."""
    if status not in REPORT_STATUSES:
        raise ValueError(f"status must be one of {REPORT_STATUSES}")
    doc = get_report(report_id)
    if doc is None:
        raise KeyError(report_id)
    doc["status"] = status
    doc.setdefault("audit", []).append({"at": _now(), "status": status, "actor": actor[:60], "note": note[:300]})
    _put(aws.REPORTS_TABLE, "reports", doc)
    return doc


def list_reports(city_id: str) -> list[dict]:
    if aws.REPORTS_TABLE:
        from boto3.dynamodb.conditions import Attr
        table, items, kwargs = aws.table(aws.REPORTS_TABLE), [], {"FilterExpression": Attr("city_id").eq(city_id)}
        while True:  # a scan returns at most 1 MB per call
            page = table.scan(**kwargs)
            items += page.get("Items", [])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [json.loads(i["body"]) for i in items]
    out = []
    for f in _dir("reports").glob("*.json"):
        d = json.loads(f.read_text())
        if d.get("city_id") == city_id:
            out.append(d)
    return out


# ── street sensors (Feature G: AWS IoT Core) ─────────────────
# On AWS the IoT rule writes each reading straight into DynamoDB (latest reading per sensor in
# SENSOR_LATEST_TABLE, keyed by city + sensor_id). Locally the simulator writes JSON files.
def put_sensor_reading(reading: dict) -> None:
    """Local store only; on AWS readings arrive through IoT Core, never through the API."""
    (_dir("sensors") / f"{reading['city']}__{reading['sensor_id']}.json").write_text(json.dumps(reading))


def list_sensor_readings(city_id: str) -> list[dict]:
    import os
    table_name = os.environ.get("SENSOR_LATEST_TABLE")
    if table_name:
        from boto3.dynamodb.conditions import Key
        table, items, kwargs = aws.table(table_name), [], {"KeyConditionExpression": Key("city").eq(city_id)}
        while True:
            page = table.query(**kwargs)
            items += page.get("Items", [])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return items
    return [d for d in (json.loads(f.read_text()) for f in _dir("sensors").glob(f"{city_id}__*.json"))]
