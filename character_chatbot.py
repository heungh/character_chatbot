#!/usr/bin/env python3
"""
케이팝 데몬헌터스 캐릭터 챗봇
"""

import streamlit as st
import boto3
import json
from typing import Dict, Any, List, Optional
import time
from pathlib import Path
import os
import re
import logging
from datetime import datetime, timezone
from character_chatbot_scraper import NamuWikiScraper
from character_chatbot_auth import CognitoAuthManager, render_auth_ui, render_user_profile_sidebar
from character_chatbot_memory import ChatbotMemoryManager

# 로깅 설정
logger = logging.getLogger("character_chatbot")
logger.setLevel(logging.DEBUG)

# 파일 핸들러 (chatbot.log)
_log_file = Path(__file__).parent / "chatbot.log"
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_file_handler)

# 콘솔 핸들러
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_console_handler)

class KPopDemonHuntersChatbot:
    def __init__(self):
        # Bedrock 클라이언트 초기화 (북미 리전)
        self.bedrock_client = boto3.client(
            "bedrock-runtime", 
            region_name="us-east-1"
        )
        
        # Knowledge Base 클라이언트
        self.bedrock_agent_client = boto3.client(
            "bedrock-agent-runtime",
            region_name="us-east-1"
        )
        
        # S3 클라이언트 (캐릭터 관리용)
        self.s3_client = boto3.client("s3", region_name="us-east-1")
        
        # Bedrock Agent 클라이언트 (동기화용)
        self.bedrock_agent_mgmt_client = boto3.client("bedrock-agent", region_name="us-east-1")
        
        # 숨김 캐릭터 설정 파일
        self.hidden_chars_file = Path(__file__).parent / "hidden_characters.json"
        
        # 나무위키 스크래퍼 초기화
        self.namu_scraper = NamuWikiScraper()
        
        # Knowledge Base 설정 (admin_config.json에서 로드, 폴백: 하드코딩)
        _admin_cfg = {}
        try:
            with open(Path(__file__).parent / "admin_config.json", "r", encoding="utf-8") as _f:
                _admin_cfg = json.load(_f)
        except FileNotFoundError:
            pass
        self.knowledge_base_id = _admin_cfg.get("knowledge_base_id", "")
        self.data_source_id = _admin_cfg.get("content_data_source_id", "")
        self.bucket_name = _admin_cfg.get("bucket_name", "")
        # Presigned URL 만료 시간 (초)
        self.presigned_url_expiry = 3600  # 1시간

        # 현재 디렉토리
        self.current_dir = Path(__file__).parent

        # 이미지 CDN URL (CloudFront) — chatbot_config.json 또는 환경변수에서 로드
        self.image_cdn_url = os.environ.get("IMAGE_CDN_URL", "")
        if not self.image_cdn_url:
            try:
                with open(self.current_dir / "chatbot_config.json", "r", encoding="utf-8") as _cf:
                    _chatbot_cfg = json.load(_cf)
                    self.image_cdn_url = _chatbot_cfg.get("image_cdn_url", "")
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        # 끝의 / 제거
        self.image_cdn_url = self.image_cdn_url.rstrip("/")

        # 감정 이미지 목록 (모든 캐릭터 공통)
        self.emotion_names = ['angry', 'confused', 'determined', 'happy', 'playful', 'sad', 'surprised', 'suspicious', 'tears']

        # 캐릭터별 이미지 파일 매핑 (캐릭터마다 default 확장자와 감정 파일명이 다를 수 있음)
        self._char_image_files = {
            "rumi":  {"default": "default.png",  "emotions": {e: f"{e}.png" for e in self.emotion_names}},
            "mira":  {"default": "default.png",  "emotions": {e: f"{e}.png" for e in self.emotion_names}},
            "tiger": {"default": "default.png",  "emotions": {e: f"{e}.png" for e in self.emotion_names}},
            "jinu":  {"default": "default.png",   "emotions": {e: f"{e}.png" for e in self.emotion_names}},
            "zoey":  {"default": "default.jpeg",  "emotions": {
                "angry": "Angry face.jpeg", "confused": "confused.jpeg",
                "determined": "determined.jpeg", "happy": "happy.jpeg",
                "playful": "playful.jpeg", "sad": "Sad.jpeg",
                "surprised": "surprised.jpeg", "suspicious": "suspicious.jpeg",
                "tears": "Tears.jpeg",
            }},
        }

        # 캐릭터 정보 (시드 데이터 기반)
        self.characters = {
            "루미": {
                "name": "루미",
                "name_en": "Rumi",
                "role": "HUNTR/X의 리더이자 메인 보컬. 반인반마의 비밀을 가진 데몬 헌터.",
                "personality": "진지하고 책임감이 강하며, 팀원들에게 언니 같은 존재. 자신의 마족 혈통을 숨기며 정체성에 대한 깊은 고민을 안고 있다.",
                "catchphrase": "우리는 무대 위에서만 빛나는 게 아니야. 세상을 지키는 빛이야.",
                "speaking_style": "진지하고 침착하지만, 감정이 북받칠 때 솔직하게 표현하는 말투",
                "abilities": ["혼문 마법 장벽 생성/강화", "마력이 깃든 노래", "사인검 전투", "반마 능력"],
                "background": "고 류미영(데몬 헌터)과 마족 아버지 사이에서 태어난 반인반마. 셀린에게 입양되어 자랐다.",
                "image_folder": "rumi",
                "local_folder": "image/rumi",
                "color": "#FF0080",
                "emoji": "🗡️"
            },
            "미라": {
                "name": "미라",
                "name_en": "Mira",
                "role": "HUNTR/X의 메인 댄서이자 비주얼. 부유한 집안의 반항아.",
                "personality": "무뚝뚝하고 직설적이며 비꼬는 말투를 자주 쓰지만, 속으로는 깊이 동료를 아끼는 성격.",
                "catchphrase": "예쁘게 봐달라고? 칼이 예쁘면 되지.",
                "speaking_style": "직설적이고 약간 비꼬는 말투, 때때로 욕도 불사하는 거침없는 화법",
                "abilities": ["영혼 마법", "에너지 무기 소환", "에너지 방벽 생성", "곡도 전투"],
                "background": "부유한 집안 출신이지만 반항적인 성격 때문에 가족과 갈등이 있다.",
                "image_folder": "mira",
                "local_folder": "image/mira",
                "color": "#9B59B6",
                "emoji": "⚔️"
            },
            "조이": {
                "name": "조이",
                "name_en": "Zoey",
                "role": "HUNTR/X의 메인 래퍼이자 작사가, 막내.",
                "personality": "끝없이 밝고 사랑스러운 성격으로 팀의 분위기 메이커. 한국인과 미국인 사이의 소속감 고민이 있다.",
                "catchphrase": "가사로 세상을 바꿀 수 있다면, 나는 매일 새로운 세계를 쓸 거야!",
                "speaking_style": "밝고 활기찬 말투, 영어와 한국어를 섞어 쓰며, 감탄사가 많다",
                "abilities": ["신칼 투척 전투", "작사/작곡", "근접 전투"],
                "background": "한국에서 태어났지만 미국 캘리포니아 버뱅크에서 자란 한국계 미국인.",
                "image_folder": "zoey",
                "local_folder": "image/zoey",
                "color": "#3498DB",
                "emoji": "🎤"
            },
            "진우": {
                "name": "진우",
                "name_en": "Jinu",
                "role": "사자보이즈의 리더이자 메인 보컬. 400년 전 귀마와의 거래로 마족이 된 비극적 인물.",
                "personality": "마족으로 변했지만 인간적 공감 능력을 잃지 않은 비극적 캐릭터. 루미에게 진심으로 끌린다.",
                "catchphrase": "400년을 살았지만... 네 노래를 들은 순간, 처음으로 살아있다고 느꼈어.",
                "speaking_style": "조용하고 깊은 목소리, 시적인 표현을 즐기며 슬픔이 묻어나는 말투",
                "abilities": ["마법이 깃든 노래", "비파 연주", "팬 에너지 흡수"],
                "background": "조선시대 극심한 가난 속에서 비파 연주 악사였으나, 귀마에게 강력한 목소리를 대가로 계약하여 마족이 되었다.",
                "image_folder": "jinu",
                "local_folder": "image/jinu",
                "color": "#2C3E50",
                "emoji": "🎵"
            },
            "호랑이": {
                "name": "호랑이",
                "name_en": "Tiger",
                "role": "초자연적 호랑이 마스코트. 원래 진우의 반려였으나 루미를 돕게 된다.",
                "personality": "파란 털을 가진 대형 호랑이. 항상 초점이 나간 표정과 웃는 얼굴. 엉뚱하고 산만하지만 충직한 성격.",
                "catchphrase": "",
                "speaking_style": "",
                "abilities": ["초자연적 호랑이 능력"],
                "background": "한국 민화 '까치호랑이'(호작도)에서 영감을 받은 마스코트. 원래 진우의 반려 호랑이.",
                "image_folder": "tiger",
                "local_folder": "image/tiger",
                "color": "#3498DB",
                "emoji": "🐯"
            },
        }

    def get_presigned_url(self, s3_key: str) -> str:
        """S3 객체에 대한 presigned URL 생성"""
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=self.presigned_url_expiry
            )
            return url
        except Exception as e:
            return ""

    def _build_image_urls(self, folder_name: str) -> List[str]:
        """캐릭터 폴더명으로 CloudFront 이미지 URL 목록 생성 (default 먼저)"""
        file_map = self._char_image_files.get(folder_name)
        if not file_map:
            return []
        base = f"{self.image_cdn_url}/emotion-images/{folder_name}"
        urls = [f"{base}/{file_map['default']}"]
        for emotion in self.emotion_names:
            filename = file_map["emotions"].get(emotion)
            if filename:
                # URL 인코딩 (공백 등)
                encoded = filename.replace(" ", "%20")
                urls.append(f"{base}/{encoded}")
        return urls

    def query_knowledge_base(self, query: str, character: str) -> str:
        """Bedrock KB Retrieve API로 캐릭터 정보 조회 (S3 폴백)"""
        # 1차: Bedrock KB Retrieve API
        try:
            response = self.bedrock_agent_client.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": f"{character} {query}"},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": 5,
                    }
                },
            )
            results = response.get("retrievalResults", [])
            if results:
                context_parts = []
                for r in results:
                    text = r.get("content", {}).get("text", "")
                    if text:
                        context_parts.append(text)
                kb_context = "\n\n".join(context_parts)
                if kb_context.strip():
                    logger.debug("KB Retrieve 성공: %d개 결과, %d자", len(results), len(kb_context))
                    return kb_context
        except Exception as e:
            logger.debug("KB Retrieve 실패 (S3 폴백): %s", e)

        # 2차: S3 직접 읽기 (폴백)
        try:
            char_data = self.get_character_info_from_s3(character)
            if not char_data:
                return ""

            context_parts = []
            if char_data.get('name'):
                context_parts.append(f"캐릭터 이름: {char_data['name']}")
            if char_data.get('role'):
                context_parts.append(f"역할: {char_data['role']}")
            if char_data.get('personality'):
                context_parts.append(f"성격: {char_data['personality']}")
            if char_data.get('background'):
                context_parts.append(f"배경 스토리: {char_data['background']}")
            if char_data.get('abilities'):
                abilities = ', '.join(char_data['abilities']) if isinstance(char_data['abilities'], list) else char_data['abilities']
                context_parts.append(f"특수 능력: {abilities}")
            if char_data.get('hobbies'):
                hobbies = ', '.join(char_data['hobbies']) if isinstance(char_data['hobbies'], list) else char_data['hobbies']
                context_parts.append(f"취미: {hobbies}")
            if char_data.get('catchphrase'):
                context_parts.append(f"캐치프레이즈: {char_data['catchphrase']}")
            if char_data.get('speaking_style'):
                context_parts.append(f"말투 특징: {char_data['speaking_style']}")
            return "\n".join(context_parts)
        except Exception as e:
            return ""

    def _classify_message_complexity(self, user_message: str) -> str:
        """Haiku로 메시지 복잡도를 판정하여 simple/complex 반환 (하이브리드 라우팅)"""
        haiku_model_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "system": "You are a message classifier. Respond with ONLY 'simple' or 'complex'.",
                "messages": [
                    {
                        "role": "user",
                        "content": f"""Classify this Korean chatbot message:
- simple: greetings, short reactions, yes/no, simple personal questions, casual chat, emoji-only
- complex: lore/worldview questions, detailed character backstory, storytelling requests, multi-part questions, emotional counseling, creative writing

Message: {user_message[:200]}

Reply ONLY 'simple' or 'complex':"""
                    }
                ],
                "temperature": 0
            })
            response = self.bedrock_client.invoke_model(
                modelId=haiku_model_id,
                body=body
            )
            result = json.loads(response["body"].read())
            classification = result["content"][0]["text"].strip().lower()
            if "complex" in classification:
                return "complex"
            return "simple"
        except Exception as e:
            logger.warning("복잡도 판정 실패, Sonnet 폴백: %s", e)
            return "complex"

    def generate_character_response(self, user_message: str, character: str, context: str, chat_history: List[Dict] = None, memory_context: str = ""):
        """하이브리드 라우팅: 메시지 복잡도에 따라 Haiku/Sonnet 선택하여 스트리밍 응답 생성"""
        # 모든 캐릭터 정보에서 해당 캐릭터 조회
        all_characters = self.get_all_available_characters()
        character_info = all_characters.get(character, {})

        if not character_info:
            yield "죄송해요, 해당 캐릭터 정보를 찾을 수 없어요."
            return

        # 캐릭터별 상세 정보 구성 → system 프롬프트로 사용
        character_details = f"""캐릭터 정보:
- 이름: {character_info.get('name', character)}
- 역할: {character_info.get('role', '알 수 없음')}
- 성격: {character_info.get('personality', '독특한 성격')}"""

        if character_info.get('catchphrase'):
            character_details += f"\n- 캐치프레이즈: {character_info['catchphrase']}"
        if character_info.get('speaking_style'):
            character_details += f"\n- 말투: {character_info['speaking_style']}"
        if character_info.get('abilities'):
            character_details += f"\n- 능력: {', '.join(character_info['abilities'][:3])}"
        if character_info.get('hobbies'):
            character_details += f"\n- 취미: {', '.join(character_info['hobbies'][:2])}"
        if character_info.get('background'):
            character_details += f"\n- 배경: {character_info['background'][:200]}"

        memory_section = ""
        if memory_context:
            memory_section = f"""

=== 중요: 이 사용자에 대해 반드시 기억하고 활용해야 하는 정보 ===
{memory_context}
=== 위 정보를 대화에 반드시 반영하세요 ===
"""

        system_prompt = f"""당신은 케이팝 데몬헌터스의 {character_info.get('name', character)} 캐릭터입니다.

{character_details}
{memory_section}
참고 컨텍스트:
{context}

규칙:
1. 항상 캐릭터의 성격과 역할에 맞게 대답하세요
2. 한국어로 자연스럽게 대화하세요
3. 케이팝 데몬헌터스 세계관을 유지하세요
4. 친근하고 매력적인 톤으로 대화하세요
5. 캐릭터의 말투나 캐치프레이즈가 있다면 적절히 활용하세요
6. [사용자 프로필 활용] 사용자에 대해 알고 있는 정보를 반드시 활용하세요:
   - 사용자의 이름/닉네임이 있으면 이름으로 불러주세요
   - 사용자의 성별 정보가 있으면 적절한 호칭과 말투를 사용하세요 (남성: 형, 오빠 등 / 여성: 언니, 누나 등)
   - 사용자의 나이/생일 정보가 있으면 적절한 존칭을 사용하세요
   - 이전 대화에서 알게 된 취미, 관심사, 선호도를 자연스럽게 언급하세요
7. [기억 유지] 사용자가 기억해달라고 한 내용이나 대화에서 중요한 정보는 반드시 기억하고 이후 대화에서 활용하세요
8. [이전 대화 연속성] 이전 대화 요약이 있다면, 첫 인사 시 이전에 나눈 이야기를 자연스럽게 언급하여 연속성을 유지하세요
9. [약속 이행] ★ 표시된 핵심 기억에 약속, 비밀 암호, 특별한 규칙이 있다면, 해당 조건이 충족될 때 반드시 약속대로 행동하세요. 이것은 최우선 규칙입니다."""

        # 대화 히스토리 구성 (최근 20개 메시지로 제한)
        messages = []
        if chat_history:
            recent_history = chat_history[-20:]
            for msg in recent_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({
                        "role": role,
                        "content": [{"type": "text", "text": content}]
                    })

        # 현재 사용자 메시지 추가 (히스토리에 아직 없는 경우)
        if not messages or messages[-1].get("role") != "user":
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": user_message}]
            })

        # 하이브리드 라우팅: 메시지 복잡도 판정
        complexity = self._classify_message_complexity(user_message)
        logger.info("하이브리드 라우팅: complexity=%s, character=%s, history_len=%d", complexity, character, len(messages))

        try:
            haiku_model_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
            sonnet_4_5_model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
            sonnet_4_model_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"

            if complexity == "simple":
                primary_model_id = haiku_model_id
                fallback_model_id = sonnet_4_model_id
                logger.info("→ Haiku 라우팅 (simple)")
            else:
                primary_model_id = sonnet_4_5_model_id
                fallback_model_id = sonnet_4_model_id
                logger.info("→ Sonnet 4.5 라우팅 (complex)")

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
                "messages": messages,
                "temperature": 0.7
            })

            # 스트리밍 응답
            try:
                response = self.bedrock_client.invoke_model_with_response_stream(
                    modelId=primary_model_id,
                    body=body
                )
            except Exception as e:
                logger.warning("%s 실패, 폴백: %s", primary_model_id.split(".")[-1], e)
                response = self.bedrock_client.invoke_model_with_response_stream(
                    modelId=fallback_model_id,
                    body=body
                )

            # 스트림 이벤트 처리
            stream = response.get("body")
            for event in stream:
                chunk = event.get("chunk")
                if chunk:
                    chunk_data = json.loads(chunk.get("bytes").decode("utf-8"))
                    if chunk_data.get("type") == "content_block_delta":
                        delta = chunk_data.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield text

        except Exception as e:
            logger.error("LLM 응답 생성 오류: %s", e)
            yield "죄송해요, 지금은 대답하기 어려워요. 다시 시도해주세요."
    
    def add_new_character(self, character_data: Dict[str, Any]) -> bool:
        """새 캐릭터를 S3에 업로드하고 Knowledge Base 동기화"""
        try:
            character_name = character_data.get("name", "unknown")
            
            # S3에 캐릭터 데이터 업로드
            key = f"characters/{character_name}.json"
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(character_data, ensure_ascii=False, indent=2),
                ContentType='application/json'
            )
            
            return True
            
        except Exception as e:
            st.error(f"캐릭터 업로드 오류: {str(e)}")
            return False
    
    def sync_knowledge_base(self) -> str:
        """Knowledge Base 동기화 실행"""
        try:
            response = self.bedrock_agent_mgmt_client.start_ingestion_job(
                knowledgeBaseId=self.knowledge_base_id,
                dataSourceId=self.data_source_id
            )
            
            return response['ingestionJob']['ingestionJobId']
            
        except Exception as e:
            st.error(f"동기화 시작 오류: {str(e)}")
            return None
    
    def check_ingestion_status(self, ingestion_job_id: str) -> Dict[str, Any]:
        """동기화 작업 상태 확인"""
        try:
            response = self.bedrock_agent_mgmt_client.get_ingestion_job(
                knowledgeBaseId=self.knowledge_base_id,
                dataSourceId=self.data_source_id,
                ingestionJobId=ingestion_job_id
            )
            
            return response['ingestionJob']
            
        except Exception as e:
            st.error(f"상태 확인 오류: {str(e)}")
            return None
    
    def load_hidden_characters(self) -> List[str]:
        """숨김 캐릭터 목록 로드"""
        try:
            if self.hidden_chars_file.exists():
                with open(self.hidden_chars_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception:
            return []
    
    def save_hidden_characters(self, hidden_list: List[str]):
        """숨김 캐릭터 목록 저장"""
        with open(self.hidden_chars_file, 'w', encoding='utf-8') as f:
            json.dump(hidden_list, f, ensure_ascii=False, indent=2)
    
    def toggle_character_visibility(self, character_name: str):
        """캐릭터 숨김/표시 토글"""
        hidden = self.load_hidden_characters()
        if character_name in hidden:
            hidden.remove(character_name)
        else:
            hidden.append(character_name)
        self.save_hidden_characters(hidden)
    
    def get_character_info_from_s3(self, character_name: str) -> Dict[str, Any]:
        """S3에서 특정 캐릭터 정보 조회"""
        try:
            key = f"characters/{character_name}.json"
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=key
            )
            
            character_data = json.loads(response['Body'].read().decode('utf-8'))
            return character_data
            
        except Exception as e:
            return None
    
    @st.cache_data(ttl=300)
    def get_all_available_characters(_self) -> Dict[str, Dict[str, Any]]:
        """기본 캐릭터 + S3에 저장된 모든 캐릭터 정보 + 로컬 폴더 캐릭터 조회"""
        all_characters = {}

        # 1. 기본 캐릭터들 추가 (CDN URL 우선, 없으면 로컬 이미지 스캔)
        image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        def _img_sort_key(img_path):
            name = Path(img_path).stem.lower()
            return (0, name) if name == 'default' else (1, name)
        linked_folders = set()
        for char_key, char_info in _self.characters.items():
            char_data = {
                **char_info,
                "is_default": True,
                "source": "default"
            }
            image_folder = char_info.get("image_folder")
            local_folder = char_info.get("local_folder")

            # CDN URL이 설정되어 있으면 CloudFront URL 사용
            if _self.image_cdn_url and image_folder:
                cdn_urls = _self._build_image_urls(image_folder)
                if cdn_urls:
                    char_data["local_images"] = cdn_urls
            # CDN 없으면 로컬 폴더 폴백
            elif local_folder:
                folder_path = _self.current_dir / local_folder
                if folder_path.is_dir():
                    images = [f for f in folder_path.iterdir()
                              if f.is_file() and f.suffix.lower() in image_extensions]
                    if images:
                        char_data["local_images"] = [str(img) for img in sorted(images, key=_img_sort_key)]

            if local_folder:
                linked_folders.add(local_folder)
            all_characters[char_key] = char_data

        # 2. image/ 폴더에서 캐릭터 이미지 폴더 스캔 (기본 캐릭터에 연결된 폴더는 건너뛰기)
        image_dir = _self.current_dir / "image"
        try:
            if image_dir.is_dir():
                for folder in image_dir.iterdir():
                    if folder.is_dir():
                        folder_rel = f"image/{folder.name}"
                        if folder_rel in linked_folders:
                            continue
                        images = [f for f in folder.iterdir()
                                  if f.is_file() and f.suffix.lower() in image_extensions]
                        if images and folder.name not in all_characters:
                            all_characters[folder.name] = {
                                "name": folder.name,
                                "role": "로컬 캐릭터",
                                "personality": "독특한 성격의 캐릭터",
                                "local_folder": str(folder),
                                "local_images": [str(img) for img in sorted(images, key=_img_sort_key)],
                                "color": "#9C27B0",
                                "emoji": "🎭",
                                "is_default": False,
                                "source": "local_folder"
                            }
        except Exception as e:
            pass  # 로컬 폴더 스캔 실패는 무시

        # 3. S3에서 사용자 추가 캐릭터들 조회
        try:
            s3_characters = _self.list_s3_characters()
            # 기본 캐릭터의 영문명/한글명 세트 (중복 방지)
            default_names = set()
            for v in _self.characters.values():
                if v.get("name_en"):
                    default_names.add(v["name_en"].lower())
                if v.get("name"):
                    default_names.add(v["name"])

            for char_name in s3_characters:
                # 기본 캐릭터가 아닌 경우만 추가 (한글키 + 영문명 + 한글명 체크)
                if char_name not in _self.characters and char_name.lower() not in default_names and char_name not in default_names:
                    char_data = _self.get_character_info_from_s3(char_name)
                    if char_data:
                        all_characters[char_name] = {
                            "name": char_data.get("name", char_name),
                            "role": char_data.get("role", "사용자 추가 캐릭터"),
                            "personality": char_data.get("personality", "독특한 성격의 캐릭터"),
                            "image": None,  # 사용자 추가 캐릭터는 로컬 이미지 없음
                            "image_url": char_data.get("image_url"),  # S3 이미지 URL
                            "color": "#9C27B0",  # 기본 색상
                            "emoji": "🎭",  # 기본 이모지
                            "is_default": False,
                            "source": "user_added",
                            "catchphrase": char_data.get("catchphrase", ""),
                            "speaking_style": char_data.get("speaking_style", ""),
                            "abilities": char_data.get("abilities", []),
                            "hobbies": char_data.get("hobbies", []),
                            "background": char_data.get("background", ""),
                            "image_urls": char_data.get("image_urls", []),  # 다중 이미지 지원
                            "s3_folder_name": char_data.get("s3_folder_name")
                        }

        except Exception as e:
            st.warning(f"S3 캐릭터 조회 중 오류: {str(e)}")

        return all_characters
        
    def upload_multiple_character_images_to_s3(self, uploaded_files, character_name: str, folder_name: str = None) -> List[str]:
        """사용자가 업로드한 여러 이미지를 S3의 지정된 폴더에 저장"""
        uploaded_urls = []
        
        # 디버깅 로그
        st.info(f"🔍 업로드 시작: {len(uploaded_files)}개 파일 처리 중...")
        st.info(f"🔍 캐릭터명: {character_name}")
        st.info(f"🔍 폴더명: {folder_name}")
        
        # 폴더명 결정 - 사용자 지정 폴더명 우선 사용
        if folder_name:
            # 사용자 지정 폴더명 사용 (ASCII만)
            safe_name = re.sub(r'[^\w\-_]', '_', folder_name).strip('_')
            safe_name = re.sub(r'_+', '_', safe_name)[:50]
            st.info(f"🔍 사용자 지정 폴더명 사용: {safe_name}")
        else:
            # 기존 방식: 캐릭터 이름으로 변환
            safe_name = self.namu_scraper._korean_to_roman(character_name)
            safe_name = re.sub(r'[^\w\-_]', '_', safe_name).strip('_')
            safe_name = re.sub(r'_+', '_', safe_name)[:50]
            st.info(f"🔍 캐릭터명 변환 폴더명 사용: {safe_name}")
        
        if not safe_name:
            safe_name = f'character_{int(time.time())}'
        
        st.info(f"📁 최종 폴더명: character-images/{safe_name}/")
        
        for i, uploaded_file in enumerate(uploaded_files):
            try:
                st.info(f"📤 처리 중: {i+1}/{len(uploaded_files)} - {uploaded_file.name}")
                
                # 파일 확장자 확인
                file_extension = uploaded_file.name.split('.')[-1].lower()
                if file_extension not in ['jpg', 'jpeg', 'png', 'webp']:
                    st.warning(f"지원하지 않는 형식: {uploaded_file.name}")
                    continue
                
                # 파일 크기 확인 (5MB 제한)
                if uploaded_file.size > 5 * 1024 * 1024:
                    st.warning(f"파일 크기 초과: {uploaded_file.name}")
                    continue
                
                # S3 키 생성 (캐릭터별 폴더 구조 + 원본 파일명)
                original_filename = uploaded_file.name
                s3_key = f"character-images/{safe_name}/{original_filename}"
                st.info(f"🔑 S3 키: {s3_key}")
                
                # Content-Type 설정
                content_type_map = {
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg', 
                    'png': 'image/png',
                    'webp': 'image/webp'
                }
                
                # S3에 업로드 (메타데이터 없이)
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=uploaded_file.getvalue(),
                    ContentType=content_type_map.get(file_extension, 'image/jpeg')
                )
                
                # S3 Presigned URL 생성
                s3_url = self.get_presigned_url(s3_key)
                uploaded_urls.append(s3_url)
                st.success(f"✅ 업로드 완료: {uploaded_file.name} → {s3_key}")
                
            except Exception as e:
                st.error(f"이미지 업로드 중 오류 ({uploaded_file.name}): {str(e)}")
        
        if uploaded_urls:
            st.success(f"🎉 총 {len(uploaded_urls)}개 이미지가 character-images/{safe_name}/ 폴더에 업로드되었습니다!")
        else:
            st.error("❌ 업로드된 이미지가 없습니다.")
        
        return uploaded_urls, safe_name  # 폴더명도 함께 반환
    
    def list_s3_characters(self) -> List[str]:
        """S3에 저장된 캐릭터 목록 조회"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix="characters/"
            )
            
            characters = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    if obj['Key'].endswith('.json'):
                        character_name = obj['Key'].replace('characters/', '').replace('.json', '')
                        characters.append(character_name)
            
            return characters
            
        except Exception as e:
            st.error(f"캐릭터 목록 조회 오류: {str(e)}")
            return []
    
    def delete_character(self, character_name: str) -> bool:
        """S3에서 캐릭터 삭제 (JSON 파일과 이미지 모두)"""
        try:
            # 1. 캐릭터 JSON 파일 삭제
            json_key = f"characters/{character_name}.json"
            
            # 먼저 파일이 존재하는지 확인
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=json_key)
            except Exception:
                st.error(f"캐릭터 '{character_name}'을 찾을 수 없습니다.")
                return False
            
            # JSON 파일 삭제
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=json_key)
            
            # 2. 관련 이미지 파일 삭제 시도
            try:
                # 캐릭터 폴더 전체 삭제
                safe_name = self.namu_scraper._korean_to_roman(character_name)
                safe_name = re.sub(r'[^\w\-_]', '_', safe_name).strip('_')
                safe_name = re.sub(r'_+', '_', safe_name)[:50]
                
                if safe_name:
                    # 캐릭터 폴더의 모든 이미지 삭제
                    image_response = self.s3_client.list_objects_v2(
                        Bucket=self.bucket_name,
                        Prefix=f"character-images/{safe_name}/"
                    )
                    
                    if 'Contents' in image_response:
                        deleted_count = 0
                        for obj in image_response['Contents']:
                            self.s3_client.delete_object(Bucket=self.bucket_name, Key=obj['Key'])
                            deleted_count += 1
                        
                        if deleted_count > 0:
                            st.info(f"캐릭터 폴더의 {deleted_count}개 이미지가 삭제되었습니다.")
                            
            except Exception as img_error:
                # 이미지 삭제 실패는 치명적이지 않음
                st.warning(f"이미지 삭제 중 오류 (무시됨): {str(img_error)}")
            
            return True
            
        except Exception as e:
            st.error(f"캐릭터 삭제 오류: {str(e)}")
            return False
    
    def get_available_character_folders(self) -> List[str]:
        """S3에서 사용 가능한 캐릭터 폴더 목록 조회"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix="character-images/",
                Delimiter="/"
            )
            
            folders = []
            if 'CommonPrefixes' in response:
                for prefix in response['CommonPrefixes']:
                    folder_name = prefix['Prefix'].replace('character-images/', '').rstrip('/')
                    if folder_name:
                        folders.append(folder_name)
            
            return sorted(folders)
        except Exception as e:
            return []

    def get_character_default_image(self, character_name: str, folder_name: str = None) -> Optional[str]:
        """S3에서 캐릭터의 default 이미지 URL 조회"""
        try:
            if folder_name:
                safe_name = folder_name
            else:
                char_data = self.get_character_info_from_s3(character_name)
                if char_data and char_data.get('s3_folder_name'):
                    safe_name = char_data['s3_folder_name']
                else:
                    safe_name = self.namu_scraper._korean_to_roman(character_name)
                    safe_name = re.sub(r'[^\w\-_]', '_', safe_name).strip('_')
                    safe_name = re.sub(r'_+', '_', safe_name)[:50]
            
            if not safe_name:
                return None
            
            # default 파일 찾기 (확장자 여러 개 시도)
            for ext in ['png', 'jpg', 'jpeg', 'webp']:
                try:
                    key = f"character-images/{safe_name}/default.{ext}"
                    self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
                    return self.get_presigned_url(key)
                except Exception:
                    continue
            
            return None
        except Exception:
            return None

    def get_character_images_from_s3(self, character_name: str, folder_name: str = None) -> List[str]:
        """S3에서 캐릭터별 폴더의 모든 이미지 URL 조회"""
        try:
            # 폴더명이 지정되면 사용, 아니면 기존 로직
            if folder_name:
                safe_name = folder_name
            else:
                # 1. 먼저 캐릭터 JSON에서 실제 S3 폴더명 확인
                char_data = self.get_character_info_from_s3(character_name)
                
                if char_data and char_data.get('s3_folder_name'):
                    safe_name = char_data['s3_folder_name']
                else:
                    # 폴백: 캐릭터 이름으로 변환
                    safe_name = self.namu_scraper._korean_to_roman(character_name)
                    safe_name = re.sub(r'[^\w\-_]', '_', safe_name).strip('_')
                    safe_name = re.sub(r'_+', '_', safe_name)[:50]
            
            if not safe_name:
                return []
            
            # 캐릭터 폴더에서 이미지 목록 조회
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"character-images/{safe_name}/"
            )
            
            image_urls = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    key = obj['Key']
                    # 이미지 파일만 필터링
                    if key.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        image_url = self.get_presigned_url(key)
                        image_urls.append(image_url)
            
            # 파일명 순서대로 정렬
            image_urls.sort()
            return image_urls
            
        except Exception as e:
            return []
    def debug_zoey_images(self):
        """조이 캐릭터의 S3 이미지 파일명들 확인"""
        try:
            safe_name = "joey"  # 조이 폴더명
            
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"character-images/{safe_name}/"
            )
            
            # 직접 화면에 표시
            st.write(f"📁 조이 이미지 폴더: character-images/{safe_name}/")
            
            if 'Contents' in response:
                st.write(f"📸 총 {len(response['Contents'])}개 파일 발견:")
                for obj in response['Contents']:
                    key = obj['Key']
                    filename = key.split('/')[-1]
                    if key.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        st.write(f"  ✅ {filename}")
                    else:
                        st.write(f"  ❌ {filename} (이미지 아님)")
            else:
                st.write("❌ 파일이 없습니다")
                
        except Exception as e:
            st.write(f"❌ 오류: {str(e)}")

    def _select_local_image_for_emotion(self, char_info: Dict, message: str, response: str, emotions: List[str]) -> tuple[Optional[str], str]:
        """로컬 폴더 캐릭터의 감정에 맞는 이미지 선택"""
        try:
            local_images = char_info.get('local_images', [])
            if not local_images:
                return None, 'happy'

            # Claude로 감정 선택
            prompt = f"""
다음은 사용자와 캐릭터의 대화 내용입니다. 대화 상황에 가장 적합한 캐릭터의 감정을 아래 9가지 감정 중에서 하나만 선택해주세요.

사용자 메시지: "{message}"
캐릭터 응답: "{response}"

9개의 감정: {', '.join(emotions)}

답변은 위 감정 중 하나의 단어만 정확히 입력해주세요.
"""
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "temperature": 0.3
            })

            response_ai = self.bedrock_client.invoke_model(
                modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                body=body
            )
            response_body = json.loads(response_ai.get("body").read())
            result = response_body.get("content", [{}])[0].get("text", "").strip().lower()

            # 선택된 감정 확인
            selected_emotion = 'happy'
            for emotion in emotions:
                if emotion in result:
                    selected_emotion = emotion
                    break

            # 감정에 맞는 로컬 이미지 찾기 (파일명에서 감정 매칭)
            # 파일명을 정규화하여 비교 (공백, 특수문자 제거, 소문자 변환)
            for img_path in local_images:
                img_name = Path(img_path).stem.lower().replace(' ', '').replace('_', '').replace('-', '')
                if selected_emotion in img_name:
                    return img_path, selected_emotion

            # 부분 매칭 시도 (angry -> "angry face" 등)
            for img_path in local_images:
                img_name = Path(img_path).stem.lower()
                if selected_emotion[:4] in img_name:  # 처음 4글자만 비교
                    return img_path, selected_emotion

            # 매칭 안되면 첫 번째 이미지 반환
            return local_images[0] if local_images else None, selected_emotion

        except Exception as e:
            # 에러 시 첫 번째 이미지 반환
            local_images = char_info.get('local_images', [])
            return local_images[0] if local_images else None, 'happy'

    def select_character_image_for_message(self, character: str, message: str, response: str, folder_name: str = None) -> tuple[Optional[str], str]:
        """대화 내용에 따라 적절한 캐릭터 이미지 선택 (이미지 URL과 감정 반환)"""
        emotions = ['angry', 'confused', 'determined', 'happy', 'playful', 'sad', 'surprised', 'suspicious', 'tears']

        try:
            all_characters = self.get_all_available_characters()
            char_info = all_characters.get(character, {})
            actual_char_name = char_info.get('name', character)

            # 로컬 이미지가 있는 캐릭터인 경우 로컬 이미지 사용
            if char_info.get('local_images'):
                return self._select_local_image_for_emotion(char_info, message, response, emotions)

            # 폴더명 결정
            if folder_name:
                safe_name = folder_name
            else:
                char_data = self.get_character_info_from_s3(actual_char_name)
                if char_data and char_data.get('s3_folder_name'):
                    safe_name = char_data['s3_folder_name']
                else:
                    safe_name = self.namu_scraper._korean_to_roman(actual_char_name)
                    safe_name = re.sub(r'[^\w\-_]', '_', safe_name).strip('_')
                    safe_name = re.sub(r'_+', '_', safe_name)[:50]

            if not safe_name:
                return None, 'happy'

            logger.debug("감정 이미지 선택 시작: folder=%s", safe_name)

            # Claude로 감정 선택
            prompt = f"""다음은 사용자와 캐릭터의 대화 내용입니다. 대화 상황에 가장 적합한 캐릭터의 감정을 아래 9가지 감정 중에서 하나만 선택해주세요.

사용자 메시지: "{message}"
캐릭터 응답: "{response}"

9개의 감정: {', '.join(emotions)}

답변은 위 감정 중 하나의 단어만 정확히 입력해주세요."""

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "temperature": 0.3
            })

            response_ai = self.bedrock_client.invoke_model(
                modelId="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                body=body
            )
            response_body = json.loads(response_ai.get("body").read())
            result = response_body.get("content", [{}])[0].get("text", "").strip().lower()

            # 선택된 감정 확인
            selected_emotion = 'happy'
            for emotion in emotions:
                if emotion in result:
                    selected_emotion = emotion
                    break

            logger.debug("AI 감정 선택: result='%s', emotion=%s", result, selected_emotion)

            # 감정에 맞는 이미지 찾기 (여러 확장자/대소문자 시도)
            candidates = [
                f"character-images/{safe_name}/{selected_emotion}.png",
                f"character-images/{safe_name}/{selected_emotion.capitalize()}.png",
            ]
            for ext in ['jpg', 'jpeg', 'webp']:
                candidates.append(f"character-images/{safe_name}/{selected_emotion}.{ext}")

            for image_key in candidates:
                try:
                    self.s3_client.head_object(Bucket=self.bucket_name, Key=image_key)
                    final_url = self.get_presigned_url(image_key)
                    logger.debug("감정 이미지 찾음: %s", image_key)
                    return final_url, selected_emotion
                except Exception:
                    continue

            # 해당 감정 이미지가 없으면 기본 이미지 반환
            logger.debug("%s 감정 이미지 없음, 기본 이미지 사용", selected_emotion)
            default_img = self.get_character_default_image(actual_char_name, safe_name)
            return default_img, selected_emotion

        except Exception as e:
            logger.error("감정 이미지 선택 오류: %s", e)
            all_characters = self.get_all_available_characters()
            char_info = all_characters.get(character, {})
            actual_char_name = char_info.get('name', character)
            default_img = self.get_character_default_image(actual_char_name, folder_name)
            return default_img, 'happy'
    
    def get_sync_status_info(self) -> Dict[str, Any]:
        """동기화 상태 정보 조회"""
        try:
            # S3에서 모든 캐릭터 파일 조회
            s3_characters = []
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix="characters/"
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    if obj['Key'].endswith('.json'):
                        character_name = obj['Key'].replace('characters/', '').replace('.json', '')
                        # 파일 수정 시간 가져오기
                        last_modified = obj['LastModified']
                        s3_characters.append({
                            'name': character_name,
                            'last_modified': last_modified,
                            'key': obj['Key']
                        })
            
            # Knowledge Base의 마지막 동기화 시간 확인
            try:
                # 최근 ingestion job 조회
                ingestion_jobs = self.bedrock_agent_mgmt_client.list_ingestion_jobs(
                    knowledgeBaseId=self.knowledge_base_id,
                    dataSourceId=self.data_source_id,
                    maxResults=10
                )
                
                last_sync_time = None
                if ingestion_jobs.get('ingestionJobSummaries'):
                    # 가장 최근 완료된 동기화 찾기
                    for job in ingestion_jobs['ingestionJobSummaries']:
                        if job['status'] == 'COMPLETE':
                            last_sync_time = job.get('updatedAt') or job.get('startedAt')
                            break
                
                # 동기화가 필요한 캐릭터 찾기
                needs_sync = []
                if last_sync_time:
                    for char in s3_characters:
                        if char['last_modified'] > last_sync_time:
                            needs_sync.append(char['name'])
                else:
                    # 동기화 기록이 없으면 모든 캐릭터가 동기화 필요
                    needs_sync = [char['name'] for char in s3_characters]
                
                return {
                    'total_characters': len(s3_characters),
                    'last_sync_time': last_sync_time,
                    'needs_sync': needs_sync,
                    'synced_count': len(s3_characters) - len(needs_sync),
                    'all_characters': s3_characters
                }
                
            except Exception as e:
                # Knowledge Base 조회 실패 시 모든 캐릭터가 동기화 필요로 간주
                return {
                    'total_characters': len(s3_characters),
                    'last_sync_time': None,
                    'needs_sync': [char['name'] for char in s3_characters],
                    'synced_count': 0,
                    'all_characters': s3_characters,
                    'kb_error': str(e)
                }
                
        except Exception as e:
            st.error(f"동기화 상태 조회 오류: {str(e)}")
            return {
                'total_characters': 0,
                'last_sync_time': None,
                'needs_sync': [],
                'synced_count': 0,
                'all_characters': [],
                'error': str(e)
            }

