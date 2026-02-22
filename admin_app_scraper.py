#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 스크래퍼 파이프라인 UI
"""

import streamlit as st
import json
from admin_app_data import AdminDataManager
from admin_app_scraper_engine import ContentScraperEngine


def render_scraper_pipeline(data_mgr: AdminDataManager):
    """데이터 수집 파이프라인 UI"""
    st.markdown("""
    <div class="main-header">
        <h1>🔍 데이터 수집</h1>
        <p>나무위키 / Wikipedia 스크래핑 → AI 정제 → DDB 저장</p>
    </div>
    """, unsafe_allow_html=True)

    # 스크래퍼 엔진 초기화
    if "scraper_engine" not in st.session_state:
        st.session_state.scraper_engine = ContentScraperEngine()
    engine = st.session_state.scraper_engine

    # 콘텐츠 선택
    contents = data_mgr.list_contents()
    if not contents:
        st.warning("등록된 콘텐츠가 없습니다. '콘텐츠 관리'에서 먼저 콘텐츠를 등록해주세요.")
        return

    content_options = {c["content_id"]: f"{c.get('title', c['content_id'])}" for c in contents}
    selected_content_id = st.selectbox(
        "대상 콘텐츠",
        list(content_options.keys()),
        format_func=lambda x: content_options[x],
    )

    tab_single, tab_bulk, tab_content_meta = st.tabs(
        ["🎭 캐릭터 단건 수집", "📦 캐릭터 벌크 수집", "📋 콘텐츠 메타데이터 수집"]
    )

    # ── 단건 캐릭터 수집 ──
    with tab_single:
        _render_single_character_scrape(engine, data_mgr, selected_content_id)

    # ── 벌크 캐릭터 수집 ──
    with tab_bulk:
        _render_bulk_character_scrape(engine, data_mgr, selected_content_id)

    # ── 콘텐츠 메타데이터 수집 ──
    with tab_content_meta:
        _render_content_metadata_scrape(engine, data_mgr, selected_content_id)


def _render_single_character_scrape(engine: ContentScraperEngine, data_mgr: AdminDataManager, content_id: str):
    """단건 캐릭터 스크래핑 UI"""
    st.markdown("### 캐릭터 단건 수집")

    col1, col2 = st.columns([3, 1])
    search_term = col1.text_input("검색어", placeholder="캐릭터 이름 (예: 케이팝 데몬헌터스 루미)")
    source = col2.selectbox("소스", ["나무위키", "Wikipedia (EN)", "Wikipedia (KO)"], key="single_source")

    if st.button("스크래핑 시작", key="single_scrape_btn", use_container_width=True):
        if not search_term:
            st.error("검색어를 입력해주세요.")
            return

        with st.spinner("스크래핑 중..."):
            if source == "나무위키":
                raw = engine.scrape_namuwiki(search_term)
            elif source == "Wikipedia (EN)":
                raw = engine.scrape_wikipedia(search_term, lang="en")
            else:
                raw = engine.scrape_wikipedia(search_term, lang="ko")

        if not raw.get("raw_text"):
            st.error("데이터를 가져올 수 없습니다.")
            return

        st.success(f"원시 텍스트 {len(raw['raw_text'])}자 수집 완료")
        if raw.get("url"):
            st.markdown(f"소스: {raw['url']}")

        # 원시 텍스트 미리보기
        with st.expander("원시 텍스트 미리보기"):
            st.text(raw["raw_text"][:2000])

        # AI 정제
        with st.spinner("AI로 캐릭터 프로필 정제 중..."):
            content = data_mgr.get_content(content_id)
            title = content.get("title", content_id) if content else content_id
            refined = engine.refine_character_profile(raw["raw_text"], search_term, title)

        if not refined:
            st.error("AI 정제에 실패했습니다.")
            return

        st.session_state[f"refined_char_{content_id}"] = refined

        st.markdown("### AI 정제 결과")
        st.json(refined)

        # 이미지
        if raw.get("images"):
            st.markdown("### 발견된 이미지")
            img_cols = st.columns(min(len(raw["images"]), 4))
            for i, img_url in enumerate(raw["images"][:4]):
                img_cols[i].image(img_url, width=150)

    # DDB 저장 버튼
    refined = st.session_state.get(f"refined_char_{content_id}")
    if refined:
        st.markdown("---")
        if st.button("DDB에 저장", key="save_refined_char", use_container_width=True):
            char_id = data_mgr.create_character(content_id, refined)
            st.success(f"캐릭터 저장 완료! ID: `{char_id}`")
            st.session_state.pop(f"refined_char_{content_id}", None)
            st.rerun()


def _render_bulk_character_scrape(engine: ContentScraperEngine, data_mgr: AdminDataManager, content_id: str):
    """벌크 캐릭터 스크래핑 UI"""
    st.markdown("### 캐릭터 벌크 수집")

    char_names = st.text_area(
        "캐릭터 이름 목록 (줄바꿈 구분)",
        height=150,
        placeholder="루미\n미라\n조이\n지누",
    )

    source = st.selectbox("소스", ["나무위키", "Wikipedia (EN)", "Wikipedia (KO)"], key="bulk_source")
    search_prefix = st.text_input("검색어 접두사", placeholder="케이팝 데몬헌터스", key="bulk_prefix")

    if st.button("벌크 수집 시작", key="bulk_scrape_btn", use_container_width=True):
        names = [n.strip() for n in char_names.split("\n") if n.strip()]
        if not names:
            st.error("캐릭터 이름을 입력해주세요.")
            return

        content = data_mgr.get_content(content_id)
        title = content.get("title", content_id) if content else content_id

        progress = st.progress(0)
        results = []

        for i, name in enumerate(names):
            search_term = f"{search_prefix} {name}".strip() if search_prefix else name
            st.markdown(f"**[{i+1}/{len(names)}]** {name} 수집 중...")

            # 스크래핑
            if source == "나무위키":
                raw = engine.scrape_namuwiki(search_term)
            elif source == "Wikipedia (EN)":
                raw = engine.scrape_wikipedia(search_term, lang="en")
            else:
                raw = engine.scrape_wikipedia(search_term, lang="ko")

            if raw.get("raw_text"):
                refined = engine.refine_character_profile(raw["raw_text"], name, title)
                if refined:
                    char_id = data_mgr.create_character(content_id, refined)
                    results.append({"name": name, "status": "success", "char_id": char_id})
                    st.success(f"  {name} → `{char_id}` 저장 완료")
                else:
                    results.append({"name": name, "status": "refine_failed"})
                    st.warning(f"  {name} — AI 정제 실패")
            else:
                results.append({"name": name, "status": "scrape_failed"})
                st.warning(f"  {name} — 스크래핑 실패")

            progress.progress((i + 1) / len(names))

        # 결과 요약
        success = sum(1 for r in results if r["status"] == "success")
        st.markdown(f"### 결과: {success}/{len(names)} 성공")


def _render_content_metadata_scrape(engine: ContentScraperEngine, data_mgr: AdminDataManager, content_id: str):
    """콘텐츠 메타데이터 스크래핑 UI"""
    st.markdown("### 콘텐츠 메타데이터 수집")

    col1, col2 = st.columns([3, 1])
    search_term = col1.text_input("검색어", placeholder="콘텐츠 제목 (예: 케이팝 데몬헌터스)", key="meta_search")
    source = col2.selectbox("소스", ["나무위키", "Wikipedia (EN)", "Wikipedia (KO)"], key="meta_source")

    if st.button("메타데이터 수집 시작", key="meta_scrape_btn", use_container_width=True):
        if not search_term:
            st.error("검색어를 입력해주세요.")
            return

        with st.spinner("스크래핑 중..."):
            if source == "나무위키":
                raw = engine.scrape_namuwiki(search_term)
            elif source == "Wikipedia (EN)":
                raw = engine.scrape_wikipedia(search_term, lang="en")
            else:
                raw = engine.scrape_wikipedia(search_term, lang="ko")

        if not raw.get("raw_text"):
            st.error("데이터를 가져올 수 없습니다.")
            return

        with st.spinner("AI로 메타데이터 정제 중..."):
            refined = engine.refine_content_metadata(raw["raw_text"], search_term)

        if not refined:
            st.error("AI 정제에 실패했습니다.")
            return

        st.session_state[f"refined_meta_{content_id}"] = refined
        st.markdown("### AI 정제 결과")
        st.json(refined)

    refined = st.session_state.get(f"refined_meta_{content_id}")
    if refined:
        st.markdown("---")
        if st.button("콘텐츠 메타데이터 업데이트", key="save_refined_meta", use_container_width=True):
            data_mgr.update_content(content_id, refined)
            st.success("메타데이터 업데이트 완료!")
            st.session_state.pop(f"refined_meta_{content_id}", None)
            st.rerun()
