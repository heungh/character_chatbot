#!/usr/bin/env python3
"""
스토리보드 어시스턴트 앱 - 고객 반응 분석
AI 요약 분석 + 원본 데이터 열람
"""

import streamlit as st
from typing import Dict, Any, List

from admin_app_analytics import CustomerAnalyticsManager, _model_display_name, MODEL_PRIMARY


def render_audience_insights(analytics_mgr: CustomerAnalyticsManager, data_mgr):
    """고객 반응 분석 페이지"""

    st.markdown("""
    <div class="main-header">
        <h1>👥 고객 반응</h1>
        <p>사용자 반응 AI 요약 분석 &amp; 원본 데이터 열람</p>
    </div>
    """, unsafe_allow_html=True)

    # 탭 구성
    tab_summary, tab_raw = st.tabs(["🔍 반응 요약 (AI 분석)", "📄 원본 데이터"])

    with tab_summary:
        _render_summary_tab(analytics_mgr, data_mgr)

    with tab_raw:
        _render_raw_data_tab(analytics_mgr)


# ═══════════════════════════════════════════════════════════════
# 탭 1: 반응 요약 (AI 분석)
# ═══════════════════════════════════════════════════════════════

def _render_summary_tab(analytics_mgr: CustomerAnalyticsManager, data_mgr):
    """AI 분석 기반 고객 반응 요약"""

    # 사용자 목록 로드
    if st.button("사용자 목록 새로고침", key="story_refresh_users"):
        st.session_state.pop("story_users", None)

    if "story_users" not in st.session_state:
        with st.spinner("사용자 목록 로딩 중..."):
            st.session_state.story_users = analytics_mgr.list_users()

    users = st.session_state.story_users
    if not users:
        st.warning("등록된 사용자가 없습니다.")
        return

    # ── 전체 사용자 대화 통계 요약 ──
    _render_overall_stats(analytics_mgr, users)

    st.markdown("---")

    # ── 개별 사용자 AI 분석 ──
    st.subheader("개별 사용자 AI 분석")

    user_options = {
        f"{u.get('nickname') or u.get('display_name') or u['user_id']} ({u.get('email', '')})": u["user_id"]
        for u in users
    }
    selected_label = st.selectbox(
        "분석할 사용자 선택", list(user_options.keys()), key="story_pref_user"
    )
    selected_user_id = user_options[selected_label]

    if st.button("데이터 로드 + AI 분석", key="story_load_analyze"):
        with st.spinner("사용자 데이터 수집 중..."):
            user_data = analytics_mgr.get_user_full_data(selected_user_id)
            st.session_state.story_user_data = user_data

        with st.spinner(f"{_model_display_name(MODEL_PRIMARY)}(이)가 분석 중입니다..."):
            result = analytics_mgr.analyze_preferences(user_data)
            st.session_state.story_analysis_result = result

    result = st.session_state.get("story_analysis_result")
    if result:
        _display_story_analysis(result)


