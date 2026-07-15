"""
Meta(Instagram/Threads) 도배 방지 가드 — Gist 기반 업로드 이력.

2026-07 자매 프로젝트(ai-card-publisher) Threads 계정정지 사고 이후 Meta
전 플랫폼에 동일 정책 적용. 이 저장소도 Threads 발행이 추가되면서 동일한
"고빈도 게시" 위험에 노출됨 — 크론을 2회/일로 유지하고, 실행당 산출물까지
코드 레벨에서 강제해 정확히 플랫폼별 2개/일을 넘지 않도록 최후 방어선을 둔다.

crawler/manager.py의 posted_history.json Gist 저장 패턴을 그대로 재사용
(별도 파일 "upload_state.json" — 콘텐츠 중복 이력과 개념적으로 분리).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

STATE_FILENAME = "upload_state.json"
LOCAL_STATE_FILE = Path(STATE_FILENAME)

MIN_INTERVAL_HOURS = 8.0   # 플랫폼별 최소 게시 간격 (크론 2회/일, 약 12h 간격)
DAILY_CAP = 2              # 플랫폼별 일일 게시 한도


def _load_state() -> dict:
    """Gist 우선 로드, 실패 시 로컬 파일 폴백 (posted_history.json과 동일 패턴)."""
    gist_id = os.getenv("GIST_ID")
    gh_pat = os.getenv("GH_PAT")

    if gist_id and gh_pat:
        try:
            headers = {"Authorization": f"token {gh_pat}", "Accept": "application/vnd.github.v3+json"}
            resp = requests.get(f"https://api.github.com/gists/{gist_id}", headers=headers, timeout=10)
            if resp.status_code == 200:
                files = resp.json().get("files", {})
                if STATE_FILENAME in files:
                    return json.loads(files[STATE_FILENAME]["content"])
        except Exception as e:
            print(f"[rate_limiter] Gist 로드 실패, 로컬 폴백: {e}")

    if LOCAL_STATE_FILE.exists():
        try:
            return json.loads(LOCAL_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    gist_id = os.getenv("GIST_ID")
    gh_pat = os.getenv("GH_PAT")

    if gist_id and gh_pat:
        try:
            headers = {"Authorization": f"token {gh_pat}", "Accept": "application/vnd.github.v3+json"}
            payload = {"files": {STATE_FILENAME: {"content": json.dumps(state, ensure_ascii=False, indent=2)}}}
            requests.patch(f"https://api.github.com/gists/{gist_id}", headers=headers, json=payload, timeout=10)
        except Exception as e:
            print(f"[rate_limiter] Gist 저장 실패: {e}")

    try:
        LOCAL_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[rate_limiter] 로컬 상태 저장 실패: {e}")


def check_rate_limit(platform: str) -> tuple[bool, str]:
    """(업로드 허용 여부, 차단 사유) 반환. platform: 'instagram' | 'threads'"""
    state = _load_state()
    uploads = state.get(platform, [])
    if not uploads:
        return True, ""

    now = datetime.now(timezone.utc)
    try:
        last_ts = max(datetime.fromisoformat(t) for t in uploads)
    except Exception:
        return True, ""

    elapsed_h = (now - last_ts).total_seconds() / 3600
    if elapsed_h < MIN_INTERVAL_HOURS:
        remain = MIN_INTERVAL_HOURS - elapsed_h
        return False, (
            f"{platform} 도배 방지: 마지막 업로드 후 {elapsed_h:.1f}h 경과 "
            f"(최소 {MIN_INTERVAL_HOURS}h 필요, {remain:.1f}h 대기)"
        )

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = sum(1 for t in uploads if datetime.fromisoformat(t) >= today_start)
    if today_count >= DAILY_CAP:
        return False, f"{platform} 일일 업로드 한도 도달 ({today_count}/{DAILY_CAP}) — Meta 스팸 정책 대응"

    return True, ""


def record_upload(platform: str) -> None:
    """업로드 성공 직후 호출 — 쿨다운/일일카운터 갱신."""
    state = _load_state()
    uploads = state.get(platform, [])
    now_iso = datetime.now(timezone.utc).isoformat()
    uploads.append(now_iso)

    # 7일 이상 지난 기록은 정리 (무한 누적 방지)
    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    uploads = [t for t in uploads if datetime.fromisoformat(t).timestamp() >= cutoff]

    state[platform] = uploads
    _save_state(state)
