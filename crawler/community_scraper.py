"""
커뮤니티 스크레이퍼 — BeautifulSoup 파싱 구현 (dcinside, fmkorea, clien)
"""
from __future__ import annotations
from typing import Any
import requests
from bs4 import BeautifulSoup

class CommunityScraper:
    SUPPORTED_SITES = ["dcinside", "fmkorea", "clien"]

    def __init__(self, site: str) -> None:
        if site not in self.SUPPORTED_SITES:
            raise ValueError(f"지원하지 않는 사이트: {site}")
        self.site = site
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def fetch(self, board: str = "hot") -> list[dict[str, Any]]:
        """해당 사이트의 핫게시물 목록을 가져온다."""
        items: list[dict[str, Any]] = []
        try:
            if self.site == "dcinside":
                items = self._fetch_dcinside(board)
            elif self.site == "fmkorea":
                items = self._fetch_fmkorea(board)
            elif self.site == "clien":
                items = self._fetch_clien(board)
        except Exception as e:
            print(f"[{self.site}] 크롤링 실패: {e}")
        return items

    def _fetch_dcinside(self, board: str) -> list[dict[str, Any]]:
        # TODO: CSS 선택자 실제 사이트 맞춤 검증 필요
        # 더미 반환
        return []

    def _fetch_fmkorea(self, board: str) -> list[dict[str, Any]]:
        return []

    def _fetch_clien(self, board: str) -> list[dict[str, Any]]:
        return []
