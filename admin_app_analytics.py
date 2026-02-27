#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 고객 분석
CustomerAnalyticsManager: DDB/S3 사용자 데이터 수집 + Bedrock Claude 분석
"""

import boto3
import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional

import streamlit as st

logger = logging.getLogger("admin_app.analytics")

# Config 로드
def _load_configs():
    tables, bucket = {}, ""
    for cfg_file in ["chatbot_config.json", "admin_config.json"]:
        try:
            with open(Path(__file__).parent / cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if not tables and "dynamodb_tables" in cfg:
                    t = cfg["dynamodb_tables"]
                    if "chatbot" in t:
                        tables = t
                if not bucket:
                    bucket = cfg.get("bucket_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    return tables, bucket

_tables, _bucket = _load_configs()

# DynamoDB 단일 테이블 (chatbot 측과 동일)
TABLE_CHATBOT = _tables.get("chatbot", "character_chatbot")

BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", _bucket)

# LLM 모델
MODEL_PRIMARY = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
MODEL_FALLBACK = "us.anthropic.claude-sonnet-4-20250514-v1:0"

# 모델 ID → 표시명 매핑
MODEL_DISPLAY_NAMES = {
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude Sonnet 4.5",
    "us.anthropic.claude-sonnet-4-20250514-v1:0": "Claude Sonnet 4",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5",
}


def _model_display_name(model_id: str) -> str:
    """모델 ID에서 사용자 표시용 이름 추출"""
    if model_id in MODEL_DISPLAY_NAMES:
        return MODEL_DISPLAY_NAMES[model_id]
    # 알 수 없는 모델: ID에서 추출 시도
    parts = model_id.replace("us.anthropic.", "").split("-v")[0].split("-")
    return "Claude " + " ".join(p.capitalize() for p in parts if not p.isdigit())

# ─── 분석 프롬프트 ───────────────────────────────────────────────

PREFERENCE_ANALYSIS_PROMPT = """당신은 고객 분석 전문가입니다. 아래 사용자 데이터를 종합적으로 분석하여 JSON으로 결과를 반환해주세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

=== 사용자 데이터 ===
{user_data}

=== 분석 요청 ===
다음 항목을 분석해주세요:

1. overall_profile: 사용자의 종합 프로필 요약 (2-3문장)
2. character_preferences: 캐릭터 선호도 분석 (각 캐릭터별 선호도와 이유)
3. interest_topics: 관심 주제 Top 5 (주제명, 근거)
4. emotion_patterns: 대화에서 나타나는 감정 패턴 (긍정/중립/부정 비율 및 특징)
5. engagement_level: 참여도 평가 ("high"/"medium"/"low", 근거 포함)
6. personality_insights: 사용자 성격 특성 추정 (2-3가지)

JSON 출력:"""

CONTENT_RECOMMENDATION_PROMPT = """당신은 콘텐츠 추천 전문가입니다. 사용자 데이터와 콘텐츠 목록을 분석하여 개인화된 추천을 JSON으로 반환해주세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

=== 사용자 데이터 ===
{user_data}

=== 콘텐츠 목록 ===
{content_list}

=== 추천 요청 ===
위 콘텐츠 중 이 사용자가 좋아할 만한 콘텐츠를 추천해주세요.
각 추천 항목에 대해 다음을 포함하세요:

recommendations 배열 (최대 5개):
- content_id: 콘텐츠 ID
- title: 콘텐츠 제목
- match_score: 매칭 점수 (0-100)
- reasons: 추천 이유 3가지 (배열)

