#!/usr/bin/env python3
"""
스토리보드 어시스턴트 앱 - 스토리 현황 대시보드
콘텐츠 정보, 캐릭터 맵, 세계관, 작가 메모 관리
"""

import streamlit as st
from typing import Dict, Any, List


def render_story_dashboard(data_mgr):
    """스토리 현황 대시보드 페이지"""

    st.markdown("""
    <div class="main-header">
        <h1>📋 스토리 현황</h1>
        <p>콘텐츠 개요, 캐릭터 맵, 세계관 설정, 작가 메모</p>
    </div>
    """, unsafe_allow_html=True)

    # ── 콘텐츠 목록 로드 ──
    if "story_contents" not in st.session_state:
        with st.spinner("콘텐츠 목록 로딩 중..."):
            st.session_state.story_contents = data_mgr.list_contents()

    contents = st.session_state.story_contents
    if not contents:
        st.warning("등록된 콘텐츠가 없습니다. 관리자 앱에서 콘텐츠를 먼저 등록해주세요.")
        return

    # ── 콘텐츠 선택 ──
    col_select, col_refresh = st.columns([4, 1])
    with col_select:
        content_options = {
            f"{c.get('title', '')} ({c.get('title_en', '')})": c["content_id"]
            for c in contents
        }
        selected_label = st.selectbox(
            "콘텐츠 선택", list(content_options.keys()), key="story_content_select"
        )
        content_id = content_options[selected_label]
    with col_refresh:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("새로고침", key="refresh_story_contents"):
            st.session_state.pop("story_contents", None)
            st.session_state.pop("story_characters", None)
            st.session_state.pop("story_relationships", None)
            st.rerun()

    # ── 선택한 콘텐츠 데이터 로드 ──
    content = next((c for c in contents if c["content_id"] == content_id), {})

    cache_key_chars = f"story_chars_{content_id}"
    cache_key_rels = f"story_rels_{content_id}"

    if cache_key_chars not in st.session_state:
        with st.spinner("캐릭터 데이터 로딩 중..."):
            st.session_state[cache_key_chars] = data_mgr.list_characters(content_id)
            st.session_state[cache_key_rels] = data_mgr.list_relationships(content_id)

    characters = st.session_state[cache_key_chars]
    relationships = st.session_state[cache_key_rels]

    # ── 1. 콘텐츠 기본 정보 ──
    _render_content_info(content, characters, relationships)

    st.markdown("---")

    # ── 2. 캐릭터 맵 ──
    _render_character_map(characters, relationships)

    st.markdown("---")

    # ── 3. 세계관 설정 ──
    _render_world_setting(content)

    st.markdown("---")

    # ── 4. 스토리 노트 ──
    _render_story_notes(content_id)


def _render_content_info(content: Dict[str, Any], characters: list, relationships: list):
    """콘텐츠 기본 정보 카드"""

    st.subheader("작품 개요")

    # 통계 카드
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{content.get('title', '-')}</h3>
            <p>작품명</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        genres = content.get("genre", [])
        genre_text = ", ".join(genres) if genres else "-"
        st.markdown(f"""
        <div class="stat-card">
            <h3>{genre_text}</h3>
            <p>장르</p>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{len(characters)}</h3>
            <p>등록 캐릭터</p>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <h3>{len(relationships)}</h3>
            <p>관계 설정</p>
        </div>
        """, unsafe_allow_html=True)

    # 시놉시스
    synopsis = content.get("synopsis", "")
    if synopsis:
        with st.expander("시놉시스", expanded=True):
            st.write(synopsis)

    # 상세 정보
    with st.expander("작품 상세 정보", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.write(f"**영문 제목:** {content.get('title_en', '-')}")
            st.write(f"**플랫폼:** {content.get('platform', '-')}")
            st.write(f"**공개일:** {content.get('release_date', '-')}")
            st.write(f"**포맷:** {content.get('format', '-')}")
            st.write(f"**러닝타임:** {content.get('runtime', '-')}")
        with col_b:
            st.write(f"**원작:** {content.get('creator', '-')}")
            directors = content.get("director", [])
            st.write(f"**감독:** {', '.join(directors) if directors else '-'}")
            writers = content.get("writer", [])
            st.write(f"**각본:** {', '.join(writers) if writers else '-'}")
            st.write(f"**제작:** {content.get('production', '-')}")

        reception = content.get("reception", {})
        if reception:
            st.markdown("**평가:**")
            for k, v in reception.items():
                st.write(f"- {k}: {v}")


def _render_character_map(characters: List[Dict[str, Any]], relationships: List[Dict[str, Any]]):
    """캐릭터 맵: 역할별 분류 + 관계 요약"""

    st.subheader("캐릭터 맵")

    if not characters:
        st.info("등록된 캐릭터가 없습니다.")
        return

    # 역할별 분류
    role_groups = {}
    role_labels = {
        "protagonist": "주인공",
        "antagonist": "악역",
        "supporting": "조연",
        "mentor": "멘토",
    }
    for char in characters:
        role = char.get("role_type", "supporting")
        label = role_labels.get(role, role)
        if label not in role_groups:
            role_groups[label] = []
        role_groups[label].append(char)

    # 역할별 표시
    for role_label, chars in role_groups.items():
        st.markdown(f"**{role_label}** ({len(chars)}명)")
        cols = st.columns(min(len(chars), 4))
        for i, char in enumerate(chars):
            with cols[i % 4]:
                name = char.get("name", "")
                name_en = char.get("name_en", "")
                emoji = char.get("emoji", "")
                group = char.get("group", "")
                traits = char.get("personality_traits", [])
                traits_text = ", ".join(traits[:3]) if traits else "-"

                st.markdown(f"""
                <div class="stat-card" style="text-align:left; margin-bottom:0.5rem;">
                    <h3 style="font-size:1rem;">{emoji} {name} ({name_en})</h3>
                    <p><b>그룹:</b> {group or '-'}</p>
                    <p><b>성격:</b> {traits_text}</p>
                </div>
                """, unsafe_allow_html=True)

    # 관계 요약
    if relationships:
        with st.expander(f"관계 설정 ({len(relationships)}개)", expanded=False):
            for rel in relationships:
                source = rel.get("source_character", "")
                target = rel.get("target_character", "")
                rel_type = rel.get("relationship_type", "")
                desc = rel.get("description", "")
                direction = "↔" if rel.get("bidirectional", True) else "→"
                st.write(f"- **{source}** {direction} **{target}** ({rel_type}): {desc}")


def _render_world_setting(content: Dict[str, Any]):
    """세계관 설정 표시"""

    st.subheader("세계관 설정")

    world_setting = content.get("world_setting", "")
    if world_setting:
        st.write(world_setting)
    else:
        st.info("세계관 설정이 아직 입력되지 않았습니다. 관리자 앱에서 등록해주세요.")


def _render_story_notes(content_id: str):
    """작가 스토리 노트 (세션 내 유지)"""

    st.subheader("스토리 노트")
    st.caption("작가님의 메모를 자유롭게 작성하세요. (세션 내 유지)")

    notes_key = f"story_notes_{content_id}"
    if notes_key not in st.session_state:
        st.session_state[notes_key] = ""

    notes = st.text_area(
        "스토리 메모",
        value=st.session_state[notes_key],
        height=200,
        key=f"story_notes_input_{content_id}",
        placeholder="예: 다음 에피소드에서 루미의 마족 혈통이 드러나는 장면 구상 중...",
        label_visibility="collapsed",
    )
    st.session_state[notes_key] = notes
