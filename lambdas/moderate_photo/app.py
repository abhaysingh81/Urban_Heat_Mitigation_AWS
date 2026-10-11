"""Photo moderation Lambda (Amazon Rekognition).

Reads EventBridge "Object Created" events (or direct S3 Records) for report_photos/,
validates content type and size, calls Rekognition DetectModerationLabels, tags safe
images with moderation=approved and deletes everything else. The optional labels
sidecar goes under report_labels/ (outside report_photos/, so it cannot re-trigger
this function). The API only ever shows photos that carry the approved tag.
"""
import json
import os
import urllib.parse

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
MAX_BYTES = 5 * 1024 * 1024  # size cap; the browser re-encodes to a 1600 px JPEG, far below this
s3 = boto3.client('s3', region_name=REGION)
rekognition = boto3.client('rekognition', region_name=REGION)

# Rekognition could not read the file as an image: it is not a photo, so remove it
_BAD_IMAGE = {"InvalidImageFormatException", "ImageTooLargeException"}
_GONE = {"404", "NoSuchKey", "NotFound"}


def _records(event: dict) -> list[tuple[str, str]]:
    """(bucket, key) pairs from either event shape."""
    out = []
    detail = event.get('detail')
    if isinstance(detail, dict) and 'bucket' in detail and 'object' in detail:
        # EventBridge delivers the key as-is (not URL-encoded)
        out.append((detail['bucket']['name'], detail['object']['key']))
    for r in event.get('Records') or []:
        if 's3' in r:
            # direct S3 notifications URL-encode the key
            out.append((r['s3']['bucket']['name'], urllib.parse.unquote_plus(r['s3']['object']['key'])))
    return out


def moderate(bucket: str, key: str) -> str:
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in _GONE:
            return "gone"  # already deleted (e.g. a retried event)
        raise
    content_type, size = head.get('ContentType', ''), head.get('ContentLength', 0)
    if content_type not in ('image/jpeg', 'image/png') or size > MAX_BYTES:
        print(f"Invalid content type ({content_type}) or size ({size}) for {key}, deleting.")
        s3.delete_object(Bucket=bucket, Key=key)
        return "deleted_invalid"

    image = {'S3Object': {'Bucket': bucket, 'Name': key}}
    try:
        mod_res = rekognition.detect_moderation_labels(Image=image, MinConfidence=70)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in _BAD_IMAGE:
            print(f"Not a readable image: {key}, deleting.")
            s3.delete_object(Bucket=bucket, Key=key)
            return "deleted_unreadable"
        raise

    if mod_res.get('ModerationLabels'):
        names = [m.get('Name') for m in mod_res['ModerationLabels']]
        print(f"Flagged inappropriate content in {key}: {names}, deleting.")
        s3.delete_object(Bucket=bucket, Key=key)
        return "deleted_flagged"

    s3.put_object_tagging(Bucket=bucket, Key=key,
                          Tagging={'TagSet': [{'Key': 'moderation', 'Value': 'approved'}]})
    print(f"Approved photo {key}.")

    # Optional hint for officers, never a gate
    try:
        labels_res = rekognition.detect_labels(Image=image, MaxLabels=10, MinConfidence=70)
        sidecar_key = key.replace("report_photos/", "report_labels/", 1) + ".json"
        labels = [{"name": l.get("Name"), "confidence": round(l.get("Confidence", 0), 1)}
                  for l in labels_res.get('Labels', [])]
        s3.put_object(Bucket=bucket, Key=sidecar_key, Body=json.dumps(labels),
                      ContentType="application/json")
    except Exception as e:
        print(f"Labels sidecar failed for {key}: {type(e).__name__}")
    return "approved"


def handler(event, context):
    results = {}
    for bucket, key in _records(event or {}):
        # Only photos uploaded through the API's presigned URL (report_photos/<city>/<id>.jpg)
        if not key.startswith("report_photos/"):
            print(f"Skipping key outside report_photos/: {key}")
            continue
        if not key.lower().endswith(('.jpg', '.jpeg', '.png')):
            print(f"Not an image key, deleting: {key}")
            s3.delete_object(Bucket=bucket, Key=key)
            results[key] = "deleted_invalid"
            continue
        try:
            results[key] = moderate(bucket, key)
        except Exception as e:
            print(f"Error processing {key}: {type(e).__name__}: {e}")
            raise  # let Lambda retry; an unprocessed photo stays untagged, so it is never shown
    if not results:
        print("No report photos in event.")
    return {"status": "ok", "results": results}
