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

import requests
import jinja2
from dotenv import load_dotenv
from google import genai
from google.genai import types

from crawler.manager import CrawlerManager, NormalizedItem
from renderer import render_to_video

load_dotenv()

# 사용 가능한 템플릿 목록
TEMPLATES: dict[str, Path] = {
    "receipt": Path("templates/receipt.html"),
    "chat": Path("templates/chat.html"),
    "news": Path("templates/news.html"),
}

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ---------------------------------------------------------------------------
# LLM 템플릿 선택 및 데이터 추출
# ---------------------------------------------------------------------------

def process_content_via_llm(items: list[NormalizedItem], query: str = "", max_retries: int = 3, retry_delay: float = 2.0) -> dict[str, Any]:
    """
    Gemini API를 호출하여 여러 개의 뉴스/게시물을 하나의 시퀀스(news_sequence) 템플릿용으로 요약한다.
    검색어(query)를 함께 전달하여 해시태그와 캡션의 주제 적합성을 높인다.
    결과 JSON 스키마 강제.
    """
    # 묶음 데이터 컨텍스트 생성
    context_text = ""
    for idx, item in enumerate(items, 1):
        context_text += f"\n[뉴스{idx}]\n제목: {item['title']}\n출처: {item['source']}\n내용: {item['content'][:500]}\n"

    query_hint = f"오늘의 주제 키워드: '{query}'\n" if query else ""
    today_str = datetime.now().strftime("%Y년 %m월 %d일")

    prompt = f"""[오늘 날짜: {today_str}] 지금은 2026년이야. 아래 뉴스는 모두 {today_str} 기준 최신 이슈야.
다음 여러 개의 뉴스/커뮤니티 게시물들을 최대 5개 묶음으로 엮어 1개의 '뉴스 시퀀스(순차 전환)' 릴스 영상으로 만들거야.
각 뉴스 항목(scene)은 화면에 단 4초만 노출될 것이므로 가독성이 생명이야.
⚠️ 절대 2024년이나 과거 연도를 언급하지 마. 모든 내용은 2026년 현재 기준으로 작성해야 해.
{query_hint}아래 데이터를 분석하여 지정된 JSON 스키마에 맞춰 변환해줘.

{context_text}

반드시 다음 JSON 구조를 반환해야 해 (마크다운 백틱 없이 순수 JSON만 반환):
{{
  "template_type": "news", 
  "instagram_caption": "인스타그램 릴스 본문에 들어갈 찰진 전체 요약 설명 (2~3줄) + 주제 키워드 '{query}'와 직접 관련된 한국어 해시태그 7개. 마지막에 반드시 두 줄 추가: '👉 매일 AI 트렌드를 받아보고 싶다면 팔로우 @jaeil.park' 그리고 '📌 더 깊은 인사이트는 infralog.kr (프로필 바이오 링크)'",
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
            resp = _client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="너는 숏폼(릴스) 콘텐츠 전문 바이럴 마케터이자 데이터 정제 AI야. 오직 JSON만 응답상태로 반환해.",
                    temperature=0.7,
                    response_mime_type="application/json",
                )
            )
            res_str = resp.text or "{}"
            break
        except Exception as e:
            print(f"[main] Gemini API 호출 에러 (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                print("[main] Gemini API 최종 실패. 빈 데이터를 반환합니다.")
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
    # 2026-07 개편: 실행당 릴스 1개로 축소 (기존 5개씩 2개 생성).
    # 크론 2회/일 × 릴스 1개/실행 = 정확히 2개/일을 코드 레벨에서 강제
    # (rate_limiter.py의 플랫폼별 일일한도 2건과 일치 — Meta 스팸 정책 대응)
    items = items[:5]
    chunk_size = 5
    item_chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    print(f"[main] {len(items)}개 아이템 → {len(item_chunks)}개 릴스 생성 예정")

    for chunk_idx, chunk in enumerate(item_chunks):
        try:
            llm_data = process_content_via_llm(chunk, query=query)

            # 빈 콘텐츠 가드 — scenes 없거나 캡션 실패 시 해당 chunk 건너뜀
            scenes = llm_data.get("scenes", [])
            caption = llm_data.get("instagram_caption", "")
            if not scenes:
                print(f"[main] ⚠️ Chunk {chunk_idx}: scenes 비어있음 → 건너뜀 (Gemini 실패 또는 데이터 부족)")
                continue
            if not caption or caption in ("요약 실패", "Trend Now News Sequence"):
                print(f"[main] ⚠️ Chunk {chunk_idx}: 캡션 생성 실패 → 건너뜀")
                continue

            # Jinja2 기반으로 HTML 생성
            tmp_html = inject_template_variables(llm_data)

            output_path = output_dir / f"sequence_reel_{chunk_idx:03d}.mp4"

            # 동적 시간 설정: 장면당 4초 + 여유 1초
            scenes_count = len(scenes)
            calc_duration = max(5, (scenes_count * 4) + 1)

            video = render_to_video(
                html_path=tmp_html,
                output_path=output_path,
                duration=calc_duration
            )

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

    return results


def notify_discord(message: str) -> None:
    """Discord 웹훅으로 발행 결과를 알린다."""
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        return
    try:
        requests.post(webhook, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"[main] Discord 알림 실패: {e}")


if __name__ == "__main__":
    pairs = run_pipeline()
    print(f"\n[main] 총 {len(pairs)}개 영상 생성 완료")

    if not pairs:
        notify_discord("⚠️ AI 트렌드 릴스 생성 실패 — 뉴스 수집 또는 Gemini 처리 오류로 발행 건너뜀")
        raise SystemExit(1)

    ig_count = 0
    th_count = 0

    if pairs and os.getenv("INSTAGRAM_ACCESS_TOKEN"):
        from uploader import InstagramUploader, ThreadsUploader

        ig_uploader = InstagramUploader()
        th_uploader = ThreadsUploader()

        if ig_uploader.login():
            for video_path, caption in pairs:
                if not caption or not video_path.exists():
                    print(f"[main] 건너뜀: 캡션 없음 또는 파일 없음 ({video_path})")
                    continue
                success = ig_uploader.upload_reel(video_path, caption)
                if success:
                    ig_count += 1

                    # Instagram 브릿지 URL을 Threads에 재사용 (중복 업로드 없음)
                    bridge_url = ig_uploader._last_bridge_url
                    if bridge_url and th_uploader.is_configured():
                        th_success = th_uploader.upload_reel(bridge_url, caption)
                        if th_success:
                            th_count += 1

        print(f"[main] Instagram {ig_count}개 / Threads {th_count}개 업로드 완료")

        platforms = []
        if ig_count:
            platforms.append(f"Instagram {ig_count}개")
        if th_count:
            platforms.append(f"Threads {th_count}개")

        if platforms:
            notify_discord(f"✅ AI 트렌드 릴스 발행 완료 | {' + '.join(platforms)} | 키워드: {pairs[0][1][:30] if pairs else '-'}...")
        else:
            notify_discord(f"⚠️ AI 트렌드 릴스 발행 실패 — 영상 {len(pairs)}개 생성됐으나 Instagram 업로드 모두 실패")
    else:
        print("[main] INSTAGRAM_ACCESS_TOKEN 미설정 → 업로드 단계 건너뜀")
