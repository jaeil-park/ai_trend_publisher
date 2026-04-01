"""
Playwright 기반 렌더러 — HTML 템플릿을 1080×1920 mp4로 녹화한다.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


# Viewport 규격 (720x1280, 9:16 비율)
VIEWPORT_WIDTH = 720
VIEWPORT_HEIGHT = 1280
RECORD_DURATION_SEC = 10


def render_to_video(
    html_path: str | Path,
    output_path: str | Path,
    duration: int = RECORD_DURATION_SEC,
) -> Path:
    """
    HTML 파일을 Playwright로 열고 지정 시간(초) 동안 녹화 후 mp4를 반환한다.

    Args:
        html_path:   렌더링할 HTML 파일 경로
        output_path: 저장할 mp4 파일 경로
        duration:    녹화 시간 (초, 기본 10)

    Returns:
        완성된 mp4 파일의 Path 객체

    Raises:
        FileNotFoundError: html_path가 존재하지 않을 때
        RuntimeError:      Playwright 녹화 실패 시
    """
    html_path = Path(html_path).resolve()
    output_path = Path(output_path).resolve()

    if not html_path.exists():
        raise FileNotFoundError(f"HTML not found: {html_path}")

    # TODO: playwright 설치 확인 (playwright install chromium)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                record_video_dir=str(output_path.parent),
                record_video_size={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            )
            page = context.new_page()
            page.goto(html_path.as_uri())

            # 10초 대기 (애니메이션 / 전환 효과 캡처)
            time.sleep(duration)

            page.close()
            context.close()
            browser.close()

            # Playwright는 context 닫힐 때 video 파일을 확정함
            generated = next(output_path.parent.glob("*.webm"), None)
            if generated is None:
                raise RuntimeError("Playwright did not produce a video file.")

            final = output_path.with_suffix(".mp4")
            _webm_to_mp4(generated, final)
            return final

    except ImportError as e:
        raise RuntimeError("playwright 패키지가 설치되지 않았습니다: pip install playwright") from e


def _webm_to_mp4(src: Path, dst: Path) -> None:
    """
    ffmpeg로 webm → mp4(H.264/AAC) 변환 후 원본 webm 삭제.

    Raises:
        RuntimeError: ffmpeg 미설치 또는 변환 실패 시
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg를 찾을 수 없습니다. https://ffmpeg.org/download.html 에서 설치 후 PATH에 추가하세요."
        )

    cmd = [
        "ffmpeg",
        "-y",                    # 덮어쓰기 허용
        "-i", str(src),
        "-c:v", "libx264",       # H.264 인코딩
        "-preset", "fast",
        "-crf", "18",            # 화질 (0=무손실, 51=최저, 18=고품질)
        "-pix_fmt", "yuv420p",   # 호환성 최대화
        "-c:a", "aac",
        "-movflags", "+faststart",  # 스트리밍 최적화
        str(dst),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 변환 실패:\n{result.stderr}")

    src.unlink()  # 원본 webm 삭제
