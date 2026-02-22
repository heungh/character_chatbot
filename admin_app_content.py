#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 콘텐츠 메타데이터 관리 UI
"""

import streamlit as st
from admin_app_data import AdminDataManager


def render_content_management(data_mgr: AdminDataManager):
    """콘텐츠 메타데이터 관리 UI"""
    st.markdown("""
    <div class="main-header">
        <h1>📦 콘텐츠 관리</h1>
        <p>콘텐츠 메타데이터 등록/수정/삭제</p>
    </div>
    """, unsafe_allow_html=True)

    tab_list, tab_add = st.tabs(["📋 콘텐츠 목록", "➕ 새 콘텐츠 등록"])

    # ── 목록 탭 ──
    with tab_list:
        contents = data_mgr.list_contents()

        if not contents:
            st.info("등록된 콘텐츠가 없습니다. '새 콘텐츠 등록' 탭에서 추가해주세요.")
        else:
            for content in contents:
                cid = content["content_id"]
                with st.expander(
                    f"**{content.get('title', cid)}** ({content.get('title_en', '')}) "
                    f"— 캐릭터 {content.get('character_count', 0)}명",
                    expanded=False,
                ):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**ID:** `{cid}`")
                        st.markdown(f"**장르:** {', '.join(content.get('genre', []))}")
                        st.markdown(f"**플랫폼:** {content.get('platform', '-')}")
                        st.markdown(f"**공개일:** {content.get('release_date', '-')}")
                        st.markdown(f"**형식:** {content.get('format', '-')} / {content.get('runtime', '-')}")
                        st.markdown(f"**제작:** {content.get('production', '-')}")
                        st.markdown(f"**감독:** {', '.join(content.get('director', []))}")
                        st.markdown(f"**작가:** {', '.join(content.get('writer', []))}")

                        if content.get("synopsis"):
                            st.markdown("**시놉시스:**")
                            st.markdown(content["synopsis"][:500])
                        if content.get("world_setting"):
                            st.markdown("**세계관:**")
                            st.markdown(content["world_setting"][:500])

                        reception = content.get("reception", {})
                        if reception:
                            st.markdown("**평가:**")
                            rcols = st.columns(5)
                            for i, (k, v) in enumerate(reception.items()):
                                if v:
                                    rcols[i % 5].metric(k, v)

                    with col2:
                        st.markdown(f"**등록:** {content.get('created_at', '')[:10]}")
                        st.markdown(f"**수정:** {content.get('updated_at', '')[:10]}")

                    # 편집 폼
                    with st.form(f"edit_content_{cid}"):
                        st.markdown("---")
                        st.markdown("**편집**")
                        new_title = st.text_input("제목 (한글)", value=content.get("title", ""), key=f"et_{cid}")
                        new_title_en = st.text_input("제목 (영문)", value=content.get("title_en", ""), key=f"ete_{cid}")
                        new_synopsis = st.text_area("시놉시스", value=content.get("synopsis", ""), key=f"es_{cid}")
                        new_world = st.text_area("세계관", value=content.get("world_setting", ""), key=f"ew_{cid}")

                        col_save, col_del = st.columns(2)
                        save_btn = col_save.form_submit_button("저장", use_container_width=True)
                        del_btn = col_del.form_submit_button("삭제", use_container_width=True)

                        if save_btn:
                            updates = {}
                            if new_title != content.get("title", ""):
                                updates["title"] = new_title
                            if new_title_en != content.get("title_en", ""):
                                updates["title_en"] = new_title_en
                            if new_synopsis != content.get("synopsis", ""):
                                updates["synopsis"] = new_synopsis
                            if new_world != content.get("world_setting", ""):
                                updates["world_setting"] = new_world
                            if updates:
                                data_mgr.update_content(cid, updates)
                                st.success("저장 완료")
                                st.rerun()
                            else:
                                st.info("변경 사항 없음")

                        if del_btn:
                            data_mgr.delete_content(cid)
                            st.success(f"'{cid}' 삭제 완료")
                            st.rerun()

    # ── 등록 탭 ──
    with tab_add:
        with st.form("add_content_form"):
            st.markdown("### 기본 정보")
            col1, col2 = st.columns(2)
            title = col1.text_input("제목 (한글) *")
            title_en = col2.text_input("제목 (영문) *")
            content_id = st.text_input("콘텐츠 ID (slug, 자동 생성 가능)", placeholder="예: kpop-demon-hunters")

            col3, col4 = st.columns(2)
            platform = col3.text_input("플랫폼", placeholder="스트리밍 플랫폼명")
            release_date = col4.text_input("공개일", placeholder="2025-06-20")

            col5, col6 = st.columns(2)
            fmt = col5.selectbox("형식", ["극장판", "시리즈", "OVA", "기타"])
            runtime = col6.text_input("러닝타임", placeholder="88분")

            genre = st.text_input("장르 (쉼표 구분)", placeholder="애니메이션, 뮤지컬, 판타지, 액션")

            st.markdown("### 제작진")
            creator = st.text_input("원작자")
            director = st.text_input("감독 (쉼표 구분)")
            writer = st.text_input("작가 (쉼표 구분)")
            production = st.text_input("제작사")

            st.markdown("### 내용")
            synopsis = st.text_area("시놉시스", height=150)
            world_setting = st.text_area("세계관 설명", height=150)

            st.markdown("### 평가 (선택)")
            rcol1, rcol2, rcol3 = st.columns(3)
            rt_score = rcol1.text_input("Rotten Tomatoes")
            imdb_score = rcol2.text_input("IMDb")
            metacritic = rcol3.text_input("Metacritic")
            rcol4, rcol5 = st.columns(2)
            awards = rcol4.text_input("수상 내역")
            box_office = rcol5.text_input("박스오피스")

            submitted = st.form_submit_button("등록", use_container_width=True)

            if submitted:
                if not title or not title_en:
                    st.error("제목은 필수입니다.")
                else:
                    content_data = {
                        "content_id": content_id.strip() if content_id.strip() else "",
                        "title": title,
                        "title_en": title_en,
                        "genre": [g.strip() for g in genre.split(",") if g.strip()],
                        "platform": platform,
                        "release_date": release_date,
                        "format": fmt,
                        "runtime": runtime,
                        "creator": creator,
                        "director": [d.strip() for d in director.split(",") if d.strip()],
                        "writer": [w.strip() for w in writer.split(",") if w.strip()],
                        "production": production,
                        "synopsis": synopsis,
                        "world_setting": world_setting,
                        "reception": {
                            k: v for k, v in {
                                "rt_score": rt_score,
                                "imdb_score": imdb_score,
                                "metacritic": metacritic,
                                "awards": awards,
                                "box_office": box_office,
                            }.items() if v
                        },
                    }
                    new_id = data_mgr.create_content(content_data)
                    st.success(f"콘텐츠 등록 완료! ID: `{new_id}`")
                    st.rerun()
