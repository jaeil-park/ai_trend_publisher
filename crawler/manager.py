"""
크롤러 매니저 — 모든 소스의 데이터를 수집하고 정규화한다.
"""
from __future__ import annotations

from typing import Any

from crawler.news_api import NewsApiCrawler
from crawler.community_scraper import CommunityScraper


# 정규화된 아이템 타입
NormalizedItem = dict[str, str]  # {"title": str, "content": str, "source": str}


class CrawlerManager:
    """하위 크롤러를 조율하고 결과를 단일 형식으로 정규화한다."""

    def __init__(self, news_api_key: str = "") -> None:
        self.news_crawler = NewsApiCrawler(api_key=news_api_key)
        self.community_crawlers = [
            CommunityScraper(site=s) for s in CommunityScraper.SUPPORTED_SITES
        ]

    def collect(self, query: str = "가성비 핫이슈") -> list[NormalizedItem]:
        """
        모든 소스에서 데이터를 수집하고 정규화하여 반환한다.

        Returns:
            [{"title": str, "content": str, "source": str}, ...]
        """
        raw_items: list[dict[str, Any]] = []

        try:
            raw_items.extend(self.news_crawler.fetch(query=query))
        except Exception as e:
            print(f"[CrawlerManager] news_api error: {e}")

        for scraper in self.community_crawlers:
            try:
                raw_items.extend(scraper.fetch(board="hot"))
            except Exception as e:
                print(f"[CrawlerManager] {scraper.site} error: {e}")

        return self._normalize(raw_items)

    @staticmethod
    def _normalize(items: list[dict[str, Any]]) -> list[NormalizedItem]:
        """원시 데이터를 {"title", "content", "source"} 형태로 정규화한다."""
        normalized: list[NormalizedItem] = []
        for item in items:
            normalized.append(
                {
                    "title": str(item.get("title", "")),
                    "content": str(item.get("content", "")),
                    "source": str(item.get("source", "unknown")),
                }
            )
        return normalized