def _render_overall_stats(analytics_mgr: CustomerAnalyticsManager, users: list):
    """전체 사용자 대화 통계 요약"""

    st.subheader("전체 대화 통계")

    if st.button("통계 집계", key="story_aggregate_stats"):
        with st.spinner("전체 사용자 데이터 집계 중..."):
            total_conversations = 0
            char_total_counts = {}
            sentiment_total = {"positive": 0, "neutral": 0, "negative": 0}

            for user in users:
                user_data = analytics_mgr.get_user_full_data(user["user_id"])
                total_conversations += user_data.get("conversation_count", 0)

                for char, cnt in user_data.get("character_chat_counts", {}).items():
                    char_total_counts[char] = char_total_counts.get(char, 0) + cnt

                for sentiment, cnt in user_data.get("sentiment_distribution", {}).items():
                    sentiment_total[sentiment] = sentiment_total.get(sentiment, 0) + cnt

            st.session_state.story_overall_stats = {
                "total_users": len(users),
                "total_conversations": total_conversations,
                "character_counts": char_total_counts,
                "sentiment_total": sentiment_total,
            }

    stats = st.session_state.get("story_overall_stats")
    if not stats:
        st.info("'통계 집계' 버튼을 클릭하면 전체 사용자 대화 데이터를 집계합니다.")
        return

    # 통계 카드
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{stats['total_users']}</h3>
            <p>총 사용자 수</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{stats['total_conversations']}</h3>
            <p>총 대화 수</p>
        </div>
        """, unsafe_allow_html=True)

    # 캐릭터별 대화 수
    char_counts = stats.get("character_counts", {})
    if char_counts:
        st.markdown("**캐릭터별 대화 수:**")
        sorted_chars = sorted(char_counts.items(), key=lambda x: -x[1])
        cols = st.columns(min(len(sorted_chars), 5))
        for i, (char, cnt) in enumerate(sorted_chars):
            with cols[i % 5]:
                st.markdown(f"""
                <div class="stat-card">
                    <h3>{cnt}</h3>
                    <p>{char}</p>
                </div>
                """, unsafe_allow_html=True)

    # 감정 분포
    sentiment = stats.get("sentiment_total", {})
    if sentiment:
        total = sum(sentiment.values())
        if total > 0:
            st.markdown("**전체 감정 분포:**")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                pct = round(sentiment.get("positive", 0) / total * 100)
                st.markdown(f"""
                <div class="stat-card">
                    <h3>{pct}%</h3>
                    <p>긍정</p>
                </div>
                """, unsafe_allow_html=True)
            with col_b:
                pct = round(sentiment.get("neutral", 0) / total * 100)
                st.markdown(f"""
                <div class="stat-card">
                    <h3>{pct}%</h3>
                    <p>중립</p>
                </div>
                """, unsafe_allow_html=True)
            with col_c:
                pct = round(sentiment.get("negative", 0) / total * 100)
                st.markdown(f"""
                <div class="stat-card">
                    <h3>{pct}%</h3>
                    <p>부정</p>
                </div>
                """, unsafe_allow_html=True)


def _display_story_analysis(result: Dict[str, Any]):
    """AI 분석 결과를 스토리 관점으로 표시"""

    if "error" in result:
        st.error(f"분석 실패: {result['error']}")
        return

    if "raw_response" in result:
        st.warning("JSON 파싱 실패 — 원본 응답:")
        st.text(result["raw_response"])
        return

    used_model = result.pop("_model", "")
    model_badge = f" — *{used_model}*" if used_model else ""
    st.subheader(f"분석 결과{model_badge}")

    # 종합 프로필
    overall = result.get("overall_profile", "")
    if overall:
        st.markdown(f"""
        <div class="stat-card" style="text-align:left; margin-bottom:1rem;">
            <h3 style="font-size:1rem;">사용자 종합 프로필</h3>
            <p style="font-size:0.95rem;">{overall}</p>
        </div>
        """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        # 캐릭터별 인기도
        char_prefs = result.get("character_preferences", {})
        if char_prefs:
            st.markdown("**캐릭터별 인기도**")
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

    with col2:
        # 관심 주제
        topics = result.get("interest_topics", [])
        if topics:
            st.markdown("**관심 주제**")
            if isinstance(topics, list):
                for i, t in enumerate(topics, 1):
                    if isinstance(t, dict):
                        st.write(f"{i}. **{t.get('topic', t.get('name', ''))}** — {t.get('reason', t.get('evidence', ''))}")
                    else:
                        st.write(f"{i}. {t}")

        # 감정 패턴
        emotion = result.get("emotion_patterns", {})
        if emotion:
            st.markdown("**감정 패턴**")
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
            st.markdown(f"**참여도:** {badge} {level}  —  {reason}")
        else:
            st.markdown(f"**참여도:** {engagement}")


# ═══════════════════════════════════════════════════════════════
# 탭 2: 원본 데이터
# ═══════════════════════════════════════════════════════════════

def _render_raw_data_tab(analytics_mgr: CustomerAnalyticsManager):
    """원본 데이터 열람"""

    # 사용자 목록 (탭 1과 공유)
    if "story_users" not in st.session_state:
        with st.spinner("사용자 목록 로딩 중..."):
            st.session_state.story_users = analytics_mgr.list_users()

    users = st.session_state.story_users
    if not users:
        st.warning("등록된 사용자가 없습니다.")
        return

    user_options = {
        f"{u.get('nickname') or u.get('display_name') or u['user_id']} ({u.get('email', '')})": u["user_id"]
        for u in users
    }
    selected_label = st.selectbox(
        "사용자 선택", list(user_options.keys()), key="story_raw_user"
    )
    selected_user_id = user_options[selected_label]

    if st.button("원본 데이터 로드", key="story_load_raw"):
        with st.spinner("사용자 데이터 수집 중..."):
            st.session_state.story_raw_data = analytics_mgr.get_user_full_data(selected_user_id)

    raw_data = st.session_state.get("story_raw_data")
    if not raw_data:
        st.info("사용자를 선택하고 '원본 데이터 로드' 버튼을 클릭하세요.")
        return

    # 프로필 상세
    with st.expander("프로필 상세", expanded=True):
        profile = raw_data.get("profile", {})
        if profile:
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**닉네임:** {profile.get('nickname', '-')}")
                st.write(f"**성별:** {profile.get('gender', '-')}")
                st.write(f"**생일:** {profile.get('birthday', '-')}")
                st.write(f"**이메일:** {profile.get('email', '-')}")
                st.write(f"**총 세션:** {profile.get('total_sessions', 0)}")
            with col2:
                interests = profile.get("interests", [])
                st.write(f"**관심사:** {', '.join(interests) if interests else '-'}")
                kpop = profile.get("kpop_preferences", {})
                if isinstance(kpop, dict) and kpop:
                    for k, v in kpop.items():
                        display_val = v if isinstance(v, str) else ", ".join(v) if isinstance(v, list) else str(v)
                        st.write(f"**K-Pop {k}:** {display_val}")
                topics = profile.get("preferred_topics", [])
                st.write(f"**선호 주제:** {', '.join(topics) if topics else '-'}")
        else:
            st.info("프로필 데이터 없음")

    # 대화 이력
    conversations = raw_data.get("conversations", [])
    with st.expander(f"대화 이력 ({len(conversations)}건)", expanded=False):
        if conversations:
            for conv in conversations:
                char = conv.get("character", "")
                summary = conv.get("summary", "")
                sentiment = conv.get("user_sentiment", "")
                keywords = conv.get("keywords", [])
                msg_count = conv.get("message_count", 0)
                session_start = conv.get("session_start", "")[:16]

                badge = {"positive": "🟢", "neutral": "🟡", "negative": "🔴"}.get(sentiment, "⚪")
                st.markdown(f"**{char}** ({session_start}) — {badge} {sentiment} — {msg_count}개 메시지")
                st.write(f"요약: {summary}")
                if keywords:
                    st.write(f"키워드: {', '.join(keywords)}")
                st.markdown("---")
        else:
            st.info("대화 이력 없음")

    # 장기 기억
    memories_by_cat = raw_data.get("memories_by_category", {})
    with st.expander(f"장기 기억 ({sum(len(v) for v in memories_by_cat.values())}건)", expanded=False):
        if memories_by_cat:
            for cat, items in memories_by_cat.items():
                st.markdown(f"**[{cat}]** ({len(items)}건)")
                for item in items[:10]:
                    st.write(f"  - {item}")
                if len(items) > 10:
                    st.write(f"  ... 외 {len(items) - 10}건")
        else:
            st.info("장기 기억 없음")

    # 최근 대화 로그
    recent_logs = raw_data.get("recent_logs", [])
    with st.expander(f"최근 대화 로그 ({len(recent_logs)}건)", expanded=False):
        if recent_logs:
            for log in recent_logs:
                char = log.get("character", "")
                session_start = log.get("session_start", "")[:16]
                msg_count = log.get("message_count", 0)
                st.markdown(f"**{char}** ({session_start}) — {msg_count}개 메시지")

                messages = log.get("messages", [])
                for msg in messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        st.markdown(f"> **사용자:** {content}")
                    else:
                        st.markdown(f"> **{char}:** {content}")
                st.markdown("---")
        else:
            st.info("최근 대화 로그 없음")
