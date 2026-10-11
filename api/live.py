"""
Live updates for the officer screens (Feature L: API Gateway WebSocket API).

Browsers connect to the WebSocket API; lambdas/ws_connections records each connection id in
DynamoDB. broadcast() pushes one small JSON event to every open connection. It is best effort:
without WS_CONNECTIONS_TABLE / WS_API_ENDPOINT (local dev) it does nothing, and the officer page
falls back to refreshing on a timer. Events carry a grid cell id, never coordinates.
"""

from __future__ import annotations

import json
import os


def enabled() -> bool:
    return bool(os.environ.get("WS_CONNECTIONS_TABLE") and os.environ.get("WS_API_ENDPOINT"))


def report_event(kind: str, doc: dict) -> dict:
    return {"type": kind, "report": {"id": doc["id"], "city_id": doc["city_id"], "grid_id": doc["grid_id"],
                                     "kind": doc["kind"], "status": doc.get("status", "new"),
                                     "created_at": doc["created_at"], "has_photo": bool(doc.get("photo_key"))}}


def broadcast(event: dict) -> int:
    """Send `event` to every connected screen. Returns how many received it; never raises."""
    if not enabled():
        return 0
    sent = 0
    try:
        import boto3
        from botocore.config import Config
        from api import aws
        table = aws.table(os.environ["WS_CONNECTIONS_TABLE"])
        api = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ["WS_API_ENDPOINT"],
                           region_name=aws.AWS_REGION,
                           config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1}))
        data = json.dumps(event).encode()
        page = table.scan(ProjectionExpression="id", Limit=200)   # an operations room, not a broadcast service
        for item in page.get("Items", []):
            try:
                api.post_to_connection(ConnectionId=item["id"], Data=data)
                sent += 1
            except Exception as e:
                code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
                if code in ("GoneException", "410"):          # browser closed without $disconnect
                    table.delete_item(Key={"id": item["id"]})
    except Exception as e:
        print(f"live broadcast failed: {type(e).__name__}")
    return sent
