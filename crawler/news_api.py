"""
뉴스 API 크롤러 — NewsAPI(글로벌) + Naver News API(국내) 이중 소스
환경변수: NEWSAPI_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
"""
from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_NAVER_URL = "https://openapi.naver.com/v1/search/news.json"


class NewsApiCrawler:
    """외부 뉴스 API를 호출해 원시 기사 목록을 반환한다."""

    def __init__(self, api_key: str = "") -> None:
        self.newsapi_key = api_key or os.getenv("NEWSAPI_KEY", "")
        self.naver_client_id = os.getenv("NAVER_CLIENT_ID", "")
        self.naver_client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    def fetch(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """
        NewsAPI → Naver 순으로 시도하고 합산하여 반환한다.

        Returns:
            [{"title": str, "content": str, "source": str}, ...]
        """
        items: list[dict[str, Any]] = []

        if self.newsapi_key:
            items.extend(self._fetch_newsapi(query, max_results))

        if self.naver_client_id and self.naver_client_secret:
            items.extend(self._fetch_naver(query, max_results))

        if not items:
            raise RuntimeError(
                "유효한 API 키가 없습니다. .env에 NEWSAPI_KEY 또는 "
                "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 를 설정하세요."
            )

        return items[:max_results]

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
                "source": item.get("originallink") or "Naver News",
            }
            for item in data.get("items", [])
        ]


def _strip_tags(text: str) -> str:
    """Naver API 응답의 <b>, </b> 등 HTML 태그 제거."""
    import re
    return re.sub(r"<[^>]+>", "", text)
