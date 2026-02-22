#!/usr/bin/env python3
"""
이미지용 CloudFront 배포 생성 (S3 + OAC)
- S3 버킷의 emotion-images/ 프리픽스를 CloudFront로 서빙
- OAC로 S3 접근 (퍼블릭 액세스 불필요)
"""

import boto3
import json
import time
import sys
from pathlib import Path

REGION = "us-east-1"

# Config에서 버킷명 로드
import os as _os
def _get_bucket_name():
    env_val = _os.environ.get("S3_BUCKET_NAME", "")
    if env_val:
        return env_val
    try:
        with open(Path(__file__).resolve().parent.parent / "admin_config.json", "r") as f:
            return json.load(f).get("bucket_name", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

BUCKET_NAME = _get_bucket_name()
OAC_NAME = "chatbot-image-oac"
DISTRIBUTION_COMMENT = "Character Chatbot Emotion Images CDN"


def get_account_id() -> str:
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def create_oac(cf_client) -> str:
    """OAC(Origin Access Control) 생성 또는 기존 OAC ID 반환"""
    # 기존 OAC 검색
    try:
        resp = cf_client.list_origin_access_controls()
        for item in resp.get("OriginAccessControlList", {}).get("Items", []):
            if item["Name"] == OAC_NAME:
                print(f"  OAC already exists: {item['Id']}")
                return item["Id"]
    except Exception:
        pass

    resp = cf_client.create_origin_access_control(
        OriginAccessControlConfig={
            "Name": OAC_NAME,
            "Description": "OAC for character chatbot emotion images",
            "SigningProtocol": "sigv4",
            "SigningBehavior": "always",
            "OriginAccessControlOriginType": "s3",
        }
    )
    oac_id = resp["OriginAccessControl"]["Id"]
    print(f"  Created OAC: {oac_id}")
    return oac_id


def create_distribution(cf_client, oac_id: str) -> dict:
    """CloudFront 배포 생성"""
    origin_domain = f"{BUCKET_NAME}.s3.{REGION}.amazonaws.com"
    caller_ref = f"chatbot-images-{int(time.time())}"

    resp = cf_client.create_distribution(
        DistributionConfig={
            "CallerReference": caller_ref,
            "Comment": DISTRIBUTION_COMMENT,
            "Enabled": True,
            "DefaultRootObject": "",
            "Origins": {
                "Quantity": 1,
                "Items": [
                    {
                        "Id": "S3-emotion-images",
                        "DomainName": origin_domain,
                        "OriginPath": "",
                        "S3OriginConfig": {"OriginAccessIdentity": ""},
                        "OriginAccessControlId": oac_id,
                    }
                ],
            },
            "DefaultCacheBehavior": {
                "TargetOriginId": "S3-emotion-images",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": {
                    "Quantity": 2,
                    "Items": ["GET", "HEAD"],
                    "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
                },
                "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",  # CachingOptimized
                "Compress": True,
            },
            "ViewerCertificate": {
                "CloudFrontDefaultCertificate": True,
            },
            "PriceClass": "PriceClass_200",
            "HttpVersion": "http2and3",
        }
    )

    dist = resp["Distribution"]
    return {
        "id": dist["Id"],
        "domain": dist["DomainName"],
        "arn": dist["ARN"],
        "status": dist["Status"],
    }


def update_s3_bucket_policy(account_id: str, distribution_arn: str):
    """S3 버킷 정책에 CloudFront OAC 접근 허용 추가"""
    s3 = boto3.client("s3", region_name=REGION)

    # 기존 정책 가져오기
    existing_policy = {}
    try:
        resp = s3.get_bucket_policy(Bucket=BUCKET_NAME)
        existing_policy = json.loads(resp["Policy"])
    except s3.exceptions.from_code("NoSuchBucketPolicy"):
        pass
    except Exception:
        pass

    statements = existing_policy.get("Statement", [])

    # CloudFront OAC 정책 statement
    cf_statement = {
        "Sid": "AllowCloudFrontServicePrincipal",
        "Effect": "Allow",
        "Principal": {"Service": "cloudfront.amazonaws.com"},
        "Action": "s3:GetObject",
        "Resource": f"arn:aws:s3:::{BUCKET_NAME}/emotion-images/*",
        "Condition": {
            "StringEquals": {
                "AWS:SourceArn": distribution_arn
            }
        },
    }

    # 기존에 같은 Sid가 있으면 교체, 없으면 추가
    found = False
    for i, stmt in enumerate(statements):
        if stmt.get("Sid") == "AllowCloudFrontServicePrincipal":
            statements[i] = cf_statement
            found = True
            break
    if not found:
        statements.append(cf_statement)

    policy = {
        "Version": "2012-10-17",
        "Statement": statements,
    }

    s3.put_bucket_policy(Bucket=BUCKET_NAME, Policy=json.dumps(policy))
    print("  S3 bucket policy updated for CloudFront OAC access")


def save_config(domain: str, dist_id: str):
    """chatbot_config.json에 image_cdn_url 추가"""
    config_path = Path(__file__).resolve().parent.parent / "chatbot_config.json"

    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    config["image_cdn_url"] = f"https://{domain}"
    config["image_cdn_distribution_id"] = dist_id

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"  Saved image_cdn_url to {config_path}")


def find_existing_distribution(cf_client) -> dict | None:
    """기존 이미지 CDN 배포 찾기"""
    paginator = cf_client.get_paginator("list_distributions")
    for page in paginator.paginate():
        dist_list = page.get("DistributionList", {})
        for dist in dist_list.get("Items", []):
            if dist.get("Comment") == DISTRIBUTION_COMMENT:
                return {
                    "id": dist["Id"],
                    "domain": dist["DomainName"],
                    "arn": dist["ARN"],
                    "status": dist["Status"],
                }
    return None


def main():
    cf_client = boto3.client("cloudfront", region_name=REGION)
    account_id = get_account_id()

    print(f"Account: {account_id}")
    print(f"Bucket: {BUCKET_NAME}")
    print()

    # 1. 기존 배포 확인
    print("[1/4] Checking for existing distribution...")
    existing = find_existing_distribution(cf_client)
    if existing:
        print(f"  Found existing distribution: {existing['id']} ({existing['domain']})")
        print(f"  Status: {existing['status']}")
        save_config(existing["domain"], existing["id"])
        print(f"\nImage CDN URL: https://{existing['domain']}/emotion-images/<character>/<image>")
        return

    # 2. OAC 생성
    print("[1/4] Creating OAC...")
    oac_id = create_oac(cf_client)

    # 3. CloudFront 배포 생성
    print("[2/4] Creating CloudFront distribution...")
    dist_info = create_distribution(cf_client, oac_id)
    print(f"  Distribution ID: {dist_info['id']}")
    print(f"  Domain: {dist_info['domain']}")
    print(f"  Status: {dist_info['status']}")

    # 4. S3 버킷 정책 업데이트
    print("[3/4] Updating S3 bucket policy...")
    update_s3_bucket_policy(account_id, dist_info["arn"])

    # 5. config 저장
    print("[4/4] Saving configuration...")
    save_config(dist_info["domain"], dist_info["id"])

    print(f"\nImage CDN URL: https://{dist_info['domain']}/emotion-images/<character>/<image>")
    print("Note: Distribution deployment takes ~5 minutes. Status will change to 'Deployed'.")


if __name__ == "__main__":
    main()
