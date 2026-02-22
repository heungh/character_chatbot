#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - 스크래퍼 엔진
NamuWiki + Wikipedia + AI 정제 파이프라인
"""

import boto3
import json
import logging
import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from urllib.parse import quote, urljoin

logger = logging.getLogger("admin_app.scraper_engine")


def _load_config() -> dict:
    try:
        with open("admin_config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


class ContentScraperEngine:
    """나무위키 + Wikipedia + Bedrock AI 정제 엔진"""

    def __init__(self):
        cfg = _load_config()
        region = cfg.get("region", "us-east-1")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        })
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.bucket_name = cfg.get("bucket_name", "")

    # ─── 나무위키 스크래핑 ──────────────────────────────────────────

    def scrape_namuwiki(self, search_term: str) -> Dict[str, Any]:
        """나무위키에서 검색하여 원시 데이터 추출"""
        base_url = "https://namu.wiki"
        result = {"source": "namuwiki", "search_term": search_term, "url": "", "raw_text": "", "images": []}

        try:
            # 직접 접근 시도
            page_url = f"{base_url}/w/{quote(search_term)}"
            resp = self.session.get(page_url, timeout=15)

            if resp.status_code != 200:
                # 검색으로 대체
                search_url = f"{base_url}/Search?q={quote(search_term)}"
                resp = self.session.get(search_url, timeout=15)
                if resp.status_code != 200:
                    return result

            result["url"] = str(resp.url)
            soup = BeautifulSoup(resp.content, "html.parser")

            # 본문 추출
            content_div = (
                soup.find("div", {"class": "wiki-content"})
                or soup.find("div", {"id": "content"})
                or soup.find("div", {"class": "document"})
                or soup.find("article")
                or soup.find("main")
                or soup.find("body")
            )

            if content_div:
                raw_text = content_div.get_text()
                raw_text = re.sub(r"\s+", " ", raw_text).strip()
                result["raw_text"] = raw_text[:10000]

            # 이미지 추출
            result["images"] = self._extract_images(soup)

        except Exception as e:
            logger.error("나무위키 스크래핑 오류: %s", e)

        return result

    # ─── Wikipedia 스크래핑 ─────────────────────────────────────────

    def scrape_wikipedia(self, search_term: str, lang: str = "en") -> Dict[str, Any]:
        """Wikipedia REST API로 검색/추출"""
        result = {"source": "wikipedia", "search_term": search_term, "lang": lang, "url": "", "raw_text": "", "images": []}

        try:
            # Wikipedia REST API - search
            api_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(search_term)}"
            resp = self.session.get(api_url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                result["url"] = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                result["raw_text"] = data.get("extract", "")

                if data.get("thumbnail"):
                    result["images"].append(data["thumbnail"].get("source", ""))
            else:
                # search API 대체
                search_api = f"https://{lang}.wikipedia.org/w/api.php"
                params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": search_term,
                    "format": "json",
                    "srlimit": 1,
                }
                resp = self.session.get(search_api, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    search_results = data.get("query", {}).get("search", [])
                    if search_results:
                        title = search_results[0]["title"]
                        # 찾은 제목으로 다시 요청
                        return self.scrape_wikipedia(title, lang)

            # 상세 텍스트 가져오기 (요약이 짧은 경우)
            if len(result["raw_text"]) < 500:
                html_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{quote(search_term)}"
                html_resp = self.session.get(html_url, timeout=15)
                if html_resp.status_code == 200:
                    soup = BeautifulSoup(html_resp.content, "html.parser")
                    # 주요 섹션 텍스트 추출
                    paragraphs = soup.find_all("p")
                    full_text = " ".join(p.get_text() for p in paragraphs[:20])
                    full_text = re.sub(r"\s+", " ", full_text).strip()
                    result["raw_text"] = full_text[:10000]

        except Exception as e:
            logger.error("Wikipedia 스크래핑 오류: %s", e)

        return result

    # ─── AI 정제 ────────────────────────────────────────────────────

    def refine_content_metadata(self, raw_text: str, title: str) -> Dict[str, Any]:
        """원시 텍스트에서 콘텐츠 메타데이터 AI 추출"""
        prompt = f"""다음은 '{title}'에 대한 원시 텍스트입니다. 콘텐츠 메타데이터를 JSON으로 추출해주세요.

원시 텍스트:
{raw_text[:5000]}

