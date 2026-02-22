#!/usr/bin/env python3
"""
스토리보드 어시스턴트 앱 - 메인 (Streamlit :8505)
"""

import streamlit as st
import json
import logging
from character_chatbot_auth import CognitoAuthManager, render_auth_ui, render_user_profile_sidebar
from admin_app_data import AdminDataManager
from admin_app_analytics import CustomerAnalyticsManager
from story_app_dashboard import render_story_dashboard
from story_app_audience import render_audience_insights
from story_app_assistant import render_story_assistant

logger = logging.getLogger("story_app")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def load_cognito_config() -> dict:
    """chatbot_config.json에서 Cognito 설정 로드"""
    try:
        with open("chatbot_config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        try:
            with open("admin_config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}


def main():
    st.set_page_config(
        page_title="스토리보드 어시스턴트",
        page_icon="📝",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── 스타일 ──
    st.markdown("""
    <style>
    /* 다크 테마 기본 */
    .stApp { background-color: #0e1117; color: #e0e0e0; }

    /* Streamlit 기본 텍스트 색상 오버라이드 */
    .stApp p, .stApp span, .stApp li, .stApp div, .stApp label {
        color: #e0e0e0 !important;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
        color: #ffffff !important;
    }

    /* 탭 텍스트 */
    .stTabs [data-baseweb="tab"] {
        color: #b0b0b0 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #00d4ff !important;
    }

    /* Expander 헤더 */
    .streamlit-expanderHeader {
        color: #e0e0e0 !important;
    }

    /* 입력 필드 */
    .stTextInput input, .stTextArea textarea,
    .stNumberInput input, .stDateInput input {
        color: #e0e0e0 !important;
        background-color: #1a1a2e !important;
    }
    /* placeholder 텍스트 */
    .stTextInput input::placeholder,
    .stTextArea textarea::placeholder,
    .stNumberInput input::placeholder {
        color: #999999 !important;
        opacity: 1 !important;
    }
    .stTextInput label, .stTextArea label, .stSelectbox label,
    .stNumberInput label, .stDateInput label, .stMultiSelect label {
        color: #b0b0b0 !important;
    }

    /* Selectbox / Dropdown */
    .stSelectbox [data-baseweb="select"],
    .stSelectbox [data-baseweb="select"] * {
        color: #000000 !important;
    }
    .stSelectbox [data-baseweb="select"] svg {
        fill: #000000 !important;
    }
    /* 드롭다운 메뉴 옵션 */
    [data-baseweb="menu"] [role="option"],
    [data-baseweb="menu"] [role="option"] *,
    [data-baseweb="popover"] [role="option"],
    [data-baseweb="popover"] [role="option"] * {
        color: #000000 !important;
    }
    /* MultiSelect 태그 텍스트 */
    .stMultiSelect [data-baseweb="select"] span,
    .stMultiSelect [data-baseweb="tag"] span {
        color: #000000 !important;
    }

    /* 사이드바 */
    section[data-testid="stSidebar"] {
        background-color: #0e1117;
    }
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label {
        color: #e0e0e0 !important;
    }

    /* 헤더 배너 */
    .main-header {
        text-align: center;
        padding: 1rem 0;
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        border-radius: 10px;
        margin-bottom: 1rem;
    }
    .main-header h1 { color: #00d4ff !important; font-size: 1.8rem; }
    .main-header p { color: #7ec8e3 !important; font-size: 0.9rem; }

    /* 통계 카드 */
    .stat-card {
        background: #1a1a2e;
        border: 1px solid #30475e;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .stat-card h3 { color: #00d4ff !important; margin: 0; }
    .stat-card p { color: #ccc !important; margin: 0.3rem 0 0; font-size: 0.85rem; }

    /* 테이블 */
    .stDataFrame { color: #e0e0e0 !important; }

    /* 알림/경고 박스 텍스트 유지 */
    .stAlert p { color: inherit !important; }

    /* 모든 버튼 → 파란색 */
    .stButton > button,
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-secondary"] {
        background-color: #0066ff !important;
        border-color: #0066ff !important;
        color: #ffffff !important;
    }
    .stButton > button:hover,
    button[data-testid="baseButton-primary"]:hover,
    button[data-testid="baseButton-secondary"]:hover {
        background-color: #0052cc !important;
        border-color: #0052cc !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Cognito 인증 ──
    config = load_cognito_config()
    pool_id = config.get("cognito_user_pool_id", "")
    client_id = config.get("cognito_client_id", "")
    region = config.get("region", "us-east-1")

    if not pool_id or not client_id:
        st.error("Cognito 설정이 없습니다. chatbot_config.json 또는 admin_config.json을 확인해주세요.")
        st.stop()

    auth_manager = CognitoAuthManager(pool_id, client_id, region)
    user_id = render_auth_ui(auth_manager)
    if not user_id:
        st.stop()

    # ── 데이터 매니저 초기화 ──
    if "story_data_mgr" not in st.session_state:
        st.session_state.story_data_mgr = AdminDataManager()
    data_mgr = st.session_state.story_data_mgr

    if "story_analytics_mgr" not in st.session_state:
        st.session_state.story_analytics_mgr = CustomerAnalyticsManager()
    analytics_mgr = st.session_state.story_analytics_mgr

    # ── 사이드바 ──
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center; padding:0.5rem 0;">
            <h2 style="color:#00d4ff;">📝 스토리보드 어시스턴트</h2>
        </div>
        """, unsafe_allow_html=True)

        menu = st.radio(
            "메뉴",
            ["스토리 현황", "고객 반응", "AI 어시스턴트"],
            format_func=lambda x: {
                "스토리 현황": "📋 스토리 현황",
                "고객 반응": "👥 고객 반응",
                "AI 어시스턴트": "🤖 AI 어시스턴트",
            }[x],
            label_visibility="collapsed",
        )

        st.markdown("---")
        render_user_profile_sidebar(auth_manager)

    # ── 메인 콘텐츠 ──
    if menu == "스토리 현황":
        render_story_dashboard(data_mgr)
    elif menu == "고객 반응":
        render_audience_insights(analytics_mgr, data_mgr)
    elif menu == "AI 어시스턴트":
        render_story_assistant(analytics_mgr, data_mgr)


if __name__ == "__main__":
    main()
