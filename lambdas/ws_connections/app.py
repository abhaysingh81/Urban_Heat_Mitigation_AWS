"""WebSocket connection registry (Feature L): $connect, $disconnect and $default routes.

Each open officer screen is one row in the connections table (it expires by itself after two
hours through the table's TTL). When Cognito is configured, connecting needs a valid officer or
planner access token in the `token` query parameter; otherwise the feed is open, like the public
report summary it mirrors.
"""
import os
import time

import boto3

from api import auth

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
TTL_S = 2 * 3600
_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=REGION).Table(os.environ["WS_CONNECTIONS_TABLE"])
    return _table


def handler(event, context):
    ctx = event.get("requestContext", {})
    route, connection_id = ctx.get("routeKey"), ctx.get("connectionId")
    if route == "$connect":
        if auth.mode() == "cognito":
            token = (event.get("queryStringParameters") or {}).get("token", "")
            try:
                user = auth.user_from_token(token)
            except ValueError:
                return {"statusCode": 401, "body": "sign in required"}
            if not user["groups"]:
                return {"statusCode": 403, "body": "officer or planner role required"}
        table().put_item(Item={"id": connection_id, "expires_at": int(time.time()) + TTL_S})
        return {"statusCode": 200, "body": "connected"}
    if route == "$disconnect":
        table().delete_item(Key={"id": connection_id})
        return {"statusCode": 200, "body": "bye"}
    return {"statusCode": 200, "body": "ok"}   # $default: keep-alive pings from the browser
