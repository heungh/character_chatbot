#!/usr/bin/env python3
"""
케이팝 데몬헌터스 챗봇 - 메모리 매니저
DynamoDB + S3 + Bedrock LLM 기반 장기 메모리 시스템
"""

import boto3
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("character_chatbot.memory")

REGION = "us-east-1"

# Config 로드 (chatbot_config.json)
def _load_chatbot_config():
    try:
        with open(Path(__file__).parent / "chatbot_config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_chatbot_cfg = _load_chatbot_config()
BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", _chatbot_cfg.get("bucket_name", ""))
if not BUCKET_NAME:
    try:
        with open(Path(__file__).parent / "admin_config.json", "r", encoding="utf-8") as f:
            BUCKET_NAME = json.load(f).get("bucket_name", "")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

# DynamoDB 테이블명
_ddb_tables = _chatbot_cfg.get("dynamodb_tables", {})
TABLE_USERS = _ddb_tables.get("users", "CharacterChatbot-Users")
TABLE_CONVERSATIONS = _ddb_tables.get("conversations", "CharacterChatbot-Conversations")
TABLE_MEMORIES = _ddb_tables.get("memories", "CharacterChatbot-Memories")

# 온보딩 단계 정의
ONBOARDING_STEPS = {
    0: {
        "field": "nickname",
        "instruction": "사용자에게 자기소개를 하면서 사용자의 이름이나 닉네임을 자연스럽게 물어보세요.",
    },
    1: {
        "field": "birthday",
        "instruction": "대화 흐름에 맞춰 사용자의 생년월일을 자연스럽게 물어보세요.",
    },
    2: {
        "field": "interests",
        "instruction": "사용자가 좋아하는 것이나 취미를 자연스럽게 물어보세요.",
    },
    3: {
        "field": "kpop_preferences",
        "instruction": "좋아하는 케이팝 그룹, 멤버, 장르 등 케이팝 취향을 물어보세요.",
    },
    4: {
        "field": "preferred_topics",
        "instruction": "앞으로 어떤 이야기를 하고 싶은지 자연스럽게 물어보세요. 이것이 마지막 질문입니다.",
    },
}

# 프로필 보완 필드 정의 (온보딩 완료 후에도 빈 필드 수집)
PROFILE_COMPLETION_FIELDS = {
    "gender": {
        "instruction": "대화 흐름에 맞춰 사용자의 성별을 자연스럽게 파악하세요. 직접 묻기보다는 '오빠라고 불러도 될까요?' 같은 자연스러운 방식으로 확인하세요.",
        "extraction_key": "gender",
        "valid_values": ["male", "female"],
    },
}

PROFILE_COMPLETION_EXTRACTION_PROMPT = """다음 대화에서 사용자의 성별 정보를 추출해주세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

대화:
{conversation}

추출 형식:
- gender: "male" 또는 "female" 또는 null (판단 불가 시)
- confidence: "high" 또는 "low"

판단 기준:
- 사용자가 직접 성별을 밝힌 경우 → high
- "오빠/형이라고 불러줘" → male, high
- "언니/누나라고 불러줘" → female, high
- 맥락상 명확히 추론 가능한 경우 → high
- 불확실한 경우 → null, low

JSON 출력:"""

# LLM에서 추출할 때 사용하는 프롬프트
EXTRACTION_PROMPT = """다음 캐릭터({character})와 사용자 간의 대화를 분석하여 아래 정보를 JSON으로 추출해주세요.
중요: 반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

대화 내용:
{conversation}

추출할 정보:
1. summary: 대화 내용을 2-3문장으로 요약
2. keywords: 대화의 핵심 키워드 (최대 5개)
3. user_sentiment: 사용자의 전반적 감정 ("positive", "neutral", "negative" 중 하나)
4. new_user_info: 대화에서 발견된 사용자 개인 정보 (이름, 생일, 취미, 좋아하는 그룹 등). 없으면 빈 객체
5. memories: 장기적으로 기억해야 할 중요한 정보 리스트. 각 항목:
   - character: "global" (모든 캐릭터 공유) 또는 캐릭터명 (해당 캐릭터만 관련)
   - category: "fact" | "preference" | "emphasis" | "relationship" | "event" 중 하나
   - content: 기억할 내용 (한 문장)
   - importance: 1-5 (5가 가장 중요, 사용자가 명시적으로 강조한 내용은 5)

예시 출력:
{{
  "summary": "사용자가 다음 주 콘서트에 대해 설명하며 기대감을 표현했다.",
  "keywords": ["콘서트", "ATEEZ", "다음주"],
  "user_sentiment": "positive",
  "new_user_info": {{"favorite_group": "ATEEZ"}},
  "memories": [
    {{"character": "global", "category": "event", "content": "사용자는 다음 주 ATEEZ 콘서트에 갈 예정이다", "importance": 4}},
    {{"character": "{character}", "category": "preference", "content": "사용자는 ATEEZ의 홍중을 최애로 꼽았다", "importance": 3}}
  ]
}}

JSON 출력:"""

# 온보딩 응답 분석 프롬프트
ONBOARDING_EXTRACTION_PROMPT = """다음 대화에서 사용자가 제공한 개인 정보를 추출해주세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

현재 수집 중인 정보: {field}
대화의 마지막 사용자 메시지를 중심으로 분석하세요.

대화:
{conversation}

추출 형식:
- nickname: 사용자의 이름이나 닉네임 (문자열 또는 null)
- birthday: 생년월일 "YYYY-MM-DD" 형식 (문자열 또는 null)
- interests: 관심사/취미 리스트 (배열 또는 null)
- kpop_preferences: 케이팝 취향 (객체: favorite_groups, favorite_members, bias 등, 또는 null)
- preferred_topics: 대화하고 싶은 주제 리스트 (배열 또는 null)
- step_complete: 현재 단계의 정보가 충분히 수집되었는지 (true/false)

JSON 출력:"""


class ChatbotMemoryManager:
    """DynamoDB + S3 + Bedrock LLM 기반 메모리 매니저"""

    def __init__(self, region: str = REGION):
        self.ddb = boto3.resource("dynamodb", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)

        self.table_users = self.ddb.Table(TABLE_USERS)
        self.table_conversations = self.ddb.Table(TABLE_CONVERSATIONS)
        self.table_memories = self.ddb.Table(TABLE_MEMORIES)

    # ─── 사용자 프로필 ──────────────────────────────────────────────

    def get_or_create_user(self, user_id: str, email: str, display_name: str) -> Dict[str, Any]:
        """로그인 시 사용자 프로필 조회/생성"""
        now = datetime.now(timezone.utc).isoformat()

        resp = self.table_users.get_item(Key={"user_id": user_id})
        if "Item" in resp:
            # 기존 사용자 - last_login 업데이트
            self.table_users.update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET last_login_at = :now, total_sessions = if_not_exists(total_sessions, :zero) + :one",
                ExpressionAttributeValues={":now": now, ":zero": 0, ":one": 1},
            )
            user = resp["Item"]
            # Decimal → int 변환
            user = self._convert_decimals(user)
            return user

        # 새 사용자 생성
        user = {
            "user_id": user_id,
            "email": email,
            "display_name": display_name,
            "nickname": "",
            "birthday": "",
            "interests": [],
            "kpop_preferences": {},
            "preferred_topics": [],
            "onboarding_complete": False,
            "onboarding_step": 0,
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
            "total_sessions": 1,
        }
        self.table_users.put_item(Item=user)
        return user

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """사용자 프로필 조회"""
        resp = self.table_users.get_item(Key={"user_id": user_id})
        if "Item" in resp:
            return self._convert_decimals(resp["Item"])
        return None

    def update_user_profile(self, user_id: str, updates: Dict[str, Any]):
        """사용자 프로필 부분 업데이트"""
        if not updates:
            return

        now = datetime.now(timezone.utc).isoformat()
        updates["updated_at"] = now

        expr_parts = []
        attr_names = {}
        attr_values = {}
        for i, (key, value) in enumerate(updates.items()):
            placeholder = f"#k{i}"
            val_placeholder = f":v{i}"
            expr_parts.append(f"{placeholder} = {val_placeholder}")
            attr_names[placeholder] = key
            attr_values[val_placeholder] = value

        self.table_users.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

    # ─── 대화 저장 파이프라인 ──────────────────────────────────────

    def save_conversation(
        self, user_id: str, character: str, messages: List[Dict], session_start: str
    ):
        """대화 종료 시 전체 저장 파이프라인 (비동기 불가 → 동기 처리)"""
        if not messages or len(messages) < 2:
            logger.debug("저장할 메시지가 부족합니다 (최소 2개 필요)")
            return

        now = datetime.now(timezone.utc).isoformat()
        conversation_id = f"{character}#{session_start}"

        # 1) LLM으로 요약/키워드/메모리 추출 (단일 호출)
        extraction = self._extract_all_from_conversation(character, messages)

        # 2) S3에 원문 로그 저장
        s3_log_path = f"chat-logs/{user_id}/{conversation_id}.json"
        log_data = {
            "user_id": user_id,
            "character": character,
            "session_start": session_start,
            "session_end": now,
            "message_count": len(messages),
            "messages": [
                {
                    "role": m.get("role", "user"),
                    "content": m.get("content", ""),
                    "timestamp": m.get("timestamp", ""),
                    **({"selected_emotion": m["selected_emotion"]} if "selected_emotion" in m else {}),
                }
                for m in messages
            ],
        }

        try:
            self.s3.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_log_path,
                Body=json.dumps(log_data, ensure_ascii=False, indent=2),
                ContentType="application/json",
            )
        except Exception as e:
            logger.error("S3 로그 저장 오류: %s", e)

        # 3) DDB Conversations 테이블 저장
        conv_item = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "character": character,
            "session_start": session_start,
            "session_end": now,
            "message_count": len(messages),
            "summary": extraction.get("summary", ""),
            "keywords": extraction.get("keywords", []),
            "user_sentiment": extraction.get("user_sentiment", "neutral"),
            "topics_discussed": extraction.get("keywords", []),
            "s3_log_path": s3_log_path,
            "new_user_info": extraction.get("new_user_info", {}),
        }
        try:
            self.table_conversations.put_item(Item=self._sanitize_for_ddb(conv_item))
        except Exception as e:
            logger.error("DDB 대화 저장 오류: %s", e)

        # 4) DDB Memories 테이블에 추출 메모리 저장
        for mem in extraction.get("memories", []):
            memory_char = mem.get("character", "global")
            memory_id = f"{memory_char}#{uuid.uuid4().hex[:12]}"
            mem_item = {
                "user_id": user_id,
                "memory_id": memory_id,
                "character": memory_char,
                "category": mem.get("category", "fact"),
                "content": mem.get("content", ""),
                "importance": mem.get("importance", 3),
                "source_conversation": conversation_id,
                "created_at": now,
                "last_referenced": now,
                "reference_count": 0,
                "active": True,
            }
            try:
                self.table_memories.put_item(Item=self._sanitize_for_ddb(mem_item))
            except Exception as e:
                logger.error("DDB 메모리 저장 오류: %s", e)

        # 5) 새 사용자 정보 발견 시 프로필 업데이트
        new_info = extraction.get("new_user_info", {})
        if new_info:
            profile_updates = {}
            if new_info.get("favorite_group"):
                profile_updates["kpop_preferences"] = new_info
            if new_info.get("birthday"):
                profile_updates["birthday"] = new_info["birthday"]
            if new_info.get("nickname"):
                profile_updates["nickname"] = new_info["nickname"]
            if profile_updates:
                self.update_user_profile(user_id, profile_updates)

        logger.info("대화 저장 완료: user=%s, char=%s, msgs=%d", user_id, character, len(messages))

    def save_messages_incremental(
        self, user_id: str, character: str, messages: List[Dict], session_start: str
    ):
        """매 응답 후 S3에 원문 메시지만 저장 (LLM 추출 없이 lightweight)"""
        if not messages:
            return

        conversation_id = f"{character}#{session_start}"
        s3_log_path = f"chat-logs/{user_id}/{conversation_id}.json"
        log_data = {
            "user_id": user_id,
            "character": character,
            "session_start": session_start,
            "message_count": len(messages),
            "messages": [
                {
                    "role": m.get("role", "user"),
                    "content": m.get("content", ""),
                    "timestamp": m.get("timestamp", ""),
                    **({"selected_emotion": m["selected_emotion"]} if "selected_emotion" in m else {}),
                }
                for m in messages
            ],
        }

        try:
            self.s3.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_log_path,
                Body=json.dumps(log_data, ensure_ascii=False, indent=2),
                ContentType="application/json",
            )
        except Exception as e:
            logger.error("S3 incremental 저장 오류: %s", e)

    def _extract_all_from_conversation(
        self, character: str, messages: List[Dict]
    ) -> Dict[str, Any]:
        """LLM 단일 호출로 요약+키워드+메모리 추출"""
        # 대화 텍스트 구성
        conv_lines = []
        for m in messages:
            role_label = "사용자" if m.get("role") == "user" else character
            conv_lines.append(f"{role_label}: {m.get('content', '')}")
        conversation_text = "\n".join(conv_lines)

        prompt = EXTRACTION_PROMPT.format(
            character=character, conversation=conversation_text
        )

        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "temperature": 0.3,
            })

            # Haiku 사용 (비용 최적화)
            response = self.bedrock.invoke_model(
                modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                body=body,
            )
            result = json.loads(response["body"].read())
            text = result["content"][0]["text"].strip()

            # JSON 파싱 (코드블록 래핑 제거)
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            return json.loads(text)
        except Exception as e:
            logger.error("LLM 추출 오류: %s", e)
            return {
                "summary": "",
                "keywords": [],
                "user_sentiment": "neutral",
                "new_user_info": {},
                "memories": [],
            }

    # ─── 메모리 컨텍스트 구축 ──────────────────────────────────────

    def build_memory_context(self, user_id: str, character: str) -> str:
        """LLM 호출 전 메모리 컨텍스트 문자열 구축"""
        parts = []

        # 1) 사용자 프로필 요약
        profile = self.get_user_profile(user_id)
        if profile:
            profile_lines = []
            if profile.get("nickname"):
                profile_lines.append(f"이름/닉네임: {profile['nickname']}")
            if profile.get("gender"):
                gender_label = "남성" if profile["gender"] == "male" else "여성"
                profile_lines.append(f"성별: {gender_label}")
            if profile.get("birthday"):
                profile_lines.append(f"생년월일: {profile['birthday']}")
            if profile.get("interests"):
                profile_lines.append(f"관심사: {', '.join(profile['interests'])}")
            kpop = profile.get("kpop_preferences", {})
            if kpop:
                if isinstance(kpop, dict):
                    for k, v in kpop.items():
                        if v:
                            profile_lines.append(f"케이팝 {k}: {v if isinstance(v, str) else ', '.join(v)}")
            if profile.get("preferred_topics"):
                profile_lines.append(f"선호 주제: {', '.join(profile['preferred_topics'])}")

            if profile_lines:
                parts.append("[사용자 프로필]\n" + "\n".join(profile_lines))

        # 2) 캐릭터별 + 글로벌 메모리 (중요도순, 최대 15개)
        memories = self._get_top_memories(user_id, character, limit=15)
        if memories:
            critical = [m for m in memories if int(m.get("importance", 0)) >= 5]
            normal = [m for m in memories if int(m.get("importance", 0)) < 5]
            mem_lines = []
            if critical:
                mem_lines.append("★★★ 최우선 행동 지시 (반드시 따를 것) ★★★")
                for m in critical:
                    mem_lines.append(f"  → {m['content']}")
                mem_lines.append("")
            if normal:
                mem_lines.append("[참고 기억]")
                for m in normal:
                    mem_lines.append(f"- [{m['category']}] {m['content']}")
            parts.append("[기억하고 있는 정보]\n" + "\n".join(mem_lines))

        # 3) 최근 대화 요약 (최대 5개)
        summaries = self._get_recent_summaries(user_id, character, limit=5)
        if summaries:
            sum_lines = [f"- ({s['session_start'][:10]}) {s['summary']}" for s in summaries if s.get("summary")]
            if sum_lines:
                parts.append("[이전 대화 요약]\n" + "\n".join(sum_lines))

        if not parts:
            return ""

        context = "\n\n".join(parts)
        # 토큰 크기 제한 (대략 2000 토큰 ≈ 4000자)
        if len(context) > 4000:
            context = context[:4000] + "\n... (일부 생략)"

        return context

    def _get_top_memories(
        self, user_id: str, character: str, limit: int = 15
    ) -> List[Dict]:
        """캐릭터별 + 글로벌 메모리 조회 (중요도순)"""
        try:
            # GSI로 글로벌 메모리 조회
            global_resp = self.table_memories.query(
                IndexName="CharacterMemoryIndex",
                KeyConditionExpression="user_id = :uid AND #char = :char",
                FilterExpression="active = :active",
                ExpressionAttributeNames={"#char": "character"},
                ExpressionAttributeValues={
                    ":uid": user_id,
                    ":char": "global",
                    ":active": True,
                },
            )
            global_mems = global_resp.get("Items", [])

            # 캐릭터 전용 메모리 조회
            char_resp = self.table_memories.query(
                IndexName="CharacterMemoryIndex",
                KeyConditionExpression="user_id = :uid AND #char = :char",
                FilterExpression="active = :active",
                ExpressionAttributeNames={"#char": "character"},
                ExpressionAttributeValues={
                    ":uid": user_id,
                    ":char": character,
                    ":active": True,
                },
            )
            char_mems = char_resp.get("Items", [])

            all_mems = global_mems + char_mems
            # 중요도순 정렬
            all_mems.sort(key=lambda x: int(x.get("importance", 0)), reverse=True)

            # reference_count 증가 (상위 항목만)
            for m in all_mems[:limit]:
                try:
                    self.table_memories.update_item(
                        Key={"user_id": user_id, "memory_id": m["memory_id"]},
                        UpdateExpression="SET reference_count = if_not_exists(reference_count, :zero) + :one, last_referenced = :now",
                        ExpressionAttributeValues={
                            ":zero": 0,
                            ":one": 1,
                            ":now": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception:
                    pass

            return [self._convert_decimals(m) for m in all_mems[:limit]]
        except Exception as e:
            logger.error("메모리 조회 오류: %s", e)
            return []

    def _get_recent_summaries(
        self, user_id: str, character: str, limit: int = 5
    ) -> List[Dict]:
        """최근 대화 요약 조회 (시간역순)"""
        try:
            resp = self.table_conversations.query(
                IndexName="CharacterTimeIndex",
                KeyConditionExpression="user_id = :uid",
                FilterExpression="#char = :char",
                ExpressionAttributeNames={"#char": "character"},
                ExpressionAttributeValues={
                    ":uid": user_id,
                    ":char": character,
                },
                ScanIndexForward=False,
                Limit=limit,
            )
            return [self._convert_decimals(item) for item in resp.get("Items", [])]
        except Exception as e:
            logger.error("대화 요약 조회 오류: %s", e)
            return []

    # ─── 온보딩 ───────────────────────────────────────────────────

    def get_onboarding_prompt_addition(self, user_id: str, character: str) -> str:
        """온보딩 미완료 시 시스템 프롬프트에 추가할 지시문"""
        profile = self.get_user_profile(user_id)
        if not profile:
            return ""
        if profile.get("onboarding_complete"):
            return ""

        step = int(profile.get("onboarding_step", 0))
        if step not in ONBOARDING_STEPS:
            return ""

        step_info = ONBOARDING_STEPS[step]
        return (
            f"\n\n[온보딩 지시]\n"
            f"이 사용자는 아직 프로필 수집이 완료되지 않았습니다. (현재 단계: {step}/4)\n"
            f"대화 중 자연스럽게 다음 정보를 수집해주세요: {step_info['instruction']}\n"
            f"너무 직접적으로 묻지 말고, 대화 흐름에 녹여서 물어보세요."
        )

    def process_onboarding_response(
        self, user_id: str, messages: List[Dict], current_step: int
    ) -> int:
        """온보딩 응답 처리 - LLM으로 정보 추출 후 프로필 업데이트. 새 단계 반환."""
        if current_step not in ONBOARDING_STEPS:
            return current_step

        step_info = ONBOARDING_STEPS[current_step]

        # 최근 대화 (마지막 4개 메시지)
        recent = messages[-4:] if len(messages) >= 4 else messages
        conv_lines = []
        for m in recent:
            role_label = "사용자" if m.get("role") == "user" else "캐릭터"
            conv_lines.append(f"{role_label}: {m.get('content', '')}")
        conversation_text = "\n".join(conv_lines)

        prompt = ONBOARDING_EXTRACTION_PROMPT.format(
            field=step_info["field"], conversation=conversation_text
        )

        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "temperature": 0.2,
            })
            response = self.bedrock.invoke_model(
                modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                body=body,
            )
            result = json.loads(response["body"].read())
            text = result["content"][0]["text"].strip()

            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            extracted = json.loads(text)
        except Exception as e:
            logger.error("온보딩 추출 오류: %s", e)
            return current_step

        step_complete = extracted.get("step_complete", False)
        if not step_complete:
            return current_step

        # 추출된 정보로 프로필 업데이트
        updates = {}
        field = step_info["field"]

        if field == "nickname" and extracted.get("nickname"):
            updates["nickname"] = extracted["nickname"]
        elif field == "birthday" and extracted.get("birthday"):
            updates["birthday"] = extracted["birthday"]
        elif field == "interests" and extracted.get("interests"):
            updates["interests"] = extracted["interests"]
        elif field == "kpop_preferences" and extracted.get("kpop_preferences"):
            updates["kpop_preferences"] = extracted["kpop_preferences"]
        elif field == "preferred_topics" and extracted.get("preferred_topics"):
            updates["preferred_topics"] = extracted["preferred_topics"]

        new_step = current_step + 1
        updates["onboarding_step"] = new_step

        if new_step > 4:
            updates["onboarding_complete"] = True

        self.update_user_profile(user_id, updates)
        logger.info("온보딩 단계 완료: user=%s, step=%d→%d", user_id, current_step, new_step)

        return new_step

    # ─── 프로필 보완 (온보딩 완료 후 빈 필드 수집) ─────────────────

    def get_profile_completion_prompt(self, user_id: str) -> str:
        """프로필에 빈 필수 필드가 있으면 수집 지시문 반환"""
        profile = self.get_user_profile(user_id)
        if not profile:
            return ""

        missing = []
        for field, config in PROFILE_COMPLETION_FIELDS.items():
            if not profile.get(field):
                missing.append(config["instruction"])

        if not missing:
            return ""

        return (
            "\n\n[프로필 보완 지시]\n"
            "아직 파악하지 못한 사용자 정보가 있습니다. 대화 중 자연스럽게 확인해주세요:\n"
            + "\n".join(f"- {m}" for m in missing)
        )

    def process_profile_completion(self, user_id: str, messages: List[Dict]) -> None:
        """대화에서 빈 프로필 필드 추출 시도"""
        profile = self.get_user_profile(user_id)
        if not profile:
            return

        missing_fields = [f for f in PROFILE_COMPLETION_FIELDS if not profile.get(f)]
        if not missing_fields:
            return

        # 최근 4개 메시지로 LLM 추출
        recent = messages[-4:] if len(messages) >= 4 else messages
        conv_lines = []
        for m in recent:
            role_label = "사용자" if m.get("role") == "user" else "캐릭터"
            conv_lines.append(f"{role_label}: {m.get('content', '')}")
        conversation_text = "\n".join(conv_lines)

        prompt = PROFILE_COMPLETION_EXTRACTION_PROMPT.format(
            conversation=conversation_text
        )

        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "temperature": 0.1,
            })
            response = self.bedrock.invoke_model(
                modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                body=body,
            )
            result = json.loads(response["body"].read())
            text = result["content"][0]["text"].strip()

            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            extracted = json.loads(text)
        except Exception as e:
            logger.error("프로필 보완 추출 오류: %s", e)
            return

        # confidence가 high일 때만 프로필 업데이트
        if extracted.get("confidence") != "high":
            return

        updates = {}
        gender = extracted.get("gender")
        if gender in ("male", "female") and "gender" in missing_fields:
            updates["gender"] = gender

        if updates:
            self.update_user_profile(user_id, updates)
            logger.info("프로필 보완 완료: user=%s, updates=%s", user_id, updates)

    # ─── 유틸리티 ─────────────────────────────────────────────────

    @staticmethod
    def _convert_decimals(obj):
        """DynamoDB Decimal → Python int/float 변환"""
        if isinstance(obj, dict):
            return {k: ChatbotMemoryManager._convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ChatbotMemoryManager._convert_decimals(i) for i in obj]
        elif isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return obj

    @staticmethod
    def _sanitize_for_ddb(obj):
        """DDB 저장 전 float→Decimal, 빈 문자열 처리"""
        if isinstance(obj, dict):
            cleaned = {}
            for k, v in obj.items():
                sanitized = ChatbotMemoryManager._sanitize_for_ddb(v)
                # DDB는 빈 문자열을 키가 아닌 속성에서 허용 (2020+)
                cleaned[k] = sanitized
            return cleaned
        elif isinstance(obj, list):
            return [ChatbotMemoryManager._sanitize_for_ddb(i) for i in obj]
        elif isinstance(obj, float):
            return Decimal(str(obj))
        return obj
