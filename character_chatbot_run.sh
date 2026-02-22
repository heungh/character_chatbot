#!/bin/bash

# 케이팝 데몬헌터스 챗봇 실행 스크립트

echo "케이팝 데몬헌터스 챗봇을 시작합니다..."

# 필요한 패키지 설치
echo "필요한 패키지를 설치 중..."
pip install -r requirements.txt

# Streamlit 앱 실행
echo "챗봇 서비스를 시작합니다..."
streamlit run character_chatbot.py --server.port 8502 --server.address 0.0.0.0
