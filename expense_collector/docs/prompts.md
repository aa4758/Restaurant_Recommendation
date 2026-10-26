# Claude Code 프롬프트 모음 — 업무추진비 수집기

각 프롬프트는 **한 Phase 씩** 사용한다. Claude Code 는 Phase 끝에 요약을 보고하고 멈춘다 → 결과를 확인한 뒤 다음 프롬프트를 붙여넣는다.
실행 위치: `C:\Restaurant_Recommendation\expense_collector` 에서 `claude`.

---

## P0. 기획 결정 (코드 작업 전, 1회)

> `CLAUDE.md` 와 `docs/handoff.md` 를 읽고 요약해줘. 그다음 B절의 결정 대기 항목 D-1(공공기관 홈페이지 사전공표 게시판 자동 수집을 찐맛 크롤링 금지 원칙의 예외로 둘지)과 D-2(카페 포함 여부)를 찬성팀/반대팀 토론으로 검토하고, 메인이 중재안을 제시해줘. 근거로 정보공개법상 사전공표 의무, 각 기관 robots.txt·이용약관, 공공누리 유형, 9절 준수사항을 따져줘. 토론 에이전트는 경량 모델, 출력은 `<result>` XML 요약만. 내가 승인하면 결정을 `../docs/01_planning_decision.md` 에 기록하고 `CLAUDE.md` B절의 '결정 대기' 문구를 결과에 맞게 고쳐줘. 승인 전에는 코드를 쓰지 마.

## P1. 골격 + Phase 0 (기관 마스터)

> CLAUDE.md 12절 1~2번을 진행해줘. 이미 있는 `pyproject.toml`·`config.yaml`·`.gitignore` 는 유지하고, `src/` 골격(cli·db·http_client·config 로더)과 SQLite 스키마(institutions, source_survey, board_registry, files, parsed_tables, runs)를 만든 뒤 `status` 명령까지 동작하게 해줘. 그다음 Phase 0 을 실행해 `data/institutions.csv` 를 만들고, 공식 출처마다 접근 가능 여부·사용한 방법을 먼저 보고해줘. 자동으로 못 받는 목록은 추측하지 말고 `needs_review` 로 두고 나에게 파일을 요청해. 유형별 기관 수와 예상 수의 차이를 표로 보고하고 멈춰. db·config·http_client 는 단위 테스트를 붙이고 `python -m pytest -q` 통과 후 커밋.

## P2. 파일럿 Phase 1~2 (10~15곳)

> 유형별 2~3곳씩 파일럿 기관을 골라 근거와 함께 보여주고, Phase 1(3개 출처 조사)과 Phase 2(게시판 분류)를 파일럿에만 실행해줘. 공공데이터포털은 이용약관상 허용되는 목록 조회 수단을 먼저 확인해 보고해. 요청 간격·robots·User-Agent(9절)를 http_client 에서 강제하고, config 의 연락처가 `CHANGE_ME` 면 실행을 거부하게 해. 결과로 출처별 found 비율, 발견한 CMS 패턴(→ `cms_fingerprints.yaml`), 등급 A/B/C 분포, 파일 형식 분포, 문제점을 보고하고 멈춰.

## P3. 전체 확장 Phase 1~2

> 파일럿 결과에서 내가 지적한 점을 반영한 뒤 Phase 1~2 를 전체 기관으로 실행해줘(이어하기 가능해야 함). 끝나면 CMS별·등급별 기관 수, 출처 없는 기관(`foi_candidates.csv`) 수를 보고하고, 기관 수가 많은 CMS 순으로 크롤러 어댑터 구현 계획을 제안하고 멈춰.

## P4. Phase 3 수집

> Phase 3 을 `--source datagokr` 부터 진행해줘. 오픈API 키가 필요하면 `.env` 의 `DATAGOKR_API_KEY` 를 쓰고, 없으면 나에게 요청한 뒤 파일데이터만 받아. 그다음 승인된 범위(P0 결정) 안에서 `--source board` 를 등급 A → B 순으로, CMS 어댑터 1개씩 구현·검증하며 진행해. 기관별 파일 수, 월별 빈 구간, 실패 목록을 보고하고 멈춰.

## P5. Phase 4 파싱

> Phase 4 를 진행해줘. 형식별 파서는 `tests/fixtures/` 의 가상 샘플로 먼저 테스트를 쓰고 구현해(실데이터 커밋 금지). OCR·HWP 의존성은 필요한 형식이 실제로 있을 때만 설치하고 설치 방법(Windows)을 `docs/handoff.md` 에 적어. 형식별 성공률, 실패 파일 목록, OCR 처리 수를 보고하고 멈춰.

## P6. Phase 5 통합 + 찐맛 export

> Phase 5 를 진행해 `expenses_merged.csv`·`unmapped_columns.csv`·`quality_report.md` 를 만들어줘. 정규화·중복 제거·PII 마스킹은 단위 테스트 필수. 이어서 13절 `export-jjinmat` 을 구현하고, 헤더 일치·PII 부재 테스트를 추가해. 품질 리포트 요약(기관별 레코드 수, 결측률, 저신뢰 레코드 수, Top 50 음식점 미리보기)을 보고하고 멈춰. 찐맛 백엔드에서 이름+주소로 매칭해 적재하는 로더가 필요하면 제안만 해줘.

## P7. QA (품질검증팀)

> 품질검증팀 에이전트(상위 모델)로 이 프로젝트를 검증해줘: idempotent·이어하기(중간 중단 후 재실행), robots·요청 간격 준수, PII 누출, 문구 원칙("공직자" 표현), export 계약. 결함은 strict xfail 테스트로 기록하고 리포트를 `docs/qa_report.md` 에 남긴 뒤, 수정 → 테스트 통과 → 커밋.

---

### 매 세션 끝에 붙일 한 줄
> 오늘 한 일과 다음 할 일, 사용자 결정 대기 항목을 `docs/handoff.md` 에 갱신하고 커밋·푸시해줘.
