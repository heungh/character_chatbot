#!/usr/bin/env python3
"""
케이팝 데몬헌터스 챗봇 - Cognito 인증 모듈
"""

import boto3
import json
import logging
import streamlit as st
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("character_chatbot.auth")


class CognitoAuthManager:
    """Amazon Cognito 기반 사용자 인증 관리"""

    def __init__(self, user_pool_id: str, client_id: str, region: str = "us-east-1"):
        self.user_pool_id = user_pool_id
        self.client_id = client_id
        self.region = region
        self.client = boto3.client("cognito-idp", region_name=region)

    def sign_up(self, email: str, password: str, display_name: str) -> Dict[str, Any]:
        """회원가입"""
        try:
            response = self.client.sign_up(
                ClientId=self.client_id,
                Username=email,
                Password=password,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "name", "Value": display_name},
                ],
            )
            return {
                "success": True,
                "message": "인증 코드가 이메일로 발송되었습니다.",
                "user_sub": response.get("UserSub"),
            }
        except self.client.exceptions.UsernameExistsException:
            return {"success": False, "message": "이미 등록된 이메일입니다."}
        except self.client.exceptions.InvalidPasswordException as e:
            return {"success": False, "message": f"비밀번호 조건을 충족하지 않습니다: {e}"}
        except Exception as e:
            logger.error("회원가입 오류: %s", e)
            return {"success": False, "message": f"회원가입 오류: {e}"}

    def confirm_sign_up(self, email: str, code: str) -> Dict[str, Any]:
        """이메일 인증 코드 확인"""
        try:
            self.client.confirm_sign_up(
                ClientId=self.client_id,
                Username=email,
                ConfirmationCode=code,
            )
            return {"success": True, "message": "이메일 인증 완료!"}
        except self.client.exceptions.CodeMismatchException:
            return {"success": False, "message": "인증 코드가 일치하지 않습니다."}
        except self.client.exceptions.ExpiredCodeException:
            return {"success": False, "message": "인증 코드가 만료되었습니다. 다시 요청해주세요."}
        except Exception as e:
            logger.error("인증 확인 오류: %s", e)
            return {"success": False, "message": f"인증 확인 오류: {e}"}

    def sign_in(self, email: str, password: str) -> Dict[str, Any]:
        """로그인"""
        try:
            response = self.client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": email,
                    "PASSWORD": password,
                },
            )
            auth_result = response["AuthenticationResult"]
            # 사용자 정보 조회
            user_info = self.get_user_info(auth_result["AccessToken"])
            return {
                "success": True,
                "id_token": auth_result["IdToken"],
                "access_token": auth_result["AccessToken"],
                "refresh_token": auth_result["RefreshToken"],
                "user_sub": user_info.get("sub", ""),
                "email": user_info.get("email", email),
                "display_name": user_info.get("name", ""),
            }
        except self.client.exceptions.NotAuthorizedException:
            return {"success": False, "message": "이메일 또는 비밀번호가 올바르지 않습니다."}
        except self.client.exceptions.UserNotConfirmedException:
            return {"success": False, "message": "이메일 인증이 필요합니다. 인증 코드를 입력해주세요.", "needs_confirmation": True}
        except Exception as e:
            logger.error("로그인 오류: %s", e)
            return {"success": False, "message": f"로그인 오류: {e}"}

    def refresh_session(self, refresh_token: str) -> Dict[str, Any]:
        """토큰 갱신"""
        try:
            response = self.client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )
            auth_result = response["AuthenticationResult"]
            return {
                "success": True,
                "id_token": auth_result["IdToken"],
                "access_token": auth_result["AccessToken"],
            }
        except Exception as e:
            logger.error("토큰 갱신 오류: %s", e)
            return {"success": False, "message": f"세션 갱신 실패: {e}"}

    def get_user_info(self, access_token: str) -> Dict[str, str]:
        """액세스 토큰으로 사용자 정보 조회"""
        try:
            response = self.client.get_user(AccessToken=access_token)
            attrs = {a["Name"]: a["Value"] for a in response.get("UserAttributes", [])}
            return {
                "sub": attrs.get("sub", ""),
                "email": attrs.get("email", ""),
                "name": attrs.get("name", ""),
            }
        except Exception as e:
            logger.error("사용자 정보 조회 오류: %s", e)
            return {}

    def sign_out(self, access_token: str) -> bool:
        """로그아웃 (글로벌)"""
        try:
            self.client.global_sign_out(AccessToken=access_token)
            return True
        except Exception as e:
            logger.error("로그아웃 오류: %s", e)
            return False

    def resend_confirmation_code(self, email: str) -> Dict[str, Any]:
        """인증 코드 재발송"""
        try:
            self.client.resend_confirmation_code(
                ClientId=self.client_id,
                Username=email,
            )
            return {"success": True, "message": "인증 코드가 재발송되었습니다."}
        except Exception as e:
            logger.error("인증 코드 재발송 오류: %s", e)
            return {"success": False, "message": f"재발송 오류: {e}"}


# ─── Streamlit UI 함수 ─────────────────────────────────────────────


