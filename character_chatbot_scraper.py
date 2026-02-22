#!/usr/bin/env python3
"""
나무위키 캐릭터 정보 자동 추출기
"""

import requests
from bs4 import BeautifulSoup
import re
import json
from typing import Dict, Any, Optional
import time
from urllib.parse import quote, urljoin, urlparse
import streamlit as st
import boto3
import os
from pathlib import Path
import hashlib

class NamuWikiScraper:
    def __init__(self):
        self.base_url = "https://namu.wiki"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Bedrock 클라이언트 초기화
        self.bedrock_client = boto3.client(
            "bedrock-runtime", 
            region_name="us-east-1"
        )
        
        # S3 클라이언트 초기화 (이미지 저장용)
        self.s3_client = boto3.client("s3", region_name="us-east-1")
        try:
            with open(Path(__file__).parent / "admin_config.json", "r", encoding="utf-8") as f:
                _cfg = json.load(f)
                self.bucket_name = _cfg.get("bucket_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            self.bucket_name = os.environ.get("S3_BUCKET_NAME", "")
    
    def search_character(self, character_name: str) -> Optional[str]:
        """캐릭터 이름으로 나무위키 페이지 URL 찾기"""
        try:
            # 나무위키 검색 URL
            search_url = f"{self.base_url}/go/{quote(character_name)}"
            
            response = self.session.get(search_url, timeout=10)
            if response.status_code == 200:
                return response.url
            
            # 검색 결과 페이지에서 첫 번째 결과 찾기
            search_results_url = f"{self.base_url}/Search?q={quote(character_name)}"
            response = self.session.get(search_results_url, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                # 첫 번째 검색 결과 링크 찾기
                first_result = soup.find('a', {'class': 'title'})
                if first_result and first_result.get('href'):
                    return urljoin(self.base_url, first_result['href'])
            
            return None
            
        except Exception as e:
            st.error(f"검색 중 오류 발생: {str(e)}")
            return None
    
    def extract_character_info(self, page_url: str) -> Dict[str, Any]:
        """나무위키 페이지에서 캐릭터 정보 추출"""
        try:
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 페이지 제목
            title_element = soup.find('h1', {'class': 'title'}) or soup.find('title')
            title = title_element.get_text().strip() if title_element else "알 수 없음"
            
            # 정보 추출
            character_info = {
                "name": self._clean_title(title),
                "role": "",
                "personality": "",
                "abilities": [],
                "hobbies": [],
                "background": "",
                "catchphrase": "",
                "speaking_style": "",
                "additional_info": {}
            }
            
            # 본문 텍스트 추출
            content_div = soup.find('div', {'class': 'wiki-content'}) or soup.find('div', {'id': 'content'})
            if not content_div:
                content_div = soup.find('div', {'class': 'document'})
            
            if content_div:
                # 텍스트 추출 및 정리
                text_content = content_div.get_text()
                
                # 정보 박스에서 정보 추출
                self._extract_from_infobox(soup, character_info)
                
                # 본문에서 정보 추출
                self._extract_from_content(text_content, character_info)
                
                # 섹션별 정보 추출
                self._extract_sections(soup, character_info)
            
            return character_info
            
        except Exception as e:
            st.error(f"페이지 분석 중 오류 발생: {str(e)}")
            return None
    
    def _clean_title(self, title: str) -> str:
        """제목 정리"""
        # 나무위키 특수 문자 제거
        title = re.sub(r'\s*-\s*나무위키.*', '', title)
        title = re.sub(r'\([^)]*\)', '', title)  # 괄호 내용 제거
        return title.strip()
    
    def _extract_from_infobox(self, soup: BeautifulSoup, character_info: Dict[str, Any]):
        """정보 박스에서 정보 추출"""
        try:
            # 정보 박스 찾기
            infobox = soup.find('table', {'class': 'infobox'}) or soup.find('div', {'class': 'infobox'})
            
            if infobox:
                rows = infobox.find_all('tr')
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    if len(cells) >= 2:
                        key = cells[0].get_text().strip()
                        value = cells[1].get_text().strip()
                        
                        # 키워드 매칭
                        if any(keyword in key.lower() for keyword in ['직업', '역할', '포지션']):
                            character_info['role'] = value
                        elif any(keyword in key.lower() for keyword in ['성격', '특징']):
                            character_info['personality'] = value
                        elif any(keyword in key.lower() for keyword in ['능력', '스킬', '기술']):
                            character_info['abilities'] = [ability.strip() for ability in value.split(',')]
                        elif any(keyword in key.lower() for keyword in ['취미', '좋아하는 것']):
                            character_info['hobbies'] = [hobby.strip() for hobby in value.split(',')]
                        else:
                            character_info['additional_info'][key] = value
        except Exception:
            pass
    
    def _extract_from_content(self, text: str, character_info: Dict[str, Any]):
        """본문에서 정보 추출"""
        try:
            # 성격 관련 키워드 찾기
            personality_patterns = [
                r'성격.*?(?:이다|하다|있다)\.?',
                r'.*?한 성격.*?\.?',
                r'.*?성향.*?\.?'
            ]
            
            for pattern in personality_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches and not character_info['personality']:
                    character_info['personality'] = matches[0][:200]  # 200자 제한
                    break
            
            # 배경 스토리 추출 (첫 번째 문단)
            paragraphs = text.split('\n\n')
            if paragraphs and not character_info['background']:
                first_paragraph = paragraphs[0].strip()
                if len(first_paragraph) > 50:  # 충분히 긴 문단만
                    character_info['background'] = first_paragraph[:300]  # 300자 제한
            
            # 능력 관련 키워드 찾기
            ability_keywords = ['능력', '스킬', '기술', '마법', '초능력', '특수능력']
            for keyword in ability_keywords:
                pattern = f'{keyword}.*?(?:이다|하다|있다)\.?'
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    abilities_text = ' '.join(matches)
                    # 쉼표나 '그리고'로 분리
                    abilities = re.split(r'[,，、]|그리고|또한', abilities_text)
                    character_info['abilities'].extend([
                        ability.strip() for ability in abilities 
                        if ability.strip() and len(ability.strip()) > 2
                    ])
                    break
            
        except Exception:
            pass
    
    def _extract_sections(self, soup: BeautifulSoup, character_info: Dict[str, Any]):
        """섹션별 정보 추출"""
        try:
            # 헤딩 태그 찾기
            headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            
            for heading in headings:
                heading_text = heading.get_text().lower()
                
                # 성격 섹션
                if any(keyword in heading_text for keyword in ['성격', '특징', '개성']):
                    next_content = self._get_section_content(heading)
                    if next_content and not character_info['personality']:
                        character_info['personality'] = next_content[:200]
                
                # 능력 섹션
                elif any(keyword in heading_text for keyword in ['능력', '스킬', '기술', '전투']):
                    next_content = self._get_section_content(heading)
                    if next_content:
                        abilities = re.split(r'[,，、]|\n', next_content)
                        character_info['abilities'].extend([
                            ability.strip() for ability in abilities 
                            if ability.strip() and len(ability.strip()) > 2
                        ])
                
                # 배경 섹션
                elif any(keyword in heading_text for keyword in ['배경', '과거', '역사', '스토리']):
                    next_content = self._get_section_content(heading)
                    if next_content and not character_info['background']:
                        character_info['background'] = next_content[:300]
        except Exception:
            pass
    
    def refine_character_info_with_bedrock(self, raw_text: str, character_name: str) -> Dict[str, Any]:
        """Bedrock Claude를 활용하여 추출된 원시 텍스트를 캐릭터 정보로 정제"""
        try:
            prompt = f"""
다음은 나무위키에서 추출한 '{character_name}' 캐릭터에 대한 원시 텍스트입니다.
이 정보를 분석하여 아래 JSON 형식으로 정리해주세요.

원시 텍스트:
{raw_text[:3000]}  # 텍스트 길이 제한

다음 JSON 형식으로 응답해주세요:
{{
    "name": "캐릭터의 정확한 이름",
    "role": "캐릭터의 역할이나 직업 (50자 이내)",
    "personality": "캐릭터의 성격 특징을 자연스럽게 설명 (150자 이내)",
    "abilities": ["능력1", "능력2", "능력3"],  // 최대 5개
    "hobbies": ["취미1", "취미2"],  // 최대 3개
    "background": "캐릭터의 배경 스토리를 흥미롭게 요약 (200자 이내)",
    "catchphrase": "캐릭터가 자주 하는 말이나 대표 대사",
    "speaking_style": "캐릭터의 말투나 언어 특징 설명 (100자 이내)"
}}

규칙:
1. 모든 내용은 한국어로 작성
2. 캐릭터의 매력을 살린 자연스러운 문체 사용
3. 정보가 부족하면 캐릭터의 특성에 맞게 창의적으로 보완
4. JSON 형식을 정확히 지켜주세요
5. 각 필드는 지정된 글자 수를 초과하지 않도록 주의
"""

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}]
                    }
                ],
                "temperature": 0.3  # 일관성을 위해 낮은 온도 설정
            })

            # Claude 4.0 모델 시도, 실패시 3.5 Sonnet 사용
            sonnet_4_model_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"
            sonnet_3_7_model_id = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
            
            try:
                response = self.bedrock_client.invoke_model(
                    modelId=sonnet_4_model_id,
                    body=body
                )
            except Exception:
                response = self.bedrock_client.invoke_model(
                    modelId=sonnet_3_7_model_id,
                    body=body
                )
            
            response_body = json.loads(response.get("body").read())
            refined_text = response_body.get("content", [{}])[0].get("text", "")
            
            # JSON 추출
            json_match = re.search(r'\{.*\}', refined_text, re.DOTALL)
            if json_match:
                refined_info = json.loads(json_match.group())
                return refined_info
            else:
                st.warning("Bedrock 응답에서 JSON을 찾을 수 없습니다. 기본 추출 방식을 사용합니다.")
                return None
                
        except Exception as e:
            st.warning(f"Bedrock 정제 중 오류 발생: {str(e)}. 기본 추출 방식을 사용합니다.")
            return None
    
    def extract_character_image(self, soup: BeautifulSoup, character_name: str) -> Optional[str]:
        """나무위키 페이지에서 캐릭터 대표 이미지 추출"""
        try:
            # 이미지 후보들을 찾기 위한 여러 방법 시도
            image_candidates = []
            
            # 1. 정보박스 내 이미지
            infobox = soup.find('table', {'class': 'infobox'}) or soup.find('div', {'class': 'infobox'})
            if infobox:
                infobox_imgs = infobox.find_all('img')
                for img in infobox_imgs:
                    src = img.get('src') or img.get('data-src')
                    if src and self._is_valid_character_image(src):
                        image_candidates.append(src)
            
            # 2. 첫 번째 섹션의 이미지들
            first_images = soup.find_all('img')[:10]  # 처음 10개만 확인
            for img in first_images:
                src = img.get('src') or img.get('data-src')
                if src and self._is_valid_character_image(src):
                    image_candidates.append(src)
            
            # 3. 가장 적합한 이미지 선택
            if image_candidates:
                # 중복 제거
                image_candidates = list(set(image_candidates))
                
                # 우선순위: 큰 이미지, 캐릭터 이름 포함, jpg/png 확장자
                best_image = self._select_best_image(image_candidates, character_name)
                
                if best_image:
                    # 상대 URL을 절대 URL로 변환
                    if best_image.startswith('//'):
                        best_image = 'https:' + best_image
                    elif best_image.startswith('/'):
                        best_image = urljoin(self.base_url, best_image)
                    
                    return best_image
            
            return None
            
        except Exception as e:
            st.warning(f"이미지 추출 중 오류: {str(e)}")
            return None
    
    def _is_valid_character_image(self, src: str) -> bool:
        """유효한 캐릭터 이미지인지 확인"""
        if not src:
            return False
        
        # 제외할 이미지들
        exclude_patterns = [
            'icon', 'logo', 'banner', 'button', 'arrow', 'edit',
            'commons', 'wikimedia', 'namu.wiki', 'advertisement'
        ]
        
        src_lower = src.lower()
        
        # 제외 패턴 확인
        for pattern in exclude_patterns:
            if pattern in src_lower:
                return False
        
        # 이미지 확장자 확인
        valid_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
        if not any(ext in src_lower for ext in valid_extensions):
            return False
        
        return True
    
    def _select_best_image(self, candidates: list, character_name: str) -> Optional[str]:
        """이미지 후보 중 가장 적합한 이미지 선택"""
        if not candidates:
            return None
        
        scored_images = []
        
        for img_url in candidates:
            score = 0
            img_lower = img_url.lower()
            
            # 캐릭터 이름이 포함된 경우 높은 점수
            if character_name.lower() in img_lower:
                score += 10
            
            # 파일 크기 추정 (URL에 크기 정보가 있는 경우)
            size_match = re.search(r'(\d+)x(\d+)', img_url)
            if size_match:
                width, height = int(size_match.group(1)), int(size_match.group(2))
                # 적당한 크기의 이미지 선호 (너무 작거나 크지 않은)
                if 100 <= width <= 800 and 100 <= height <= 800:
                    score += 5
                elif width >= 200 and height >= 200:
                    score += 3
            
            # 확장자별 점수
            if '.jpg' in img_lower or '.jpeg' in img_lower:
                score += 2
            elif '.png' in img_lower:
                score += 3
            elif '.webp' in img_lower:
                score += 1
            
            scored_images.append((score, img_url))
        
        # 점수가 높은 순으로 정렬
        scored_images.sort(key=lambda x: x[0], reverse=True)
        
        return scored_images[0][1] if scored_images else None
    
    def _korean_to_roman(self, text: str) -> str:
        """한글을 로마자로 변환 (간단한 매핑)"""
        # 간단한 한글 단어 매핑
        word_map = {
            '피카츄': 'pikachu',
            '나루토': 'naruto', 
            '세일러문': 'sailormoon',
            '손오공': 'songoku',
            '루피': 'luffy',
            '이치고': 'ichigo',
            '나츠': 'natsu',
            '루미': 'rumi',
            '미라': 'mira',
            '사쿠라': 'sakura',
            '히나타': 'hinata',
            '저승사자': 'reaper',
            '까치': 'magpie',
            '호랑이': 'tiger'
        }
        
        # 전체 단어 매핑 확인
        clean_text = re.sub(r'[^\w가-힣]', '', text)  # 특수문자 제거
        if clean_text in word_map:
            return word_map[clean_text]
        
        # 괄호 안의 영어 추출
        english_match = re.search(r'\(([A-Za-z\s]+)\)', text)
        if english_match:
            return re.sub(r'[^\w]', '_', english_match.group(1).strip())
        
        # 영어가 포함된 경우 영어 부분만 추출
        english_only = re.sub(r'[^A-Za-z0-9\s]', '', text)
        if english_only.strip():
            return re.sub(r'[^\w]', '_', english_only.strip())
        
        # 한글의 경우 기본 변환
        if re.search(r'[가-힣]', text):
            return f'korean_{hash(text) % 10000}'
        
        return 'character'
    
    def download_and_upload_image(self, image_url: str, character_name: str) -> Optional[str]:
        """이미지를 다운로드하고 S3에 업로드"""
        try:
            # 이미지 다운로드
            response = self.session.get(image_url, timeout=30)
            response.raise_for_status()
            
            # 이미지 데이터 확인
            if len(response.content) < 1000:  # 너무 작은 이미지는 제외
                st.warning("이미지가 너무 작습니다.")
                return None
            
            # 파일 확장자 결정
            content_type = response.headers.get('content-type', '').lower()
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = '.jpg'
            elif 'png' in content_type:
                ext = '.png'
            elif 'webp' in content_type:
                ext = '.webp'
            else:
                # URL에서 확장자 추출 시도
                parsed_url = urlparse(image_url)
                path = parsed_url.path.lower()
                if '.jpg' in path or '.jpeg' in path:
                    ext = '.jpg'
                elif '.png' in path:
                    ext = '.png'
                elif '.webp' in path:
                    ext = '.webp'
                else:
                    ext = '.jpg'  # 기본값
            
            # S3 키 생성 (캐릭터 이름을 안전한 파일명으로 변환)
            # 한글을 로마자로 변환
            roman_name = self._korean_to_roman(character_name)
            
            # 안전한 파일명으로 변환 (영숫자, 하이픈, 언더스코어만 허용)
            safe_name = re.sub(r'[^\w\-_]', '_', roman_name).strip('_')
            
            # 연속된 언더스코어 제거
            safe_name = re.sub(r'_+', '_', safe_name)
            
            # 최대 길이 제한
            safe_name = safe_name[:50]
            
            # 빈 문자열 방지
            if not safe_name:
                safe_name = f'character_{int(time.time())}'
            
            s3_key = f"character-images/{safe_name}{ext}"
            
            # S3에 업로드
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=response.content,
                ContentType=content_type or 'image/jpeg',
                Metadata={
                    'character_name_safe': safe_name,  # ASCII 안전한 이름
                    'original_url': image_url,
                    'uploaded_at': str(int(time.time()))
                }
            )
            
            # S3 URL 생성
            s3_url = f"https://{self.bucket_name}.s3.amazonaws.com/{s3_key}"
            
            st.success(f"✅ 이미지가 S3에 업로드되었습니다: {s3_key}")
            return s3_url
            
        except Exception as e:
            st.warning(f"이미지 업로드 중 오류: {str(e)}")
            return None

    def _get_section_content(self, heading) -> str:
        """헤딩 다음의 내용 추출"""
        try:
            content = ""
            current = heading.next_sibling

            while current and current.name not in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                if hasattr(current, 'get_text'):
                    content += current.get_text() + " "
                elif isinstance(current, str):
                    content += current + " "
                current = current.next_sibling

                if len(content) > 500:  # 너무 길면 중단
                    break

            return content.strip()
        except Exception:
            return ""
    
    def auto_extract_character(self, character_name: str, use_bedrock_refinement: bool = True, extract_image: bool = True) -> Optional[Dict[str, Any]]:
        """캐릭터 이름으로 자동 정보 추출 (Bedrock 정제 옵션 포함)"""
        try:
            # 1단계: 페이지 URL 찾기
            with st.spinner(f"'{character_name}' 검색 중..."):
                page_url = self.search_character(character_name)
                
            if not page_url:
                st.error(f"'{character_name}' 페이지를 찾을 수 없습니다.")
                return None
            
            st.success(f"페이지 발견: {page_url}")
            
            # 2단계: 원시 텍스트 추출
            with st.spinner("페이지 분석 중..."):
                response = self.session.get(page_url, timeout=15)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # 본문 텍스트 추출 (더 유연한 방식)
                content_div = (
                    soup.find('div', {'class': 'wiki-content'}) or 
                    soup.find('div', {'id': 'content'}) or
                    soup.find('div', {'class': 'document'}) or
                    soup.find('div', {'class': 'wiki-inner-content'}) or
                    soup.find('main') or
                    soup.find('article')
                )
                
                if not content_div:
                    # 마지막 시도: body에서 텍스트 추출
                    content_div = soup.find('body')
                
                if not content_div:
                    st.error("페이지 내용을 찾을 수 없습니다.")
                    return None
                
                raw_text = content_div.get_text()
                
                # 텍스트 정리 (불필요한 공백, 특수문자 제거)
                raw_text = re.sub(r'\s+', ' ', raw_text)  # 연속 공백을 하나로
                raw_text = re.sub(r'[^\w\s가-힣.,!?()[\]{}:;"\'-]', '', raw_text)  # 특수문자 제거
            
            # 3단계: 이미지 추출 및 업로드 (옵션)
            character_image_url = None
            if extract_image:
                with st.spinner("🖼️ 캐릭터 이미지 추출 중..."):
                    image_url = self.extract_character_image(soup, character_name)
                    if image_url:
                        st.info(f"이미지 발견: {image_url}")
                        character_image_url = self.download_and_upload_image(image_url, character_name)
                    else:
                        st.info("적합한 캐릭터 이미지를 찾을 수 없습니다.")
            
            # 4단계: Bedrock으로 정보 정제 (옵션)
            if use_bedrock_refinement:
                with st.spinner("🤖 AI가 정보를 정제하는 중..."):
                    refined_info = self.refine_character_info_with_bedrock(raw_text, character_name)
                    
                    if refined_info:
                        # 이미지 URL 추가
                        if character_image_url:
                            refined_info['image_url'] = character_image_url
                        
                        st.success("✨ AI 정제 완료! 고품질 캐릭터 정보가 생성되었습니다.")
                        return refined_info
                    else:
                        st.info("AI 정제에 실패했습니다. 기본 추출 방식을 사용합니다.")
            
            # 4단계: 기본 추출 방식 (fallback)
            with st.spinner("기본 방식으로 정보 추출 중..."):
                character_info = self.extract_character_info(page_url)
                
            if character_info:
                # 이미지 URL 추가
                if character_image_url:
                    character_info['image_url'] = character_image_url
                
                # 빈 필드 기본값 설정
                if not character_info['role']:
                    character_info['role'] = f"{character_name}의 역할"
                if not character_info['personality']:
                    character_info['personality'] = f"{character_name}의 독특한 성격"
                if not character_info['background']:
                    character_info['background'] = f"{character_name}의 흥미로운 배경 스토리"
                if not character_info['catchphrase']:
                    character_info['catchphrase'] = f"{character_name}의 멋진 캐치프레이즈!"
                if not character_info['speaking_style']:
                    character_info['speaking_style'] = f"{character_name}만의 독특한 말투"
                
                # 리스트 중복 제거
                character_info['abilities'] = list(set(character_info['abilities']))[:10]  # 최대 10개
                character_info['hobbies'] = list(set(character_info['hobbies']))[:10]  # 최대 10개
                
                st.success("정보 추출 완료!")
                return character_info
            else:
                st.error("정보 추출에 실패했습니다.")
                return None
                
        except Exception as e:
            st.error(f"자동 추출 중 오류 발생: {str(e)}")
            return None

# 사용 예시
if __name__ == "__main__":
    scraper = NamuWikiScraper()
    
    # 테스트
    character_name = "피카츄"
    result = scraper.auto_extract_character(character_name)
    
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