다음 JSON 형식으로 정확히 응답하세요 (JSON만 출력):
{{
  "title": "한글 제목",
  "title_en": "영문 제목",
  "genre": ["장르1", "장르2"],
  "platform": "플랫폼",
  "release_date": "YYYY-MM-DD",
  "format": "극장판/시리즈",
  "runtime": "러닝타임",
  "creator": "원작자",
  "director": ["감독"],
  "writer": ["작가"],
  "production": "제작사",
  "synopsis": "줄거리 (300자 이내)",
  "world_setting": "세계관 설명 (300자 이내)"
}}"""
        return self._invoke_llm(prompt)

    def refine_character_profile(self, raw_text: str, char_name: str, title: str) -> Dict[str, Any]:
        """원시 텍스트에서 캐릭터 프로필 AI 추출"""
        prompt = f"""다음은 '{title}'의 캐릭터 '{char_name}'에 대한 원시 텍스트입니다. 캐릭터 프로필을 JSON으로 추출해주세요.

원시 텍스트:
{raw_text[:5000]}

다음 JSON 형식으로 정확히 응답하세요 (JSON만 출력):
{{
  "name": "한글 이름",
  "name_en": "영문 이름",
  "group": "소속 그룹 (없으면 빈 문자열)",
  "role_type": "protagonist/antagonist/supporting/mentor 중 하나",
  "role_in_story": "스토리 내 역할 (100자 이내)",
  "personality_traits": ["특성1", "특성2", "특성3"],
  "personality_description": "성격 상세 설명 (150자 이내)",
  "abilities": ["능력1", "능력2"],
  "weapon": "무기 (없으면 빈 문자열)",
  "speaking_style": "말투 특징 (100자 이내)",
  "catchphrase": "대표 대사",
  "background": "배경 스토리 (200자 이내)",
  "age": "나이/연령대",
  "species": "인간/반마/마족 등"
}}"""
        return self._invoke_llm(prompt)

    def extract_relationships(self, raw_text: str, character_names: List[str]) -> List[Dict[str, Any]]:
        """원시 텍스트에서 캐릭터 관계 AI 추출"""
        names_str = ", ".join(character_names)
        prompt = f"""다음 텍스트에서 캐릭터들 간의 관계를 추출해주세요.
캐릭터 목록: {names_str}

원시 텍스트:
{raw_text[:5000]}

다음 JSON 배열 형식으로 정확히 응답하세요 (JSON만 출력):
[
  {{
    "source_character": "캐릭터1 slug (영문 소문자)",
    "target_character": "캐릭터2 slug (영문 소문자)",
    "relationship_type": "팀원/연인/적/멘토/가족/부하 중 하나",
    "description": "관계 설명 (100자 이내)",
    "bidirectional": true,
    "key_moments": ["장면1", "장면2"]
  }}
]"""
        result = self._invoke_llm(prompt, expect_array=True)
        return result if isinstance(result, list) else []

    def _invoke_llm(self, prompt: str, expect_array: bool = False):
        """Bedrock Claude 호출"""
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 3000,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                "temperature": 0.3,
            })

            # Sonnet 4.5 시도, 실패 시 Sonnet 4 폴백
            model_ids = [
                "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "us.anthropic.claude-sonnet-4-20250514-v1:0",
            ]
            response = None
            for model_id in model_ids:
                try:
                    response = self.bedrock.invoke_model(modelId=model_id, body=body)
                    break
                except Exception:
                    continue

            if not response:
                return [] if expect_array else {}

            result = json.loads(response["body"].read())
            text = result["content"][0]["text"].strip()

            # 코드블록 제거
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            # JSON 파싱
            if expect_array:
                match = re.search(r"\[.*\]", text, re.DOTALL)
                if match:
                    return json.loads(match.group())
            else:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    return json.loads(match.group())

            return [] if expect_array else {}

        except Exception as e:
            logger.error("LLM 호출 오류: %s", e)
            return [] if expect_array else {}

    # ─── 이미지 처리 ────────────────────────────────────────────────

    def _extract_images(self, soup: BeautifulSoup) -> List[str]:
        """페이지에서 유효한 이미지 URL 추출"""
        images = []
        exclude = ["icon", "logo", "banner", "button", "arrow", "edit", "commons", "advertisement"]
        valid_ext = [".jpg", ".jpeg", ".png", ".webp"]

        for img in soup.find_all("img")[:20]:
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            src_lower = src.lower()
            if any(ex in src_lower for ex in exclude):
                continue
            if not any(ext in src_lower for ext in valid_ext):
                continue
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = "https://namu.wiki" + src
            images.append(src)

        return images[:10]

    def download_and_store_image(self, url: str, content_slug: str, char_slug: str, filename: str = "default.png") -> Optional[str]:
        """이미지를 다운로드하여 S3에 저장"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            if len(resp.content) < 500:
                return None

            content_type = resp.headers.get("content-type", "image/png")
            s3_key = f"content-data/{content_slug}/characters/{char_slug}/images/{filename}"

            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=resp.content,
                ContentType=content_type,
            )
            return s3_key
        except Exception as e:
            logger.error("이미지 저장 오류: %s", e)
            return None
