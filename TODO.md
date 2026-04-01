# 프로젝트 현황 (AI Trend Publisher)

**완벽 자동화된 인스타그램 릴스 생성/업로드 파이프라인 (Sequencing 버전)**

## 완료 내역 (Done)
- [x] 프로젝트 스켈레톤 및 코어 파이프라인 생성
- [x] 크롤러 (NewsAPI, 네이버 뉴스, 커뮤니티 파싱)
- [x] 렌더러 (Playwright Headless + ffmpeg webm -> mp4)
- [x] OpenAI LLM 연동 (템플릿 분류, 3줄 요약, 대사 매핑, JSON 스키마 강제)
- [x] **[신규]** 다중 뉴스 Sequencing 병합 렌더링 도입 (비디오 도배 방지, 5개 Chunking)
- [x] **[신규]** 모든 템플릿(news, chat, receipt) 720x1280 (9:16) 상대단위(vw/vh) 반응형 스케일링 적용
- [x] **[신규]** META 공식 Instagram Graph API 업로더 개발 (Catbox 미디어 브릿지 연동)
- [x] **[신규]** GitHub Actions 자동 업로드 워크플로우 구성 (`auto_upload.yml`)
- [x] 민감 세션/미디어 파일 GitHub 노출 방지 (`.gitignore` 및 `git rm --cached`)

## 최종 남은 작업 (Next & Final)
- [ ] 현재까지 변경된 모든 소스 코드를 GitHub에 Push 반영하기
- [ ] GitHub Repository Settings > Secrets 에 `.env` 의 환경변수 정보 동일하게 입력하기
  - `OPENAI_API_KEY`
  - `NEWSAPI_KEY`
  - `NAVER_CLIENT_ID`
  - `NAVER_CLIENT_SECRET`
  - `INSTAGRAM_ACCESS_TOKEN`
- [ ] GitHub Actions 탭에서 `workflow_dispatch` 버튼으로 완전 원격 자동화 E2E 테스트 돌려보기
