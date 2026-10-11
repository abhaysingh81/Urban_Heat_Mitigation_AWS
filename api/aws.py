"""AWS/runtime configuration, read from environment (never hard-coded)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pipeline.config import PROJECT_ROOT, REAL_MODEL_DIR

RUNTIME_DIR = Path(os.environ.get("RUNTIME_DIR", PROJECT_ROOT / "data" / "runtime"))

DATA_BUCKET = os.environ.get("DATA_BUCKET")          # S3: data, briefs, report photos
PLANS_TABLE = os.environ.get("PLANS_TABLE")          # DynamoDB
REPORTS_TABLE = os.environ.get("REPORTS_TABLE")      # DynamoDB
SHELTERS_TABLE = os.environ.get("SHELTERS_TABLE")    # DynamoDB: live cool-refuge status (Feature L)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


@lru_cache(maxsize=None)
def client(service: str):
    import boto3
    return boto3.client(service, region_name=AWS_REGION)


@lru_cache(maxsize=None)
def table(name: str):
    import boto3
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(name)


def model_card() -> dict | None:
    f = REAL_MODEL_DIR / "model_card.json"
    return json.loads(f.read_text()) if f.exists() else None


def model_version() -> str:
    card = model_card()
    return card["model_version"] if card else "synthetic-preview"


def data_date() -> str:
    card = model_card()
    return (card or {}).get("trained_at", "")[:10]


def presign_get(key: str, expires: int = 3600) -> str:
    return client("s3").generate_presigned_url(
        "get_object", Params={"Bucket": DATA_BUCKET, "Key": key}, ExpiresIn=expires)
