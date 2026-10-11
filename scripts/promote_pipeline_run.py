#!/usr/bin/env python3
"""Promote an S3 pipeline run's artifacts into local data/processed and models/artifacts/real.

Usage:
    python scripts/promote_pipeline_run.py --bucket <pipeline-bucket> --run-id <run-id>
    python scripts/promote_pipeline_run.py --s3-uri s3://<pipeline-bucket>/runs/<run-id>

This validates the quality gate in manifest.json before downloading.
Once downloaded, run the smoke tests and deploy.sh to bake the artifacts into the Lambda image:
    python -m pytest tests/
    python scripts/smoke_golden_path.py --offline
    ./scripts/deploy.sh
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import PROCESSED_DIR, REAL_MODEL_DIR
from pipeline.real.s3_sync import sync_s3_down


def promote(bucket: str, run_id: str, force: bool = False):
    import boto3
    s3 = boto3.client("s3")

    manifest_key = f"runs/{run_id}/manifest.json"
    print(f"Checking manifest: s3://{bucket}/{manifest_key}…")
    try:
        resp = s3.get_object(Bucket=bucket, Key=manifest_key)
        manifest = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        print(f"Error reading manifest from s3://{bucket}/{manifest_key}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Manifest Run ID: {manifest.get('run_id')}")
    print(f"Model Version:   {manifest.get('model_version')}")
    print(f"Quality Gate:    Passed={manifest.get('quality_gate_passed')}")

    if not manifest.get("quality_gate_passed", False) and not force:
        print(
            f"ERROR: Quality gate did NOT pass for this run (failing cities: {manifest.get('failing_cities')}).\n"
            "Will not promote unvalidated models without --force.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"\n1. Downloading model artifacts to {REAL_MODEL_DIR}…")
    sync_s3_down(bucket, f"runs/{run_id}/models", REAL_MODEL_DIR)

    print(f"\n2. Downloading processed city datasets to {PROCESSED_DIR}…")
    sync_s3_down(bucket, f"runs/{run_id}/processed", PROCESSED_DIR)

    print("\n3. Validating required artifacts…")
    required_models = ["lst_point.json", "lst_q10.json", "lst_q90.json", "feature_names.json", "model_card.json"]
    for m in required_models:
        f = REAL_MODEL_DIR / m
        if not f.exists():
            print(f"  [WARN] Missing model artifact: {f}")
        else:
            print(f"  [OK] Found model artifact: {f.name} ({f.stat().st_size} bytes)")

    for cid in manifest.get("cities", []):
        feat = PROCESSED_DIR / cid / "features_real.parquet"
        grid = PROCESSED_DIR / cid / "grid.geojson"
        print(f"  [OK] City {cid}: features_real={feat.exists()}, grid={grid.exists()}")

    print(
        f"\nSUCCESS: Run {run_id} promoted successfully.\n"
        "Next steps:\n"
        "  1. Run smoke tests: python scripts/smoke_golden_path.py --offline\n"
        "  2. Rebuild and deploy: ./scripts/deploy.sh\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Promote pipeline artifacts from S3")
    parser.add_argument("--bucket", help="S3 pipeline bucket")
    parser.add_argument("--run-id", help="Pipeline Run ID")
    parser.add_argument("--s3-uri", help="S3 URI like s3://<bucket>/runs/<run-id>")
    parser.add_argument("--force", action="store_true", help="Promote even if quality gate failed")

    args = parser.parse_args()
    bucket = args.bucket
    run_id = args.run_id

    if args.s3_uri:
        uri = args.s3_uri.replace("s3://", "").strip("/")
        parts = uri.split("/")
        if len(parts) >= 3 and parts[1] == "runs":
            bucket = parts[0]
            run_id = parts[2]
        else:
            print("Invalid S3 URI format. Expected: s3://<bucket>/runs/<run-id>", file=sys.stderr)
            sys.exit(1)

    if not bucket or not run_id:
        print("Must specify --bucket and --run-id, or --s3-uri.", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    promote(bucket, run_id, force=args.force)


if __name__ == "__main__":
    main()
