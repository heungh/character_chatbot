#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 인프라 셋업

플로우:
  1) .env 파일이 없으면 → 대화형 프롬프트로 리소스명 한번에 수집 → .env 저장
  2) .env 로드 → DynamoDB 테이블 생성 → S3 버킷 확인 → KB 선택/생성 → admin_config.json 저장

사용법:
  python3 admin_app_setup.py            # .env 없으면 대화형, 있으면 바로 셋업
  python3 admin_app_setup.py --reset    # .env 재생성 후 셋업
"""

import boto3
import json
import os
import random
import string
import sys
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


# ─── .env 유틸리티 ──────────────────────────────────────────────────

def load_env() -> dict:
    """기존 .env 파일 로드"""
    env = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def save_env(env: dict):
    """dict → .env 파일 저장"""
    lines = [
        "# 콘텐츠 관리자 앱 환경설정 (자동 생성)",
        "# 수정 후 python3 admin_app_setup.py 재실행",
        "",
    ]
    for key, value in env.items():
        lines.append(f'{key}="{value}"')
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def random_suffix(length: int = 5) -> str:
    """소문자+숫자 랜덤 접미사"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


# ─── 대화형 환경설정 수집 ───────────────────────────────────────────

def collect_env_interactive() -> dict:
    """대화형으로 모든 설정을 한번에 수집"""
    suffix = random_suffix()

    print("\n" + "=" * 60)
    print("  환경설정 수집")
    print("  각 항목의 기본값을 제안합니다. Enter로 수락, 직접 입력 가능.")
    print("=" * 60)

    # 기존 chatbot_config.json에서 Cognito 정보 읽기
    cognito_pool_id = ""
    cognito_client_id = ""
    try:
        with open("chatbot_config.json", "r", encoding="utf-8") as f:
            cc = json.load(f)
            cognito_pool_id = cc.get("cognito_user_pool_id", "")
            cognito_client_id = cc.get("cognito_client_id", "")
    except FileNotFoundError:
        pass

    # AWS 계정 ID 자동 감지
    detected_account_id = ""
    try:
        sts = boto3.client("sts")
        detected_account_id = sts.get_caller_identity()["Account"]
    except Exception:
        pass

    defaults = {
        "AWS_ACCOUNT_ID": detected_account_id,
        "AWS_REGION": "us-east-1",
        "S3_BUCKET_NAME": f"content-chatbot-{suffix}",
        "DDB_TABLE_NAME": "character_chatbot",
        "KB_NAME": f"content-chatbot-kb-{suffix}",
        "CONTENT_DATA_PREFIX": "content-data/",
        "COGNITO_USER_POOL_ID": cognito_pool_id,
        "COGNITO_CLIENT_ID": cognito_client_id,
    }

    prompts = {
        "AWS_ACCOUNT_ID": "AWS 계정 ID",
        "AWS_REGION": "AWS 리전",
        "S3_BUCKET_NAME": "S3 버킷 이름",
        "DDB_TABLE_NAME": "DynamoDB 테이블 이름 (Single-Table Design)",
        "KB_NAME": "Bedrock Knowledge Base 이름 (기존 KB 사용 시 'existing' 입력)",
        "CONTENT_DATA_PREFIX": "S3 콘텐츠 데이터 접두사",
        "COGNITO_USER_POOL_ID": "Cognito User Pool ID (없으면 빈 칸)",
        "COGNITO_CLIENT_ID": "Cognito Client ID (없으면 빈 칸)",
    }

    env = {}
    for key, label in prompts.items():
        default = defaults[key]
        display_default = default if default else "(없음)"
        raw = input(f"\n  {label}\n  [기본값: {display_default}] > ").strip()
        env[key] = raw if raw else default

    # KB 기존 사용 여부
    env["KB_ID"] = ""
    env["KB_DATA_SOURCE_ID"] = ""

    if env["KB_NAME"].lower() == "existing":
        env["KB_NAME"] = ""
        # 기존 KB 선택
        kb_id = _select_existing_kb(env["AWS_REGION"])
        if kb_id:
            env["KB_ID"] = kb_id

    print("\n" + "─" * 60)
    print("  설정 요약:")
    for k, v in env.items():
        print(f"    {k} = {v}")
    print("─" * 60)

    confirm = input("\n  이 설정으로 진행하시겠습니까? (Y/n): ").strip()
    if confirm.lower() == "n":
        print("  취소되었습니다. 다시 실행해주세요.")
        sys.exit(0)

    save_env(env)
    print(f"\n  .env 파일 저장 완료: {ENV_FILE}")
    return env


