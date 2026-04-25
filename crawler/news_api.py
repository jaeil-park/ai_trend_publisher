"""
뉴스 API 크롤러 — NewsAPI(글로벌) + Naver News API(국내) + Kakao Search API(바이럴) 이중 소스
환경변수: NEWSAPI_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, KAKAO_API_KEY
"""
from __future__ import annotations

import re
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_NAVER_URL = "https://openapi.naver.com/v1/search/news.json"
_KAKAO_BLOG_URL = "https://dapi.kakao.com/v2/search/blog"
_KAKAO_CAFE_URL = "https://dapi.kakao.com/v2/search/cafe"


class NewsApiCrawler:
    """외부 뉴스 API를 호출해 원시 기사 목록을 반환한다."""

    def __init__(self, api_key: str = "") -> None:
        self.newsapi_key = api_key or os.getenv("NEWSAPI_KEY", "")
        self.naver_client_id = os.getenv("NAVER_CLIENT_ID", "")
        self.naver_client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
        self.kakao_api_key = os.getenv("KAKAO_API_KEY", "")

    def fetch(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """
        NewsAPI → Naver → Kakao 순으로 시도하고 합산하여 반환한다.
        각 소스가 실패해도 다른 소스에서 계속 수집한다.

        Returns:
            [{"title": str, "content": str, "source": str}, ...]
        """
        items: list[dict[str, Any]] = []
        per_source = max(max_results, 10)  # 소스당 최대 10개 수집

        if self.newsapi_key:
            try:
                items.extend(self._fetch_newsapi(query, per_source))
            except Exception as e:
                print(f"[NewsApiCrawler] NewsAPI 실패 (무시): {e}")

        if self.naver_client_id and self.naver_client_secret:
            try:
                items.extend(self._fetch_naver(query, per_source))
            except Exception as e:
                print(f"[NewsApiCrawler] Naver API 실패 (무시): {e}")

        if self.kakao_api_key:
            try:
                items.extend(self._fetch_kakao(query, per_source))
            except Exception as e:
                print(f"[NewsApiCrawler] Kakao API 실패 (무시): {e}")

        if not items:
            raise RuntimeError(
                "유효한 API 키가 없습니다. .env에 NEWSAPI_KEY, NAVER_CLIENT_ID, "
                "또는 KAKAO_API_KEY 를 설정하세요."
            )

        return items[:max_results * 3]  # 더 많이 전달하여 manager에서 필터링

    def _fetch_newsapi(self, query: str, max_results: int) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "language": "ko",
            "pageSize": max_results,
            "sortBy": "publishedAt",
            "apiKey": self.newsapi_key,
        }
        resp = requests.get(_NEWSAPI_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "title": a.get("title") or "",
                "content": a.get("description") or a.get("content") or "",
                "source": a.get("source", {}).get("name") or "NewsAPI",
            }
            for a in data.get("articles", [])
        ]

    def _fetch_naver(self, query: str, max_results: int) -> list[dict[str, Any]]:
        headers = {
            "X-Naver-Client-Id": self.naver_client_id,
            "X-Naver-Client-Secret": self.naver_client_secret,
        }
        params = {"query": query, "display": max_results, "sort": "date"}
        resp = requests.get(_NAVER_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "title": _strip_tags(item.get("title") or ""),
                "content": _strip_tags(item.get("description") or ""),
                "source": item.get("link") or "Naver News",
            }
            for item in data.get("items", [])
        ]

    def _fetch_kakao(self, query: str, max_results: int) -> list[dict[str, Any]]:
        headers = {"Authorization": f"KakaoAK {self.kakao_api_key}"}
        # 블로그와 카페에서 각각 절반씩 수집
        size_per_source = max(1, max_results // 2)
        params = {"query": query, "size": size_per_source, "sort": "recency"}
        
        results = []
        for url in [_KAKAO_BLOG_URL, _KAKAO_CAFE_URL]:
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for doc in data.get("documents", []):
                        results.append({
                            "title": _strip_tags(doc.get("title", "")),
                            "content": _strip_tags(doc.get("contents", "")),
                            "source": doc.get("url") or "Kakao Search",
                        })
            except Exception as e:
                print(f"[NewsApiCrawler] Kakao API error ({url}): {e}")
                
        return results


def _strip_tags(text: str) -> str:
    """Naver API 응답의 <b>, </b> 등 HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text)
