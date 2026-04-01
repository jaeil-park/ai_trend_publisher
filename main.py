"""
메인 라우터 — 크롤 → LLM (요약 및 템플릿 선택) → 렌더 파이프라인
"""
from __future__ import annotations

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Any

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

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


# ---------------------------------------------------------------------------
# LLM 템플릿 선택 및 데이터 추출
# ---------------------------------------------------------------------------

def process_content_via_llm(item: NormalizedItem) -> dict[str, Any]:
    """
    OpenAI API를 호출하여 콘텐츠에 맞는 템플릿 키와 세부 데이터를 추출한다.
    결과 JSON 스키마 강제.
    """
    prompt = f"""다음 뉴스/커뮤니티 게시물을 SNS 릴스로 만들 때 가장 어울리는 형식을 고르고, 
해당 형식에 필요한 데이터를 지정된 JSON 스키마에 맞춰 변환해줘.

제목: {item['title']}
내용: {item['content'][:800]}
출처: {item['source']}

선택지:
- receipt: 가격 비교, 가성비 정보, 지출 내역 관련
- chat: 댓글 반응, 갑론을박, 여러 사람의 의견 위주
- news: 속보, 단독, 사건·사고 등 팩트 전달 위주

반드시 다음 JSON 구조를 반환해야 해 (마크다운 백틱 없이 순수 JSON만 반환):
{{
  "template_type": "news", 
  "hook_title": "첫 3초 시선을 끌 강력한 헤드라인 (공통)",
  "news_summary": "뉴스 템플릿용 3줄 요약 텍스트",
  "chat_dialogue": [{{"speaker": "A", "text": "대사1"}}, {{"speaker": "B", "text": "대사2"}}],
  "receipt_items": [{{"name": "항목명", "value": "가치/가격"}}]
}}"""

    response = _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a professional social media content producer."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    try:
        data = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        data = {"template_type": "news", "hook_title": item["title"], "news_summary": "텍스트 분석 실패"}
        
    # 기본값 보장
    if "template_type" not in data or data["template_type"] not in TEMPLATES:
        data["template_type"] = "news"
    
    return data


# ---------------------------------------------------------------------------
# 템플릿별 변수 주입
# ---------------------------------------------------------------------------

def inject_template_variables(item: NormalizedItem, llm_data: dict[str, Any]) -> str:
    """
    선택된 템플릿에 데이터를 주입하고 임시 HTML 파일을 반환한다.
    """
    template_key = llm_data["template_type"]
    html = TEMPLATES[template_key].read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y.%m.%d")

    if template_key == "receipt":
        html = _inject_receipt(html, llm_data, today)
    elif template_key == "chat":
        html = _inject_chat(html, llm_data)
    else:
        html = _inject_news(html, item, llm_data, today)

    tmp_path = f"tmp_render_{template_key}.html"
    Path(tmp_path).write_text(html, encoding="utf-8")
    return tmp_path


def _inject_receipt(html: str, llm_data: dict[str, Any], today: str) -> str:
    """LLM이 파싱한 receipt_items 배열 → <tr> 반복 주입."""
    rows = llm_data.get("receipt_items", [])
    if not rows:
        rows = [{"name": "확인 요망", "value": "0"}]

    items_html = "\n".join(
        f'<tr><td>{str(r.get("name", ""))}</td><td>{str(r.get("value", ""))}</td></tr>' for r in rows
    )
    
    total = _calc_total(rows)

    return (
        html
        .replace("{{TITLE}}", str(llm_data.get("hook_title", ""))[:20])
        .replace("{{DATE}}", today)
        .replace("{{ITEMS}}", items_html)
        .replace("{{TOTAL}}", total)
    )


def _calc_total(rows: list[dict[str, Any]]) -> str:
    """금액 합산. 숫자 파싱 실패 시 '-' 반환."""
    total = 0
    for r in rows:
        val = str(r.get("value", ""))
        digits = re.sub(r"[^\d]", "", val)
        if digits:
            total += int(digits)
    return f"{total:,}원" if total else "-"


def _inject_chat(html: str, llm_data: dict[str, Any]) -> str:
    """LLM이 파싱한 chat_dialogue 배열 → 좌/우 말풍선 교차 주입."""
    dialogue = llm_data.get("chat_dialogue", [])
    if not dialogue:
        dialogue = [{"speaker": "알림", "text": "대화 내용이 부족합니다."}]

    bubbles_html = ""
    sides = ["left", "right"]
    
    for i, msg in enumerate(dialogue[:8]):
        side = sides[i % 2]
        nick = msg.get("speaker", f"익명{i+1}")
        text = msg.get("text", "")
        bubbles_html += (
            f'<div class="bubble {side}">'
            f'<div class="sender">{nick}</div>'
            f'{text}'
            f'</div>\n'
        )

    return (
        html
        .replace("{{CHAT_TITLE}}", str(llm_data.get("hook_title", ""))[:25])
        .replace("{{MESSAGES}}", bubbles_html)
    )


def _inject_news(html: str, item: NormalizedItem, llm_data: dict[str, Any], today: str) -> str:
    """뉴스 헤드라인 직접 주입."""
    return (
        html
        .replace("{{HEADLINE}}", str(llm_data.get("hook_title", "")))
        .replace("{{SUMMARY}}", str(llm_data.get("news_summary", "")))
        .replace("{{SOURCE}}", str(item.get("source", "")))
        .replace("{{PUBLISHED_AT}}", today)
    )

# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def run_pipeline(query: str = "가성비 핫이슈") -> list[Path]:
    """
    전체 파이프라인 실행: 크롤 → 템플릿 전처리(OpenAI) → 렌더링
    """
    manager = CrawlerManager()
    items = manager.collect(query=query)

    if not items:
        print("[main] 수집된 데이터가 없습니다.")
        return []

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    results: list[Path] = []
    template_key = "news"  # fallback (finally 블록 참조용)

    for idx, item in enumerate(items):
        try:
            llm_data = process_content_via_llm(item)
            template_key = llm_data.get("template_type", "news")
            
            tmp_html = inject_template_variables(item, llm_data)

            output_path = output_dir / f"reel_{idx:03d}.mp4"
            video = render_to_video(html_path=tmp_html, output_path=output_path)
            results.append(video)
            print(f"[main] 완료: {video}")

        except Exception as e:
            print(f"[main] item[{idx}] 처리 실패: {e}")
        finally:
            tmp = Path(f"tmp_render_{template_key}.html")
            if tmp.exists():
                tmp.unlink()

    return results


if __name__ == "__main__":
    videos = run_pipeline()
    print(f"\n[main] 총 {len(videos)}개 영상 생성 완료")
