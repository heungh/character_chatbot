#!/usr/bin/env python3
"""
스토리보드 어시스턴트 앱 - AI 스토리 어시스턴트
StoryAssistantManager: 스토리 가이드 + 초안 생성
"""

import boto3
import json
import logging
from typing import Dict, Any, List

import streamlit as st

from admin_app_analytics import CustomerAnalyticsManager

logger = logging.getLogger("story_app.assistant")

# LLM 모델
MODEL_PRIMARY = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
MODEL_FALLBACK = "us.anthropic.claude-sonnet-4-20250514-v1:0"

MODEL_DISPLAY_NAMES = {
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude Sonnet 4.5",
    "us.anthropic.claude-sonnet-4-20250514-v1:0": "Claude Sonnet 4",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5",
}


def _model_display_name(model_id: str) -> str:
    if model_id in MODEL_DISPLAY_NAMES:
        return MODEL_DISPLAY_NAMES[model_id]
    parts = model_id.replace("us.anthropic.", "").split("-v")[0].split("-")
    return "Claude " + " ".join(p.capitalize() for p in parts if not p.isdigit())


# ─── 프롬프트 ───────────────────────────────────────────────

STORY_GUIDE_PROMPT = """당신은 전문 스토리 컨설턴트입니다. 아래 스토리 컨텍스트와 고객 반응 데이터를 분석하여, 스토리 작가에게 유용한 방향 가이드를 JSON으로 반환해주세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

=== 스토리 컨텍스트 ===
{story_context}

=== 고객 반응 데이터 ===
{audience_data}

=== 가이드 요청 ===
다음 항목을 포함하여 스토리 방향 가이드를 제안해주세요:

1. story_direction: 전체 스토리 방향 제안 (2-3문장, 현재까지의 흐름과 고객 반응을 고려)
2. character_arcs: 캐릭터별 발전 방향 (각 캐릭터의 성장 포인트와 갈등 제안)
3. plot_suggestions: 플롯 제안 3가지 (각각 제목, 개요, 예상 효과 포함)
4. audience_alignment: 고객 반응 기반 조언 (인기 캐릭터 활용, 관심 주제 반영, 감정 흐름 조절)
5. tension_points: 긴장감 포인트 제안 2-3가지

JSON 출력:"""

STORY_DRAFT_PROMPT = """당신은 전문 스토리 작가입니다. 아래 스토리 컨텍스트와 선택한 가이드를 바탕으로 에피소드 초안을 작성해주세요.
반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.

=== 스토리 컨텍스트 ===
{story_context}

=== 선택한 가이드 ===
{guide_selection}

=== 작성 요청 ===
다음 구조로 에피소드 초안을 JSON으로 작성해주세요:

1. episode_title: 에피소드 제목
2. episode_summary: 에피소드 요약 (2-3문장)
3. draft_text: 에피소드 본문 초안 (대화와 서술을 포함한 자연스러운 스토리. 최소 800자)
4. key_scenes: 주요 장면 리스트 (각 장면의 제목, 설명, 등장 캐릭터)
5. character_moments: 캐릭터별 하이라이트 (캐릭터명, 핵심 순간, 감정 변화)
6. cliffhanger: 다음 에피소드 예고/떡밥 (1-2문장)

JSON 출력:"""


