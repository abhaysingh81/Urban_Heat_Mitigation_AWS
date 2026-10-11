"""Street-sensor threshold alarm (Feature G). Invoked by the AWS IoT rule for hot readings.

The rule forwards any reading at or above its temperature threshold. This function works out
the heat index and alert level and, for orange or red, tells the operations topic. It notifies
operators only: one sensor is not enough evidence to alert citizens. At most one notice per
sensor per hour (a conditional write in the rate-limit table).
"""
import os
import time

import boto3

from models.risk import alert_level
from pipeline.real.weather import heat_index_c

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
NOTIFY_LEVELS = ("orange", "red")
sns = boto3.client("sns", region_name=REGION)
dynamodb = boto3.client("dynamodb", region_name=REGION)


def _first_this_hour(sensor_id: str) -> bool:
    table = os.environ.get("RATE_LIMIT_TABLE")
    if not table:
        return True
    hour = int(time.time() // 3600)
    try:
        dynamodb.put_item(
            TableName=table, ConditionExpression="attribute_not_exists(id)",
            Item={"id": {"S": f"sensor#{sensor_id}#{hour}"}, "expires_at": {"N": str((hour + 2) * 3600)}})
        return True
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        return code != "ConditionalCheckFailedException"   # on any other error, prefer to notify


def handler(event, context):
    try:
        temp = float(event["temp_c"])
    except (KeyError, TypeError, ValueError):
        return {"notified": False, "reason": "no temperature"}
    if not -30 <= temp <= 70:
        return {"notified": False, "reason": "implausible temperature"}
    try:
        rh = float(event.get("humidity"))
        hi = round(heat_index_c(temp, rh), 1) if 0 <= rh <= 100 else None
    except (TypeError, ValueError):
        hi = None
    level = alert_level(temp, hi)
    sensor, city = str(event.get("sensor_id", "unknown"))[:64], str(event.get("city", "unknown"))[:40]
    if level not in NOTIFY_LEVELS:
        return {"notified": False, "level": level}
    topic = os.environ.get("OPS_TOPIC_ARN")
    if not topic or not _first_this_hour(sensor):
        return {"notified": False, "level": level, "reason": "no topic" if not topic else "already notified this hour"}
    sns.publish(
        TopicArn=topic, Subject=f"Street sensor {level.upper()}: {city}"[:100],
        Message=(f"Sensor {sensor} in {city} reads {temp:.1f} °C"
                 + (f" (heat index {hi} °C)" if hi is not None else "")
                 + f": {level.upper()} level.\n\nThis is one sensor reading, sent to operators only. "
                   "Check the sensor and the area before acting. No citizen alert was sent."))
    return {"notified": True, "level": level}
