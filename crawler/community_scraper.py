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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate"
        }

    def fetch(self, board: str = "hot") -> list[dict[str, Any]]:
        """해당 사이트의 핫게시물 목록을 가져온다."""
        items: list[dict[str, Any]] = []
        if self.site == "dcinside":
            items = self._fetch_dcinside(board)
        elif self.site == "fmkorea":
            items = self._fetch_fmkorea(board)
        elif self.site == "clien":
            items = self._fetch_clien(board)
        return items

    def _fetch_dcinside(self, board: str) -> list[dict[str, Any]]:
        # 디시인사이드 실시간 베스트 갤러리 (실베)
        url = "https://gall.dcinside.com/board/lists/?id=dcbest"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        items = []
        # 일반 게시물 행(tr) 파싱
        for tr in soup.select("tr.us-post"):
            title_tag = tr.select_one("td.gall_tit a:not(.reply_numbox)")
            if not title_tag:
                continue
                
            title = title_tag.text.strip()
            link = title_tag.get("href", "")
            if link.startswith("/"):
                link = "https://gall.dcinside.com" + link
                
            items.append({"title": title, "content": "", "source": link})
            
        return items[:10]  # 상위 10개만 추출

    def _fetch_fmkorea(self, board: str) -> list[dict[str, Any]]:
        # 에펨코리아 포텐 터짐 게시판
        url = "https://www.fmkorea.com/best"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        items = []
        for li in soup.select(".fm_best_board li"):
            title_tag = li.select_one(".title a")
            if not title_tag:
                continue
                
            # 제목 안에 있는 댓글수 태그 제거
            for span in title_tag.select("span"):
                span.decompose()
                
            title = title_tag.text.strip()
            link = title_tag.get("href", "")
            if link.startswith("/"):
                link = "https://www.fmkorea.com" + link
                
            items.append({"title": title, "content": "", "source": link})
            
        return items[:10]

    def _fetch_clien(self, board: str) -> list[dict[str, Any]]:
        # 클리앙 공감게시물
        url = "https://www.clien.net/service/recommend"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        items = []
        for item in soup.select(".list_item"):
            title_tag = item.select_one(".subject_fixed")
            link_tag = item.select_one(".list_subject")
            
            if not title_tag or not link_tag:
                continue
                
            # title 속성에 전체 제목이 들어있음
            title = title_tag.get("title", title_tag.text).strip()
            link = link_tag.get("href", "")
            if link.startswith("/"):
                link = "https://www.clien.net" + link
                
            items.append({"title": title, "content": "", "source": link})
            
        return items[:10]