class StoryAssistantManager:
    """AI 스토리 가이드 + 초안 생성"""

    def __init__(self, region: str = "us-east-1"):
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)

    def generate_story_guide(self, story_context: str, audience_data: str) -> Dict[str, Any]:
        """스토리 방향 가이드 생성"""
        prompt = STORY_GUIDE_PROMPT.format(
            story_context=story_context,
            audience_data=audience_data,
        )
        return self._invoke_llm(prompt)

    def generate_draft(self, story_context: str, guide_selection: str) -> Dict[str, Any]:
        """스토리 초안 생성"""
        prompt = STORY_DRAFT_PROMPT.format(
            story_context=story_context,
            guide_selection=guide_selection,
        )
        return self._invoke_llm(prompt, max_tokens=8192)

    def _invoke_llm(self, prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        """Bedrock Claude 호출 (primary → fallback)"""
        for model_id in [MODEL_PRIMARY, MODEL_FALLBACK]:
            try:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                    "temperature": 0.7,
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


# ═══════════════════════════════════════════════════════════════
# Streamlit UI
# ═══════════════════════════════════════════════════════════════

def render_story_assistant(analytics_mgr: CustomerAnalyticsManager, data_mgr):
    """AI 스토리 어시스턴트 페이지"""

    st.markdown("""
    <div class="main-header">
        <h1>🤖 AI 스토리 어시스턴트</h1>
        <p>고객 반응 기반 스토리 가이드 &amp; 에피소드 초안 생성</p>
    </div>
    """, unsafe_allow_html=True)

    # 매니저 초기화
    if "story_assistant_mgr" not in st.session_state:
        st.session_state.story_assistant_mgr = StoryAssistantManager()
    assistant = st.session_state.story_assistant_mgr

    # ── 1. 스토리 컨텍스트 입력 ──
    st.subheader("스토리 컨텍스트")

    # 콘텐츠 선택
    if "assistant_contents" not in st.session_state:
        with st.spinner("콘텐츠 목록 로딩 중..."):
            st.session_state.assistant_contents = data_mgr.list_contents()

    contents = st.session_state.assistant_contents
    if not contents:
        st.warning("등록된 콘텐츠가 없습니다.")
        return

    content_options = {
        f"{c.get('title', '')} ({c.get('title_en', '')})": c["content_id"]
        for c in contents
    }
    selected_label = st.selectbox(
        "콘텐츠 선택", list(content_options.keys()), key="assistant_content_select"
    )
    content_id = content_options[selected_label]
    content = next((c for c in contents if c["content_id"] == content_id), {})

    col1, col2 = st.columns([3, 1])
    with col2:
        episode_num = st.number_input(
            "현재 에피소드 번호", min_value=1, value=1, key="assistant_episode_num"
        )

    with col1:
        writer_notes = st.text_area(
            "작가 메모 (현재 스토리 상황, 원하는 방향 등)",
            height=120,
            key="assistant_writer_notes",
            placeholder="예: 루미의 마족 혈통이 팀원들에게 밝혀지는 장면을 구상 중. 미라와의 갈등을 중심으로...",
        )

    # ── 2. 고객 데이터 자동 수집 ──
    st.markdown("---")
    st.subheader("고객 반응 데이터")

    if st.button("고객 데이터 수집", key="assistant_collect_audience"):
        with st.spinner("전체 사용자 데이터 집계 중..."):
            users = analytics_mgr.list_users()
            audience_summary_parts = []

            total_conversations = 0
            char_counts = {}
            sentiment_total = {"positive": 0, "neutral": 0, "negative": 0}
            all_keywords = []

            for user in users:
                user_data = analytics_mgr.get_user_full_data(user["user_id"])
                total_conversations += user_data.get("conversation_count", 0)

                for char, cnt in user_data.get("character_chat_counts", {}).items():
                    char_counts[char] = char_counts.get(char, 0) + cnt

                for sentiment, cnt in user_data.get("sentiment_distribution", {}).items():
                    sentiment_total[sentiment] = sentiment_total.get(sentiment, 0) + cnt

                all_keywords.extend(user_data.get("top_keywords", []))

            # 요약 텍스트 생성
            audience_summary_parts.append(f"총 사용자 수: {len(users)}")
            audience_summary_parts.append(f"총 대화 수: {total_conversations}")

            if char_counts:
                sorted_chars = sorted(char_counts.items(), key=lambda x: -x[1])
                audience_summary_parts.append(
                    "캐릭터별 대화 수: " + ", ".join(f"{c}({n}회)" for c, n in sorted_chars)
                )

            total_sentiments = sum(sentiment_total.values())
            if total_sentiments > 0:
                audience_summary_parts.append(
                    "감정 분포: " + ", ".join(
                        f"{k}={round(v/total_sentiments*100)}%" for k, v in sentiment_total.items()
                    )
                )

            if all_keywords:
                from collections import Counter
                top_kw = [kw for kw, _ in Counter(all_keywords).most_common(15)]
                audience_summary_parts.append(f"주요 키워드: {', '.join(top_kw)}")

            st.session_state.assistant_audience_data = "\n".join(audience_summary_parts)

    audience_data = st.session_state.get("assistant_audience_data", "")
    if audience_data:
        st.text_area("수집된 고객 데이터 요약", value=audience_data, height=120, disabled=True, key="audience_display")
    else:
        st.info("'고객 데이터 수집' 버튼을 클릭하면 전체 사용자의 대화 통계를 자동 집계합니다.")

    # ── 3. 스토리 컨텍스트 구성 ──
    story_context = _build_story_context(content, content_id, data_mgr, episode_num, writer_notes)

    # ── 4. 스토리 가이드 생성 ──
    st.markdown("---")
    st.subheader("스토리 가이드 생성")

    if st.button("가이드 생성", key="assistant_generate_guide", type="primary"):
        if not audience_data:
            st.warning("먼저 '고객 데이터 수집'을 실행해주세요.")
        else:
            with st.spinner(f"{_model_display_name(MODEL_PRIMARY)}(이)가 스토리 가이드를 생성 중입니다..."):
                result = assistant.generate_story_guide(story_context, audience_data)
                st.session_state.assistant_guide_result = result

    guide_result = st.session_state.get("assistant_guide_result")
    if guide_result:
        _display_guide_result(guide_result)

    # ── 5. 초안 생성 ──
    st.markdown("---")
    st.subheader("에피소드 초안 생성")

    if guide_result and "error" not in guide_result and "raw_response" not in guide_result:
        if st.button("초안 작성", key="assistant_generate_draft", type="primary"):
            guide_text = json.dumps(guide_result, ensure_ascii=False, indent=2)
            with st.spinner(f"{_model_display_name(MODEL_PRIMARY)}(이)가 에피소드 초안을 작성 중입니다..."):
                draft = assistant.generate_draft(story_context, guide_text)
                st.session_state.assistant_draft_result = draft

        draft_result = st.session_state.get("assistant_draft_result")
        if draft_result:
            _display_draft_result(draft_result)
    else:
        st.info("먼저 '가이드 생성'을 실행한 후 초안을 생성할 수 있습니다.")


def _build_story_context(content, content_id, data_mgr, episode_num, writer_notes) -> str:
    """스토리 컨텍스트 텍스트 구성"""
    parts = []

    # 작품 정보
    parts.append(f"[작품] {content.get('title', '')} ({content.get('title_en', '')})")
    genres = content.get("genre", [])
    if genres:
        parts.append(f"장르: {', '.join(genres)}")

    synopsis = content.get("synopsis", "")
    if synopsis:
        parts.append(f"시놉시스: {synopsis}")

    world_setting = content.get("world_setting", "")
    if world_setting:
        parts.append(f"세계관: {world_setting[:500]}")

    # 캐릭터 정보
    cache_key = f"assistant_chars_{content_id}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = data_mgr.list_characters(content_id)
    characters = st.session_state[cache_key]

    if characters:
        char_lines = []
        for char in characters:
            name = char.get("name", "")
            role_type = char.get("role_type", "")
            role = char.get("role_in_story", "")
            traits = ", ".join(char.get("personality_traits", [])[:3])
            char_lines.append(f"  - {name} ({role_type}): {role}. 성격: {traits}")
        parts.append("[캐릭터]\n" + "\n".join(char_lines))

    # 관계
    rel_cache_key = f"assistant_rels_{content_id}"
    if rel_cache_key not in st.session_state:
        st.session_state[rel_cache_key] = data_mgr.list_relationships(content_id)
    relationships = st.session_state[rel_cache_key]

    if relationships:
        rel_lines = []
        for rel in relationships[:10]:
            source = rel.get("source_character", "")
            target = rel.get("target_character", "")
            rel_type = rel.get("relationship_type", "")
            desc = rel.get("description", "")
            rel_lines.append(f"  - {source} ↔ {target} ({rel_type}): {desc}")
        parts.append("[관계]\n" + "\n".join(rel_lines))

    # 에피소드 & 작가 메모
    parts.append(f"[현재 에피소드] {episode_num}화")
    if writer_notes:
        parts.append(f"[작가 메모] {writer_notes}")

    return "\n\n".join(parts)


def _display_guide_result(result: Dict[str, Any]):
    """스토리 가이드 결과 표시"""

    if "error" in result:
        st.error(f"가이드 생성 실패: {result['error']}")
        return

    if "raw_response" in result:
        st.warning("JSON 파싱 실패 — 원본 응답:")
        st.text(result["raw_response"])
        return

    used_model = result.get("_model", "")
    model_badge = f" — *{used_model}*" if used_model else ""
    st.markdown(f"**가이드 결과{model_badge}**")

    # 전체 방향
    direction = result.get("story_direction", "")
    if direction:
        st.markdown(f"""
        <div class="stat-card" style="text-align:left; margin-bottom:1rem;">
            <h3 style="font-size:1rem;">전체 스토리 방향</h3>
            <p style="font-size:0.95rem;">{direction}</p>
        </div>
        """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        # 캐릭터별 발전 방향
        char_arcs = result.get("character_arcs", {})
        if char_arcs:
            with st.expander("캐릭터별 발전 방향", expanded=True):
                if isinstance(char_arcs, dict):
                    for char, arc in char_arcs.items():
                        if isinstance(arc, dict):
                            st.write(f"**{char}**: {arc.get('direction', arc.get('growth', str(arc)))}")
                        else:
                            st.write(f"**{char}**: {arc}")
                elif isinstance(char_arcs, list):
                    for item in char_arcs:
                        if isinstance(item, dict):
                            st.write(f"**{item.get('character', '')}**: {item.get('direction', item.get('growth', ''))}")
                        else:
                            st.write(f"- {item}")

    with col2:
        # 고객 반응 기반 조언
        alignment = result.get("audience_alignment", "")
        if alignment:
            with st.expander("고객 반응 기반 조언", expanded=True):
                if isinstance(alignment, dict):
                    for k, v in alignment.items():
                        st.write(f"**{k}**: {v}")
                elif isinstance(alignment, list):
                    for item in alignment:
                        st.write(f"- {item}")
                else:
                    st.write(alignment)

    # 플롯 제안
    plots = result.get("plot_suggestions", [])
    if plots:
        st.markdown("**플롯 제안:**")
        if isinstance(plots, list):
            for i, plot in enumerate(plots, 1):
                if isinstance(plot, dict):
                    title = plot.get("title", plot.get("name", f"제안 {i}"))
                    overview = plot.get("overview", plot.get("description", plot.get("summary", "")))
                    effect = plot.get("expected_effect", plot.get("effect", ""))
                    st.markdown(f"""
                    <div class="stat-card" style="text-align:left; margin-bottom:0.5rem;">
                        <h3 style="font-size:0.95rem;">{i}. {title}</h3>
                        <p style="font-size:0.9rem;">{overview}</p>
                        <p style="font-size:0.85rem; color:#7ec8e3 !important;">예상 효과: {effect}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.write(f"{i}. {plot}")

    # 긴장감 포인트
    tensions = result.get("tension_points", [])
    if tensions:
        with st.expander("긴장감 포인트 제안", expanded=False):
            if isinstance(tensions, list):
                for t in tensions:
                    if isinstance(t, dict):
                        st.write(f"- **{t.get('title', t.get('point', ''))}**: {t.get('description', t.get('detail', str(t)))}")
                    else:
                        st.write(f"- {t}")
            else:
                st.write(tensions)


def _display_draft_result(result: Dict[str, Any]):
    """에피소드 초안 결과 표시"""

    if "error" in result:
        st.error(f"초안 생성 실패: {result['error']}")
        return

    if "raw_response" in result:
        st.warning("JSON 파싱 실패 — 원본 응답:")
        st.text(result["raw_response"])
        return

    used_model = result.get("_model", "")
    model_badge = f" — *{used_model}*" if used_model else ""

    # 에피소드 제목 & 요약
    title = result.get("episode_title", "")
    summary = result.get("episode_summary", "")

    st.markdown(f"""
    <div class="stat-card" style="text-align:left; margin-bottom:1rem;">
        <h3 style="font-size:1.1rem;">{title}{model_badge}</h3>
        <p style="font-size:0.95rem;">{summary}</p>
    </div>
    """, unsafe_allow_html=True)

    # 본문 초안
    draft_text = result.get("draft_text", "")
    if draft_text:
        with st.expander("에피소드 본문 초안", expanded=True):
            st.write(draft_text)

    col1, col2 = st.columns(2)

    with col1:
        # 주요 장면
        scenes = result.get("key_scenes", [])
        if scenes:
            with st.expander("주요 장면", expanded=True):
                for i, scene in enumerate(scenes, 1):
                    if isinstance(scene, dict):
                        scene_title = scene.get("title", scene.get("name", f"장면 {i}"))
                        desc = scene.get("description", scene.get("detail", ""))
                        chars = scene.get("characters", [])
                        chars_text = ", ".join(chars) if isinstance(chars, list) else str(chars)
                        st.write(f"**{i}. {scene_title}**")
                        st.write(f"  {desc}")
                        if chars_text:
                            st.write(f"  등장: {chars_text}")
                    else:
                        st.write(f"{i}. {scene}")

    with col2:
        # 캐릭터 하이라이트
        moments = result.get("character_moments", [])
        if moments:
            with st.expander("캐릭터 하이라이트", expanded=True):
                if isinstance(moments, list):
                    for m in moments:
                        if isinstance(m, dict):
                            char = m.get("character", m.get("name", ""))
                            moment = m.get("moment", m.get("key_moment", ""))
                            emotion = m.get("emotion_change", m.get("emotion", ""))
                            st.write(f"**{char}**: {moment}")
                            if emotion:
                                st.write(f"  감정 변화: {emotion}")
                        else:
                            st.write(f"- {m}")
                elif isinstance(moments, dict):
                    for char, info in moments.items():
                        st.write(f"**{char}**: {info}")

    # 다음 에피소드 예고
    cliffhanger = result.get("cliffhanger", "")
    if cliffhanger:
        st.markdown("---")
        st.markdown(f"""
        <div class="stat-card" style="text-align:left;">
            <h3 style="font-size:0.95rem;">다음 에피소드 예고</h3>
            <p style="font-size:0.95rem; color:#7ec8e3 !important;">{cliffhanger}</p>
        </div>
        """, unsafe_allow_html=True)
