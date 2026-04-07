# 🚀 AI Trend Publisher

**완벽 자동화된 인스타그램 릴스(Reels) 생성 및 업로드 파이프라인**  
트렌드 뉴스와 커뮤니티 핫이슈를 자동으로 수집하여, AI가 요약하고, 숏폼 영상(9:16)으로 렌더링한 뒤 인스타그램에 게시하는 100% 무인 자동화 시스템입니다.

---

## ✨ 핵심 기능 (Features)

1. **지능형 데이터 수집 (Crawling)**
   - **다중 소스 지원:** NewsAPI, 네이버 뉴스 API, 주요 커뮤니티(핫게시물) 등에서 실시간 이슈 수집.
   - **스마트 중복 방지:** GitHub Gist를 활용하여 클라우드 환경에서도 업로드 히스토리를 영구적으로 유지/필터링합니다. (30일 초과 시 자동 삭제)
   - **랜덤 키워드:** 실행될 때마다 다양한 키워드 풀(가성비, 신제품, AI 트렌드 등)을 순회하며 다채로운 소식을 가져옵니다.
   - **재시도(Retry) 로직:** 네트워크 지연이나 API 오류 발생 시 자동으로 재시도하여 안정성을 보장합니다.

2. **LLM 기반 콘텐츠 정제 (AI Processing)**
   - **OpenAI (GPT-4o) 연동:** 수집된 여러 개의 뉴스를 최대 5개 단위(Chunking)로 묶어 '시퀀스(순차 전환)' 방식의 대본으로 요약합니다.
   - **JSON 스키마 강제:** 화면 가독성을 위해 후킹 타이틀(15자 이내)과 짧은 요약(2줄 이내)을 정확한 JSON 형태로 추출합니다.

3. **고해상도 영상 렌더링 (Rendering)**
   - **Playwright + FFmpeg:** HTML/CSS 템플릿(Jinja2)에 데이터를 주입한 뒤, Headless 브라우저로 화면을 캡처(WebM)하고 H.264/AAC 코덱의 MP4로 자동 인코딩합니다.
   - **숏폼 최적화:** 720×1280 (9:16) 릴스/쇼츠 규격 지원. 뉴스 개수에 맞춰 영상 길이를 동적으로 조절합니다.

4. **인스타그램 자동 게시 (Auto Upload)**
   - **Meta Graph API 연동:** 비공식 스크래핑이 아닌 공식 Instagram Graph API(v22.0)를 사용하여 계정 밴(Ban) 위험을 낮췄습니다.
   - **Catbox Media Bridge:** 로컬 렌더링 영상을 Catbox 터널링 서버에 임시 업로드하여 공개 URL을 얻은 후 인스타그램 컨테이너에 전달하여 매끄럽게 업로드합니다.

5. **완전 무인화 (GitHub Actions)**
   - 스케줄러(CRON)를 통해 하루 3번 등 정해진 시간에 클라우드에서 파이프라인이 자동 실행됩니다.

---

## 🛠 환경 구축 및 설치 (Prerequisites)

### 1. 필수 시스템 요구사항
- **Python:** 3.10 이상
- **FFmpeg:** 영상 인코딩을 위해 시스템 PATH에 설치되어 있어야 합니다. (Ubuntu: `sudo apt-get install ffmpeg`, MacOS: `brew install ffmpeg`)

### 2. 패키지 설치
저장소를 클론한 후, 필요한 파이썬 라이브러리를 설치합니다.
```bash
pip install -r requirements.txt

# Playwright 렌더링을 위한 Chromium 브라우저 필수 설치
playwright install chromium
```

### 3. 환경 변수 설정 (`.env`)
프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 아래 API 키들을 입력합니다.
```env
# OpenAI (대본 요약용)
OPENAI_API_KEY="sk-..."

# 크롤링 API 키
NEWSAPI_KEY="..."
NAVER_CLIENT_ID="..."
NAVER_CLIENT_SECRET="..."

# 인스타그램 업로드 토큰 (Meta for Developers에서 획득)
INSTAGRAM_ACCESS_TOKEN="..."

# 클라우드 히스토리(중복 방지) 연동 (선택)
GIST_ID="..."
GH_PAT="..."
```

---

## 🚀 실행 방법 (Usage)

### 로컬 수동 실행
메인 스크립트를 실행하면 전체 파이프라인(크롤링 ➔ 요약 ➔ 렌더링 ➔ 업로드)이 순차적으로 작동합니다.
```bash
python main.py
```
- 생성된 비디오는 `output/` 폴더에 임시 저장되며, 업로드가 완료되면 `output/uploaded/` 디렉토리로 아카이브 됩니다.
- 업로드된 기사의 내역은 `posted_history.json`에 기록됩니다.

### GitHub Actions 완전 자동화
1. 이 레포지토리를 본인의 GitHub에 Push 합니다.
2. **Settings > Secrets and variables > Actions** 메뉴로 이동합니다.
3. `New repository secret` 버튼을 눌러 `.env`에 적었던 5개의 환경변수 키를 모두 등록합니다.
4. **Actions** 탭에서 `AI Trend Auto Upload` 워크플로우를 활성화하면 설정된 스케줄(`cron`)에 따라 매일 자동 실행됩니다. (수동 `workflow_dispatch` 실행도 가능)

---

## 📂 프로젝트 구조 (Structure)

```text
ai_trend_publisher/
├── main.py                     # 파이프라인 메인 엔트리포인트 (크롤링 -> LLM -> 렌더 -> 업로드)
├── renderer.py                 # Playwright + FFmpeg 영상 렌더러
├── uploader.py                 # 인스타그램 Graph API + Catbox 연동 업로더
├── crawler/
│   ├── manager.py              # 크롤링 종합 및 중복 필터링(History) 관리
│   ├── news_api.py             # Naver / NewsAPI 호출 모듈
│   └── community_scraper.py    # 커뮤니티(디시, 펨코, 클리앙) 웹 스크래퍼
├── templates/                  # 영상 렌더링용 HTML/CSS 뷰 템플릿
│   ├── news.html               # 릴스 시퀀스용 템플릿
│   └── ...
├── .github/workflows/          
│   └── auto_upload.yml         # GitHub Actions CI/CD 스케줄러
├── requirements.txt            # 파이썬 의존성 패키지
└── README.md                   # 프로젝트 설명 문서
```

---

## ⚠️ 주의사항 및 팁
- **Instagram API 토큰 만료:** Meta Graph API 토큰은 종류(단기/장기)에 따라 만료될 수 있으니 주기적으로 갱신이 필요할 수 있습니다.
- **Playwright 메모리 누수 방지:** `main.py`는 청크 단위(5개)로 묶어 처리한 후 인스턴스를 즉각 해제하도록 설계되어 장시간 구동에도 안전합니다.
- **게시물 중복 히스토리:** `posted_history.json` 파일은 클라우드(GitHub Actions)에서 실행 시 임시(Ephemeral)로만 존재하므로, 완벽한 중복 방지를 원한다면 AWS S3나 Firebase와 같은 외부 스토리지를 연동하는 방향으로 확장이 필요할 수 있습니다.