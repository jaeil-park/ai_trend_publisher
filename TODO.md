# 프로젝트 현황

## 완료
- [x] 프로젝트 스켈레톤 생성 (2026-04-01)
  - `crawler/__init__.py`, `news_api.py`, `community_scraper.py`, `manager.py`
  - `templates/receipt.html`, `chat.html`, `news.html`
  - `renderer.py`, `main.py`
- [x] `output/` 폴더 생성 (.gitkeep 포함) (2026-04-01)
- [x] `requirements.txt` 작성 + 패키지 설치 완료 (2026-04-01)
  - anthropic, playwright, jinja2, python-dotenv, requests, beautifulsoup4
- [x] `crawler/news_api.py` — NewsAPI + Naver News API 이중 소스 구현 (2026-04-01)
- [x] `crawler/community_scraper.py` — BeautifulSoup 파싱 구현 (dcinside, fmkorea, clien) (2026-04-01)
- [x] `renderer.py` — ffmpeg webm→mp4 변환 subprocess 구현 (2026-04-01)
- [x] `main.py` — OpenAI API(`gpt-4o`) 템플릿 선택, 훅/요약 구조화 생성(JSON) 반영 (2026-04-01)
- [x] `main.py` — 템플릿별 변수 주입 고도화 (receipt: 항목 파싱, chat: 말풍선, news: 직접 주입) (2026-04-01)

## 다음 작업 (Next)
- [x] `.env` 파일 생성 및 실제 API 키 입력 (OPENAI_API_KEY, NEWSAPI_KEY 또는 NAVER_*)
- [ ] `playwright install chromium` 실행 (최초 1회)
- [ ] 엔드-투-엔드 테스트: `python main.py`
- [ ] 커뮤니티 스크래퍼 CSS 선택자 검증 (사이트 레이아웃 변경 대응)
- [ ] GitHub Actions 워크플로우 작성 (자동 스케줄 실행)
- [ ] 인스타그램 업로드 자동화 연결

## 아키텍처 메모
- Viewport 고정: 1080×1920 (rules.md 강제)
- 녹화 시간: 10초, 포맷: H.264/AAC mp4 (ffmpeg)
- 정규화 포맷: `[{"title": str, "content": str, "source": str}]`
- 템플릿 키: `receipt` | `chat` | `news`
- LLM: `gpt-4o`, JSON structured output으로 템플릿 결정 및 대본 요약/대사 매핑
