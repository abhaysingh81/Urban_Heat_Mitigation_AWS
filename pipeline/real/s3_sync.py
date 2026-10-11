"""S3 synchronization utilities for cloud-native pipeline runs."""
from __future__ import annotations

import os
from pathlib import Path


def sync_s3_down(bucket: str, s3_prefix: str, local_dir: Path, strict: bool = False) -> int:
    """Download all objects under s3://bucket/s3_prefix to local_dir.
    strict=True re-raises instead of warning (use it for inputs a run depends on)."""
    try:
        import boto3
        s3 = boto3.client("s3")
        local_dir.mkdir(parents=True, exist_ok=True)
        paginator = s3.get_paginator("list_objects_v2")
        prefix = s3_prefix.strip("/") + "/"
        downloaded = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                rel_path = obj["Key"][len(prefix):]
                if not rel_path or rel_path.endswith("/"):
                    continue
                dest = local_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, obj["Key"], str(dest))
                downloaded += 1
        print(f"  [s3 sync down] downloaded {downloaded} files from s3://{bucket}/{prefix} -> {local_dir}")
        return downloaded
    except Exception as e:
        if strict:
            raise
        print(f"  [s3 sync down warn] failed to sync from s3://{bucket}/{s3_prefix}: {e}")
        return 0


def sync_s3_up(local_dir: Path, bucket: str, s3_prefix: str, strict: bool = False) -> int:
    """Upload all files in local_dir to s3://bucket/s3_prefix.
    strict=True re-raises instead of warning (use it for a run's outputs)."""
    try:
        import boto3
        s3 = boto3.client("s3")
        if not local_dir.exists():
            return 0
        prefix = s3_prefix.strip("/")
        uploaded = 0
        for path in local_dir.rglob("*"):
            if path.is_file():
                rel_path = path.relative_to(local_dir)
                key = f"{prefix}/{rel_path.as_posix()}"
                s3.upload_file(str(path), bucket, key)
                uploaded += 1
        print(f"  [s3 sync up] uploaded {uploaded} files from {local_dir} -> s3://{bucket}/{prefix}")
        return uploaded
    except Exception as e:
        if strict:
            raise
        print(f"  [s3 sync up warn] failed to upload {local_dir} to s3://{bucket}/{s3_prefix}: {e}")
        return 0


def upload_file_to_s3(local_path: Path, bucket: str, s3_key: str, strict: bool = False) -> bool:
    """Upload a single file to s3://bucket/s3_key."""
    try:
        import boto3
        s3 = boto3.client("s3")
        if not local_path.is_file():
            return False
        s3.upload_file(str(local_path), bucket, s3_key)
        print(f"  [s3 upload] {local_path} -> s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        if strict:
            raise
        print(f"  [s3 upload warn] failed to upload {local_path} to s3://{bucket}/{s3_key}: {e}")
        return False
