#!/usr/bin/env python3
"""
로컬 image/ 폴더의 캐릭터 감정 이미지를 S3 emotion-images/ 프리픽스에 업로드
"""

import boto3
import mimetypes
import sys
from pathlib import Path

REGION = "us-east-1"
S3_PREFIX = "emotion-images"

# Config에서 버킷명 로드
def _get_bucket_name():
    import os
    env_val = os.environ.get("S3_BUCKET_NAME", "")
    if env_val:
        return env_val
    try:
        import json
        with open(Path(__file__).resolve().parent.parent / "admin_config.json", "r") as f:
            return json.load(f).get("bucket_name", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

BUCKET_NAME = _get_bucket_name()
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def upload_images(image_dir: Path, bucket: str = BUCKET_NAME, prefix: str = S3_PREFIX, dry_run: bool = False):
    s3 = boto3.client("s3", region_name=REGION)

    if not image_dir.is_dir():
        print(f"Error: {image_dir} is not a directory")
        sys.exit(1)

    uploaded = 0
    skipped = 0

    for char_folder in sorted(image_dir.iterdir()):
        if not char_folder.is_dir():
            continue

        folder_name = char_folder.name  # e.g. rumi, mira, zoey
        for img_file in sorted(char_folder.iterdir()):
            if not img_file.is_file() or img_file.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            s3_key = f"{prefix}/{folder_name}/{img_file.name}"
            content_type = mimetypes.guess_type(str(img_file))[0] or "application/octet-stream"

            if dry_run:
                print(f"  [DRY-RUN] {img_file} -> s3://{bucket}/{s3_key}  ({content_type})")
                uploaded += 1
                continue

            try:
                s3.upload_file(
                    str(img_file),
                    bucket,
                    s3_key,
                    ExtraArgs={"ContentType": content_type},
                )
                print(f"  Uploaded: s3://{bucket}/{s3_key}")
                uploaded += 1
            except Exception as e:
                print(f"  FAILED: {s3_key} — {e}")
                skipped += 1

    print(f"\nDone. Uploaded: {uploaded}, Skipped/Failed: {skipped}")
    return uploaded


def verify_upload(bucket: str = BUCKET_NAME, prefix: str = S3_PREFIX):
    s3 = boto3.client("s3", region_name=REGION)
    paginator = s3.get_paginator("list_objects_v2")

    print(f"\nVerifying s3://{bucket}/{prefix}/")
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/"):
        for obj in page.get("Contents", []):
            print(f"  {obj['Key']}  ({obj['Size']} bytes)")
            count += 1
    print(f"Total objects: {count}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    image_dir = project_root / "image"

    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN MODE ===\n")

    print(f"Source: {image_dir}")
    print(f"Target: s3://{BUCKET_NAME}/{S3_PREFIX}/\n")

    upload_images(image_dir, dry_run=dry_run)

    if not dry_run:
        verify_upload()