def _select_existing_kb(region: str) -> str:
    """기존 KB 목록에서 선택"""
    try:
        client = boto3.client("bedrock-agent", region_name=region)
        resp = client.list_knowledge_bases(maxResults=20)
        kb_list = [
            kb for kb in resp.get("knowledgeBaseSummaries", [])
            if kb.get("status") == "ACTIVE"
        ]
    except Exception as e:
        print(f"  [ERROR] KB 목록 조회 실패: {e}")
        return ""

    if not kb_list:
        print("  활성 KB가 없습니다. 새로 생성합니다.")
        return ""

    print(f"\n  {'#':<4} {'ID':<14} {'이름'}")
    print(f"  {'─'*4} {'─'*14} {'─'*40}")
    for i, kb in enumerate(kb_list, 1):
        print(f"  {i:<4} {kb['knowledgeBaseId']:<14} {kb['name']}")

    while True:
        choice = input(f"\n  사용할 KB 번호 (1-{len(kb_list)}, 새로 생성: n): ").strip()
        if choice.lower() == "n":
            return ""
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(kb_list):
                selected = kb_list[idx]
                print(f"  선택됨: {selected['name']} ({selected['knowledgeBaseId']})")
                return selected["knowledgeBaseId"]
        except ValueError:
            pass
        print(f"  1~{len(kb_list)} 사이의 숫자 또는 'n'을 입력해주세요.")


# ─── 리소스 생성 ────────────────────────────────────────────────────

def ensure_s3_bucket(env: dict):
    """S3 버킷 확인/생성"""
    bucket = env["S3_BUCKET_NAME"]
    region = env["AWS_REGION"]
    s3 = boto3.client("s3", region_name=region)

    try:
        s3.head_bucket(Bucket=bucket)
        print(f"  [SKIP] S3 버킷 '{bucket}' — 이미 존재합니다")
    except s3.exceptions.ClientError as e:
        error_code = int(e.response["Error"]["Code"])
        if error_code == 404:
            print(f"  [CREATE] S3 버킷 '{bucket}' ...", end=" ", flush=True)
            create_args = {"Bucket": bucket}
            if region != "us-east-1":
                create_args["CreateBucketConfiguration"] = {"LocationConstraint": region}
            s3.create_bucket(**create_args)
            print("완료")
        elif error_code == 403:
            print(f"  [WARN] S3 버킷 '{bucket}' — 접근 권한 없음 (다른 계정 소유일 수 있음)")
        else:
            raise


def create_dynamodb_tables(env: dict):
    """DynamoDB 단일 테이블 (character_chatbot) 확인/생성"""
    table_name = env.get("DDB_TABLE_NAME", "character_chatbot")
    region = env["AWS_REGION"]
    ddb = boto3.client("dynamodb", region_name=region)
    existing = ddb.list_tables()["TableNames"]

    if table_name in existing:
        print(f"  [SKIP] {table_name} — 이미 존재합니다")
        return

    print(f"  [CREATE] {table_name} ...", end=" ", flush=True)
    ddb.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1_PK", "AttributeType": "S"},
            {"AttributeName": "GSI1_SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1_PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1_SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    waiter = ddb.get_waiter("table_exists")
    waiter.wait(TableName=table_name, WaiterConfig={"Delay": 3, "MaxAttempts": 30})
    print("완료")


def setup_knowledge_base(env: dict) -> tuple:
    """KB 설정 — 기존 선택 or 새 생성 + 데이터소스 추가. (kb_id, ds_id) 반환."""
    region = env["AWS_REGION"]
    client = boto3.client("bedrock-agent", region_name=region)

    kb_id = env.get("KB_ID", "")

    # 기존 KB 사용
    if kb_id:
        try:
            resp = client.get_knowledge_base(knowledgeBaseId=kb_id)
            print(f"  기존 KB 사용: {resp['knowledgeBase']['name']} ({kb_id})")
        except Exception as e:
            print(f"  [ERROR] KB '{kb_id}' 확인 실패: {e}")
            return "", ""
    else:
        # 새 KB 이름이 있으면 목록에서 같은 이름 찾거나, 사용자에게 선택 요청
        kb_name = env.get("KB_NAME", "")
        if kb_name:
            # 같은 이름의 기존 KB 확인
            try:
                resp = client.list_knowledge_bases(maxResults=20)
                for kb in resp.get("knowledgeBaseSummaries", []):
                    if kb["name"] == kb_name and kb["status"] == "ACTIVE":
                        kb_id = kb["knowledgeBaseId"]
                        print(f"  기존 KB 발견 (이름 매칭): {kb_name} ({kb_id})")
                        break
            except Exception:
                pass

        if not kb_id:
            # KB 생성은 콘솔에서 해야 함 (임베딩 모델 등 복잡한 설정)
            print(f"  [INFO] KB '{kb_name}'를 자동 생성하려면 AWS 콘솔에서 생성 후")
            print(f"         .env의 KB_ID에 입력하고 다시 실행해주세요.")
            print()
            # 대안: 기존 KB에서 선택
            kb_id = _select_existing_kb(region)
            if not kb_id:
                print("  [SKIP] KB 설정을 건너뜁니다.")
                return "", ""

    # .env 업데이트
    env["KB_ID"] = kb_id

    # 데이터소스 추가
    ds_id = _ensure_data_source(client, kb_id, env)
    env["KB_DATA_SOURCE_ID"] = ds_id or ""

    save_env(env)
    return kb_id, ds_id or ""


def _ensure_data_source(client, kb_id: str, env: dict) -> str:
    """KB에 content-data/ 데이터소스 확인/생성"""
    bucket = env["S3_BUCKET_NAME"]
    prefix = env["CONTENT_DATA_PREFIX"]

    # 기존 데이터소스 확인
    try:
        resp = client.list_data_sources(knowledgeBaseId=kb_id)
        for ds in resp.get("dataSourceSummaries", []):
            if ds.get("name") == "content-catalog-data":
                print(f"  [SKIP] 데이터소스 'content-catalog-data' — 이미 존재 (ID: {ds['dataSourceId']})")
                return ds["dataSourceId"]
    except Exception as e:
        print(f"  [WARN] 데이터소스 조회 실패: {e}")

    print("  [CREATE] 데이터소스 'content-catalog-data' ...", end=" ", flush=True)
    try:
        resp = client.create_data_source(
            knowledgeBaseId=kb_id,
            name="content-catalog-data",
            description="콘텐츠 카탈로그 데이터 (캐릭터 프로필, 세계관, 관계 등)",
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{bucket}",
                    "inclusionPrefixes": [prefix],
                },
            },
            dataDeletionPolicy="DELETE",
        )
        ds_id = resp["dataSource"]["dataSourceId"]
        print(f"완료 (ID: {ds_id})")
        return ds_id
    except Exception as e:
        print(f"실패: {e}")
        return ""


