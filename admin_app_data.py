#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 데이터 레이어
AdminDataManager: DDB/S3 CRUD + KB 동기화
"""

import boto3
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

logger = logging.getLogger("admin_app.data")


def _load_config() -> dict:
    """admin_config.json 로드"""
    try:
        with open("admin_config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("admin_config.json 없음 — 기본값 사용")
        return {}


class AdminDataManager:
    """DDB/S3 CRUD + Bedrock KB 동기화"""

    def __init__(self):
        cfg = _load_config()
        region = cfg.get("region", "us-east-1")
        self.region = region
        self.ddb = boto3.resource("dynamodb", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.bedrock_agent = boto3.client("bedrock-agent", region_name=region)

        tables = cfg.get("dynamodb_tables", {})
        self.table = self.ddb.Table(tables.get("chatbot", "character_chatbot"))

        self.bucket_name = cfg.get("bucket_name", "")
        self.kb_id = cfg.get("knowledge_base_id", "")
        self.content_ds_id = cfg.get("content_data_source_id", "")
        self.content_data_prefix = cfg.get("content_data_prefix", "content-data/")

    # ─── 콘텐츠 CRUD ────────────────────────────────────────────────

    def create_content(self, content_data: Dict[str, Any]) -> str:
        """콘텐츠 메타데이터 생성"""
        now = datetime.now(timezone.utc).isoformat()
        content_id = content_data.get("content_id", "")
        if not content_id:
            content_id = self._slugify(content_data.get("title_en", content_data.get("title", "")))

        item = {
            "PK": f"CONTENT#{content_id}",
            "SK": "METADATA",
            "GSI1_PK": "CONTENTS",
            "GSI1_SK": content_id,
            "entity_type": "CONTENT",
            "content_id": content_id,
            "title": content_data.get("title", ""),
            "title_en": content_data.get("title_en", ""),
            "genre": content_data.get("genre", []),
            "platform": content_data.get("platform", ""),
            "release_date": content_data.get("release_date", ""),
            "format": content_data.get("format", ""),
            "runtime": content_data.get("runtime", ""),
            "creator": content_data.get("creator", ""),
            "director": content_data.get("director", []),
            "writer": content_data.get("writer", []),
            "production": content_data.get("production", ""),
            "synopsis": content_data.get("synopsis", ""),
            "world_setting": content_data.get("world_setting", ""),
            "reception": content_data.get("reception", {}),
            "cover_image_url": content_data.get("cover_image_url", ""),
            "character_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.table.put_item(Item=self._sanitize(item))
        return content_id

    def get_content(self, content_id: str) -> Optional[Dict[str, Any]]:
        resp = self.table.get_item(Key={"PK": f"CONTENT#{content_id}", "SK": "METADATA"})
        if "Item" in resp:
            return self._convert_decimals(resp["Item"])
        return None

    def list_contents(self) -> List[Dict[str, Any]]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1_PK = :pk",
            ExpressionAttributeValues={":pk": "CONTENTS"},
        )
        items = resp.get("Items", [])
        return [self._convert_decimals(i) for i in items]

    def update_content(self, content_id: str, updates: Dict[str, Any]):
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        expr_parts, attr_names, attr_values = [], {}, {}
        for i, (key, value) in enumerate(updates.items()):
            expr_parts.append(f"#k{i} = :v{i}")
            attr_names[f"#k{i}"] = key
            attr_values[f":v{i}"] = self._sanitize(value)
        self.table.update_item(
            Key={"PK": f"CONTENT#{content_id}", "SK": "METADATA"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

    def delete_content(self, content_id: str):
        """콘텐츠 및 연관 캐릭터/관계 일괄 삭제 (단일 PK query → batch delete)"""
        pk = f"CONTENT#{content_id}"
        resp = self.table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": pk},
            ProjectionExpression="PK, SK",
        )
        items = resp.get("Items", [])
        if not items:
            return
        # batch_write_item 25개 단위
        ddb_client = self.ddb.meta.client
        table_name = self.table.table_name
        for i in range(0, len(items), 25):
            batch = items[i:i + 25]
            ddb_client.batch_write_item(
                RequestItems={
                    table_name: [
                        {"DeleteRequest": {"Key": {"PK": {"S": item["PK"]}, "SK": {"S": item["SK"]}}}}
                        for item in batch
                    ]
                }
            )

    # ─── 캐릭터 CRUD ────────────────────────────────────────────────

    def create_character(self, content_id: str, char_data: Dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        character_id = char_data.get("character_id", "")
        if not character_id:
            character_id = self._slugify(char_data.get("name_en", char_data.get("name", "")))

        role_type = char_data.get("role_type", "supporting")
        item = {
            "PK": f"CONTENT#{content_id}",
            "SK": f"CHAR#{character_id}",
            "GSI1_PK": f"CONTENT#{content_id}",
            "GSI1_SK": f"ROLE#{role_type}#{character_id}",
            "entity_type": "CHARACTER",
            "content_id": content_id,
            "character_id": character_id,
            "name": char_data.get("name", ""),
            "name_en": char_data.get("name_en", ""),
            "group": char_data.get("group", ""),
            "role_type": role_type,
            "role_in_story": char_data.get("role_in_story", ""),
            "personality_traits": char_data.get("personality_traits", []),
            "personality_description": char_data.get("personality_description", ""),
            "abilities": char_data.get("abilities", []),
            "weapon": char_data.get("weapon", ""),
            "speaking_style": char_data.get("speaking_style", ""),
            "catchphrase": char_data.get("catchphrase", ""),
            "background": char_data.get("background", ""),
            "age": char_data.get("age", ""),
            "species": char_data.get("species", "인간"),
            "voice_actor": char_data.get("voice_actor", {}),
            "public_reception": char_data.get("public_reception", ""),
            "s3_image_folder": char_data.get("s3_image_folder", ""),
            "emoji": char_data.get("emoji", ""),
            "color_theme": char_data.get("color_theme", "#FFFFFF"),
            "is_playable": char_data.get("is_playable", True),
            "created_at": now,
            "updated_at": now,
        }
        self.table.put_item(Item=self._sanitize(item))

        # character_count 업데이트
        self._update_character_count(content_id)
        return character_id

    def get_character(self, content_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        resp = self.table.get_item(
            Key={"PK": f"CONTENT#{content_id}", "SK": f"CHAR#{character_id}"}
        )
        if "Item" in resp:
            return self._convert_decimals(resp["Item"])
        return None

    def list_characters(self, content_id: str, role_type: str = None) -> List[Dict[str, Any]]:
        pk = f"CONTENT#{content_id}"
        if role_type:
            resp = self.table.query(
                IndexName="GSI1",
                KeyConditionExpression="GSI1_PK = :pk AND begins_with(GSI1_SK, :prefix)",
                ExpressionAttributeValues={":pk": pk, ":prefix": f"ROLE#{role_type}#"},
            )
        else:
            resp = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={":pk": pk, ":prefix": "CHAR#"},
            )
        return [self._convert_decimals(i) for i in resp.get("Items", [])]

    def update_character(self, content_id: str, character_id: str, updates: Dict[str, Any]):
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        expr_parts, attr_names, attr_values = [], {}, {}
        for i, (key, value) in enumerate(updates.items()):
            expr_parts.append(f"#k{i} = :v{i}")
            attr_names[f"#k{i}"] = key
            attr_values[f":v{i}"] = self._sanitize(value)
        self.table.update_item(
            Key={"PK": f"CONTENT#{content_id}", "SK": f"CHAR#{character_id}"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

    def delete_character(self, content_id: str, character_id: str):
        self.table.delete_item(
            Key={"PK": f"CONTENT#{content_id}", "SK": f"CHAR#{character_id}"}
        )
        self._update_character_count(content_id)

    def _update_character_count(self, content_id: str):
        chars = self.list_characters(content_id)
        self.table.update_item(
            Key={"PK": f"CONTENT#{content_id}", "SK": "METADATA"},
            UpdateExpression="SET character_count = :cnt",
            ExpressionAttributeValues={":cnt": len(chars)},
        )

    # ─── 관계 CRUD ──────────────────────────────────────────────────

    def create_relationship(self, content_id: str, rel_data: Dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        source = rel_data.get("source_character", "")
        target = rel_data.get("target_character", "")
        rel_type = rel_data.get("relationship_type", "")
        relationship_id = f"{source}#{target}#{rel_type}"

        item = {
            "PK": f"CONTENT#{content_id}",
            "SK": f"REL#{relationship_id}",
            "GSI1_PK": f"CONTENT#{content_id}",
            "GSI1_SK": f"REL#{relationship_id}",
            "entity_type": "RELATIONSHIP",
            "content_id": content_id,
            "relationship_id": relationship_id,
            "source_character": source,
            "target_character": target,
            "relationship_type": rel_type,
            "description": rel_data.get("description", ""),
            "bidirectional": rel_data.get("bidirectional", True),
            "key_moments": rel_data.get("key_moments", []),
            "created_at": now,
        }
        self.table.put_item(Item=self._sanitize(item))
        return relationship_id

    def list_relationships(self, content_id: str) -> List[Dict[str, Any]]:
        resp = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": f"CONTENT#{content_id}", ":prefix": "REL#"},
        )
        return [self._convert_decimals(i) for i in resp.get("Items", [])]

    def delete_relationship(self, content_id: str, relationship_id: str):
        self.table.delete_item(
            Key={"PK": f"CONTENT#{content_id}", "SK": f"REL#{relationship_id}"}
        )

    # ─── S3 이미지 업로드 ───────────────────────────────────────────

    def upload_character_image(
        self, content_slug: str, char_slug: str, file_bytes: bytes, filename: str, content_type: str = "image/png"
    ) -> str:
        """캐릭터 이미지를 S3에 업로드하고 키 반환"""
        s3_key = f"{self.content_data_prefix}{content_slug}/characters/{char_slug}/images/{filename}"
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=file_bytes,
            ContentType=content_type,
        )
        return s3_key

    def get_character_default_image_url(self, char_folder: str) -> str:
        """S3 emotion-images/{char_folder}/default.* presigned URL 반환"""
        prefix = f"emotion-images/{char_folder}/default"
        try:
            resp = self.s3.list_objects_v2(
                Bucket=self.bucket_name, Prefix=prefix, MaxKeys=5
            )
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if key.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    return self.s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": self.bucket_name, "Key": key},
                        ExpiresIn=3600,
                    )
        except Exception as e:
            logger.error("디폴트 이미지 조회 오류 (%s): %s", char_folder, e)
        return ""

    # ─── 자연어 프로필 생성 ──────────────────────────────────────────

    def generate_kb_profile(self, content_id: str, character_id: str) -> Dict[str, Any]:
        """DDB 데이터로 자연어 프로필 JSON 생성 (KB 인덱싱용)"""
        char = self.get_character(content_id, character_id)
        content = self.get_content(content_id)
        if not char or not content:
            return {}

        # 관계 정보 조합
        rels = self.list_relationships(content_id)
        rel_texts = []
        for r in rels:
            if r["source_character"] == character_id or r["target_character"] == character_id:
                other = r["target_character"] if r["source_character"] == character_id else r["source_character"]
                rel_texts.append(f"{other}와(과) {r['relationship_type']} 관계: {r.get('description', '')}")

        name = char.get("name", character_id)
        name_en = char.get("name_en", "")
        group = char.get("group", "")
        role = char.get("role_in_story", "")
        personality_traits = ", ".join(char.get("personality_traits", []))
        personality_desc = char.get("personality_description", "")
        abilities = ", ".join(char.get("abilities", []))
        weapon = char.get("weapon", "")
        speaking_style = char.get("speaking_style", "")
        catchphrase = char.get("catchphrase", "")
        background = char.get("background", "")
        age = char.get("age", "")
        species = char.get("species", "")

        profile_text_parts = [f"{name}({name_en})"]
        if group:
            profile_text_parts[0] += f"은(는) {group}의 멤버이다."
        if char.get("role_type"):
            profile_text_parts.append(f"작품에서 {char['role_type']}으로 등장한다.")
        if role:
            profile_text_parts.append(role)
        if age:
            profile_text_parts.append(f"나이/연령대: {age}")
        if species and species != "인간":
            profile_text_parts.append(f"종족: {species}")
        if background:
            profile_text_parts.append(f"배경: {background}")

        personality_text_parts = []
        if personality_desc:
            personality_text_parts.append(personality_desc)
        if personality_traits:
            personality_text_parts.append(f"주요 성격 특성: {personality_traits}")
        if speaking_style:
            personality_text_parts.append(f"말투 특징: {speaking_style}")
        if catchphrase:
            personality_text_parts.append(f"캐치프레이즈: {catchphrase}")

        abilities_text_parts = []
        if abilities:
            abilities_text_parts.append(f"능력: {abilities}")
        if weapon:
            abilities_text_parts.append(f"무기: {weapon}")

        profile = {
            "content_title": content.get("title_en", content.get("title", "")),
            "content_title_kr": content.get("title", ""),
            "character_name": name_en or name,
            "character_name_kr": name,
            "profile_text": " ".join(profile_text_parts),
            "personality_text": " ".join(personality_text_parts),
            "abilities_text": " ".join(abilities_text_parts),
            "relationships_text": " ".join(rel_texts) if rel_texts else "",
            "story_role_text": role,
        }
        return profile

    # ─── S3 동기화 ──────────────────────────────────────────────────

    def sync_to_s3(self, content_id: str) -> Dict[str, int]:
        """DDB 데이터를 S3 content-data/에 자연어 JSON으로 동기화"""
        content = self.get_content(content_id)
        if not content:
            return {"error": "콘텐츠를 찾을 수 없습니다"}

        uploaded = 0
        prefix = f"{self.content_data_prefix}{content_id}/"

        # 1) metadata.json
        metadata_doc = {
            "document_type": "content_metadata",
            "content_id": content_id,
            "title": content.get("title", ""),
            "title_en": content.get("title_en", ""),
            "genre": content.get("genre", []),
            "platform": content.get("platform", ""),
            "release_date": content.get("release_date", ""),
            "format": content.get("format", ""),
            "runtime": content.get("runtime", ""),
            "creator": content.get("creator", ""),
            "director": content.get("director", []),
            "writer": content.get("writer", []),
            "production": content.get("production", ""),
            "synopsis": content.get("synopsis", ""),
            "reception": content.get("reception", {}),
            "text": (
                f"{content.get('title', '')} ({content.get('title_en', '')})은(는) "
                f"{content.get('production', '')}에서 제작한 {', '.join(content.get('genre', []))} 작품이다. "
                f"{content.get('platform', '')}에서 {content.get('release_date', '')}에 공개되었다. "
                f"{content.get('synopsis', '')}"
            ),
        }
        self._upload_json(f"{prefix}metadata.json", metadata_doc)
        uploaded += 1

        # 2) world-setting.json
        if content.get("world_setting"):
            world_doc = {
                "document_type": "world_setting",
                "content_id": content_id,
                "title": content.get("title", ""),
                "text": content["world_setting"],
            }
            self._upload_json(f"{prefix}world-setting.json", world_doc)
            uploaded += 1

        # 3) 캐릭터 프로필
        characters = self.list_characters(content_id)
        for char in characters:
            char_id = char["character_id"]
            profile = self.generate_kb_profile(content_id, char_id)
            if profile:
                self._upload_json(f"{prefix}characters/{char_id}/profile.json", profile)
                uploaded += 1

        # 4) relationships.json
        rels = self.list_relationships(content_id)
        if rels:
            rel_texts = []
            for r in rels:
                text = (
                    f"{r['source_character']}와(과) {r['target_character']}의 관계: "
                    f"{r['relationship_type']}. {r.get('description', '')}"
                )
                if r.get("key_moments"):
                    text += f" 주요 장면: {', '.join(r['key_moments'])}"
                rel_texts.append(text)

            rel_doc = {
                "document_type": "relationships",
                "content_id": content_id,
                "title": content.get("title", ""),
                "relationships": [self._convert_decimals(r) for r in rels],
                "text": " ".join(rel_texts),
            }
            self._upload_json(f"{prefix}relationships.json", rel_doc)
            uploaded += 1

        return {"uploaded": uploaded, "characters": len(characters), "relationships": len(rels)}

    def _upload_json(self, s3_key: str, data: dict):
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=json.dumps(data, ensure_ascii=False, indent=2),
            ContentType="application/json",
        )

    # ─── KB 동기화 ──────────────────────────────────────────────────

    def trigger_kb_sync(self) -> Optional[str]:
        """KB 인제스천 시작"""
        if not self.content_ds_id:
            logger.warning("content_data_source_id가 설정되지 않음")
            return None
        try:
            resp = self.bedrock_agent.start_ingestion_job(
                knowledgeBaseId=self.kb_id,
                dataSourceId=self.content_ds_id,
            )
            return resp["ingestionJob"]["ingestionJobId"]
        except Exception as e:
            logger.error("KB 인제스천 시작 오류: %s", e)
            return None

    def check_kb_sync_status(self, job_id: str) -> Dict[str, Any]:
        """KB 인제스천 상태 조회"""
        try:
            resp = self.bedrock_agent.get_ingestion_job(
                knowledgeBaseId=self.kb_id,
                dataSourceId=self.content_ds_id,
                ingestionJobId=job_id,
            )
            job = resp["ingestionJob"]
            return {
                "status": job["status"],
                "started_at": str(job.get("startedAt", "")),
                "updated_at": str(job.get("updatedAt", "")),
                "statistics": job.get("statistics", {}),
            }
        except Exception as e:
            logger.error("KB 상태 조회 오류: %s", e)
            return {"status": "ERROR", "message": str(e)}

    def list_kb_sync_jobs(self, max_results: int = 10) -> List[Dict]:
        """최근 KB 인제스천 작업 목록"""
        if not self.content_ds_id:
            return []
        try:
            resp = self.bedrock_agent.list_ingestion_jobs(
                knowledgeBaseId=self.kb_id,
                dataSourceId=self.content_ds_id,
                maxResults=max_results,
                sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
            )
            return [
                {
                    "job_id": j["ingestionJobId"],
                    "status": j["status"],
                    "started_at": str(j.get("startedAt", "")),
                    "statistics": j.get("statistics", {}),
                }
                for j in resp.get("ingestionJobSummaries", [])
            ]
        except Exception as e:
            logger.error("KB 작업 목록 조회 오류: %s", e)
            return []

    # ─── S3 상태 비교 ───────────────────────────────────────────────

    def get_sync_comparison(self, content_id: str) -> Dict[str, Any]:
        """DDB vs S3 동기화 상태 비교"""
        ddb_chars = self.list_characters(content_id)
        ddb_char_ids = {c["character_id"] for c in ddb_chars}

        # S3 프로필 목록
        prefix = f"{self.content_data_prefix}{content_id}/characters/"
        s3_char_ids = set()
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/profile.json"):
                        parts = key.replace(prefix, "").split("/")
                        if parts:
                            s3_char_ids.add(parts[0])
        except Exception:
            pass

        return {
            "ddb_characters": sorted(ddb_char_ids),
            "s3_characters": sorted(s3_char_ids),
            "missing_in_s3": sorted(ddb_char_ids - s3_char_ids),
            "extra_in_s3": sorted(s3_char_ids - ddb_char_ids),
            "synced": ddb_char_ids == s3_char_ids,
        }

    # ─── 유틸리티 ───────────────────────────────────────────────────

    @staticmethod
    def _slugify(text: str) -> str:
        """텍스트를 slug 형식으로 변환"""
        import re
        text = text.strip().lower()
        text = re.sub(r'[^a-z0-9가-힣\s-]', '', text)
        text = re.sub(r'[\s]+', '-', text)
        text = re.sub(r'-+', '-', text)
        return text.strip('-') or f"item-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _convert_decimals(obj):
        if isinstance(obj, dict):
            return {k: AdminDataManager._convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [AdminDataManager._convert_decimals(i) for i in obj]
        elif isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return obj

    @staticmethod
    def _sanitize(obj):
        if isinstance(obj, dict):
            return {k: AdminDataManager._sanitize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [AdminDataManager._sanitize(i) for i in obj]
        elif isinstance(obj, float):
            return Decimal(str(obj))
        return obj
