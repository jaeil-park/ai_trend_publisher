"""
크롤러 매니저 — 모든 소스의 데이터를 수집하고 정규화한다.
"""
from __future__ import annotations

import json
import time
import os
import requests
from datetime import datetime
from pathlib import Path
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

    def collect(self, query: str = "가성비 핫이슈", max_retries: int = 3, retry_delay: float = 2.0) -> list[NormalizedItem]:
        """
        모든 소스에서 데이터를 수집하고 정규화하여 반환한다. (실패 시 재시도 로직 포함)

        Returns:
            [{"title": str, "content": str, "source": str}, ...]
        """
        raw_items: list[dict[str, Any]] = []

        # NewsAPI 크롤링 재시도
        for attempt in range(1, max_retries + 1):
            try:
                raw_items.extend(self.news_crawler.fetch(query=query))
                break
            except Exception as e:
                print(f"[CrawlerManager] news_api error (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay)

        # 커뮤니티 스크래퍼 재시도
        for scraper in self.community_crawlers:
            for attempt in range(1, max_retries + 1):
                try:
                    raw_items.extend(scraper.fetch(board="hot"))
                    break
                except Exception as e:
                    print(f"[CrawlerManager] {scraper.site} error (attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        time.sleep(retry_delay)

        return self._normalize(raw_items)

    def _load_history(self) -> dict[str, float]:
        """posted_history.json 에서 기존에 업로드한 기사 식별자(제목/URL)와 타임스탬프를 불러온다."""
        data = None
        gist_id = os.getenv("GIST_ID")
        gh_pat = os.getenv("GH_PAT")

        # 1. Gist에서 데이터 로드 시도
        if gist_id and gh_pat:
            try:
                headers = {"Authorization": f"token {gh_pat}", "Accept": "application/vnd.github.v3+json"}
                resp = requests.get(f"https://api.github.com/gists/{gist_id}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    files = resp.json().get("files", {})
                    if "posted_history.json" in files:
                        data = json.loads(files["posted_history.json"]["content"])
            except Exception as e:
                print(f"[CrawlerManager] Gist 로드 실패, 로컬 폴백 시도: {e}")

        # 2. 로컬 파일에서 로드 시도 (Gist 실패 또는 미설정 시)
        if data is None:
            history_file = Path("posted_history.json")
            if history_file.exists():
                try:
                    with history_file.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as e:
                    print(f"[CrawlerManager] 로컬 히스토리 로드 실패: {e}")
            
        if data is None:
            data = {}

        try:
            now = datetime.now().timestamp()
            thirty_days_sec = 30 * 24 * 60 * 60
            
            # 기존 레거시 데이터(리스트 형식) 하위 호환
            if isinstance(data, list):
                return {str(item): now for item in data}
                
            # 30일 이내의 데이터만 필터링하여 반환
            if isinstance(data, dict):
                return {
                    str(k): float(v)
                    for k, v in data.items()
                    if (now - float(v)) <= thirty_days_sec
                }
            return {}
        except Exception as e:
            print(f"[CrawlerManager] 히스토리 로드 실패: {e}")
            return {}

    def update_history(self, items: list[NormalizedItem]) -> None:
        """렌더링/업로드가 확정된 뉴스 항목들을 히스토리에 추가한다."""
        history_file = Path("posted_history.json")
        history = self._load_history()
        now = datetime.now().timestamp()
        
        for item in items:
            history[item["title"]] = now
            if item["source"] and item["source"] != "unknown":
                history[item["source"]] = now
                
        # 1. Gist 업데이트 시도
        gist_id = os.getenv("GIST_ID")
        gh_pat = os.getenv("GH_PAT")
        if gist_id and gh_pat:
            try:
                headers = {"Authorization": f"token {gh_pat}", "Accept": "application/vnd.github.v3+json"}
                payload = {
                    "files": {
                        "posted_history.json": {
                            "content": json.dumps(history, ensure_ascii=False, indent=2)
                        }
                    }
                }
                requests.patch(f"https://api.github.com/gists/{gist_id}", headers=headers, json=payload, timeout=10)
                print("[CrawlerManager] ☁️ Gist 원격 히스토리 업데이트 성공")
            except Exception as e:
                print(f"[CrawlerManager] Gist 업데이트 실패: {e}")

        # 2. 로컬 파일에도 기록 (로컬 테스트용)
        history_file = Path("posted_history.json")
        try:
            with history_file.open("w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CrawlerManager] 로컬 히스토리 업데이트 실패: {e}")

    def _normalize(self, items: list[dict[str, Any]]) -> list[NormalizedItem]:
        """원시 데이터를 정규화하고 유사한 제목(중복 뉴스)을 제거한다."""
        import difflib
        
        history = set(self._load_history().keys())
        normalized: list[NormalizedItem] = []
        seen_titles: list[str] = []
        
        for item in items:
            title = str(item.get("title", "")).strip()
            source = str(item.get("source", "unknown")).strip()
            if not title:
                continue
                
            # 1. 히스토리 필터링: 이미 업로드된 기사의 제목이나 소스 URL과 일치하면 스킵
            if title in history or source in history:
                continue

            # 중복 검사: 기존 제목들과 유사도 60% 이상이면 스킵
            is_duplicate = False
            for seen in seen_titles:
                similarity = difflib.SequenceMatcher(None, title, seen).ratio()
                if similarity > 0.6:
                    is_duplicate = True
                    break
                    
            if is_duplicate:
                continue
                
            seen_titles.append(title)
            
            normalized.append(
                {
                    "title": title,
                    "content": str(item.get("content", "")),
                    "source": source,
                }
            )
        return normalized
