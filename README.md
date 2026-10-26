# 찐맛 (JJINMAT) — Restaurant_Recommendation

[한국어](#한국어) · [English](#english)

---

## 한국어

### 한 줄 소개
내 위치 근처에서 **믿을 만한 음식점 3곳**만 골라 주는 모바일 앱입니다.
별점을 일부러 엄격하게 매겨(평균 약 2.5점) 점수 인플레이션을 막고, 공공데이터(인허가·모범음식점·위생등급·공공기관 업무추진비 등)를 근거로 점수를 계산합니다.

- 백엔드: Python FastAPI + SQLite
- 앱: Expo(React Native, TypeScript)

### 이 브랜치의 역할 — `data/signals-load` (PR #7)
**공공기관이 지정한 음식점 목록**을 점수 근거로 적재하는 브랜치입니다 (`backend/app/ingest/load_designations.py`).

| 목록 | 점수에 쓰는 방식 |
|---|---|
| 서울·경기 모범음식점 | 지정 가점 |
| 원산지표시 우수 음식점 | 지정 가점 |
| 백년가게 | 업력 보정만 |
| 경기도 으뜸맛집 | 가이드 신호 |
| 착한가격업소 | 점수 무관, '가성비' 태그만 |

- 가게 매칭: 인허가번호 → 상호+주소 → 좌표 순. 주소가 없는 경기 목록은 같은 시군에 후보가 딱 1곳일 때만 매칭합니다(프랜차이즈 제외).
- 매칭 못 한 행은 `backend/data/out/unmatched_<출처>.csv` 로 남깁니다(개인정보 없음).
- 검수 결과: `docs/qa/report_signals_load.md`

### 브랜치 안내
| 브랜치 | 역할 | 상태 |
|---|---|---|
| `master` | 기준 브랜치. 병합된 기능만 들어감 | 기준 |
| `claude/upbeat-gauss-m8wec0` | 업무추진비 적재·구청 게시판 시범·`expense_collector` 하위 프로젝트 | PR #8 열림 |
| `data/signals-load` | 공공 지정 신호 적재(모범음식점·원산지표시 우수·백년가게·착한가격·경기도 맛집 등) | PR #7 열림 (이 브랜치) |
| `claude/blissful-brahmagupta-w7t81a` | MVP(백엔드·앱·QA·운영), 점수 모델 v2·v2.1, 릴스형 추천 화면 | master에 병합 완료 |
| `data/nationwide-db` | 전국 음식점 DB, 지역별 점수 미리 계산(D1) | master에 병합 완료 |

### 폴더·파일 안내
```
backend/            백엔드 서버 (FastAPI + SQLite)
  app/main.py         API 엔드포인트 (/recommend, /restaurants/{id} 등)
  app/schemas.py      요청·응답 형식 (API 계약)
  app/db.py           DB 스키마와 자동 마이그레이션
  app/service.py      점수 일괄 계산(rebuild_scores), 반경 안 후보 조회
  app/ratelimit.py    글쓰기 요청 횟수 제한
  app/constants.py    공통 상수
  app/scoring/        점수 계산
    prior.py            공공데이터 기반 기본 점수 (모델 v2.1)
    strict.py           시군구별 분위수로 엄격 별점(평균 약 2.5)으로 변환
    bayes.py            사용자 리뷰와 기본 점수를 섞음 (k=20)
    recommend.py        조건 완화, 로테이션, 추천 이유 문장
  app/ingest/         데이터 적재
    license.py, load_license.py   음식점 인허가(일반·휴게음식점)
    sbiz.py                       소상공인 상가정보
    load_designations.py          지정 목록(모범음식점·백년가게 등) (이 브랜치)
    load_food_safety.py           위생등급·행정처분
    signal_common.py, matcher.py  공통 도구: 표 읽기, 가게 매칭(상호+주소/좌표)
    load_seed.py, csv_adapters.py, base.py, kakao.py   샘플 데이터 적재, 어댑터
  data/seed/          작은 샘플 CSV (실데이터·DB는 git에서 제외)
  tests/              pytest 테스트 (QA 결함은 strict xfail 로 기록)
mobile/             앱 (Expo, expo-router)
  app/index.tsx           1. 조건 선택 화면
  app/recommendations.tsx 2. 추천 결과 (세로 카드 덱, 최대 5장)
  app/restaurant/[id].tsx 가게 상세
  app/review/[id].tsx     리뷰 작성
  app/scoring.tsx         점수 기준 설명
  src/api/client.ts       백엔드 API 타입과 호출
  src/components/         공통 UI (리뷰 시트, 버튼 등)
  src/state/              기기 ID·찜·숨김 저장, 위치
  src/theme/              색·글꼴 토큰
docs/               기획·설계 문서
  00_brief.md             공통 브리프
  01_planning_decision.md 기획 결정, 점수 모델, API 계약 (결정이 바뀌면 여기부터 수정)
  02_roadmap.md           단계 로드맵 · 03_handoff.md 현재 상태·다음 할 일
  04_data_plan.md         실데이터 출처와 적재 순서
  design/screens.md       화면 스펙 · qa/*.md QA 리포트
ops/runbook.md      운영 절차 (배포, 데이터 갱신, 적재 명령)
.github/workflows/  CI (백엔드 테스트, 앱 타입 검사)
CLAUDE.md           Claude Code 작업 규칙
```

### 빠른 시작 (PowerShell)
```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.ingest.load_seed            # 샘플 데이터로 DB 만들기
uvicorn app.main:app --reload --port 8000
python -m pytest -q                       # 테스트

cd ..\mobile
npm install
npx expo start                            # Expo Go 로 QR 스캔
```
자세한 내용: `backend/README.md`, `mobile/README.md`, `ops/runbook.md`.

### 꼭 지키는 원칙
- 네이버 등 **크롤링 금지**. 공식 API·공공데이터·제휴·사용자 입력만 씁니다.
  예외는 공공기관이 사전공표한 업무추진비 게시판뿐입니다(robots.txt 준수, 우회 금지, 공공누리 3·4유형 보류).
- 개인정보(작성자·참석자 이름 등)는 적재 전에 지웁니다.
- 업무추진비 배지 문구는 "공공기관 업무추진비 기록 N회"만 씁니다.
- 좋아요/싫어요는 개인화에만 쓰고 점수·순위에는 반영하지 않습니다(테스트로 보장).

---

## English

### In one line
A mobile app that picks just **three trustworthy restaurants** near you.
Ratings are deliberately strict (average ≈ 2.5/5) to avoid star inflation, and scores are built from public data (business licenses, model-restaurant lists, hygiene grades, public-agency expense records, etc.).

- Backend: Python FastAPI + SQLite
- App: Expo (React Native, TypeScript)

### What this branch does — `data/signals-load` (PR #7)
This branch loads **restaurant lists designated by public agencies** as scoring evidence (`backend/app/ingest/load_designations.py`).

| List | How it affects the score |
|---|---|
| Seoul/Gyeonggi model restaurants | Designation bonus |
| Origin-label excellence restaurants | Designation bonus |
| Century stores (백년가게) | Business-age adjustment only |
| Gyeonggi best restaurants | Guide signal |
| Good-price stores (착한가격업소) | No score effect; "value" tag only |

- Store matching: license number → name + address → coordinates. The Gyeonggi lists have no address, so they match only when exactly one candidate exists in the same city (franchises skipped).
- Unmatched rows go to `backend/data/out/unmatched_<source>.csv` (no personal data).
- QA results: `docs/qa/report_signals_load.md`

### Branches
| Branch | Purpose | Status |
|---|---|---|
| `master` | Base branch; only merged work | Base |
| `claude/upbeat-gauss-m8wec0` | Expense loading, district board pilot, `expense_collector` subproject | PR #8 open |
| `data/signals-load` | Public designation signals (model restaurants, origin-label excellence, century stores, good-price stores, Gyeonggi best, etc.) | PR #7 open (this branch) |
| `claude/blissful-brahmagupta-w7t81a` | MVP (backend, app, QA, ops), score model v2/v2.1, reels-style recommendation screen | Merged into master |
| `data/nationwide-db` | Nationwide restaurant DB, precomputed per-region scores (D1) | Merged into master |

### Folders and files
```
backend/            API server (FastAPI + SQLite)
  app/main.py         API endpoints (/recommend, /restaurants/{id}, ...)
  app/schemas.py      Request/response shapes (the API contract)
  app/db.py           DB schema and automatic migrations
  app/service.py      Batch score rebuild (rebuild_scores), nearby candidate lookup
  app/ratelimit.py    Rate limiting for write requests
  app/constants.py    Shared constants
  app/scoring/        Scoring
    prior.py            Base score from public data (model v2.1)
    strict.py           Maps scores to strict stars (avg ≈ 2.5) by district quantiles
    bayes.py            Blends user reviews with the base score (k=20)
    recommend.py        Filter relaxation, rotation, "why" reasons
  app/ingest/         Data loaders
    license.py, load_license.py   Restaurant business licenses
    sbiz.py                       Small-business store data
    load_designations.py          Designation lists (model restaurants, century stores, ...) (this branch)
    load_food_safety.py           Hygiene grades, administrative sanctions
    signal_common.py, matcher.py  Shared tools: table reading, store matching (name+address/coords)
    load_seed.py, csv_adapters.py, base.py, kakao.py   Sample data loading, adapters
  data/seed/          Small sample CSVs (real data and DBs are git-ignored)
  tests/              pytest tests (QA defects recorded as strict xfail)
mobile/             App (Expo, expo-router)
  app/index.tsx           1. Filter selection screen
  app/recommendations.tsx 2. Results (vertical card deck, up to 5)
  app/restaurant/[id].tsx Restaurant detail
  app/review/[id].tsx     Write a review
  app/scoring.tsx         How scoring works
  src/api/client.ts       Backend API types and calls
  src/components/         Shared UI (review sheet, buttons, ...)
  src/state/              Device ID, saved/hidden lists, location
  src/theme/              Color and type tokens
docs/               Planning and design docs
  00_brief.md             Shared brief
  01_planning_decision.md Decisions, score model, API contract (edit this first when decisions change)
  02_roadmap.md           Roadmap · 03_handoff.md current status and next steps
  04_data_plan.md         Real data sources and load order
  design/screens.md       Screen specs · qa/*.md QA reports
ops/runbook.md      Operations (deploy, data refresh, load commands)
.github/workflows/  CI (backend tests, app type check)
CLAUDE.md           Working rules for Claude Code
```

### Quick start (PowerShell)
```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.ingest.load_seed            # build a DB from sample data
uvicorn app.main:app --reload --port 8000
python -m pytest -q                       # tests

cd ..\mobile
npm install
npx expo start                            # scan the QR code with Expo Go
```
More details: `backend/README.md`, `mobile/README.md`, `ops/runbook.md`.

### Ground rules
- **No crawling** (e.g. Naver). Only official APIs, public data, partnerships, and user input.
  The one exception is expense boards that public agencies publish proactively (robots.txt respected, no bypassing, KOGL type 3/4 on hold).
- Personal data (writer and attendee names, etc.) is removed before loading.
- The expense badge text is exactly "공공기관 업무추진비 기록 N회" ("N public-agency expense records").
- Likes/dislikes are for personalization only and never affect scores or ranking (enforced by tests).
