#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - S3/KB 동기화 관리 UI
"""

import streamlit as st
import time
from admin_app_data import AdminDataManager


def render_sync_management(data_mgr: AdminDataManager):
    """KB 동기화 관리 UI"""
    st.markdown("""
    <div class="main-header">
        <h1>🔄 KB 동기화</h1>
        <p>DynamoDB → S3 동기화 + Bedrock Knowledge Base 인제스천</p>
    </div>
    """, unsafe_allow_html=True)

    # 콘텐츠 선택
    contents = data_mgr.list_contents()
    if not contents:
        st.warning("등록된 콘텐츠가 없습니다.")
        return

    content_options = {c["content_id"]: f"{c.get('title', c['content_id'])} ({c.get('title_en', '')})" for c in contents}
    selected_content_id = st.selectbox(
        "대상 콘텐츠",
        list(content_options.keys()),
        format_func=lambda x: content_options[x],
    )

    tab_sync, tab_status, tab_compare = st.tabs(["🔄 동기화 실행", "📊 인제스천 현황", "🔍 상태 비교"])

    # ── 동기화 실행 ──
    with tab_sync:
        st.markdown("### 1단계: DDB → S3 동기화")
        st.markdown("DynamoDB의 콘텐츠/캐릭터/관계 데이터를 자연어 JSON으로 변환하여 S3에 업로드합니다.")

        if st.button("S3 동기화 시작", key="s3_sync_btn", use_container_width=True):
            with st.spinner("DDB → S3 동기화 중..."):
                result = data_mgr.sync_to_s3(selected_content_id)

            if "error" in result:
                st.error(result["error"])
            else:
                st.success(
                    f"S3 동기화 완료! "
                    f"업로드: {result.get('uploaded', 0)}개 파일, "
                    f"캐릭터: {result.get('characters', 0)}명, "
                    f"관계: {result.get('relationships', 0)}개"
                )

        st.markdown("---")
        st.markdown("### 2단계: KB 인제스천")
        st.markdown("S3 데이터를 Bedrock Knowledge Base에 인덱싱합니다.")

        if not data_mgr.content_ds_id:
            st.warning(
                "content_data_source_id가 설정되지 않았습니다. "
                "`admin_config.json`을 확인하거나 `admin_app_setup.py`를 실행해주세요."
            )
        else:
            st.info(f"데이터소스 ID: `{data_mgr.content_ds_id}`")

            if st.button("KB 인제스천 시작", key="kb_sync_btn", use_container_width=True):
                with st.spinner("인제스천 시작 중..."):
                    job_id = data_mgr.trigger_kb_sync()

                if job_id:
                    st.success(f"인제스천 시작됨! Job ID: `{job_id}`")
                    st.session_state["last_ingestion_job_id"] = job_id
                else:
                    st.error("인제스천 시작 실패")

        st.markdown("---")
        st.markdown("### 전체 파이프라인 (S3 + KB)")
        if st.button("전체 동기화 실행", key="full_sync_btn", type="primary", use_container_width=True):
            # S3 동기화
            progress = st.progress(0)
            status = st.empty()

            status.markdown("**1/2** DDB → S3 동기화 중...")
            result = data_mgr.sync_to_s3(selected_content_id)
            progress.progress(50)

            if "error" in result:
                st.error(result["error"])
                return

            st.success(
                f"S3 동기화 완료 — {result.get('uploaded', 0)}개 파일"
            )

            # KB 인제스천
            if data_mgr.content_ds_id:
                status.markdown("**2/2** KB 인제스천 시작 중...")
                job_id = data_mgr.trigger_kb_sync()
                progress.progress(100)

                if job_id:
                    st.success(f"인제스천 시작됨! Job ID: `{job_id}`")
                    st.session_state["last_ingestion_job_id"] = job_id
                else:
                    st.warning("인제스천 시작 실패 — 수동으로 시도해주세요.")
            else:
                progress.progress(100)
                st.warning("KB 데이터소스 미설정 — S3 동기화만 완료")

    # ── 인제스천 현황 ──
    with tab_status:
        st.markdown("### 최근 인제스천 작업")

        # 특정 Job 상태 확인
        job_id = st.text_input(
            "Job ID로 상태 확인",
            value=st.session_state.get("last_ingestion_job_id", ""),
            key="check_job_id",
        )
        if job_id and st.button("상태 확인", key="check_status_btn"):
            status = data_mgr.check_kb_sync_status(job_id)
            if status.get("status") == "ERROR":
                st.error(f"오류: {status.get('message', '')}")
            else:
                status_emoji = {
                    "STARTING": "🟡",
                    "IN_PROGRESS": "🔵",
                    "COMPLETE": "🟢",
                    "FAILED": "🔴",
                }.get(status.get("status", ""), "⚪")
                st.markdown(f"{status_emoji} **상태:** {status.get('status', 'UNKNOWN')}")
                st.markdown(f"**시작:** {status.get('started_at', '-')}")
                st.markdown(f"**업데이트:** {status.get('updated_at', '-')}")
                stats = status.get("statistics", {})
                if stats:
                    st.json(stats)

        st.markdown("---")
        st.markdown("### 작업 목록")

        if st.button("새로고침", key="refresh_jobs_btn"):
            st.rerun()

        jobs = data_mgr.list_kb_sync_jobs()
        if not jobs:
            st.info("인제스천 작업 내역이 없습니다.")
        else:
            for job in jobs:
                status_emoji = {
                    "STARTING": "🟡",
                    "IN_PROGRESS": "🔵",
                    "COMPLETE": "🟢",
                    "FAILED": "🔴",
                }.get(job.get("status", ""), "⚪")
                st.markdown(
                    f"{status_emoji} `{job['job_id'][:12]}...` — "
                    f"**{job.get('status', '')}** — "
                    f"{job.get('started_at', '')[:19]}"
                )
                stats = job.get("statistics", {})
                if stats:
                    cols = st.columns(4)
                    for i, (k, v) in enumerate(stats.items()):
                        if v:
                            cols[i % 4].metric(k, v)

    # ── 상태 비교 ──
    with tab_compare:
        st.markdown("### DDB vs S3 동기화 상태")

        if st.button("비교 실행", key="compare_btn", use_container_width=True):
            with st.spinner("비교 중..."):
                comparison = data_mgr.get_sync_comparison(selected_content_id)

            if comparison.get("synced"):
                st.success("DDB와 S3가 동기화되어 있습니다!")
            else:
                st.warning("동기화 불일치가 있습니다.")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**DDB 캐릭터:**")
                for c in comparison.get("ddb_characters", []):
                    st.markdown(f"- `{c}`")
            with col2:
                st.markdown("**S3 캐릭터:**")
                for c in comparison.get("s3_characters", []):
                    st.markdown(f"- `{c}`")

            missing = comparison.get("missing_in_s3", [])
            extra = comparison.get("extra_in_s3", [])

            if missing:
                st.markdown(f"**S3에 없는 캐릭터:** {', '.join(missing)}")
            if extra:
                st.markdown(f"**S3에만 있는 캐릭터:** {', '.join(extra)}")