JSON 출력:"""


class CustomerAnalyticsManager:
    """DDB/S3 사용자 데이터 수집 + Bedrock Claude 분석"""

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.ddb = boto3.resource("dynamodb", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)

        self.table = self.ddb.Table(TABLE_CHATBOT)

    # ─── 사용자 목록 ─────────────────────────────────────────────

    def list_users(self) -> List[Dict[str, Any]]:
        """GSI1 query(GSI1_PK=USERS) → 전체 사용자 목록"""
        try:
            resp = self.table.query(
                IndexName="GSI1",
                KeyConditionExpression="GSI1_PK = :pk",
                ExpressionAttributeValues={":pk": "USERS"},
            )
            items = resp.get("Items", [])
            # 페이지네이션 처리
            while "LastEvaluatedKey" in resp:
                resp = self.table.query(
                    IndexName="GSI1",
                    KeyConditionExpression="GSI1_PK = :pk",
                    ExpressionAttributeValues={":pk": "USERS"},
                    ExclusiveStartKey=resp["LastEvaluatedKey"],
                )
                items.extend(resp.get("Items", []))
            return [self._convert_decimals(i) for i in items]
        except Exception as e:
            logger.error("사용자 목록 조회 오류: %s", e)
            return []

    # ─── 사용자 종합 데이터 ───────────────────────────────────────

    def get_user_full_data(self, user_id: str) -> Dict[str, Any]:
        """프로필 + 대화이력 + 메모리 + 최근 S3 로그 종합"""
        data = {"user_id": user_id}
        pk = f"USER#{user_id}"

        # 1) 프로필
        try:
            resp = self.table.get_item(Key={"PK": pk, "SK": "PROFILE"})
            if "Item" in resp:
                data["profile"] = self._convert_decimals(resp["Item"])
        except Exception as e:
            logger.error("프로필 조회 오류: %s", e)
            data["profile"] = {}

        # 2) 대화이력 (main table query, SK begins_with CONV#)
        try:
            resp = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={":pk": pk, ":prefix": "CONV#"},
                ScanIndexForward=False,
            )
            convs = [self._convert_decimals(i) for i in resp.get("Items", [])]
            data["conversations"] = convs
            data["conversation_count"] = len(convs)

            # 캐릭터별 대화 수
            char_counts = {}
            sentiments = {"positive": 0, "neutral": 0, "negative": 0}
            all_keywords = []
            for c in convs:
                char = c.get("character", "unknown")
                char_counts[char] = char_counts.get(char, 0) + 1
                sentiment = c.get("user_sentiment", "neutral")
                sentiments[sentiment] = sentiments.get(sentiment, 0) + 1
                all_keywords.extend(c.get("keywords", []))
            data["character_chat_counts"] = char_counts
            data["sentiment_distribution"] = sentiments
            data["top_keywords"] = self._top_n(all_keywords, 10)
        except Exception as e:
            logger.error("대화이력 조회 오류: %s", e)
            data["conversations"] = []
            data["conversation_count"] = 0

        # 3) 메모리 (main table query, SK begins_with MEM#)
        try:
            resp = self.table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={":pk": pk, ":prefix": "MEM#"},
            )
            memories = [self._convert_decimals(i) for i in resp.get("Items", [])]
            data["memories"] = memories

            # 카테고리별 분류
            mem_by_cat = {}
            for m in memories:
                cat = m.get("category", "etc")
                if cat not in mem_by_cat:
                    mem_by_cat[cat] = []
                mem_by_cat[cat].append(m.get("content", ""))
            data["memories_by_category"] = mem_by_cat
        except Exception as e:
            logger.error("메모리 조회 오류: %s", e)
            data["memories"] = []

        # 4) 최근 S3 대화 로그 (최대 5개)
        try:
            prefix = f"chat-logs/{user_id}/"
            resp = self.s3.list_objects_v2(
                Bucket=BUCKET_NAME, Prefix=prefix, MaxKeys=20
            )
            keys = sorted(
                [o["Key"] for o in resp.get("Contents", [])],
                reverse=True,
            )[:5]

            recent_logs = []
            for key in keys:
                obj = self.s3.get_object(Bucket=BUCKET_NAME, Key=key)
                log = json.loads(obj["Body"].read())
                recent_logs.append({
                    "character": log.get("character", ""),
                    "session_start": log.get("session_start", ""),
                    "message_count": log.get("message_count", 0),
                    "messages": log.get("messages", [])[-6:],  # 최근 6개 메시지만
                })
            data["recent_logs"] = recent_logs
        except Exception as e:
            logger.error("S3 로그 조회 오류: %s", e)
            data["recent_logs"] = []

        return data

    # ─── AI 분석 ─────────────────────────────────────────────────

    def analyze_preferences(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Claude로 취향 분석"""
        # 분석용 요약 데이터 구성
        summary = self._build_analysis_summary(user_data)
        prompt = PREFERENCE_ANALYSIS_PROMPT.format(user_data=summary)
        return self._invoke_llm(prompt)

    def predict_content(
        self, user_data: Dict[str, Any], content_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Claude로 콘텐츠 추천+이유"""
        summary = self._build_analysis_summary(user_data)
        content_text = json.dumps(
            [
                {
                    "content_id": c.get("content_id", ""),
                    "title": c.get("title", ""),
                    "title_en": c.get("title_en", ""),
                    "genre": c.get("genre", []),
                    "synopsis": c.get("synopsis", "")[:200],
                    "character_count": c.get("character_count", 0),
                }
                for c in content_list
            ],
            ensure_ascii=False,
            indent=2,
        )
        prompt = CONTENT_RECOMMENDATION_PROMPT.format(
            user_data=summary, content_list=content_text
        )
        return self._invoke_llm(prompt)

    # ─── 내부 헬퍼 ───────────────────────────────────────────────

    def _build_analysis_summary(self, user_data: Dict[str, Any]) -> str:
        """분석용 데이터 요약 텍스트 생성"""
        parts = []

        # 프로필
        profile = user_data.get("profile", {})
        if profile:
            p_lines = []
            for key in ["nickname", "gender", "birthday", "interests",
                        "kpop_preferences", "preferred_topics"]:
                val = profile.get(key)
                if val:
                    p_lines.append(f"  {key}: {val}")
            if p_lines:
                parts.append("[프로필]\n" + "\n".join(p_lines))

        # 대화 통계
        parts.append(f"[대화 통계]\n  총 대화 수: {user_data.get('conversation_count', 0)}")
        char_counts = user_data.get("character_chat_counts", {})
        if char_counts:
            parts.append("  캐릭터별 대화 수: " + ", ".join(
                f"{k}({v}회)" for k, v in sorted(char_counts.items(), key=lambda x: -x[1])
            ))
        sentiments = user_data.get("sentiment_distribution", {})
        if sentiments:
            parts.append("  감정 분포: " + ", ".join(f"{k}={v}" for k, v in sentiments.items()))
        keywords = user_data.get("top_keywords", [])
        if keywords:
            parts.append("  주요 키워드: " + ", ".join(keywords))

        # 메모리
        mem_by_cat = user_data.get("memories_by_category", {})
        if mem_by_cat:
            m_lines = []
            for cat, items in mem_by_cat.items():
                m_lines.append(f"  [{cat}] " + " / ".join(items[:5]))
            parts.append("[장기 기억]\n" + "\n".join(m_lines))

        # 최근 대화 샘플
        recent_logs = user_data.get("recent_logs", [])
        if recent_logs:
            log_lines = []
            for log in recent_logs[:3]:
                log_lines.append(f"  --- {log.get('character', '')} ({log.get('session_start', '')[:10]}) ---")
                for msg in log.get("messages", []):
                    role = "사용자" if msg.get("role") == "user" else log.get("character", "캐릭터")
                    content = msg.get("content", "")[:100]
                    log_lines.append(f"    {role}: {content}")
            parts.append("[최근 대화 샘플]\n" + "\n".join(log_lines))

        return "\n\n".join(parts)

    def _invoke_llm(self, prompt: str) -> Dict[str, Any]:
        """Bedrock Claude 호출 (primary → fallback). 결과에 _model 키로 사용 모델명 포함."""
        for model_id in [MODEL_PRIMARY, MODEL_FALLBACK]:
            try:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                    "temperature": 0.3,
                })
                response = self.bedrock.invoke_model(modelId=model_id, body=body)
                result = json.loads(response["body"].read())
                text = result["content"][0]["text"].strip()

                # JSON 파싱 (코드블록 래핑 제거)
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                parsed = json.loads(text)
                parsed["_model"] = _model_display_name(model_id)
                return parsed
            except json.JSONDecodeError:
                logger.warning("LLM JSON 파싱 실패 (%s), raw text 반환", model_id)
                return {"raw_response": text, "_model": _model_display_name(model_id)}
            except Exception as e:
                logger.warning("LLM 호출 실패 (%s): %s — fallback 시도", model_id, e)
                continue

        return {"error": "모든 모델 호출 실패"}

    @staticmethod
    def _top_n(items: list, n: int) -> list:
        """빈도순 상위 N개"""
        from collections import Counter
        return [item for item, _ in Counter(items).most_common(n)]

    @staticmethod
    def _convert_decimals(obj):
        if isinstance(obj, dict):
            return {k: CustomerAnalyticsManager._convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [CustomerAnalyticsManager._convert_decimals(i) for i in obj]
        elif isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return obj


# ═══════════════════════════════════════════════════════════════════
# Streamlit UI
# ═══════════════════════════════════════════════════════════════════

def render_analytics(data_mgr):
    """고객 분석 페이지 렌더링 (data_mgr: AdminDataManager — 콘텐츠 목록용)"""

    st.markdown("""
    <div class="main-header">
        <h1>📊 고객 취향 분석</h1>
        <p>사용자 데이터 기반 AI 분석 &amp; 콘텐츠 추천</p>
    </div>
    """, unsafe_allow_html=True)

    # 매니저 초기화
    if "analytics_mgr" not in st.session_state:
        st.session_state.analytics_mgr = CustomerAnalyticsManager()
    analytics = st.session_state.analytics_mgr

    # 탭 구성
    tab_pref, tab_rec = st.tabs(["🔍 고객 취향 분석", "🎯 콘텐츠 추천 예측"])

    # ─── 탭 1: 고객 취향 분석 ────────────────────────────────────
    with tab_pref:
        _render_preference_tab(analytics)

    # ─── 탭 2: 콘텐츠 추천 예측 ──────────────────────────────────
    with tab_rec:
        _render_recommendation_tab(analytics, data_mgr)


def _render_preference_tab(analytics: CustomerAnalyticsManager):
    """고객 취향 분석 탭"""

    # 사용자 목록 로드
    if st.button("사용자 목록 새로고침", key="refresh_users_pref"):
        st.session_state.pop("analytics_users", None)

    if "analytics_users" not in st.session_state:
        with st.spinner("사용자 목록 로딩 중..."):
            st.session_state.analytics_users = analytics.list_users()

    users = st.session_state.analytics_users
    if not users:
        st.warning("등록된 사용자가 없습니다.")
        return

    # 사용자 선택
    user_options = {
        f"{u.get('nickname') or u.get('display_name') or u['user_id']} ({u.get('email', '')})": u["user_id"]
        for u in users
    }
    selected_label = st.selectbox(
        "분석할 사용자 선택", list(user_options.keys()), key="pref_user_select"
    )
    selected_user_id = user_options[selected_label]

    # 사용자 데이터 로드
    if st.button("데이터 로드", key="load_user_data_pref"):
        with st.spinner("사용자 데이터 수집 중..."):
            st.session_state.pref_user_data = analytics.get_user_full_data(selected_user_id)

    user_data = st.session_state.get("pref_user_data")
    if not user_data:
        st.info("사용자를 선택하고 '데이터 로드' 버튼을 클릭하세요.")
        return

    # 프로필 & 통계 표시
    _display_user_stats(user_data)

    st.markdown("---")

    # AI 분석 버튼
    if st.button("🤖 AI 취향 분석 실행", key="run_pref_analysis", type="primary"):
        with st.spinner(f"{_model_display_name(MODEL_PRIMARY)}(이)가 분석 중입니다..."):
            result = analytics.analyze_preferences(user_data)
            st.session_state.pref_analysis_result = result

    result = st.session_state.get("pref_analysis_result")
    if result:
        _display_analysis_result(result)


def _render_recommendation_tab(analytics: CustomerAnalyticsManager, data_mgr):
    """콘텐츠 추천 예측 탭"""

    # 사용자 목록 (탭 1과 공유)
    if "analytics_users" not in st.session_state:
        with st.spinner("사용자 목록 로딩 중..."):
            st.session_state.analytics_users = analytics.list_users()

    users = st.session_state.analytics_users
    if not users:
        st.warning("등록된 사용자가 없습니다.")
        return

    user_options = {
        f"{u.get('nickname') or u.get('display_name') or u['user_id']} ({u.get('email', '')})": u["user_id"]
        for u in users
    }
    selected_label = st.selectbox(
        "추천 대상 사용자 선택", list(user_options.keys()), key="rec_user_select"
    )
    selected_user_id = user_options[selected_label]

    # 콘텐츠 목록 로드
    if "analytics_contents" not in st.session_state:
        with st.spinner("콘텐츠 목록 로딩 중..."):
            st.session_state.analytics_contents = data_mgr.list_contents()

    contents = st.session_state.analytics_contents
    if not contents:
        st.warning("등록된 콘텐츠가 없습니다. 먼저 콘텐츠를 등록해주세요.")
        return

    st.info(f"총 {len(contents)}개 콘텐츠 대상으로 추천 예측을 수행합니다.")

    # 추천 예측 실행
    if st.button("🎯 추천 예측 실행", key="run_rec_analysis", type="primary"):
        with st.spinner("사용자 데이터 수집 중..."):
            user_data = analytics.get_user_full_data(selected_user_id)

        # 캐릭터 정보 보강
        enriched_contents = []
        for c in contents:
            content_id = c.get("content_id", "")
            chars = data_mgr.list_characters(content_id)
            c_copy = dict(c)
            c_copy["characters"] = [
                {"name": ch.get("name", ""), "role_type": ch.get("role_type", "")}
                for ch in chars
            ]
            enriched_contents.append(c_copy)

        with st.spinner(f"{_model_display_name(MODEL_PRIMARY)}(이)가 추천을 생성 중입니다..."):
            result = analytics.predict_content(user_data, enriched_contents)
            st.session_state.rec_analysis_result = result

    result = st.session_state.get("rec_analysis_result")
    if result:
        _display_recommendation_result(result)


# ─── 표시 헬퍼 ───────────────────────────────────────────────────

def _display_user_stats(user_data: Dict[str, Any]):
    """사용자 프로필 & 통계 카드 표시"""
    profile = user_data.get("profile", {})

    # 통계 카드
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{user_data.get('conversation_count', 0)}</h3>
            <p>총 대화 수</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{len(user_data.get('memories', []))}</h3>
            <p>저장된 기억</p>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        char_counts = user_data.get("character_chat_counts", {})
        fav_char = max(char_counts, key=char_counts.get) if char_counts else "-"
        st.markdown(f"""
        <div class="stat-card">
            <h3>{fav_char}</h3>
            <p>최다 대화 캐릭터</p>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        sessions = profile.get("total_sessions", 0)
        st.markdown(f"""
        <div class="stat-card">
            <h3>{sessions}</h3>
            <p>총 세션 수</p>
        </div>
        """, unsafe_allow_html=True)

    # 프로필 상세
    with st.expander("📋 사용자 프로필 상세", expanded=False):
        p_col1, p_col2 = st.columns(2)
        with p_col1:
            st.write(f"**닉네임:** {profile.get('nickname', '-')}")
            st.write(f"**성별:** {profile.get('gender', '-')}")
            st.write(f"**생일:** {profile.get('birthday', '-')}")
            st.write(f"**이메일:** {profile.get('email', '-')}")
        with p_col2:
            interests = profile.get("interests", [])
            st.write(f"**관심사:** {', '.join(interests) if interests else '-'}")
            kpop = profile.get("kpop_preferences", {})
            if isinstance(kpop, dict) and kpop:
                for k, v in kpop.items():
                    display_val = v if isinstance(v, str) else ", ".join(v) if isinstance(v, list) else str(v)
                    st.write(f"**K-Pop {k}:** {display_val}")
            topics = profile.get("preferred_topics", [])
            st.write(f"**선호 주제:** {', '.join(topics) if topics else '-'}")

    # 캐릭터별 대화 수
    char_counts = user_data.get("character_chat_counts", {})
    if char_counts:
        with st.expander("💬 캐릭터별 대화 수", expanded=False):
            for char, cnt in sorted(char_counts.items(), key=lambda x: -x[1]):
                st.write(f"- **{char}**: {cnt}회")

    # 주요 키워드
    keywords = user_data.get("top_keywords", [])
    if keywords:
        with st.expander("🏷️ 주요 키워드", expanded=False):
            st.write(", ".join(keywords))

    # 메모리 카테고리
    mem_by_cat = user_data.get("memories_by_category", {})
    if mem_by_cat:
        with st.expander("🧠 장기 기억 (카테고리별)", expanded=False):
            for cat, items in mem_by_cat.items():
                st.write(f"**[{cat}]** ({len(items)}건)")
                for item in items[:5]:
                    st.write(f"  - {item}")
                if len(items) > 5:
                    st.write(f"  ... 외 {len(items) - 5}건")


def _display_analysis_result(result: Dict[str, Any]):
    """AI 분석 결과 표시"""
    if "error" in result:
        st.error(f"분석 실패: {result['error']}")
        return

    if "raw_response" in result:
        st.warning("JSON 파싱 실패 — 원본 응답:")
        st.text(result["raw_response"])
        return

    used_model = result.pop("_model", "")
    model_badge = f" — *{used_model}*" if used_model else ""
    st.subheader(f"🤖 AI 분석 결과{model_badge}")

    # 종합 프로필
    overall = result.get("overall_profile", "")
    if overall:
        st.markdown(f"""
        <div class="stat-card" style="text-align:left; margin-bottom:1rem;">
            <h3 style="font-size:1rem;">종합 프로필</h3>
            <p style="font-size:0.95rem;">{overall}</p>
        </div>
        """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        # 캐릭터 선호도
        char_prefs = result.get("character_preferences", {})
        if char_prefs:
            st.markdown("**🎭 캐릭터 선호도**")
            if isinstance(char_prefs, dict):
                for char, info in char_prefs.items():
                    if isinstance(info, dict):
                        st.write(f"- **{char}**: {info.get('preference', info.get('reason', str(info)))}")
                    else:
                        st.write(f"- **{char}**: {info}")
            elif isinstance(char_prefs, list):
                for item in char_prefs:
                    if isinstance(item, dict):
                        st.write(f"- **{item.get('character', '')}**: {item.get('reason', item.get('preference', ''))}")
                    else:
                        st.write(f"- {item}")

        # 성격 특성
        personality = result.get("personality_insights", [])
        if personality:
            st.markdown("**🧩 성격 특성 추정**")
            if isinstance(personality, list):
                for p in personality:
                    st.write(f"- {p}")
            else:
                st.write(personality)

    with col2:
        # 관심 주제
        topics = result.get("interest_topics", [])
        if topics:
            st.markdown("**📌 관심 주제 Top 5**")
            if isinstance(topics, list):
                for i, t in enumerate(topics, 1):
                    if isinstance(t, dict):
                        st.write(f"{i}. **{t.get('topic', t.get('name', ''))}** — {t.get('reason', t.get('evidence', ''))}")
                    else:
                        st.write(f"{i}. {t}")
            else:
                st.write(topics)

        # 감정 패턴
        emotion = result.get("emotion_patterns", {})
        if emotion:
            st.markdown("**😊 감정 패턴**")
            if isinstance(emotion, dict):
                for k, v in emotion.items():
                    st.write(f"- **{k}**: {v}")
            else:
                st.write(emotion)

    # 참여도
    engagement = result.get("engagement_level", "")
    if engagement:
        st.markdown("---")
        if isinstance(engagement, dict):
            level = engagement.get("level", engagement.get("engagement", ""))
            reason = engagement.get("reason", engagement.get("evidence", ""))
            badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(str(level).lower(), "⚪")
            st.markdown(f"**📊 참여도:** {badge} {level}  —  {reason}")
        else:
            st.markdown(f"**📊 참여도:** {engagement}")


def _display_recommendation_result(result: Dict[str, Any]):
    """콘텐츠 추천 결과 표시"""
    if "error" in result:
        st.error(f"추천 실패: {result['error']}")
        return

    if "raw_response" in result:
        st.warning("JSON 파싱 실패 — 원본 응답:")
        st.text(result["raw_response"])
        return

    used_model = result.pop("_model", "")
    model_badge = f" — *{used_model}*" if used_model else ""

    recommendations = result.get("recommendations", [])
    if not recommendations:
        st.info("추천 결과가 없습니다.")
        return

    st.subheader(f"🎯 추천 콘텐츠{model_badge}")

    for i, rec in enumerate(recommendations, 1):
        title = rec.get("title", rec.get("content_id", ""))
        score = rec.get("match_score", 0)
        reasons = rec.get("reasons", [])

        # 점수 색상
        if score >= 80:
            score_color = "#00d4ff"
        elif score >= 60:
            score_color = "#ffc107"
        else:
            score_color = "#888"

        st.markdown(f"""
        <div class="stat-card" style="text-align:left; margin-bottom:0.8rem;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h3 style="font-size:1.1rem; margin:0;">{i}. {title}</h3>
                <span style="color:{score_color}; font-size:1.3rem; font-weight:bold;">{score}점</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if reasons:
            for r in reasons:
                st.write(f"  - {r}")
        st.write("")