def save_admin_config(env: dict, kb_id: str, ds_id: str):
    """admin_config.json 저장"""
    table_name = env.get("DDB_TABLE_NAME", "character_chatbot")
    config = {
        "region": env["AWS_REGION"],
        "bucket_name": env["S3_BUCKET_NAME"],
        "knowledge_base_id": kb_id,
        "content_data_source_id": ds_id,
        "content_data_prefix": env["CONTENT_DATA_PREFIX"],
        "cognito_user_pool_id": env.get("COGNITO_USER_POOL_ID", ""),
        "cognito_client_id": env.get("COGNITO_CLIENT_ID", ""),
        "dynamodb_tables": {
            "chatbot": table_name,
        },
    }

    config_path = "admin_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  '{config_path}' 저장 완료")
    return config


# ─── 메인 ───────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  콘텐츠 관리자 앱 — 인프라 셋업")
    print("=" * 60)

    reset = "--reset" in sys.argv

    # 1) .env 로드 또는 수집
    env = load_env()
    if not env or reset:
        if reset:
            print("\n  --reset: .env를 새로 생성합니다.")
        env = collect_env_interactive()
    else:
        print(f"\n  기존 .env 로드 완료 ({ENV_FILE})")
        for k, v in env.items():
            print(f"    {k} = {v}")
        print()
        use = input("  이 설정으로 진행? (Y/n, 재설정: r): ").strip()
        if use.lower() == "n":
            sys.exit(0)
        elif use.lower() == "r":
            env = collect_env_interactive()

    # 2) S3 버킷 확인/생성
    print("\n[1/4] S3 버킷")
    ensure_s3_bucket(env)

    # 3) DynamoDB 테이블 생성
    print("\n[2/4] DynamoDB 테이블")
    create_dynamodb_tables(env)

    # 4) Knowledge Base 설정
    print("\n[3/4] Bedrock Knowledge Base")
    kb_id, ds_id = setup_knowledge_base(env)

    # 5) admin_config.json 저장
    print("\n[4/4] admin_config.json")
    config = save_admin_config(env, kb_id, ds_id)

    print("\n" + "=" * 60)
    print(json.dumps(config, indent=2, ensure_ascii=False))
    print("=" * 60)

    print("\n셋업 완료!")
    print("\n다음 단계:")
    print("  1. python3 admin_app_seed.py     # 초기 데이터 시딩")
    print("  2. ./admin_app_run.sh             # 관리자 앱 (http://localhost:8503)")
    if not kb_id:
        print("\n  [참고] KB를 나중에 설정하려면:")
        print("    .env의 KB_ID를 채우고 python3 admin_app_setup.py 재실행")


if __name__ == "__main__":
    main()
