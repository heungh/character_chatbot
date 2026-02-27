#!/usr/bin/env python3
"""
케이팝 데몬헌터스 챗봇 - 메모리 시스템 인프라 셋업
DynamoDB 테이블 + Cognito User Pool 자동 생성
"""

import boto3
import json
import sys
import time

REGION = "us-east-1"

# ─── DynamoDB 테이블 정의 ───────────────────────────────────────────

TABLES = [
    {
        "TableName": "character_chatbot",
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1_PK", "AttributeType": "S"},
            {"AttributeName": "GSI1_SK", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1_PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1_SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    },
]

# ─── Cognito 설정 ──────────────────────────────────────────────────

COGNITO_POOL_NAME = "CharacterChatbot-UserPool"
COGNITO_CLIENT_NAME = "CharacterChatbot-WebClient"


def create_dynamodb_tables(ddb_client):
    """DynamoDB 테이블 생성"""
    existing = ddb_client.list_tables()["TableNames"]

    for table_def in TABLES:
        name = table_def["TableName"]
        if name in existing:
            print(f"  [SKIP] {name} — 이미 존재합니다")
            continue

        print(f"  [CREATE] {name} ...", end=" ", flush=True)
        ddb_client.create_table(**table_def)

        # 테이블 활성 대기
        waiter = ddb_client.get_waiter("table_exists")
        waiter.wait(TableName=name, WaiterConfig={"Delay": 3, "MaxAttempts": 30})
        print("완료 ✓")


def create_cognito_pool(cognito_client):
    """Cognito User Pool + App Client 생성"""
    # 기존 풀 확인
    pools = cognito_client.list_user_pools(MaxResults=60)["UserPools"]
    for pool in pools:
        if pool["Name"] == COGNITO_POOL_NAME:
            pool_id = pool["Id"]
            print(f"  [SKIP] User Pool '{COGNITO_POOL_NAME}' — 이미 존재 (ID: {pool_id})")

            # App Client 확인/생성
            clients = cognito_client.list_user_pool_clients(
                UserPoolId=pool_id, MaxResults=60
            )["UserPoolClients"]
            for c in clients:
                if c["ClientName"] == COGNITO_CLIENT_NAME:
                    print(f"  [SKIP] App Client '{COGNITO_CLIENT_NAME}' — 이미 존재 (ID: {c['ClientId']})")
                    return pool_id, c["ClientId"]

            # Client가 없으면 생성
            client_resp = cognito_client.create_user_pool_client(
                UserPoolId=pool_id,
                ClientName=COGNITO_CLIENT_NAME,
                ExplicitAuthFlows=[
                    "ALLOW_USER_PASSWORD_AUTH",
                    "ALLOW_REFRESH_TOKEN_AUTH",
                    "ALLOW_USER_SRP_AUTH",
                ],
                PreventUserExistenceErrors="ENABLED",
            )
            client_id = client_resp["UserPoolClient"]["ClientId"]
            print(f"  [CREATE] App Client — ID: {client_id}")
            return pool_id, client_id

    # User Pool 생성
    print(f"  [CREATE] User Pool '{COGNITO_POOL_NAME}' ...", end=" ", flush=True)
    pool_resp = cognito_client.create_user_pool(
        PoolName=COGNITO_POOL_NAME,
        Policies={
            "PasswordPolicy": {
                "MinimumLength": 8,
                "RequireUppercase": True,
                "RequireLowercase": True,
                "RequireNumbers": True,
                "RequireSymbols": False,
            }
        },
        AutoVerifiedAttributes=["email"],
        UsernameAttributes=["email"],
        Schema=[
            {
                "Name": "email",
                "Required": True,
                "Mutable": True,
                "AttributeDataType": "String",
            },
            {
                "Name": "name",
                "Required": False,
                "Mutable": True,
                "AttributeDataType": "String",
            },
        ],
        AccountRecoverySetting={
            "RecoveryMechanisms": [
                {"Priority": 1, "Name": "verified_email"},
            ]
        },
    )
    pool_id = pool_resp["UserPool"]["Id"]
    print(f"완료 ✓ (ID: {pool_id})")

    # App Client 생성
    print(f"  [CREATE] App Client '{COGNITO_CLIENT_NAME}' ...", end=" ", flush=True)
    client_resp = cognito_client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=COGNITO_CLIENT_NAME,
        ExplicitAuthFlows=[
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
            "ALLOW_USER_SRP_AUTH",
        ],
        PreventUserExistenceErrors="ENABLED",
    )
    client_id = client_resp["UserPoolClient"]["ClientId"]
    print(f"완료 ✓ (ID: {client_id})")

    return pool_id, client_id


def print_config(pool_id, client_id):
    """생성된 리소스 정보를 config 형태로 출력"""
    config = {
        "cognito_user_pool_id": pool_id,
        "cognito_client_id": client_id,
        "region": REGION,
        "dynamodb_tables": {
            "chatbot": "character_chatbot",
        },
    }
    print("\n" + "=" * 60)
    print("📋 설정 정보 (character_chatbot.py에서 사용)")
    print("=" * 60)
    print(json.dumps(config, indent=2, ensure_ascii=False))
    print("=" * 60)

    # config 파일로도 저장
    config_path = "chatbot_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"\n💾 설정이 '{config_path}'에 저장되었습니다.")


def main():
    print("🚀 케이팝 데몬헌터스 챗봇 — 메모리 시스템 인프라 셋업")
    print("=" * 60)

    ddb_client = boto3.client("dynamodb", region_name=REGION)
    cognito_client = boto3.client("cognito-idp", region_name=REGION)

    print("\n📦 1/2 DynamoDB 테이블 생성")
    create_dynamodb_tables(ddb_client)

    print("\n🔐 2/2 Cognito User Pool 생성")
    pool_id, client_id = create_cognito_pool(cognito_client)

    print_config(pool_id, client_id)

    print("\n✅ 인프라 셋업 완료!")


if __name__ == "__main__":
    main()
