"""
Playwright 기반 렌더러 — HTML 템플릿을 1080×1920 mp4로 녹화한다.
"""
from __future__ import annotations

import math
import random
import shutil
import struct
import subprocess
import time
import wave
from pathlib import Path


# Viewport 규격 (720x1280, 9:16 비율)
VIEWPORT_WIDTH = 720
VIEWPORT_HEIGHT = 1280
RECORD_DURATION_SEC = 10


def generate_typing_bgm(output_path: str | Path, duration_sec: int = 60) -> Path:
    """
    Python stdlib만으로 타이핑 클릭 소리 WAV를 생성한다.
    bgm 파일이 없을 때 자동 호출된다.
    """
    output_path = Path(output_path)
    sample_rate = 44100
    frames: list[bytes] = []
    t = 0
    total = duration_sec * sample_rate

    while t < total:
        interval = int(sample_rate * (0.08 + random.random() * 0.08))
        click_len = int(sample_rate * 0.04)

        for i in range(click_len):
            freq = 800 + random.random() * 400
            env = math.exp(-i / (sample_rate * 0.015))
            sample = env * 0.15 * math.sin(2 * math.pi * freq * i / sample_rate)
            sample += env * 0.05 * (random.random() * 2 - 1)
            val = max(-32767, min(32767, int(sample * 32767)))
            frames.append(struct.pack('<h', val))

        silence = interval - click_len
        if silence > 0:
            frames.extend([struct.pack('<h', 0)] * silence)
        t += interval

    with wave.open(str(output_path), 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(frames))

    return output_path


def render_to_video(
    html_path: str | Path,
    output_path: str | Path,
    duration: int = RECORD_DURATION_SEC,
    bgm_path: str | Path | None = None,
) -> Path:
    """
    HTML 파일을 Playwright로 열고 지정 시간(초) 동안 녹화 후 mp4를 반환한다.

    Args:
        html_path:   렌더링할 HTML 파일 경로
        output_path: 저장할 mp4 파일 경로
        duration:    녹화 시간 (초, 기본 10)
        bgm_path:    배경음악/효과음 파일 경로 (선택)

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
            browser = p.chromium.launch(args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ])
            context = browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                record_video_dir=str(output_path.parent),
                record_video_size={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            )
            page = context.new_page()
            page.goto(html_path.as_uri())

            # DOM 로딩 완료 대기 (networkidle 대신 사용 — CDN 폰트 대기 불필요)
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            # 렌더링 안정화 대기
            page.wait_for_timeout(500)

            # 지정된 시간 대기 (Playwright 내부 이벤트 루프 방해 방지)
            page.wait_for_timeout(duration * 1000)

            page.close()
            context.close()
            browser.close()

            # Playwright는 context 닫힐 때 video 파일을 확정함
            generated = next(output_path.parent.glob("*.webm"), None)
            if generated is None:
                raise RuntimeError("Playwright did not produce a video file.")

            final = output_path.with_suffix(".mp4")
            _webm_to_mp4(generated, final, bgm_path)
            return final

    except ImportError as e:
        raise RuntimeError("playwright 패키지가 설치되지 않았습니다: pip install playwright") from e


def _webm_to_mp4(src: Path, dst: Path, bgm_path: str | Path | None = None) -> None:
    """
    ffmpeg로 webm → mp4(H.264/AAC) 변환 및 BGM 합성 후 원본 webm 삭제.

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
    ]

    if bgm_path:
        # BGM이 짧은 효과음일 경우를 대비해 무한 반복(-stream_loop -1) 처리
        cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

    cmd.extend([
        "-c:v", "libx264",       # H.264 인코딩
        "-preset", "fast",
        "-crf", "18",            # 화질 (0=무손실, 51=최저, 18=고품질)
        "-pix_fmt", "yuv420p",   # 호환성 최대화
    ])
    
    if bgm_path:
        # 비디오는 첫 번째 입력(0:v:0), 오디오는 두 번째 입력(1:a:0) 매핑
        cmd.extend(["-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0"])
    else:
        cmd.extend(["-c:a", "aac"])

    cmd.extend(["-movflags", "+faststart", str(dst)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 변환 실패:\n{result.stderr}")

    src.unlink()  # 원본 webm 삭제
