"""
메인 라우터 — 크롤 → LLM (요약 및 템플릿 선택) → 렌더 파이프라인
"""
from __future__ import annotations

import os
import json
import random
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import jinja2
from dotenv import load_dotenv
from openai import OpenAI

from crawler.manager import CrawlerManager, NormalizedItem
from renderer import render_to_video

load_dotenv()

# 사용 가능한 템플릿 목록
TEMPLATES: dict[str, Path] = {
    "receipt": Path("templates/receipt.html"),
    "chat": Path("templates/chat.html"),
    "news": Path("templates/news.html"),
}
BGM_PATH = Path("bgm.mp3")  # 효과음이나 타자 소리 등을 여기에 두면 자동 인식

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


# ---------------------------------------------------------------------------
# LLM 템플릿 선택 및 데이터 추출
# ---------------------------------------------------------------------------

def process_content_via_llm(items: list[NormalizedItem], max_retries: int = 3, retry_delay: float = 2.0) -> dict[str, Any]:
    """
    OpenAI API를 호출하여 여러 개의 뉴스/게시물을 하나의 시퀀스(news_sequence) 템플릿용으로 요약한다.
    결과 JSON 스키마 강제.
    """
    # 묶음 데이터 컨텍스트 생성
    context_text = ""
    for idx, item in enumerate(items, 1):
        context_text += f"\n[뉴스{idx}]\n제목: {item['title']}\n출처: {item['source']}\n내용: {item['content'][:500]}\n"

    prompt = f"""다음 여러 개의 뉴스/커뮤니티 게시물들을 최대 5개 묶음으로 엮어 1개의 '뉴스 시퀀스(순차 전환)' 릴스 영상으로 만들거야.
각 뉴스 항목(scene)은 화면에 단 4초만 노출될 것이므로 가독성이 생명이야.
아래 데이터를 분석하여 지정된 JSON 스키마에 맞춰 변환해줘.

{context_text}

반드시 다음 JSON 구조를 반환해야 해 (마크다운 백틱 없이 순수 JSON만 반환):
{{
  "template_type": "news", 
  "instagram_caption": "인스타그램 릴스 본문에 들어갈 찰진 전체 요약 설명 (2~3줄) + 관련 한국어 해시태그 5개",
  "scenes": [
    {{
      "hook_title": "해당 뉴스의 첫 3초 시선을 끌 강력한 헤드라인 (10자 이내)",
      "summary": "화면에서 4초 안에 읽히도록 아주 짧고 간결한 핵심 요약 (띄어쓰기 포함 25자 이내)",
      "source": "해당 출처명"
    }}
  ]
}}
"""

    res_str = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = _client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "너는 숏폼(릴스) 콘텐츠 전문 바이럴 마케터이자 데이터 정제 AI야. 오직 JSON만 응답상태로 반환해."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
                timeout=30.0  # 타임아웃 30초 강제 설정
            )
            res_str = resp.choices[0].message.content or "{}"
            break
        except Exception as e:
            print(f"[main] OpenAI API 호출 에러 (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                print("[main] OpenAI API 최종 실패. 빈 데이터를 반환합니다.")
                return {"template_type": "news", "scenes": [], "instagram_caption": "요약 실패"}
    
    # JSON Parsing 안전 처리
    res_str = res_str.strip()
    if res_str.startswith("```json"):
        res_str = res_str[7:]
    if res_str.startswith("```"):
        res_str = res_str[3:]
    if res_str.endswith("```"):
        res_str = res_str[:-3]
    res_str = res_str.strip()
    try:
        data = json.loads(res_str)
    except json.JSONDecodeError:
        print("[main] JSON 파싱 에러 발생:", res_str)
        data = {"template_type": "news", "scenes": [], "instagram_caption": "요약 실패"}

    if not data.get("template_type"):
        data["template_type"] = "news"
    
    return data


# ---------------------------------------------------------------------------
# 오디오 (TTS) 및 자막 (SRT) 생성
# ---------------------------------------------------------------------------

def generate_tts(text: str, output_path: Path) -> Path | None:
    """OpenAI TTS API를 사용하여 텍스트를 음성(mp3)으로 변환한다."""
    print("[main] 🎙️ AI 성우(TTS) 오디오 생성 중...")
    try:
        with _client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="nova",  # 세련되고 밝은 여성 성우 목소리로 변경 (릴스에 최적화)
            input=text,
            speed=1.0      # 1.25배속을 제거하여 4초 화면 전환 타이밍과 1:1 싱크를 맞춤
        ) as response:
            response.stream_to_file(str(output_path))
        return output_path
    except Exception as e:
        print(f"[main] TTS 생성 실패: {e}")
        return None


