#!/bin/bash
# 콘텐츠 관리자 앱 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  콘텐츠 관리자 앱 (포트 8503)"
echo "========================================"

# Python 확인
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3이 설치되어 있지 않습니다."
    exit 1
fi

# 설정 파일 확인
if [ ! -f "admin_config.json" ]; then
    echo "[WARN] admin_config.json이 없습니다."
    echo "       python3 admin_app_setup.py 를 먼저 실행해주세요."
fi

if [ ! -f "chatbot_config.json" ]; then
    echo "[WARN] chatbot_config.json이 없습니다."
    echo "       Cognito 인증이 필요합니다."
fi

# Streamlit 실행
echo ""
echo "관리자 앱을 시작합니다... (http://localhost:8503)"
echo ""
streamlit run admin_app.py --server.port 8503 --server.headless true
