# 찐맛 (JJINMAT) — 위치 기반 음식점 큐레이션 앱

엄격 별점(평균 ≈ 2.5)과 소수 큐레이션(기본 3곳)으로 추천하는 모바일 앱. 백엔드 FastAPI + SQLite, 앱 Expo(React Native, TS).
**현재 상태·다음 할 일·명령어는 `docs/03_handoff.md` 를 먼저 읽을 것.**

## 문서 (결정이 바뀌면 코드보다 문서를 먼저 고친다)
- `docs/00_brief.md` 공통 브리프 · `docs/01_planning_decision.md` 기획 결정·점수 모델(v2.1)·**API 계약**
- `docs/02_roadmap.md` 단계 로드맵 · `docs/04_data_plan.md` 실데이터 출처·적재 순서(D0~D6)
- `docs/design/screens.md` 화면 스펙 · `docs/qa/*.md` QA 리포트 · `ops/runbook.md` 운영

## 일하는 방식 (사용자 지정)
- 팀 분리: 기획(**찬성팀 / 반대팀 토론 → 메인이 중재**), 개발, 디자인, 품질검증, 운영·유지보수.
- 흐름: 기획 결정(사용자 승인) → 01 문서 개정 → 개발 → QA(결함은 strict xfail 테스트로 기록) → 수정 → PR.
- 에이전트 통신 규칙: 핸드오프는 **요약본만**, 시스템 프롬프트 경량화, 하위 에이전트는 하위 임무만 하고 종료,
  모델 티어링(토론·디자인·모바일 = 경량/중간, 백엔드·QA = 상위), **필수 도구만**, 출력은 `<result>...</result>` XML 로 구조화.
- 사용자는 Windows PowerShell 사용 → 명령은 PowerShell 기준. `python -c` 안에 `\"` 금지, here-string(`@' ... '@ | python -`) 사용.

## 원칙 (01 결정)
- 네이버 등 **크롤링 금지** — 공식 API·공공데이터·제휴·사용자 입력만.
- 업무추진비 배지 문구는 "공공기관 업무추진비 기록 N회"만("공직자" 표현 금지). 업무추진비·리뷰 PII 는 적재 전 제거.
- 미슐랭은 법무 확인 전 적재 보류(`--allow-michelin` 없이는 안 들어감). 착한가격업소는 점수 무관('가성비' 태그).
- 휴게음식점은 신규 가게로 만들지 않음(매칭 가게의 음주 불가·폐업 판별만).
- 좋아요/싫어요는 개인화 전용 — 점수·순위·로테이션에 반영 금지(테스트로 보장).

## 코드 지도
- `backend/app/scoring/` prior(v2.1)·strict(시군구 분위수)·bayes(k=20)·recommend(완화·로테이션·이유)
- `backend/app/service.py` 점수 배치(`rebuild_scores`)·후보 조회 · `backend/app/db.py` 스키마·자동 마이그레이션(v1 업그레이드 포함)
- `backend/app/ingest/` license(인허가)·sbiz(상가정보)·load_designations(지정목록)·load_food_safety(위생·처분)·signal_common·matcher
- `mobile/app/` expo-router 화면(recommendations = 릴스 덱) · `mobile/src/api/client.ts` 계약 타입

## 검사
- `cd backend; python -m pytest -q` (커밋 전 전부 통과) · `cd mobile; npx tsc --noEmit`
- 원본 데이터(`backend/data/raw/`)·DB(`*.db`)·`data/out/`·`.env` 는 git 제외.