def generate_srt_from_audio(audio_path: Path) -> Path | None:
    """OpenAI Whisper API를 사용하여 오디오 파일에서 자막(SRT)을 추출한다."""
    print("[main] 📝 오디오에서 자막(SRT) 추출 중...")
    try:
        srt_path = audio_path.with_suffix(".srt")
        with audio_path.open("rb") as audio_file:
            transcription = _client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="srt"
            )
        srt_path.write_text(transcription, encoding="utf-8")
        return srt_path
    except Exception as e:
        print(f"[main] SRT 생성 실패: {e}")
        return None

# ---------------------------------------------------------------------------
# 템플릿별 변수 주입
# ---------------------------------------------------------------------------

def inject_template_variables(llm_data: dict[str, Any]) -> str:
    """
    선택된 템플릿(news.html)에 Jinja2를 사용하여 데이터를 주입하고 임시 HTML 파일을 반환한다.
    """
    template_key = llm_data.get("template_type", "news")
    if template_key not in TEMPLATES:
        template_key = "news"
        
    html_content = TEMPLATES[template_key].read_text(encoding="utf-8")
    
    # Jinja2 렌더링 적용 (Jinja 문법인 {% for %} 등을 파싱)
    template = jinja2.Template(html_content)
    
    today = datetime.now().strftime("%Y.%m.%d")
    
    # scenes 데이터와 공통 속성들을 함께 주입 (news 외의 구 템플릿 지원은 배제)
    rendered_html = template.render(
        scenes=llm_data.get("scenes", []),
        published_at=today
    )

    tmp_path = "tmp_render_sequence.html"
    Path(tmp_path).write_text(rendered_html, encoding="utf-8")
    return tmp_path

# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def run_pipeline(query: str | None = None) -> list[tuple[Path, str]]:
    """
    전체 파이프라인 실행: 크롤 → 템플릿 전처리(OpenAI) → 렌더링

    Returns:
        [(비디오 경로, instagram_caption), ...]
    """
    if not query:
        keyword_pool = [
            # 경제/사회/정책
            "서민 경제", "물가", "가성비", "지원금", "부동산", "주식 시장", "청년 정책", "재테크",
            # IT/테크/과학
            "신제품", "AI 트렌드", "테크 핫이슈", "스마트폰", "모빌리티", "게임 신작", "우주 항공",
            # 엔터/라이프/트렌드
            "OTT 신작", "K팝 트렌드", "영화 개봉", "여행 핫플레이스", "건강 관리", "직장인 공감", "팝업스토어"
        ]
        query = random.choice(keyword_pool)
        print(f"[main] 🎲 랜덤 검색어 선택: '{query}'")

    manager = CrawlerManager()
    items = manager.collect(query=query)

    if not items:
        print("[main] 수집된 데이터가 없습니다.")
        return []

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    results: list[tuple[Path, str]] = []
    # 5개씩 묶기 (Chunking)
    chunk_size = 5
    item_chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    for chunk_idx, chunk in enumerate(item_chunks):
        tts_audio_path = None
        tts_srt_path = None
        try:
            llm_data = process_content_via_llm(chunk)
            
            # Jinja2 기반으로 HTML 생성
            tmp_html = inject_template_variables(llm_data)

            output_path = output_dir / f"sequence_reel_{chunk_idx:03d}.mp4"
            
            # [신규] TTS 오디오 텍스트 구성 및 생성
            # 인트로 멘트를 제거하여 첫 번째 화면 전환과 음성 타이밍을 0초부터 정확히 일치시킴
            tts_text = ""
            for scene in llm_data.get("scenes", []):
                # 구두점 대신 줄임표(...)를 사용하여 자연스러운 뜸(Pause)을 유도, 4초 화면과 싱크 동기화
                title = str(scene.get('hook_title', '')).strip()
                summary = str(scene.get('summary', '')).strip()
                if title:
                    tts_text += f"{title}... "
                if summary:
                    tts_text += f"{summary}... "
            
            if tts_text.strip():
                tts_audio_path = output_dir / f"tts_{chunk_idx:03d}.mp3"
                tts_audio_path = generate_tts(tts_text.strip(), tts_audio_path)
                
                # [신규] 생성된 오디오를 기반으로 자막(SRT) 추출
                if tts_audio_path and tts_audio_path.exists():
                    tts_srt_path = generate_srt_from_audio(tts_audio_path)

            # 동적 시간 설정: 장면당 4초 + 여유 1초
            scenes_count = len(llm_data.get("scenes", []))
            calc_duration = (scenes_count * 4) + 1
            
            # [신규] 오디오 길이에 맞춰 비디오 녹화 시간 연장 (ffprobe 활용)
            if tts_audio_path and tts_audio_path.exists():
                try:
                    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(tts_audio_path)]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    a_dur = float(res.stdout.strip())
                    if a_dur > calc_duration:
                        calc_duration = int(a_dur) + 2  # 오디오가 더 길면 길이를 맞추고 2초 여유 추가
                except Exception as e:
                    print(f"[main] ffprobe 오디오 길이 추출 실패: {e}")

            if calc_duration < 5:
                calc_duration = 5

            # [신규] 배경음악/효과음 파일 존재 여부 확인
            current_bgm = BGM_PATH if BGM_PATH.exists() else None

            video = render_to_video(
                html_path=tmp_html, 
                output_path=output_path, 
                duration=calc_duration,
                audio_path=tts_audio_path,
                srt_path=tts_srt_path,
                bgm_path=current_bgm
            )

            caption = llm_data.get("instagram_caption", "Trend Now News Sequence")
            results.append((video, caption))
            print(f"[main] 완료: {video} (총 {scenes_count}개 장면, {calc_duration}초)")

            # [신규] 렌더링이 성공적으로 완료된 청크(Chunk)의 기사들을 히스토리에 기록
            manager.update_history(chunk)

        except Exception as e:
            print(f"[main] 처리 실패 (Chunk {chunk_idx}): {e}")
        finally:
            tmp_path = Path("tmp_render_sequence.html")
            if tmp_path.exists():
                tmp_path.unlink()
            # 사용이 끝난 임시 오디오 파일 정리
            if tts_audio_path and tts_audio_path.exists():
                tts_audio_path.unlink()
            if tts_srt_path and tts_srt_path.exists():
                tts_srt_path.unlink()

    return results


if __name__ == "__main__":
    pairs = run_pipeline()
    print(f"\n[main] 총 {len(pairs)}개 영상 생성 완료")

    if pairs and os.getenv("INSTAGRAM_ACCESS_TOKEN"):
        from uploader import InstagramUploader
        uploader = InstagramUploader()
        if uploader.login():
            for video_path, caption in pairs:
                uploader.upload_reel(video_path, caption)
        print("[main] 인스타그램 업로드 완료")
    else:
        print("[main] INSTAGRAM_ACCESS_TOKEN 미설정 → 업로드 단계 건너뜀")