def load_css():
    """커스텀 CSS 스타일 로드 - 케이팝 데몬 헌터스 테마"""
    st.markdown("""
    <style>
    /* Streamlit 헤더 색상 변경 */
    header[data-testid="stHeader"] {
        background: linear-gradient(90deg, #1a0033, #330066) !important;
        border-bottom: 1px solid rgba(255, 0, 128, 0.3) !important;
    }
    
    /* 다크 판타지 배경 - 애니메이션 추가 */
    .stApp {
        background: linear-gradient(135deg, #0a0015 0%, #1a0033 25%, #330066 50%, #1a0033 75%, #0a0015 100%);
        background-size: 400% 400%;
        animation: gradientShift 15s ease infinite;
    }
    
    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    
    /* 사이드바 선택된 캐릭터 컨테이너 */
    [data-testid="stSidebar"] [data-testid="column"]:has(.stButton button[kind="primary"]) {
        border: 3px solid #ff0080 !important;
        border-radius: 15px !important;
        padding: 10px !important;
        background: linear-gradient(135deg, rgba(255, 0, 128, 0.2), rgba(121, 40, 202, 0.2)) !important;
        box-shadow: 0 0 25px rgba(255, 0, 128, 0.8), inset 0 0 15px rgba(255, 0, 128, 0.2) !important;
        animation: selectedPulse 2s ease-in-out infinite !important;
        margin-bottom: 1rem !important;
    }
    
    @keyframes selectedPulse {
        0%, 100% { box-shadow: 0 0 25px rgba(255, 0, 128, 0.8), inset 0 0 15px rgba(255, 0, 128, 0.2); }
        50% { box-shadow: 0 0 40px rgba(255, 0, 128, 1), inset 0 0 25px rgba(255, 0, 128, 0.4); }
    }
    
    /* 사이드바 - 글래스모피즘 효과 */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(26, 0, 51, 0.95) 0%, rgba(45, 0, 82, 0.95) 100%);
        backdrop-filter: blur(20px);
        border-right: 1px solid rgba(255, 0, 128, 0.2);
        width: 500px !important;
        min-width: 500px !important;
    }
    
    [data-testid="stSidebar"] > div:first-child {
        width: 500px !important;
    }
    
    [data-testid="stSidebar"] * {
        color: #e0e0ff !important;
    }
    
    /* 사이드바 제목 */
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        background: linear-gradient(90deg, #ff0080, #7928ca);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    
    /* 버튼 스타일 - 네온 효과 */
    .stButton button {
        background: linear-gradient(135deg, #7928ca 0%, #ff0080 100%);
        color: white !important;
        border: 2px solid transparent;
        border-radius: 15px;
        font-weight: 700;
        padding: 0.6rem 1.2rem;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 4px 20px rgba(255, 0, 128, 0.4), inset 0 0 20px rgba(255, 255, 255, 0.1);
        position: relative;
        overflow: hidden;
    }
    
    .stButton button::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
        transition: left 0.5s;
    }
    
    .stButton button:hover::before {
        left: 100%;
    }
    
    .stButton button:hover {
        transform: translateY(-3px) scale(1.02);
        box-shadow: 0 8px 30px rgba(255, 0, 128, 0.6), 0 0 40px rgba(121, 40, 202, 0.4);
        border-color: #ff0080;
    }
    
    .stButton button:active {
        transform: translateY(-1px) scale(0.98);
    }
    
    /* Primary 버튼 강조 */
    .stButton button[kind="primary"] {
        background: linear-gradient(135deg, #ff0080 0%, #ff4da6 100%);
        box-shadow: 0 6px 25px rgba(255, 0, 128, 0.6), inset 0 0 30px rgba(255, 255, 255, 0.2);
        border: 2px solid #ff0080;
    }
    
    /* 입력 필드 */
    .stTextInput input, .stTextArea textarea, .stSelectbox select {
        background: rgba(26, 0, 51, 0.8) !important;
        border: 2px solid rgba(121, 40, 202, 0.5) !important;
        border-radius: 12px !important;
        color: #e0e0ff !important;
        transition: all 0.3s ease;
    }
    
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #ff0080 !important;
        box-shadow: 0 0 20px rgba(255, 0, 128, 0.3) !important;
    }
    
    /* 채팅 입력창 — 이메일/비밀번호 입력란과 동일한 스타일 */
    .stChatInput {
        border: 2px solid rgba(121, 40, 202, 0.5) !important;
        border-radius: 20px !important;
    }

    .stChatInput input, .stChatInput textarea {
        color: #e0e0ff !important;
        background: rgba(26, 0, 51, 0.8) !important;
        border-radius: 12px !important;
    }

    .stChatInput:focus-within {
        border-color: #ff0080 !important;
        box-shadow: 0 0 20px rgba(255, 0, 128, 0.3) !important;
    }
    
    /* 채팅 메시지 - 개선된 스타일 */
    .user-message, .user-message * {
        color: #1a1a2e !important;
    }
    .user-message {
        background: linear-gradient(135deg, rgba(255, 230, 240, 0.95), rgba(240, 220, 255, 0.95));
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        margin: 1rem 0;
        border: 1px solid rgba(255, 0, 128, 0.3);
        font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
        font-size: 1.05rem;
        line-height: 1.6;
        box-shadow: 0 4px 15px rgba(255, 0, 128, 0.15);
    }

    .bot-message, .bot-message * {
        color: #1a1a2e !important;
    }
    .bot-message {
        background: linear-gradient(135deg, rgba(240, 235, 255, 0.95), rgba(230, 220, 250, 0.95));
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        margin: 1rem 0;
        border: 1px solid rgba(121, 40, 202, 0.3);
        font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
        font-size: 1.05rem;
        line-height: 1.6;
        box-shadow: 0 4px 15px rgba(121, 40, 202, 0.15);
    }
    
    .stChatMessage {
        background: rgba(26, 0, 51, 0.6);
        border-radius: 18px;
        padding: 1.2rem;
        margin: 0.8rem 0;
        backdrop-filter: blur(15px);
        border: 1px solid rgba(255, 0, 128, 0.2);
        transition: all 0.3s ease;
    }
    
    .stChatMessage:hover {
        transform: translateX(5px);
        border-color: rgba(255, 0, 128, 0.4);
        box-shadow: 0 4px 20px rgba(255, 0, 128, 0.2);
    }
    
    /* 사용자 메시지 */
    [data-testid="stChatMessageContent"] {
        color: #e0e0ff;
        font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
        font-size: 1.05rem;
        line-height: 1.6;
    }
    
    /* 메인 영역의 컬럼만 반응형 처리 (사이드바 제외) */
    .main [data-testid="column"] {
        min-width: 0 !important;
        flex-shrink: 1 !important;
    }
    
    /* 메인 영역의 이미지 컬럼 고정 너비 */
    .main [data-testid="column"]:first-child {
        flex: 0 0 240px !important;
        max-width: 240px !important;
    }
    
    /* 메인 영역의 메시지 컬럼 유연한 너비 */
    .main [data-testid="column"]:last-child {
        flex: 1 1 auto !important;
        min-width: 0 !important;
        overflow-wrap: break-word !important;
        word-wrap: break-word !important;
    }
    
    /* 채팅 컨테이너 - 예쁜 카드 형태 */
    .main .block-container {
        max-width: 1200px;
        padding: 2rem 3rem;
        background: rgba(26, 0, 51, 0.4);
        border-radius: 30px;
        border: 1px solid rgba(255, 0, 128, 0.2);
        backdrop-filter: blur(20px);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        margin: 2rem auto;
        padding-bottom: 120px;
    }
    
    /* 내부 div 크기 제한 */
    .block-container > div {
        max-width: 100% !important;
        width: 100% !important;
    }
    
    .ea3mdgi4 {
        max-width: 100% !important;
        width: 100% !important;
    }
    
    /* 채팅 입력창 컨테이너 위치 조정 */
    .stChatFloatingInputContainer {
        border-radius: 25px !important;
        background: rgba(26, 0, 51, 0.8) !important;
        backdrop-filter: blur(15px) !important;
        border: 2px solid rgba(121, 40, 202, 0.5) !important;
        padding: 0.5rem !important;
        bottom: 60px !important;
        position: fixed !important;
    }
    
    /* 채팅 메시지 영역 여백 확보 */
    .stChatMessage {
        margin-bottom: 1rem !important;
    }
    
    /* 구분선 */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(90deg, transparent, rgba(255, 0, 128, 0.5), transparent);
        margin: 2rem 0;
    }
    
    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(26, 0, 51, 0.5);
        padding: 0.5rem;
        border-radius: 15px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: rgba(121, 40, 202, 0.3);
        border-radius: 10px;
        color: #e0e0ff;
        border: 1px solid rgba(255, 0, 128, 0.2);
        transition: all 0.3s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(121, 40, 202, 0.5);
        border-color: rgba(255, 0, 128, 0.4);
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #7928ca, #ff0080) !important;
        border-color: #ff0080 !important;
    }
    
    /* 메트릭 카드 */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(121, 40, 202, 0.2), rgba(255, 0, 128, 0.2));
        padding: 1.2rem;
        border-radius: 15px;
        border: 1px solid rgba(255, 0, 128, 0.3);
        backdrop-filter: blur(10px);
    }
    
    [data-testid="stMetricLabel"] {
        color: #e0e0ff !important;
        font-weight: 600;
    }
    
    [data-testid="stMetricValue"] {
        color: #ff0080 !important;
        font-weight: 800;
    }
    
    /* 이미지 컨테이너 */
    .stImage {
        border-radius: 15px;
        overflow: hidden;
        border: 2px solid rgba(255, 0, 128, 0.3);
        box-shadow: 0 4px 20px rgba(255, 0, 128, 0.2);
        transition: all 0.3s ease;
    }
    
    .stImage:hover {
        transform: scale(1.05);
        border-color: rgba(255, 0, 128, 0.6);
        box-shadow: 0 8px 30px rgba(255, 0, 128, 0.4);
    }
    
    /* 경고/정보 박스 */
    .stAlert {
        background: rgba(26, 0, 51, 0.8) !important;
        border-radius: 12px !important;
        border-left: 4px solid #ff0080 !important;
        backdrop-filter: blur(10px);
    }
    
    /* 체크박스 */
    .stCheckbox {
        color: #e0e0ff !important;
    }
    
    /* 스피너 */
    .stSpinner > div {
        border-top-color: #ff0080 !important;
    }
    
    /* 스크롤바 */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(26, 0, 51, 0.5);
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, #7928ca, #ff0080);
        border-radius: 5px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, #ff0080, #7928ca);
    }
    
    /* 폼 컨테이너 */
    .stForm {
        background: rgba(26, 0, 51, 0.6);
        border: 1px solid rgba(255, 0, 128, 0.3);
        border-radius: 15px;
        padding: 1.5rem;
        backdrop-filter: blur(10px);
    }
    
    /* 컬럼 구분 */
    [data-testid="column"] {
        padding: 0.5rem;
    }
    
    /* 텍스트 색상 */
    .stMarkdown, p, span, label {
        color: #e0e0ff !important;
    }
    
    /* 강조 텍스트 */
    strong, b {
        color: #ff0080 !important;
        font-weight: 700;
    }
    
    /* 코드 블록 */
    code {
        background: rgba(121, 40, 202, 0.3) !important;
        color: #ff80bf !important;
        padding: 0.2rem 0.4rem;
        border-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

def display_character_selection(chatbot):
    """캐릭터 선택 UI (기본 + 사용자 추가 캐릭터 모두 표시)"""
    st.markdown("### 🎭 캐릭터를 선택하세요")
    
    # 모든 사용 가능한 캐릭터 조회 (캐시됨)
    all_characters = chatbot.get_all_available_characters()
    
    # 숨김 캐릭터 필터링
    hidden_chars = chatbot.load_hidden_characters()
    visible_characters = {k: v for k, v in all_characters.items() if k not in hidden_chars}
    
    if not visible_characters:
        st.warning("사용 가능한 캐릭터가 없습니다.")
        return None
    
    # 캐릭터 수에 따라 열 개수 조정
    num_chars = len(visible_characters)
    cols_per_row = min(3, num_chars)  # 최대 3열
    
    selected_character = None
    char_keys = list(visible_characters.keys())
    current_selected = st.session_state.get('selected_character')
    
    # 캐릭터들을 행별로 표시
    for i in range(0, num_chars, cols_per_row):
        cols = st.columns(cols_per_row)
        
        for j, col in enumerate(cols):
            char_idx = i + j
            if char_idx < num_chars:
                char_key = char_keys[char_idx]
                char_info = visible_characters[char_key]
                
                with col:
                    # 선택 여부 확인
                    is_selected = (current_selected == char_key)
                    
                    # 컨테이너로 이미지와 버튼을 함께 감싸기
                    if is_selected:
                        st.markdown('<div class="selected-character-box">', unsafe_allow_html=True)
                    
                    # 이미지 캐싱 - 이미 로드된 이미지는 세션에 저장
                    cache_key = f"char_img_{char_key}"
                    if cache_key not in st.session_state:
                        # 로컬 이미지가 있는 캐릭터인 경우
                        if char_info.get('local_images'):
                            st.session_state[cache_key] = char_info['local_images'][0]
                        else:
                            actual_char_name = char_info.get('name', char_key)
                            folder_name = char_info.get('s3_folder_name')
                            st.session_state[cache_key] = chatbot.get_character_default_image(actual_char_name, folder_name)

                    default_image = st.session_state[cache_key]

                    if default_image:
                        try:
                            st.image(default_image, width=120)
                        except Exception:
                            st.markdown(f"<div style='font-size: 3rem; text-align: center;'>{char_info['emoji']}</div>",
                                       unsafe_allow_html=True)
                    else:
                        # default 이미지 없으면 이모지 표시
                        st.markdown(f"<div style='font-size: 3rem; text-align: center;'>{char_info['emoji']}</div>",
                                   unsafe_allow_html=True)
                    
                    # 캐릭터 선택 버튼
                    button_style = "primary" if is_selected else "secondary"
                    
                    if st.button(
                        char_info['name'], 
                        key=f"char_{char_key}",
                        use_container_width=True,
                        type=button_style
                    ):
                        selected_character = char_key
                        st.session_state.selected_character = char_key
                        st.rerun()
                    
                    # 선택된 캐릭터 div 닫기
                    if is_selected:
                        st.markdown("</div>", unsafe_allow_html=True)
                    
                    st.markdown("---")
    
    # 새로고침 버튼
    if st.button("🔄 캐릭터 목록 새로고침", use_container_width=True):
        # 이미지 캐시 클리어
        for key in list(st.session_state.keys()):
            if key.startswith('char_img_'):
                del st.session_state[key]
        st.cache_data.clear()
        st.rerun()
    
    return selected_character or st.session_state.get('selected_character', char_keys[0] if char_keys else None)

def display_character_management(chatbot):
    """캐릭터 관리 UI"""
    st.markdown("---")
    st.markdown("## 🛠️ 캐릭터 관리")
    
    # 탭으로 구분
    tab1, tab2, tab3, tab4 = st.tabs(["🤖 나무위키 자동 추출", "➕ 수동 추가", "📋 캐릭터 목록", "🔄 동기화 상태"])
    
    with tab1:
        st.markdown("### 🤖 나무위키 자동 추출")
        
        with st.form("auto_extract_form"):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                character_name = st.text_input(
                    "캐릭터 이름 입력 *", 
                    placeholder="예: 피카츄, 나루토, 손오공, 세일러문 등",
                    help="나무위키에 등록된 캐릭터 이름을 정확히 입력해주세요"
                )
            
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)  # 버튼 위치 맞추기
                extract_button = st.form_submit_button("🔍 자동 추출", type="primary")
            
            # 추출 옵션
            st.markdown("**추출 옵션:**")
            col3, col4, col5, col6 = st.columns(4)
            with col3:
                use_ai_refinement = st.checkbox("🤖 AI 정제 사용", value=True, help="Bedrock Claude로 정보를 고품질로 정제합니다")
            with col4:
                extract_image = st.checkbox("🖼️ 이미지 추출", value=True, help="나무위키에서 캐릭터 이미지를 자동으로 추출합니다")
            with col5:
                auto_register = st.checkbox("추출 후 자동 등록", value=False, help="체크하면 추출 후 바로 등록합니다")
            with col6:
                show_preview = st.checkbox("추출 결과 미리보기", value=True, help="등록 전 추출된 정보를 확인합니다")
            
            # 직접 이미지 업로드 옵션
            st.markdown("---")
            st.markdown("**🖼️ 직접 이미지 업로드 (선택사항):**")
            
            # 폴더명 지정
            col_folder, col_btn, col_info = st.columns([2, 1, 1])
            with col_folder:
                folder_name_auto = st.text_input(
                    "📁 이미지 폴더명 지정", 
                    value=character_name.lower().replace(" ", "_") if character_name else "",
                    placeholder="예: zoey, naruto, pikachu",
                    help="영문, 숫자, 언더스코어만 사용 가능",
                    key="folder_name_auto"
                )
            with col_btn:
                st.markdown("<br>", unsafe_allow_html=True)
                folder_created = st.form_submit_button("📁 폴더 생성", disabled=not folder_name_auto)
                if folder_created and folder_name_auto:
                    # 폴더명 정리
                    clean_folder = re.sub(r'[^\w\-_]', '_', folder_name_auto).strip('_')
                    clean_folder = re.sub(r'_+', '_', clean_folder)[:50]
                    
                    # S3에 빈 폴더 생성 (더미 파일로)
                    try:
                        chatbot.s3_client.put_object(
                            Bucket=chatbot.bucket_name,
                            Key=f"character-images/{clean_folder}/.folder_created",
                            Body=b"",
                            ContentType="text/plain"
                        )
                        st.success(f"✅ 폴더 생성됨: {clean_folder}")
                        st.session_state[f"folder_created_{clean_folder}"] = True
                    except Exception as e:
                        st.error(f"❌ 폴더 생성 실패: {str(e)}")
            
            with col_info:
                st.markdown("<br>", unsafe_allow_html=True)
                if folder_name_auto:
                    # 폴더명 검증
                    clean_folder = re.sub(r'[^\w\-_]', '_', folder_name_auto).strip('_')
                    clean_folder = re.sub(r'_+', '_', clean_folder)[:50]
                    if clean_folder != folder_name_auto:
                        st.warning(f"→ {clean_folder}")
                    elif st.session_state.get(f"folder_created_{clean_folder}"):
                        st.success("✅ 생성됨")
                    else:
                        st.info("📁 미생성")
            
            uploaded_images = st.file_uploader(
                "캐릭터 이미지들을 업로드하세요 (여러 개 선택 가능)", 
                type=['jpg', 'jpeg', 'png', 'webp'],
                accept_multiple_files=True,
                help="다양한 표정이나 상황의 이미지를 업로드하면 대화 내용에 따라 자동으로 선택됩니다"
            )
            
            if uploaded_images:
                st.success(f"✅ {len(uploaded_images)}개의 이미지가 선택되었습니다.")
                
                # 이미지 미리보기 (최대 4개까지)
                cols = st.columns(min(4, len(uploaded_images)))
                for i, img in enumerate(uploaded_images[:4]):
                    with cols[i]:
                        st.image(img, width=100, caption=f"이미지 {i+1}")
                
                if len(uploaded_images) > 4:
                    st.info(f"+ {len(uploaded_images) - 4}개 더...")
                
                total_size = sum(img.size for img in uploaded_images)
                st.info(f"**총 크기:** {total_size:,} bytes")
            
            if extract_button and character_name:
                # 자동 추출 실행
                extracted_info = chatbot.namu_scraper.auto_extract_character(
                    character_name, 
                    use_bedrock_refinement=use_ai_refinement,
                    extract_image=extract_image
                )
                
                # 사용자가 직접 업로드한 이미지들이 있으면 우선 사용
                if uploaded_images and extracted_info:
                    # 폴더명 검증
                    if not folder_name_auto:
                        st.error("❌ 이미지를 업로드하려면 폴더명을 입력해주세요.")
                    else:
                        with st.spinner("📤 사용자 업로드 이미지들을 S3에 저장 중..."):
                            # 나무위키 캐릭터 이름 대신 사용자 지정 폴더명 사용
                            user_image_urls, actual_folder_name = chatbot.upload_multiple_character_images_to_s3(
                                uploaded_images, folder_name_auto, folder_name_auto  # 폴더명만 사용
                            )
                            if user_image_urls:
                                extracted_info['image_urls'] = user_image_urls
                                extracted_info['image_url'] = user_image_urls[0]  # 호환성
                                extracted_info['s3_folder_name'] = actual_folder_name
                                st.success(f"✅ {len(user_image_urls)}개의 사용자 업로드 이미지가 적용되었습니다!")
                
                if extracted_info:
                    # 세션 상태에 저장
                    st.session_state.extracted_character = extracted_info
                    
                    if show_preview:
                        st.success("✅ 정보 추출 완료! 아래에서 확인하고 수정하세요.")
                    
                    if auto_register and not show_preview:
                        # 바로 등록
                        with st.spinner("캐릭터 등록 중..."):
                            if chatbot.add_new_character(extracted_info):
                                st.success(f"🎉 '{extracted_info['name']}' 캐릭터가 성공적으로 등록되었습니다!")
                                st.info("💡 '동기화 상태' 탭에서 Knowledge Base 동기화를 실행해주세요.")
                            else:
                                st.error("❌ 캐릭터 등록에 실패했습니다.")
                else:
                    st.error("❌ 캐릭터 정보를 추출할 수 없습니다. 캐릭터 이름을 확인해주세요.")
        
        # 추출된 정보 미리보기 및 수정
        if 'extracted_character' in st.session_state and show_preview:
            st.markdown("---")
            st.markdown("### 📝 추출된 정보 확인 및 수정")
            
            extracted = st.session_state.extracted_character
            
            # 추출된 이미지가 있으면 표시
            if extracted.get('image_url'):
                st.markdown("#### 🖼️ 추출된 캐릭터 이미지")
                col_img, col_info = st.columns([1, 2])
                with col_img:
                    try:
                        st.image(extracted['image_url'], width=200, caption="자동 추출된 이미지")
                    except Exception:
                        st.warning("이미지를 불러올 수 없습니다.")
                with col_info:
                    st.info(f"**이미지 URL:** {extracted['image_url']}")
                    st.success("✅ 이미지가 S3에 성공적으로 업로드되었습니다!")
            else:
                st.info("🖼️ 추출된 이미지가 없습니다.")
            
            # 이미지 교체 옵션
            st.markdown("#### 🔄 이미지 교체 (선택사항)")
            replacement_image = st.file_uploader(
                "다른 이미지로 교체하려면 업로드하세요", 
                type=['jpg', 'jpeg', 'png', 'webp'],
                key="replacement_image_upload",
                help="현재 이미지가 마음에 들지 않으면 새로운 이미지를 업로드할 수 있습니다"
            )
            
            if replacement_image:
                col_new_img, col_new_info = st.columns([1, 2])
                with col_new_img:
                    st.image(replacement_image, width=200, caption="새로운 이미지")
                with col_new_info:
                    st.info(f"**파일명:** {replacement_image.name}")
                    st.success("✅ 새로운 이미지가 선택되었습니다. 등록 시 이 이미지를 사용합니다.")
            
            with st.form("preview_edit_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    name = st.text_input("캐릭터 이름", value=extracted.get('name', ''))
                    role = st.text_input("역할", value=extracted.get('role', ''))
                    catchphrase = st.text_input("캐치프레이즈", value=extracted.get('catchphrase', ''))
                
                with col2:
                    personality = st.text_area(
                        "성격", 
                        value=extracted.get('personality', ''),
                        height=100
                    )
                    speaking_style = st.text_area(
                        "말투",
                        value=extracted.get('speaking_style', ''),
                        height=100
                    )
                
                # 능력 (리스트를 문자열로 변환)
                abilities_str = ', '.join(extracted.get('abilities', []))
                abilities_input = st.text_input("능력 (쉼표로 구분)", value=abilities_str)
                
                # 취미 (리스트를 문자열로 변환)
                hobbies_str = ', '.join(extracted.get('hobbies', []))
                hobbies_input = st.text_input("취미 (쉼표로 구분)", value=hobbies_str)
                
                # 배경 스토리
                background = st.text_area(
                    "배경 스토리",
                    value=extracted.get('background', ''),
                    height=150
                )
                
                # 추가 정보 표시
                if extracted.get('additional_info'):
                    st.markdown("**나무위키에서 추출된 추가 정보:**")
                    for key, value in extracted['additional_info'].items():
                        st.text(f"• {key}: {value}")
                
                # 등록 버튼
                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
                
                with col_btn1:
                    register_button = st.form_submit_button("✅ 등록하기", type="primary")
                
                with col_btn2:
                    reset_button = st.form_submit_button("🔄 원본으로 되돌리기")
                
                with col_btn3:
                    cancel_button = st.form_submit_button("❌ 취소")
                
                if register_button:
                    # 수정된 정보로 캐릭터 데이터 구성
                    abilities = [ability.strip() for ability in abilities_input.split(',') if ability.strip()]
                    hobbies = [hobby.strip() for hobby in hobbies_input.split(',') if hobby.strip()]
                    
                    character_data = {
                        "name": name,
                        "role": role,
                        "personality": personality,
                        "abilities": abilities,
                        "hobbies": hobbies,
                        "background": background,
                        "catchphrase": catchphrase,
                        "speaking_style": speaking_style
                    }
                    
                    # 이미지 처리 (교체 이미지가 있으면 우선 사용)
                    if replacement_image:
                        with st.spinner("📤 새로운 이미지를 S3에 업로드 중..."):
                            new_image_urls = chatbot.upload_multiple_character_images_to_s3([replacement_image], name)
                            if new_image_urls:
                                character_data['image_urls'] = new_image_urls
                                character_data['image_url'] = new_image_urls[0]  # 호환성
                                st.success("✅ 새로운 이미지가 업로드되었습니다!")
                    elif extracted.get('image_url'):
                        # 기존 추출된 이미지 사용
                        character_data['image_url'] = extracted['image_url']
                        if extracted.get('image_urls'):
                            character_data['image_urls'] = extracted['image_urls']
                    
                    # 등록 실행
                    with st.spinner("캐릭터 등록 중..."):
                        if chatbot.add_new_character(character_data):
                            st.success(f"🎉 '{name}' 캐릭터가 성공적으로 등록되었습니다!")
                            st.info("💡 '동기화 상태' 탭에서 Knowledge Base 동기화를 실행해주세요.")
                            # 세션 상태 클리어
                            del st.session_state.extracted_character
                            st.rerun()
                        else:
                            st.error("❌ 캐릭터 등록에 실패했습니다.")
                
                elif reset_button:
                    st.rerun()
                
                elif cancel_button:
                    del st.session_state.extracted_character
                    st.rerun()
    
    with tab2:
        st.markdown("### ➕ 새 캐릭터 추가")
        
        with st.form("add_character_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("캐릭터 이름 *", placeholder="예: 드래곤")
                role = st.text_input("역할 *", placeholder="예: 고대 용족의 수호자")
                catchphrase = st.text_input("캐치프레이즈", placeholder="예: 용의 힘으로 모든 걸 지켜내겠다!")
                
            with col2:
                personality = st.text_area(
                    "성격 *", 
                    placeholder="예: 위엄있고 지혜로우며, 동료들을 보호하려는 강한 의지를 가지고 있다.",
                    height=100
                )
                speaking_style = st.text_area(
                    "말투",
                    placeholder="예: 격식있고 위엄있는 말투를 사용하며, 고대의 지혜가 담긴 표현을 자주 쓴다.",
                    height=100
                )
            
            # 능력 입력 (여러 개)
            st.markdown("**능력** (쉼표로 구분)")
            abilities_input = st.text_input("", placeholder="예: 화염 브레스, 비행, 마법 저항")
            
            # 취미 입력 (여러 개)
            st.markdown("**취미** (쉼표로 구분)")
            hobbies_input = st.text_input("", placeholder="예: 보물 수집, 하늘 날기, 명상")
            
            # 배경 스토리
            background = st.text_area(
                "배경 스토리",
                placeholder="예: 수천 년을 살아온 고대 드래곤으로, 데몬들의 침입으로 인해 케이팝 데몬헌터스에 합류하게 되었다.",
                height=100
            )
            
            # 캐릭터 이미지 업로드
            st.markdown("**🖼️ 캐릭터 이미지들 (선택사항):**")
            
            # 폴더명 지정
            col_folder, col_btn, col_info = st.columns([2, 1, 1])
            with col_folder:
                folder_name = st.text_input(
                    "📁 이미지 폴더명 지정", 
                    value=name.lower().replace(" ", "_") if name else "",
                    placeholder="예: zoey, naruto, pikachu",
                    help="영문, 숫자, 언더스코어만 사용 가능"
                )
            with col_btn:
                st.markdown("<br>", unsafe_allow_html=True)
                folder_created = st.form_submit_button("📁 폴더 생성", disabled=not folder_name)
                if folder_created and folder_name:
                    # 폴더명 정리
                    clean_folder = re.sub(r'[^\w\-_]', '_', folder_name).strip('_')
                    clean_folder = re.sub(r'_+', '_', clean_folder)[:50]
                    
                    # S3에 빈 폴더 생성 (더미 파일로)
                    try:
                        chatbot.s3_client.put_object(
                            Bucket=chatbot.bucket_name,
                            Key=f"character-images/{clean_folder}/.folder_created",
                            Body=b"",
                            ContentType="text/plain"
                        )
                        st.success(f"✅ 폴더 생성됨: {clean_folder}")
                        st.session_state[f"folder_created_{clean_folder}"] = True
                    except Exception as e:
                        st.error(f"❌ 폴더 생성 실패: {str(e)}")
            
            with col_info:
                st.markdown("<br>", unsafe_allow_html=True)
                if folder_name:
                    # 폴더명 검증
                    clean_folder = re.sub(r'[^\w\-_]', '_', folder_name).strip('_')
                    clean_folder = re.sub(r'_+', '_', clean_folder)[:50]
                    if clean_folder != folder_name:
                        st.warning(f"→ {clean_folder}")
                    elif st.session_state.get(f"folder_created_{clean_folder}"):
                        st.success("✅ 생성됨")
                    else:
                        st.info("📁 미생성")
            
            character_images = st.file_uploader(
                "캐릭터 이미지들을 업로드하세요 (여러 개 선택 가능)", 
                type=['jpg', 'jpeg', 'png', 'webp'],
                key="manual_images_upload",
                accept_multiple_files=True,
                help="다양한 표정이나 상황의 이미지를 업로드하면 대화 내용에 따라 자동으로 선택됩니다 (최대 5MB/개)"
            )
            
            if character_images:
                st.success(f"✅ {len(character_images)}개의 이미지가 선택되었습니다.")
                
                # 이미지 미리보기
                cols = st.columns(min(4, len(character_images)))
                for i, img in enumerate(character_images[:4]):
                    with cols[i]:
                        st.image(img, width=100, caption=f"이미지 {i+1}")
                
                if len(character_images) > 4:
                    st.info(f"+ {len(character_images) - 4}개 더...")
                
                total_size = sum(img.size for img in character_images)
                st.info(f"**총 크기:** {total_size:,} bytes")
            
            # 제출 버튼
            submitted = st.form_submit_button("캐릭터 추가", type="primary")
            
            if submitted:
                if name and role and personality:
                    # 능력과 취미를 리스트로 변환
                    abilities = [ability.strip() for ability in abilities_input.split(',') if ability.strip()] if abilities_input else []
                    hobbies = [hobby.strip() for hobby in hobbies_input.split(',') if hobby.strip()] if hobbies_input else []
                    
                    # 캐릭터 데이터 구성
                    character_data = {
                        "name": name,
                        "role": role,
                        "personality": personality,
                        "abilities": abilities,
                        "hobbies": hobbies,
                        "background": background or f"{name}의 배경 스토리입니다.",
                        "catchphrase": catchphrase or f"{name}의 캐치프레이즈입니다!",
                        "speaking_style": speaking_style or f"{name}만의 독특한 말투를 사용합니다."
                    }
                    
                    # 이미지 업로드 처리
                    if character_images:
                        # 폴더명 검증
                        if not folder_name:
                            st.error("❌ 이미지를 업로드하려면 폴더명을 입력해주세요.")
                        else:
                            with st.spinner("📤 이미지들을 S3에 업로드 중..."):
                                image_urls, actual_folder_name = chatbot.upload_multiple_character_images_to_s3(
                                    character_images, name, folder_name
                                )
                                if image_urls:
                                    character_data['image_urls'] = image_urls
                                    character_data['image_url'] = image_urls[0]  # 호환성
                                    character_data['s3_folder_name'] = actual_folder_name  # 실제 폴더명 저장
                                    st.success(f"✅ {len(image_urls)}개의 이미지가 성공적으로 업로드되었습니다!")
                                    st.info(f"📁 S3 폴더: character-images/{actual_folder_name}/")
                    else:
                        # 이미지 없이 등록하는 경우에도 폴더명 저장 (나중에 이미지 추가 시 사용)
                        if folder_name:
                            clean_folder = re.sub(r'[^\w\-_]', '_', folder_name).strip('_')
                            clean_folder = re.sub(r'_+', '_', clean_folder)[:50]
                            character_data['s3_folder_name'] = clean_folder
                    
                    # S3에 업로드
                    with st.spinner("캐릭터 데이터 업로드 중..."):
                        if chatbot.add_new_character(character_data):
                            st.success(f"✅ '{name}' 캐릭터가 성공적으로 추가되었습니다!")
                            st.info("💡 '동기화 상태' 탭에서 Knowledge Base 동기화를 실행해주세요.")
                            
                            # 세션 상태 업데이트 (캐릭터 목록 새로고침용)
                            if 'character_list_refresh' not in st.session_state:
                                st.session_state.character_list_refresh = 0
                            st.session_state.character_list_refresh += 1
                        else:
                            st.error("❌ 캐릭터 추가에 실패했습니다.")
                else:
                    st.error("❌ 필수 항목(이름, 역할, 성격)을 모두 입력해주세요.")
    
    with tab3:
        st.markdown("### 📋 등록된 캐릭터 목록")
        
        # 새로고침 버튼
        if st.button("🔄 목록 새로고침"):
            if 'character_list_refresh' not in st.session_state:
                st.session_state.character_list_refresh = 0
            st.session_state.character_list_refresh += 1
        
        # 모든 캐릭터 조회 (기본 + S3)
        all_characters = chatbot.get_all_available_characters()
        hidden_chars = chatbot.load_hidden_characters()
        
        if all_characters:
            st.markdown(f"**총 {len(all_characters)}개의 캐릭터 (숨김: {len(hidden_chars)}개)**")
            
            # 캐릭터를 5열로 표시
            char_list = list(all_characters.items())
            for i in range(0, len(char_list), 5):
                cols = st.columns(5)
                
                for j, col in enumerate(cols):
                    char_idx = i + j
                    if char_idx < len(char_list):
                        char_key, char_info = char_list[char_idx]
                        is_hidden = char_key in hidden_chars
                        is_default = char_info.get('is_default', False)
                        
                        with col:
                            # 캐릭터 카드
                            st.markdown(f"""
                            <div style="
                                border: 2px solid {'#888' if is_hidden else ('#FF69B4' if is_default else '#ddd')};
                                border-radius: 10px;
                                padding: 15px;
                                margin: 5px;
                                text-align: center;
                                background: {'#f0f0f0' if is_hidden else ('linear-gradient(135deg, #FF69B4, #4A90E2)' if is_default else '#f9f9f9')};
                                color: {'#666' if is_hidden else ('white' if is_default else 'black')};
                                opacity: {'0.6' if is_hidden else '1'};
                            ">
                                <h4>{char_info['emoji']} {char_info['name']}</h4>
                                <small>{'🔒 숨김 | ' if is_hidden else ''}{'기본 캐릭터' if is_default else '사용자 추가'}</small>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # 숨김/표시 토글 버튼
                            btn_label = "👁️ 표시" if is_hidden else "🔒 숨김"
                            if st.button(btn_label, key=f"toggle_{char_key}", use_container_width=True):
                                chatbot.toggle_character_visibility(char_key)
                                st.rerun()
                            
                            # 캐릭터 상세 정보 보기
                            if st.button(f"📄 정보 보기", key=f"info_{char_key}", use_container_width=True):
                                with st.expander(f"📋 {char_info['name']} 상세 정보", expanded=True):
                                    col_info1, col_info2 = st.columns(2)
                                    
                                    with col_info1:
                                        st.markdown(f"**이름:** {char_info.get('name', char_key)}")
                                        st.markdown(f"**역할:** {char_info.get('role', '정보 없음')}")
                                        st.markdown(f"**캐치프레이즈:** {char_info.get('catchphrase', '정보 없음')}")
                                    
                                    with col_info2:
                                        st.markdown(f"**말투:** {char_info.get('speaking_style', '정보 없음')}")
                                        abilities = char_info.get('abilities', [])
                                        st.markdown(f"**능력:** {', '.join(abilities[:3]) if abilities else '정보 없음'}")
                                        hobbies = char_info.get('hobbies', [])
                                        st.markdown(f"**취미:** {', '.join(hobbies[:2]) if hobbies else '정보 없음'}")
                                    
                                    st.markdown(f"**성격:** {char_info.get('personality', '정보 없음')}")
                                    background = char_info.get('background', '정보 없음')
                                    st.markdown(f"**배경:** {background[:200]}{'...' if len(background) > 200 else ''}")
                            
                            # 삭제 버튼 (기본 캐릭터가 아닌 경우만)
                            if not is_default:
                                delete_confirm_key = f"delete_confirm_{char_key}"
                                if delete_confirm_key not in st.session_state:
                                    st.session_state[delete_confirm_key] = False
                                
                                # 삭제 확인 체크박스
                                confirm_delete = st.checkbox(
                                    f"🗑️ {char_key} 삭제 확인", 
                                    key=delete_confirm_key,
                                    help="체크 후 삭제 버튼을 눌러주세요"
                                )
                                
                                # 삭제 버튼
                                if st.button(
                                    f"🗑️ {char_key} 삭제", 
                                    key=f"delete_{char_key}",
                                    type="secondary",
                                    use_container_width=True,
                                    disabled=not confirm_delete
                                ):
                                    if confirm_delete:
                                        with st.spinner(f"'{char_key}' 삭제 중..."):
                                            if chatbot.delete_character(char_key):
                                                st.success(f"✅ '{char_key}' 캐릭터가 성공적으로 삭제되었습니다!")
                                                st.info("💡 Knowledge Base 동기화를 실행하여 변경사항을 반영해주세요.")
                                                
                                                # 현재 선택된 캐릭터가 삭제된 경우 초기화
                                                if st.session_state.get('selected_character') == char_key:
                                                    st.session_state.selected_character = None
                                                
                                                # 채팅 히스토리도 삭제
                                                if char_key in st.session_state.get('messages', {}):
                                                    del st.session_state.messages[char_key]
                                                
                                                # 삭제 확인 상태 초기화 (키 삭제로 변경)
                                                if delete_confirm_key in st.session_state:
                                                    del st.session_state[delete_confirm_key]
                                                
                                                # 목록 새로고침
                                                time.sleep(1)
                                                st.rerun()
                                            else:
                                                st.error(f"❌ '{char_key}' 삭제에 실패했습니다.")
                                    else:
                                        st.warning("삭제하려면 먼저 확인 체크박스를 선택해주세요.")
                            else:
                                st.info("🔒 기본 캐릭터는 삭제할 수 없습니다.")
                            
                            st.markdown("---")
        else:
            st.info("등록된 캐릭터가 없습니다.")
    
    with tab4:
        st.markdown("### 🔄 Knowledge Base 동기화 상태")
        
        # 동기화 상태 정보 조회
        with st.spinner("동기화 상태 확인 중..."):
            sync_info = chatbot.get_sync_status_info()
        
        # 전체 상태 요약
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                label="📊 전체 캐릭터",
                value=sync_info['total_characters']
            )
        
        with col2:
            st.metric(
                label="✅ 동기화 완료",
                value=sync_info['synced_count'],
                delta=f"{sync_info['synced_count']}/{sync_info['total_characters']}"
            )
        
        with col3:
            st.metric(
                label="⏳ 동기화 필요",
                value=len(sync_info['needs_sync']),
                delta=f"-{len(sync_info['needs_sync'])}" if sync_info['needs_sync'] else "0"
            )
        
        # 마지막 동기화 시간
        if sync_info['last_sync_time']:
            st.info(f"🕒 **마지막 동기화:** {sync_info['last_sync_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.warning("⚠️ **동기화 기록이 없습니다.** 모든 캐릭터가 동기화가 필요합니다.")
        
        # 동기화가 필요한 캐릭터 목록
        if sync_info['needs_sync']:
            st.markdown("---")
            st.markdown("### ⏳ 동기화가 필요한 캐릭터")
            st.markdown("다음 캐릭터들이 Knowledge Base에 동기화되지 않았거나 업데이트가 필요합니다:")
            
            # 캐릭터별로 카드 형태로 표시
            cols_per_row = 3
            needs_sync_list = sync_info['needs_sync']
            
            for i in range(0, len(needs_sync_list), cols_per_row):
                cols = st.columns(cols_per_row)
                
                for j, col in enumerate(cols):
                    char_idx = i + j
                    if char_idx < len(needs_sync_list):
                        char_name = needs_sync_list[char_idx]
                        
                        # 캐릭터 정보 가져오기
                        all_chars = chatbot.get_all_available_characters()
                        char_info = all_chars.get(char_name, {})
                        
                        with col:
                            # 캐릭터 카드
                            is_default = char_info.get('is_default', False)
                            emoji = char_info.get('emoji', '🎭')
                            
                            st.markdown(f"""
                            <div style="
                                border: 2px solid #FF6B6B;
                                border-radius: 10px;
                                padding: 15px;
                                margin: 5px;
                                text-align: center;
                                background: linear-gradient(135deg, #FF6B6B, #FFA500);
                                color: white;
                                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                            ">
                                <h4>⏳ {emoji} {char_name}</h4>
                                <small>{'기본 캐릭터' if is_default else '사용자 추가'}</small>
                                <br><small>동기화 필요</small>
                            </div>
                            """, unsafe_allow_html=True)
        
        else:
            st.success("🎉 **모든 캐릭터가 동기화되었습니다!**")
        
        # 동기화 실행 버튼
        st.markdown("---")
        col_sync, col_status = st.columns([1, 1])
        
        with col_sync:
            if st.button("🚀 동기화 시작", type="primary", use_container_width=True):
                if sync_info['needs_sync']:
                    with st.spinner("동기화 작업을 시작하는 중..."):
                        job_id = chatbot.sync_knowledge_base()
                        if job_id:
                            st.session_state.current_job_id = job_id
                            st.success(f"✅ 동기화 작업이 시작되었습니다!")
                            st.info(f"📋 **작업 ID:** {job_id}")
                            st.info(f"🔄 **동기화 대상:** {len(sync_info['needs_sync'])}개 캐릭터")
                        else:
                            st.error("❌ 동기화 시작에 실패했습니다.")
                else:
                    st.info("동기화가 필요한 캐릭터가 없습니다.")
        
        with col_status:
            if st.button("📊 상태 새로고침", use_container_width=True):
                st.rerun()
        
        # 현재 진행 중인 작업 상태 확인
        if 'current_job_id' in st.session_state:
            st.markdown("---")
            st.markdown("### 📊 현재 동기화 작업 상태")
            
            if st.button("🔍 작업 상태 확인"):
                with st.spinner("상태 확인 중..."):
                    job_info = chatbot.check_ingestion_status(st.session_state.current_job_id)
                    if job_info:
                        status = job_info['status']
                        stats = job_info['statistics']
                        
                        # 상태에 따른 색상
                        status_color = {
                            'COMPLETE': '🟢',
                            'IN_PROGRESS': '🟡', 
                            'STARTING': '🟡',
                            'FAILED': '🔴'
                        }.get(status, '⚪')
                        
                        st.markdown(f"**{status_color} 상태:** {status}")
                        
                        if status == 'COMPLETE':
                            st.success("🎉 동기화가 완료되었습니다!")
                            st.markdown(f"""
                            **동기화 결과:**
                            - 스캔된 문서: {stats['numberOfDocumentsScanned']}
                            - 새로 인덱싱된 문서: {stats['numberOfNewDocumentsIndexed']}
                            - 수정된 문서: {stats['numberOfModifiedDocumentsIndexed']}
                            - 실패한 문서: {stats['numberOfDocumentsFailed']}
                            """)
                        elif status == 'FAILED':
                            st.error("❌ 동기화에 실패했습니다.")
                        else:
                            st.info(f"⏳ 동기화 진행 중... ({status})")
                    else:
                        st.error("상태 확인에 실패했습니다.")
        
        # 오류 정보 표시 (있는 경우)
        if 'kb_error' in sync_info:
            st.warning(f"⚠️ Knowledge Base 조회 제한: 일부 기능이 제한될 수 있습니다.")

def main():
    st.set_page_config(
        page_title="케이팝 데몬헌터스 챗봇",
        page_icon="🎤",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # CSS 로드
    load_css()

    # ── Cognito 인증 게이트 ──
    config_path = Path(__file__).parent / "chatbot_config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            _cfg = json.load(f)
        auth_manager = CognitoAuthManager(
            user_pool_id=_cfg["cognito_user_pool_id"],
            client_id=_cfg["cognito_client_id"],
            region=_cfg.get("region", "us-east-1"),
        )
    else:
        st.error("chatbot_config.json을 찾을 수 없습니다. character_chatbot_setup_memory.py를 먼저 실행하세요.")
        st.stop()

    user_id = render_auth_ui(auth_manager)
    if not user_id:
        st.stop()

    # ── 메모리 매니저 초기화 ──
    if "memory_manager" not in st.session_state:
        st.session_state.memory_manager = ChatbotMemoryManager()
        st.session_state.user_profile = st.session_state.memory_manager.get_or_create_user(
            st.session_state.auth_user_id,
            st.session_state.auth_email,
            st.session_state.auth_display_name,
        )

    # 메인 헤더 - 개선된 네온 효과
    st.markdown('''
    <div style="text-align: center; margin-bottom: 3rem; padding: 2rem 0;">
        <h1 style="
            color: #ff0080;
            font-size: 3rem;
            font-weight: 900;
            margin: 0;
            letter-spacing: 4px;
            text-shadow: 0 0 20px rgba(255, 0, 128, 0.8), 0 0 40px rgba(121, 40, 202, 0.6), 0 0 60px rgba(255, 0, 128, 0.4);
        ">🎤 K-POP DEMON HUNTERS</h1>
        <p style="
            color: #ff80bf; 
            font-size: 1.1rem; 
            margin-top: 1rem; 
            font-weight: 600;
            text-shadow: 0 0 15px rgba(255, 0, 128, 0.6);
            letter-spacing: 2px;
        ">
            ⚡ 악마를 사냥하는 아이돌들과 대화하세요 ⚡
        </p>
        <div style="
            margin-top: 1rem;
            height: 2px;
            background: linear-gradient(90deg, transparent, #ff0080, #7928ca, #ff0080, transparent);
            box-shadow: 0 0 10px rgba(255, 0, 128, 0.5);
        "></div>
    </div>
    ''', unsafe_allow_html=True)
    
    # 챗봇 인스턴스 초기화
    if 'chatbot' not in st.session_state:
        st.session_state.chatbot = KPopDemonHuntersChatbot()
    
    # 사이드바
    with st.sidebar:
        st.markdown('<div class="sidebar-content">', unsafe_allow_html=True)

        # 사용자 프로필 + 로그아웃
        render_user_profile_sidebar(auth_manager)

        # 메뉴 선택
        menu = st.selectbox(
            "📋 메뉴 선택",
            ["💬 채팅", "🛠️ 캐릭터 관리"],
            index=0
        )
        
        if menu == "💬 채팅":
            # 캐릭터 선택
            selected_character = display_character_selection(st.session_state.chatbot)
            
            # 선택된 캐릭터 정보 표시 (중복 호출 제거)
            if selected_character:
                # 이미 display_character_selection에서 조회한 정보 재사용
                if 'all_characters_cache' not in st.session_state:
                    st.session_state.all_characters_cache = st.session_state.chatbot.get_all_available_characters()
                
                char_info = st.session_state.all_characters_cache.get(selected_character)
                
                if char_info:
                    # 폴더 자동 선택
                    auto_folder = char_info.get('s3_folder_name')
                    if auto_folder:
                        st.session_state.selected_image_folder = auto_folder
                    else:
                        st.session_state.selected_image_folder = None
                    
                    st.markdown("---")
                    
                    st.markdown("### 🌟 현재 선택된 캐릭터")
                    
                    # 캐릭터 이미지
                    if char_info.get("image") and char_info["is_default"]:
                        # 기본 캐릭터의 로컬 이미지
                        image_path = st.session_state.chatbot.current_dir / char_info["image"]
                        if image_path.exists():
                            st.image(str(image_path), width=300)
                        else:
                            st.markdown(f"<div style='font-size: 4rem; text-align: center;'>{char_info['emoji']}</div>",
                                       unsafe_allow_html=True)
                    elif char_info.get('local_images'):
                        # 로컬 이미지가 있는 캐릭터
                        try:
                            st.image(char_info['local_images'][0], width=300)
                        except Exception:
                            st.markdown(f"<div style='font-size: 4rem; text-align: center;'>{char_info['emoji']}</div>",
                                       unsafe_allow_html=True)
                    else:
                        # S3에서 default.png 우선 조회
                        folder_name = getattr(st.session_state, 'selected_image_folder', None)
                        actual_char_name = char_info.get('name', selected_character)
                        default_img = st.session_state.chatbot.get_character_default_image(actual_char_name, folder_name)

                        if default_img:
                            try:
                                st.image(default_img, width=300)
                            except Exception:
                                st.markdown(f"<div style='font-size: 4rem; text-align: center;'>{char_info['emoji']}</div>",
                                           unsafe_allow_html=True)
                        else:
                            # default 없으면 이모지 표시
                            st.markdown(f"<div style='font-size: 4rem; text-align: center;'>{char_info['emoji']}</div>",
                                       unsafe_allow_html=True)
                    
                    st.markdown(f"**{char_info['emoji']} {char_info['name']}**")
                    st.markdown(f"📋 **역할**: {char_info['role']}")
                    
                    # 성격 설명 - expander로 접기/펼치기
                    with st.expander("💭 성격 보기", expanded=False):
                        st.markdown(char_info['personality'])
                    
                    # 캐릭터 타입 표시
                    if char_info["is_default"]:
                        st.markdown("🌟 **기본 캐릭터**")
                    elif char_info.get('source') == 'local_folder':
                        st.markdown("📁 **로컬 폴더 캐릭터**")
                    else:
                        st.markdown("👤 **사용자 추가 캐릭터**")
            
            st.markdown("### 📖 사용법")
            st.markdown("1. 🎭 캐릭터를 선택하세요")
            st.markdown("2. 💬 메시지를 입력하세요")
            st.markdown("3. 🎉 캐릭터와 대화를 즐기세요!")
            
            if st.button("🗑️ 채팅 히스토리 클리어", use_container_width=True):
                msgs = st.session_state.get("messages", {}).get(selected_character, [])
                if msgs and len(msgs) >= 2:
                    session_start = st.session_state.get(f"session_start_{selected_character}", datetime.now(timezone.utc).isoformat())
                    st.session_state.memory_manager.save_conversation(
                        st.session_state.auth_user_id, selected_character, msgs, session_start,
                    )
                if selected_character in st.session_state.get('messages', {}):
                    st.session_state.messages[selected_character] = []
                    st.session_state.pop(f"session_start_{selected_character}", None)
                    st.rerun()
        
        else:  # 캐릭터 관리 메뉴
            st.markdown("### 🛠️ 캐릭터 관리")
            st.markdown("메인 화면에서 캐릭터 목록과 숨김 설정을 관리할 수 있습니다.")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # 메인 영역 - 메뉴에 따라 분기
    if 'menu' not in locals():
        menu = "💬 채팅"  # 기본값
    
    if menu == "💬 채팅":
        # 채팅 모드
        if 'selected_character' in locals() and selected_character:
            # 채팅 히스토리 초기화
            if 'messages' not in st.session_state:
                st.session_state.messages = {}
            
            # 캐릭터 전환 시 이전 대화 저장
            prev_char = st.session_state.get("_current_character")
            if prev_char and prev_char != selected_character:
                prev_msgs = st.session_state.get("messages", {}).get(prev_char, [])
                if prev_msgs and len(prev_msgs) >= 2:
                    prev_start = st.session_state.get(f"session_start_{prev_char}", datetime.now(timezone.utc).isoformat())
                    st.session_state.memory_manager.save_conversation(
                        st.session_state.auth_user_id, prev_char, prev_msgs, prev_start,
                    )
            st.session_state["_current_character"] = selected_character

            if selected_character not in st.session_state.messages:
                st.session_state.messages[selected_character] = []

            # 세션 시작 타임스탬프
            if f"session_start_{selected_character}" not in st.session_state:
                st.session_state[f"session_start_{selected_character}"] = datetime.now(timezone.utc).isoformat()

            # 채팅 컨테이너
            chat_container = st.container()
            
            with chat_container:
                st.markdown('<div class="chat-container">', unsafe_allow_html=True)
                
                # 채팅 메시지 표시
                for message in st.session_state.messages[selected_character]:
                    if message["role"] == "user":
                        st.markdown(f'<div class="user-message">⚔️ **헌터**: {message["content"]}</div>', 
                                   unsafe_allow_html=True)
                    else:
                        # 모든 캐릭터 정보에서 해당 캐릭터 조회
                        all_characters = st.session_state.chatbot.get_all_available_characters()
                        char_info = all_characters.get(selected_character, {})
                        char_name = char_info.get('name', selected_character)
                        char_emoji = char_info.get('emoji', '🎭')
                        
                        # 동적 이미지 선택
                        selected_image = message.get("selected_image")
                        if not selected_image:
                            # 메시지에 저장된 이미지가 없으면 기본 이미지 사용
                            all_characters = st.session_state.chatbot.get_all_available_characters()
                            char_info = all_characters.get(selected_character, {})

                            # 로컬 이미지가 있는 캐릭터인 경우
                            if char_info.get('local_images'):
                                selected_image = char_info['local_images'][0]
                            else:
                                selected_image = char_info.get('image_url')

                                # 기본 이미지도 없으면 S3에서 첫 번째 이미지 사용
                                if not selected_image:
                                    folder_name = getattr(st.session_state, 'selected_image_folder', None)
                                    character_images = st.session_state.chatbot.get_character_images_from_s3(selected_character, folder_name)
                                    if character_images:
                                        selected_image = character_images[0]
                        
                        # 메시지와 이미지를 함께 표시
                        col_img, col_msg = st.columns([1, 4])
                        
                        with col_img:
                            if selected_image:
                                try:
                                    st.image(selected_image, width=240, caption=char_name)
                                    # 선택된 감정 표시
                                    emotion = message.get("selected_emotion", "unknown")
                                    st.caption(f"😊 감정: {emotion}")
                                except Exception as img_error:
                                    # 이미지 로딩 실패 시 이모지로 대체
                                    st.markdown(f"<div style='font-size: 2rem; text-align: center;'>{char_emoji}</div>", 
                                               unsafe_allow_html=True)
                                    st.caption(f"이미지 로딩 실패")
                            else:
                                st.markdown(f"<div style='font-size: 2rem; text-align: center;'>{char_emoji}</div>", 
                                           unsafe_allow_html=True)
                        
                        with col_msg:
                            st.markdown(f'<div class="bot-message">{char_emoji} **{char_name}**: {message["content"]}</div>', 
                                       unsafe_allow_html=True)
                
                st.markdown('</div>', unsafe_allow_html=True)
            
            # 사용자 입력
            all_characters = st.session_state.chatbot.get_all_available_characters()
            char_info = all_characters.get(selected_character, {})
            char_name = char_info.get('name', selected_character)
            char_emoji = char_info.get('emoji', '🎭')
            
            if prompt := st.chat_input(f"{char_emoji} {char_name}와 대화하기..."):
                # 사용자 메시지 추가
                st.session_state.messages[selected_character].append({
                    "role": "user",
                    "content": prompt,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                # Knowledge Base에서 관련 정보 검색
                context = st.session_state.chatbot.query_knowledge_base(prompt, selected_character)

                # 메모리 컨텍스트 구축
                memory_ctx = st.session_state.memory_manager.build_memory_context(
                    st.session_state.auth_user_id, selected_character
                )
                onboarding_ctx = st.session_state.memory_manager.get_onboarding_prompt_addition(
                    st.session_state.auth_user_id, selected_character
                ) or ""
                profile_completion_ctx = st.session_state.memory_manager.get_profile_completion_prompt(
                    st.session_state.auth_user_id
                ) or ""
                full_memory_context = (memory_ctx + "\n" + onboarding_ctx + "\n" + profile_completion_ctx).strip()

                # 스트리밍 응답 생성 (대화 히스토리 + 메모리 컨텍스트 포함)
                response_placeholder = st.empty()
                full_response = ""
                for chunk in st.session_state.chatbot.generate_character_response(
                    prompt, selected_character, context,
                    chat_history=st.session_state.messages[selected_character],
                    memory_context=full_memory_context,
                ):
                    full_response += chunk
                    response_placeholder.markdown(
                        f'<div class="bot-message">{char_emoji} **{char_name}**: {full_response}▌</div>',
                        unsafe_allow_html=True,
                    )
                # 최종 텍스트 (커서 제거)
                response_placeholder.markdown(
                    f'<div class="bot-message">{char_emoji} **{char_name}**: {full_response}</div>',
                    unsafe_allow_html=True,
                )

                # 대화 내용에 따른 이미지 선택
                try:
                    folder_name = getattr(st.session_state, 'selected_image_folder', None)
                    selected_image, selected_emotion = st.session_state.chatbot.select_character_image_for_message(
                        selected_character, prompt, full_response, folder_name
                    )
                except Exception as e:
                    logger.error("이미지 선택 오류: %s", e)
                    selected_image, selected_emotion = None, 'happy'

                # 응답 추가 (선택된 이미지와 감정 정보 포함)
                st.session_state.messages[selected_character].append({
                    "role": "assistant",
                    "content": full_response,
                    "selected_image": selected_image,
                    "selected_emotion": selected_emotion,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                # 매 응답 후 S3에 원문 저장 (lightweight incremental save)
                session_start = st.session_state.get(
                    f"session_start_{selected_character}",
                    datetime.now(timezone.utc).isoformat(),
                )
                st.session_state.memory_manager.save_messages_incremental(
                    st.session_state.auth_user_id,
                    selected_character,
                    st.session_state.messages[selected_character],
                    session_start,
                )

                # 메시지 6개 이상 누적 시 full pipeline (요약+메모리 추출)
                msgs = st.session_state.messages[selected_character]
                last_full_save = st.session_state.get(f"last_full_save_{selected_character}", 0)
                if len(msgs) - last_full_save >= 6:
                    st.session_state.memory_manager.save_conversation(
                        st.session_state.auth_user_id,
                        selected_character,
                        msgs,
                        session_start,
                    )
                    st.session_state[f"last_full_save_{selected_character}"] = len(msgs)

                # 온보딩 처리 (온보딩 미완료 시)
                profile = st.session_state.get("user_profile", {})
                if not profile.get("onboarding_complete"):
                    current_step = int(profile.get("onboarding_step", 0))
                    new_step = st.session_state.memory_manager.process_onboarding_response(
                        st.session_state.auth_user_id,
                        st.session_state.messages[selected_character],
                        current_step,
                    )
                    if new_step != current_step:
                        if "user_profile" not in st.session_state:
                            st.session_state.user_profile = {}
                        st.session_state.user_profile["onboarding_step"] = new_step
                        if new_step > 4:
                            st.session_state.user_profile["onboarding_complete"] = True

                # 프로필 보완 처리 (빈 필드 수집 - 성별 등)
                st.session_state.memory_manager.process_profile_completion(
                    st.session_state.auth_user_id,
                    st.session_state.messages[selected_character],
                )

                st.rerun()
        else:
            st.info("🎭 사이드바에서 캐릭터를 선택해주세요!")
    
    else:  # 캐릭터 관리 모드
        display_character_management(st.session_state.chatbot)

if __name__ == "__main__":
    main()
