"""
인스타그램 릴스 자동 업로더 — Meta Instagram API + Catbox Bridge 기반
환경변수: INSTAGRAM_ACCESS_TOKEN

업로드 플로우:
  1. 로컬 mp4 -> Catbox에 임시 업로드하여 공개 URL 획득 (video_url)
  2. Instagram API 컨테이너 생성 (POST /v22.0/me/media)
  3. 컨테이너 처리 대기 (GET /v22.0/{container_id} 폴링)
  4. 릴스 게시 (POST /v22.0/me/media_publish)
"""
from __future__ import annotations

import os
import random
import shutil
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE = "https://graph.instagram.com/v22.0"
CATBOX_API = "https://catbox.moe/user/api.php"
UPLOADED_DIR = Path("output/uploaded")

POLL_TIMEOUT = 120
POLL_INTERVAL = 5


class InstagramUploader:
    """새로운 Instagram API와 Catbox.moe를 연동하여 릴스를 업로드한다."""

    def __init__(self) -> None:
        self.access_token: str = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")

    # ------------------------------------------------------------------
    # 공개 진입점 (main.py 호환)
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """토큰 존재 여부 확인 및 API 연결성 테스트."""
        if not self.access_token:
            print("[uploader] INSTAGRAM_ACCESS_TOKEN 환경변수가 누락되었습니다.")
            return False

        # 로그인 시 장기 토큰 수명 연장 (Token Refresh)
        self._refresh_token()

        try:
            resp = requests.get(
                f"{GRAPH_BASE}/me",
                params={
                    "fields": "id,username",
                    "access_token": self.access_token,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            username = data.get("username", data.get("id", "unknown"))
            print(f"[uploader] Instagram API 인증 확인 완료 (계정: @{username})")
            return True
        except Exception as e:
            print(f"[uploader] 토큰 검증 실패: {e}")
            return False

    def upload_reel(self, video_path: Path, caption: str) -> bool:
        """
        로컬 mp4 파일을 Catbox 브릿지를 통해 서버에 올린 뒤 인스타그램에 게시한다.
        """
        if not video_path.exists():
            print(f"[uploader] 파일 없음: {video_path}")
            return False

        print(f"\n[uploader] ▶ 브릿지 연동 업로드 시작: {video_path.name}")
        try:
            # 1. Catbox 브릿지 업로드
            video_url = self._upload_to_catbox(video_path)
            if not video_url:
                return False
            
            # 2. 미디어 컨테이너 생성
            container_id = self._create_container(video_url, caption)
            if not container_id:
                return False
            
            # 3. 인스타그램 서버 처리 대기
            if not self._poll_container(container_id):
                return False
            
            # 4. 릴스 최종 게시
            media_id = self._publish(container_id)
            if not media_id:
                return False

            print(f"[uploader] ✅ 릴스 게시 완료! media_id={media_id}")
            self._archive(video_path)

            delay = random.uniform(5, 10)
            time.sleep(delay)
            return True

        except Exception as e:
            print(f"[uploader] 업로드 파이프라인 중단 ({video_path.name}): {e}")
            return False

    # ------------------------------------------------------------------
    # 내부 단계 (브릿지 -> IG 연동)
    # ------------------------------------------------------------------

    def _refresh_token(self) -> None:
        """장기 실행 토큰의 유효 기간을 갱신한다."""
        print("[uploader] Instagram 장기 토큰 갱신 시도...")
        try:
            resp = requests.get(
                f"{GRAPH_BASE}/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": self.access_token,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                new_token = resp.json().get("access_token")
                if new_token:
                    self.access_token = new_token
                    print("[uploader] ✅ 토큰 갱신 성공 (만료 기간 연장됨)")
            else:
                print(f"[uploader] ⚠️ 토큰 갱신 실패 (무시됨): {resp.text}")
        except Exception as e:
            print(f"[uploader] ⚠️ 토큰 갱신 에러: {e}")

    def _upload_to_catbox(self, video_path: Path) -> str | None:
        """Catbox에 파일을 업로드하여 Public URL을 얻어낸다."""
        print("[uploader]   1/4 Catbox 브릿지 터널링 업로드 중...")
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                with video_path.open("rb") as f:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                    }
                    resp = requests.post(
                        CATBOX_API,
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": f},
                        headers=headers,
                        timeout=60,
                    )
                
                if resp.status_code == 200 and resp.text.startswith("https://"):
                    print(f"[uploader]   브릿지 확보 성공: {resp.text}")
                    return resp.text.strip()
                    
                print(f"[uploader]   브릿지 업로드 실패 (시도 {attempt}/{max_retries}): [{resp.status_code}] {resp.text}")
            except Exception as e:
                print(f"[uploader]   Catbox API 에러 (시도 {attempt}/{max_retries}): {e}")
            
            if attempt < max_retries:
                time.sleep(5 * attempt)  # 5초, 10초 점진적 대기
        return None

    def _create_container(self, video_url: str, caption: str) -> str | None:
        """획득한 Public URL을 통해 Instagram 컨테이너를 생성한다."""
        print("[uploader]   2/4 Instagram 미디어 컨테이너 생성...")
        resp = requests.post(
            f"{GRAPH_BASE}/me/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "access_token": self.access_token,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[uploader]   컨테이너 생성 실패: {resp.json()}")
            return None
            
        container_id = resp.json().get("id")
        print(f"[uploader]   container_id={container_id}")
        return container_id

    def _poll_container(self, container_id: str) -> bool:
        """컨테이너 처리가 FINISHED 될 때까지 대기한다."""
        print("[uploader]   3/4 Instagram 비디오 처리 대기...")
        elapsed = 0
        while elapsed < POLL_TIMEOUT:
            resp = requests.get(
                f"{GRAPH_BASE}/{container_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": self.access_token,
                },
                timeout=10,
            )
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status_code", "")
                
                if status == "FINISHED":
                    print(f"[uploader]   비디오 분석 완료 ({elapsed}s)")
                    return True
                if status == "ERROR":
                    print(f"[uploader]   비디오 처리 오류: {data}")
                    return False
                    
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            
        print("[uploader]   타임아웃 — 컨테이너 처리 미완료")
        return False

    def _publish(self, container_id: str) -> str | None:
        """준비된 컨테이너를 피드에 게시한다."""
        print("[uploader]   4/4 최종 릴스 게시...")
        resp = requests.post(
            f"{GRAPH_BASE}/me/media_publish",
            params={
                "creation_id": container_id,
                "access_token": self.access_token,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[uploader]   게시 실패: {resp.json()}")
            return None
            
        return resp.json().get("id")

    def _archive(self, video_path: Path) -> None:
        """완료된 비디오를 아카이브 디렉토리로 이동."""
        UPLOADED_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOADED_DIR / video_path.name
        shutil.move(str(video_path), str(dest))
        print(f"[uploader] 아카이브: {video_path.name} → output/uploaded/")
