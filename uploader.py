"""
인스타그램 + Threads 릴스 자동 업로더 — Meta Graph API 기반
환경변수: INSTAGRAM_ACCESS_TOKEN, THREADS_USER_ID, THREADS_ACCESS_TOKEN,
          GH_PAT, GITHUB_REPOSITORY

Instagram 업로드 플로우:
  1. 로컬 mp4 → 공개 URL 획득 (브릿지 순서: GitHub Releases → transfer.sh → Litterbox)
  2. Instagram API 컨테이너 생성 (POST /v22.0/me/media)
  3. 컨테이너 처리 대기 (GET /v22.0/{container_id} 폴링)
  4. 릴스 게시 (POST /v22.0/me/media_publish)

Threads 업로드 플로우 (Instagram 브릿지 URL 재사용):
  1. Threads 컨테이너 생성 (POST /v1.0/{user_id}/threads, media_type=VIDEO)
  2. 컨테이너 처리 대기 (30초 고정)
  3. Threads 게시 (POST /v1.0/{user_id}/threads_publish)
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

GRAPH_BASE          = "https://graph.instagram.com/v22.0"
THREADS_GRAPH_BASE  = "https://graph.instagram.com/v1.0"
THREADS_POLL_TIMEOUT = 60
GH_API_BASE     = "https://api.github.com"             # 1순위: GitHub Releases (가장 안정적)
GH_UPLOAD_BASE  = "https://uploads.github.com"
GH_RELEASE_TAG  = "media-bridge"                        # 릴리즈 태그 (재사용)
TRANSFER_SH_API = "https://transfer.sh"                # 2순위: 개발자용 파일 전송
LITTERBOX_API   = "https://litterbox.catbox.moe/resources/internals/api.php"  # 3순위: Catbox 임시 저장소
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
        로컬 mp4 파일을 브릿지를 통해 서버에 올린 뒤 인스타그램에 게시한다.
        브릿지 URL은 self._last_bridge_url에 저장되어 Threads 재사용 가능.
        """
        self._last_bridge_url: str | None = None

        if not video_path.exists():
            print(f"[uploader] 파일 없음: {video_path}")
            return False

        print(f"\n[uploader] ▶ 브릿지 연동 업로드 시작: {video_path.name}")
        try:
            # 1. 브릿지 업로드
            video_url = self._upload_to_bridge(video_path)
            if not video_url:
                return False
            self._last_bridge_url = video_url  # Threads 업로드에서 재사용
            
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

    def _upload_to_bridge(self, video_path: Path) -> str | None:
        """
        공개 URL을 확보하기 위해 여러 브릿지 서비스를 순서대로 시도한다.
          1순위: GitHub Releases  (GH_PAT 인증, 가장 안정적)
          2순위: transfer.sh      (PUT, 클라우드 비차단)
          3순위: Litterbox        (POST, Catbox 임시 저장소 72h)
        """
        print("[uploader]   1/4 GitHub Releases 브릿지 업로드 중...")
        url = self._try_github_release(video_path)
        if url:
            return url

        print("[uploader]   GitHub Releases 실패, transfer.sh 폴백 시도...")
        url = self._try_transfer_sh(video_path)
        if url:
            return url

        print("[uploader]   transfer.sh 실패, Litterbox 폴백 시도...")
        url = self._try_litterbox(video_path)
        if url:
            return url

        print("[uploader]   모든 브릿지 서비스 업로드 실패")
        return None

    def _try_github_release(self, video_path: Path) -> str | None:
        """
        GitHub Releases 에셋으로 업로드 후 browser_download_url을 반환한다.
        공개 레포에서는 인증 없이 다운로드 가능 → Instagram API와 호환.
        media-bridge 태그 릴리즈를 재사용하여 스토리지 낭비를 방지한다.
        """
        gh_pat = os.getenv("GH_PAT", "")
        repo   = os.getenv("GITHUB_REPOSITORY", "jaeil-park/ai_trend_publisher")
        if not gh_pat:
            print("[uploader]   GH_PAT 미설정 → GitHub Releases 건너뜀")
            return None

        headers = {
            "Authorization": f"token {gh_pat}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            # 1. 기존 media-bridge 릴리즈 조회 또는 신규 생성
            resp = requests.get(
                f"{GH_API_BASE}/repos/{repo}/releases/tags/{GH_RELEASE_TAG}",
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                release_id = resp.json()["id"]
            else:
                create_resp = requests.post(
                    f"{GH_API_BASE}/repos/{repo}/releases",
                    headers=headers,
                    json={
                        "tag_name": GH_RELEASE_TAG,
                        "name": "Media Bridge",
                        "body": "Instagram Reels 파이프라인용 임시 미디어 호스팅 릴리즈",
                        "draft": False,
                        "prerelease": True,
                    },
                    timeout=10,
                )
                if create_resp.status_code not in (200, 201):
                    print(f"[uploader]   릴리즈 생성 실패: {create_resp.text[:200]}")
                    return None
                release_id = create_resp.json()["id"]

            # 2. 동일 이름의 기존 에셋 삭제 (재업로드 충돌 방지)
            assets_resp = requests.get(
                f"{GH_API_BASE}/repos/{repo}/releases/{release_id}/assets",
                headers=headers, timeout=10,
            )
            if assets_resp.status_code == 200:
                for asset in assets_resp.json():
                    if asset["name"] == video_path.name:
                        requests.delete(
                            f"{GH_API_BASE}/repos/{repo}/releases/assets/{asset['id']}",
                            headers=headers, timeout=10,
                        )

            # 3. 에셋 업로드
            with video_path.open("rb") as f:
                upload_resp = requests.post(
                    f"{GH_UPLOAD_BASE}/repos/{repo}/releases/{release_id}/assets"
                    f"?name={video_path.name}",
                    headers={**headers, "Content-Type": "video/mp4"},
                    data=f,
                    timeout=120,
                )
            if upload_resp.status_code in (200, 201):
                url = upload_resp.json().get("browser_download_url", "")
                if url:
                    print(f"[uploader]   GitHub Releases 확보 성공: {url}")
                    return url
            print(f"[uploader]   에셋 업로드 실패: [{upload_resp.status_code}] {upload_resp.text[:200]}")
        except Exception as e:
            print(f"[uploader]   GitHub Releases 에러: {e}")
        return None

    def _try_transfer_sh(self, video_path: Path) -> str | None:
        """transfer.sh에 PUT 방식으로 업로드 후 URL을 반환한다."""
        for attempt in range(1, 3):
            try:
                with video_path.open("rb") as f:
                    resp = requests.put(
                        f"{TRANSFER_SH_API}/{video_path.name}",
                        data=f,
                        headers={"Max-Days": "1"},
                        timeout=120,
                    )
                if resp.status_code == 200 and resp.text.strip().startswith("https://"):
                    url = resp.text.strip()
                    print(f"[uploader]   transfer.sh 확보 성공: {url}")
                    return url
                print(f"[uploader]   transfer.sh 실패 (시도 {attempt}/2): [{resp.status_code}] {resp.text[:200]}")
            except Exception as e:
                print(f"[uploader]   transfer.sh 에러 (시도 {attempt}/2): {e}")
            if attempt < 2:
                time.sleep(5)
        return None

    def _try_litterbox(self, video_path: Path) -> str | None:
        """Litterbox에 파일을 업로드하여 72h 공개 URL을 반환한다."""
        for attempt in range(1, 3):
            try:
                with video_path.open("rb") as f:
                    resp = requests.post(
                        LITTERBOX_API,
                        data={"reqtype": "fileupload", "time": "72h"},
                        files={"fileToUpload": (video_path.name, f, "video/mp4")},
                        timeout=120,
                    )
                if resp.status_code == 200 and resp.text.strip().startswith("https://"):
                    url = resp.text.strip()
                    print(f"[uploader]   Litterbox 확보 성공: {url}")
                    return url
                print(f"[uploader]   Litterbox 실패 (시도 {attempt}/2): [{resp.status_code}] {resp.text[:200]}")
            except Exception as e:
                print(f"[uploader]   Litterbox 에러 (시도 {attempt}/2): {e}")
            if attempt < 2:
                time.sleep(5)
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


class ThreadsUploader:
    """
    Threads Graph API를 통해 릴스 영상을 발행한다.
    Instagram 업로더가 확보한 브릿지 URL을 재사용하므로 별도 파일 업로드 없음.

    환경변수: THREADS_USER_ID, THREADS_ACCESS_TOKEN
    """

    def __init__(self) -> None:
        self.user_id = os.getenv("THREADS_USER_ID", "")
        self.token   = os.getenv("THREADS_ACCESS_TOKEN", "")

    def is_configured(self) -> bool:
        return bool(self.user_id and self.token)

    def upload_reel(self, video_url: str, caption: str) -> bool:
        """
        공개 video_url을 Threads에 릴스로 게시한다.
        Returns True on success.
        """
        if not self.is_configured():
            print("[threads] THREADS_USER_ID / THREADS_ACCESS_TOKEN 미설정 → 건너뜀")
            return False

        print(f"\n[threads] ▶ Threads 릴스 발행 시작...")

        # 1. 컨테이너 생성
        container_id = self._create_container(video_url, caption)
        if not container_id:
            return False

        # 2. 처리 대기 (Threads는 상태 폴링 대신 고정 대기)
        print(f"[threads]   컨테이너 처리 대기 ({THREADS_POLL_TIMEOUT}초)...")
        time.sleep(THREADS_POLL_TIMEOUT)

        # 3. 게시
        media_id = self._publish(container_id)
        if not media_id:
            return False

        print(f"[threads] ✅ Threads 릴스 게시 완료! media_id={media_id}")
        return True

    def _create_container(self, video_url: str, caption: str) -> str | None:
        """Threads 미디어 컨테이너를 생성하고 container_id를 반환한다."""
        print("[threads]   1/2 컨테이너 생성 중...")
        try:
            resp = requests.post(
                f"{THREADS_GRAPH_BASE}/{self.user_id}/threads",
                params={
                    "media_type": "VIDEO",
                    "video_url": video_url,
                    "text": caption[:480],   # Threads 500자 제한
                    "topic_tag": "TECHNOLOGY",
                    "access_token": self.token,
                },
                timeout=30,
            )
            data = resp.json()
            if resp.status_code != 200 or "id" not in data:
                print(f"[threads]   컨테이너 생성 실패: {data}")
                return None
            container_id = data["id"]
            print(f"[threads]   container_id={container_id}")
            return container_id
        except Exception as e:
            print(f"[threads]   컨테이너 생성 에러: {e}")
            return None

    def _publish(self, container_id: str) -> str | None:
        """준비된 컨테이너를 Threads 피드에 게시한다."""
        print("[threads]   2/2 최종 게시 중...")
        try:
            resp = requests.post(
                f"{THREADS_GRAPH_BASE}/{self.user_id}/threads_publish",
                params={
                    "creation_id": container_id,
                    "access_token": self.token,
                },
                timeout=30,
            )
            data = resp.json()
            if resp.status_code != 200 or "id" not in data:
                print(f"[threads]   게시 실패: {data}")
                return None
            return data["id"]
        except Exception as e:
            print(f"[threads]   게시 에러: {e}")
            return None