def render_auth_ui(auth_manager: CognitoAuthManager) -> Optional[str]:
    """로그인/회원가입 UI 렌더링. 인증 성공 시 user_id 반환, 실패 시 None."""

    # 이미 로그인 상태인지 확인
    if st.session_state.get("auth_user_id"):
        return st.session_state["auth_user_id"]

    st.markdown("""
    <style>
    /* 로그인/회원가입/인증 폼 버튼 — 로그아웃 버튼과 동일한 스타일 */
    [data-testid="stForm"] button[kind="secondaryFormSubmit"],
    [data-testid="stForm"] button[type="submit"] {
        background: linear-gradient(135deg, #7928ca 0%, #ff0080 100%) !important;
        color: white !important;
        border: 2px solid transparent !important;
        border-radius: 15px !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 20px rgba(255, 0, 128, 0.4), inset 0 0 20px rgba(255, 255, 255, 0.1) !important;
    }
    [data-testid="stForm"] button[kind="secondaryFormSubmit"]:hover,
    [data-testid="stForm"] button[type="submit"]:hover {
        transform: translateY(-3px) scale(1.02) !important;
        box-shadow: 0 8px 30px rgba(255, 0, 128, 0.6), 0 0 40px rgba(121, 40, 202, 0.4) !important;
        border-color: #ff0080 !important;
    }
    </style>
    <div style="text-align: center; padding: 2rem 0 1rem;">
        <h2 style="color: #ff0080; text-shadow: 0 0 15px rgba(255,0,128,0.5);">
            🔐 로그인이 필요합니다
        </h2>
        <p style="color: #ff80bf;">케이팝 데몬헌터스와 대화하려면 먼저 로그인해주세요</p>
    </div>
    """, unsafe_allow_html=True)

    # 중앙 정렬 + 좁은 폭 (전체의 ~40%)
    _left, center_col, _right = st.columns([3, 4, 3])

    with center_col:
        tab_login, tab_signup, tab_confirm = st.tabs(["🔑 로그인", "📝 회원가입", "✉️ 이메일 인증"])

        # ── 로그인 탭 ──
        with tab_login:
            with st.form("login_form"):
                email = st.text_input("이메일", key="login_email")
                password = st.text_input("비밀번호", type="password", key="login_password")
                submitted = st.form_submit_button("로그인", use_container_width=True)

                if submitted and email and password:
                    result = auth_manager.sign_in(email, password)
                    if result["success"]:
                        st.session_state["auth_user_id"] = result["user_sub"]
                        st.session_state["auth_email"] = result["email"]
                        st.session_state["auth_display_name"] = result["display_name"]
                        st.session_state["auth_access_token"] = result["access_token"]
                        st.session_state["auth_refresh_token"] = result["refresh_token"]
                        st.success("로그인 성공!")
                        st.rerun()
                    else:
                        if result.get("needs_confirmation"):
                            st.warning(result["message"])
                        else:
                            st.error(result["message"])

        # ── 회원가입 탭 ──
        with tab_signup:
            with st.form("signup_form"):
                s_name = st.text_input("표시 이름", key="signup_name")
                s_email = st.text_input("이메일", key="signup_email")
                s_pw = st.text_input("비밀번호 (8자 이상, 대소문자+숫자)", type="password", key="signup_password")
                s_pw2 = st.text_input("비밀번호 확인", type="password", key="signup_password2")
                submitted = st.form_submit_button("회원가입", use_container_width=True)

                if submitted:
                    if not all([s_name, s_email, s_pw, s_pw2]):
                        st.error("모든 필드를 입력해주세요.")
                    elif s_pw != s_pw2:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        result = auth_manager.sign_up(s_email, s_pw, s_name)
                        if result["success"]:
                            st.success(result["message"])
                            st.info("'이메일 인증' 탭에서 인증 코드를 입력해주세요.")
                        else:
                            st.error(result["message"])

        # ── 이메일 인증 탭 ──
        with tab_confirm:
            with st.form("confirm_form"):
                c_email = st.text_input("이메일", key="confirm_email")
                c_code = st.text_input("인증 코드", key="confirm_code")
                col1, col2 = st.columns(2)
                with col1:
                    confirm_submitted = st.form_submit_button("인증 확인", use_container_width=True)
                with col2:
                    resend_submitted = st.form_submit_button("코드 재발송", use_container_width=True)

                if confirm_submitted and c_email and c_code:
                    result = auth_manager.confirm_sign_up(c_email, c_code)
                    if result["success"]:
                        st.success(result["message"])
                        st.info("이제 '로그인' 탭에서 로그인해주세요!")
                    else:
                        st.error(result["message"])

                if resend_submitted and c_email:
                    result = auth_manager.resend_confirmation_code(c_email)
                    if result["success"]:
                        st.success(result["message"])
                    else:
                        st.error(result["message"])

    return None


def render_user_profile_sidebar(auth_manager: CognitoAuthManager):
    """사이드바에 사용자 정보 + 로그아웃 버튼"""
    if not st.session_state.get("auth_user_id"):
        return

    display_name = st.session_state.get("auth_display_name", "")
    email = st.session_state.get("auth_email", "")

    st.markdown("---")
    st.markdown(f"👤 **{display_name}**")
    st.caption(email)

    if st.button("🚪 로그아웃", use_container_width=True):
        # 로그아웃 전 모든 캐릭터 대화 저장
        mm = st.session_state.get("memory_manager")
        user_id = st.session_state.get("auth_user_id")
        if mm and user_id:
            for char, msgs in st.session_state.get("messages", {}).items():
                if msgs and len(msgs) >= 2:
                    session_start = st.session_state.get(
                        f"session_start_{char}",
                        datetime.now(timezone.utc).isoformat(),
                    )
                    try:
                        mm.save_conversation(user_id, char, msgs, session_start)
                    except Exception as e:
                        logger.warning("로그아웃 시 대화 저장 오류 (%s): %s", char, e)

        access_token = st.session_state.get("auth_access_token")
        if access_token:
            auth_manager.sign_out(access_token)

        # 세션 상태 클리어
        for key in list(st.session_state.keys()):
            if key.startswith("auth_"):
                del st.session_state[key]
        # 메모리 매니저도 클리어
        st.session_state.pop("memory_manager", None)
        st.session_state.pop("user_profile", None)
        st.rerun()
