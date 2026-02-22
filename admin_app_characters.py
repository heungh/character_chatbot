#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 캐릭터 프로필 관리 UI
"""

import streamlit as st
from admin_app_data import AdminDataManager

ROLE_TYPES = ["protagonist", "antagonist", "supporting", "mentor"]
SPECIES_OPTIONS = ["인간", "반마", "마족", "정령", "기타"]
EMOTION_IMAGES = ["default", "happy", "sad", "angry", "surprised", "love", "thinking", "excited", "cool"]


def render_character_management(data_mgr: AdminDataManager):
    """캐릭터 프로필 관리 UI"""
    st.markdown("""
    <div class="main-header">
        <h1>🎭 캐릭터 관리</h1>
        <p>캐릭터 프로필 등록/수정/삭제 및 이미지 관리</p>
    </div>
    """, unsafe_allow_html=True)

    # 콘텐츠 선택
    contents = data_mgr.list_contents()
    if not contents:
        st.warning("등록된 콘텐츠가 없습니다. '콘텐츠 관리'에서 먼저 콘텐츠를 등록해주세요.")
        return

    content_options = {c["content_id"]: f"{c.get('title', c['content_id'])} ({c.get('title_en', '')})" for c in contents}
    selected_content_id = st.selectbox(
        "콘텐츠 선택",
        list(content_options.keys()),
        format_func=lambda x: content_options[x],
    )

    tab_list, tab_add = st.tabs(["📋 캐릭터 목록", "➕ 새 캐릭터 등록"])

    # ── 목록 탭 ──
    with tab_list:
        # 역할 필터
        filter_role = st.selectbox("역할 필터", ["전체"] + ROLE_TYPES, key="char_role_filter")
        role_filter = None if filter_role == "전체" else filter_role

        characters = data_mgr.list_characters(selected_content_id, role_type=role_filter)

        if not characters:
            st.info("등록된 캐릭터가 없습니다.")
        else:
            for char in characters:
                char_id = char["character_id"]
                emoji = char.get("emoji", "🎭")
                color = char.get("color_theme", "#00d4ff")
                playable_badge = "🟢" if char.get("is_playable") else "⚪"

                with st.expander(
                    f"{emoji} **{char.get('name', char_id)}** ({char.get('name_en', '')}) "
                    f"— {char.get('role_type', '')} {playable_badge}",
                    expanded=False,
                ):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**ID:** `{char_id}`")
                        if char.get("group"):
                            st.markdown(f"**그룹:** {char['group']}")
                        st.markdown(f"**역할:** {char.get('role_type', '-')} — {char.get('role_in_story', '-')}")
                        if char.get("personality_traits"):
                            st.markdown(f"**성격 키워드:** {', '.join(char['personality_traits'])}")
                        if char.get("personality_description"):
                            st.markdown(f"**성격 설명:** {char['personality_description']}")
                        if char.get("abilities"):
                            st.markdown(f"**능력:** {', '.join(char['abilities'])}")
                        if char.get("weapon"):
                            st.markdown(f"**무기:** {char['weapon']}")
                        if char.get("speaking_style"):
                            st.markdown(f"**말투:** {char['speaking_style']}")
                        if char.get("catchphrase"):
                            st.markdown(f"**캐치프레이즈:** \"{char['catchphrase']}\"")
                        if char.get("background"):
                            st.markdown(f"**배경:** {char['background'][:300]}")
                        if char.get("age"):
                            st.markdown(f"**나이:** {char['age']}")
                        if char.get("species"):
                            st.markdown(f"**종족:** {char['species']}")
                        va = char.get("voice_actor", {})
                        if va:
                            va_text = ", ".join(f"{k}: {v}" for k, v in va.items() if v)
                            if va_text:
                                st.markdown(f"**성우:** {va_text}")
                        if char.get("public_reception"):
                            st.markdown(f"**대중 반응:** {char['public_reception']}")

                    with col2:
                        # S3 디폴트 이미지 표시
                        img_folder = char.get("s3_image_folder", "").strip("/").split("/")[-1] if char.get("s3_image_folder") else char.get("name_en", "").lower()
                        if img_folder:
                            img_url = data_mgr.get_character_default_image_url(img_folder)
                            if img_url:
                                st.image(img_url, width=150)
                            else:
                                st.markdown(f"<div style='text-align:center; font-size:3rem;'>{emoji}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div style='text-align:center; font-size:3rem;'>{emoji}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='text-align:center; color:{color};'>■ {color}</div>", unsafe_allow_html=True)
                        st.markdown(f"**대화 가능:** {'예' if char.get('is_playable') else '아니오'}")

                    # 편집 폼
                    with st.form(f"edit_char_{char_id}"):
                        st.markdown("---")
                        st.markdown("**편집**")
                        ecol1, ecol2 = st.columns(2)
                        new_name = ecol1.text_input("이름", value=char.get("name", ""), key=f"en_{char_id}")
                        new_name_en = ecol2.text_input("영문명", value=char.get("name_en", ""), key=f"ene_{char_id}")
                        new_role_type = st.selectbox(
                            "역할", ROLE_TYPES,
                            index=ROLE_TYPES.index(char.get("role_type", "supporting")) if char.get("role_type") in ROLE_TYPES else 2,
                            key=f"ert_{char_id}",
                        )
                        new_personality = st.text_area("성격 설명", value=char.get("personality_description", ""), key=f"epd_{char_id}")
                        new_speaking = st.text_input("말투", value=char.get("speaking_style", ""), key=f"ess_{char_id}")
                        new_catchphrase = st.text_input("캐치프레이즈", value=char.get("catchphrase", ""), key=f"ecp_{char_id}")
                        new_background = st.text_area("배경", value=char.get("background", ""), key=f"ebg_{char_id}")
                        new_playable = st.checkbox("대화 가능", value=char.get("is_playable", True), key=f"epl_{char_id}")

                        # 이미지 업로드
                        st.markdown("**이미지 업로드** (감정별)")
                        img_files = st.file_uploader(
                            "이미지 파일들",
                            type=["png", "jpg", "jpeg", "webp"],
                            accept_multiple_files=True,
                            key=f"img_{char_id}",
                        )

                        col_save, col_del = st.columns(2)
                        save_btn = col_save.form_submit_button("저장", use_container_width=True)
                        del_btn = col_del.form_submit_button("삭제", use_container_width=True)

                        if save_btn:
                            updates = {}
                            if new_name != char.get("name", ""):
                                updates["name"] = new_name
                            if new_name_en != char.get("name_en", ""):
                                updates["name_en"] = new_name_en
                            if new_role_type != char.get("role_type", ""):
                                updates["role_type"] = new_role_type
                            if new_personality != char.get("personality_description", ""):
                                updates["personality_description"] = new_personality
                            if new_speaking != char.get("speaking_style", ""):
                                updates["speaking_style"] = new_speaking
                            if new_catchphrase != char.get("catchphrase", ""):
                                updates["catchphrase"] = new_catchphrase
                            if new_background != char.get("background", ""):
                                updates["background"] = new_background
                            if new_playable != char.get("is_playable", True):
                                updates["is_playable"] = new_playable

                            # 이미지 업로드
                            if img_files:
                                for img_file in img_files:
                                    data_mgr.upload_character_image(
                                        selected_content_id, char_id,
                                        img_file.read(), img_file.name,
                                        content_type=img_file.type or "image/png",
                                    )
                                s3_folder = f"content-data/{selected_content_id}/characters/{char_id}/images/"
                                updates["s3_image_folder"] = s3_folder

                            if updates:
                                data_mgr.update_character(selected_content_id, char_id, updates)
                                st.success("저장 완료")
                                st.rerun()
                            else:
                                st.info("변경 사항 없음")

                        if del_btn:
                            data_mgr.delete_character(selected_content_id, char_id)
                            st.success(f"'{char_id}' 삭제 완료")
                            st.rerun()

    # ── 등록 탭 ──
    with tab_add:
        with st.form("add_char_form"):
            st.markdown("### 기본 정보")
            col1, col2 = st.columns(2)
            name = col1.text_input("이름 (한글) *")
            name_en = col2.text_input("이름 (영문) *")
            character_id = st.text_input("캐릭터 ID (slug, 자동 생성 가능)", placeholder="예: rumi")

            col3, col4 = st.columns(2)
            group = col3.text_input("소속 그룹", placeholder="Huntrix, Saja Boys 등")
            role_type = col4.selectbox("역할 유형", ROLE_TYPES)

            role_in_story = st.text_area("스토리 내 역할 설명", height=80)

            st.markdown("### 성격")
            personality_traits = st.text_input("성격 키워드 (쉼표 구분)", placeholder="용감한, 결단력 있는, 따뜻한")
            personality_description = st.text_area("성격 상세 설명", height=100)

            st.markdown("### 능력/전투")
            abilities = st.text_input("능력 (쉼표 구분)", placeholder="혼문 생성, 마력 노래")
            weapon = st.text_input("무기")

            st.markdown("### 대화 스타일")
            speaking_style = st.text_input("말투 특징")
            catchphrase = st.text_input("캐치프레이즈")

            st.markdown("### 배경")
            background = st.text_area("배경 스토리", height=100)
            col5, col6 = st.columns(2)
            age = col5.text_input("나이/연령대")
            species = col6.selectbox("종족", SPECIES_OPTIONS)

            st.markdown("### 성우")
            col7, col8 = st.columns(2)
            va_en = col7.text_input("영어 성우")
            va_kr = col8.text_input("한국어 성우")

            public_reception = st.text_area("대중 반응/평가", height=68)

            st.markdown("### 표시")
            col9, col10 = st.columns(2)
            emoji = col9.text_input("대표 이모지", placeholder="🗡️")
            color_theme = col10.color_picker("색상 테마", "#00d4ff")
            is_playable = st.checkbox("챗봇에서 대화 가능", value=True)

            st.markdown("### 이미지 업로드")
            img_files = st.file_uploader(
                "캐릭터 이미지 (감정별: default, happy, sad 등)",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key="new_char_imgs",
            )

            submitted = st.form_submit_button("등록", use_container_width=True)

            if submitted:
                if not name or not name_en:
                    st.error("이름은 필수입니다.")
                else:
                    char_data = {
                        "character_id": character_id.strip() if character_id.strip() else "",
                        "name": name,
                        "name_en": name_en,
                        "group": group,
                        "role_type": role_type,
                        "role_in_story": role_in_story,
                        "personality_traits": [t.strip() for t in personality_traits.split(",") if t.strip()],
                        "personality_description": personality_description,
                        "abilities": [a.strip() for a in abilities.split(",") if a.strip()],
                        "weapon": weapon,
                        "speaking_style": speaking_style,
                        "catchphrase": catchphrase,
                        "background": background,
                        "age": age,
                        "species": species,
                        "voice_actor": {k: v for k, v in {"en": va_en, "kr": va_kr}.items() if v},
                        "public_reception": public_reception,
                        "emoji": emoji,
                        "color_theme": color_theme,
                        "is_playable": is_playable,
                    }

                    new_char_id = data_mgr.create_character(selected_content_id, char_data)

                    # 이미지 업로드
                    if img_files:
                        for img_file in img_files:
                            data_mgr.upload_character_image(
                                selected_content_id, new_char_id,
                                img_file.read(), img_file.name,
                                content_type=img_file.type or "image/png",
                            )
                        s3_folder = f"content-data/{selected_content_id}/characters/{new_char_id}/images/"
                        data_mgr.update_character(selected_content_id, new_char_id, {"s3_image_folder": s3_folder})

                    st.success(f"캐릭터 등록 완료! ID: `{new_char_id}`")
                    st.rerun()
