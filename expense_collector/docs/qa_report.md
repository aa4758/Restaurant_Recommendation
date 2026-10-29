# QA 리포트 — expense_collector (2026-10-29)

기준: `CLAUDE.md` B절·8.5·9절·13절. 소스 수정 없음. 결함은 `tests/test_qa.py` 의 strict xfail(고치면 통과해야 할 동작을 assert).
결과: `pytest -q` → **74 passed, 12 xfailed**.

**수정 후(2026-10-29)**: QA-1~12 모두 수정, xfail 표시를 지우고 회귀 테스트로 전환 + robots.txt 리다이렉트·상호 나열 오탐 방지 테스트 추가 → **88 passed**. phase5·export 재실행: export 127,691행(금액 없음·음수 950행 제외).

| ID | 수정 |
|---|---|
| QA-1 | 첨부 중 `failed` 가 하나라도 있으면 게시글 `failed` → 재실행 때 다시(받은 첨부는 건너뜀). `blocked`(robots)는 영구라 제외 |
| QA-2 | `store.record`/`save` 가 같은 URL 의 이전 상태 행(failed 등)을 지우고 기록 → URL 당 상태 1행 |
| QA-3 | `BrokenProcessPool` 이면 깨진 첫 파일을 혼자 다시 돌려 또 죽으면 `failed`('자식 프로세스 비정상 종료'), 나머지는 새 풀로 계속 |
| QA-4·5·10 | 주민번호·이메일·`+82`·` - ` 구분 전화·점 구분 카드번호 마스킹 |
| QA-6 | `follow_redirects=False`, hop 마다 robots·간격 확인(최대 10회). robots.txt 자체 리다이렉트는 따라감 |
| QA-7 | 간격·비허용 판정에 우리 UA·ClaudeBot Crawl-delay 중 큰 값 |
| QA-8 | 호스트별 마지막 요청 시각을 프로세스 전역(잠금)으로 공유 |
| QA-9 | 괄호 속·'참석:' 뒤 쉼표 나열에 이름 꼴(상호 분류에 안 걸리는 2~4글자)이 2개 이상이면 가림 |
| QA-11 | export 는 금액 > 0 만 |
| QA-12 | `load_config` 가 `jjinmat_export.path` 를 config 폴더 기준 절대경로로 |


## 항목별 판정

| # | 항목 | 판정 |
|---|---|---|
| 1 | idempotent·이어하기 | **결함** QA-1·2·3 (phase5 는 통과: 매번 전체 재생성, 정렬 고정이라 결과 같음) |
| 2 | robots·요청 간격 | **결함** QA-6·7·8 (같은 클라이언트 안 ≥3초·지수 백오프·robots 비허용 차단·와일드카드는 통과) |
| 3 | PII | **결함** QA-4·5·9·10 (참석자 칸 미저장·export 에 직위/인원/결제수단 없음·`010 0000 0000`·`010.0000.0000` 마스킹은 통과) |
| 4 | 문구 | **통과** — `src/` 코드·설정·리포트 템플릿에 "공직자" 표현 없음 |
| 5 | export 계약 | **결함** QA-11·12 (헤더·source 형식·restaurant 만·≥0.7·base_year·날짜 형식은 통과) |

실데이터 읽기 전용 스캔(건수만): export 128,641행 — 헤더 일치, 날짜·source 형식·base_year 불일치 0, 주민번호·이메일·전화·카드번호 꼴 0.
금액 빈칸 948행·음수 1행(QA-11). 괄호 속 이름 나열 꼴 28건 중 실명으로 보이는 것은 1건 정도(QA-9 영향 작음).

## 결함

| ID | 심각도 | 내용 | 위치 | 제안 수정 |
|---|---|---|---|---|
| QA-1 | 중 | 첨부 일부만 실패한 게시글을 `posts.status='ok'` 로 기록 → 재실행 때 건너뛰어 실패 첨부가 영영 누락 | `src/phase3_collect/board.py:129-131` | 실패가 하나라도 있으면 `failed`(또는 `partial`)로 두고 재실행 때 다시 처리(받은 첨부는 `store.seen` 으로 이미 건너뜀) |
| QA-2 | 하 | `failed`/`blocked` 행은 `seen` 에 안 걸려 재실행마다 같은 URL 행이 새로 쌓임 | `src/phase3_collect/store.py:25-36`, `datagokr.py:36` | `record` 를 (institution_id, source_url) 기준 UPSERT, 또는 재시도 전 이전 failed 행 삭제 |
| QA-3 | 중 | 자식 프로세스를 죽이는 파일(BrokenProcessPool) 하나면 `f.result()` 가 run 전체를 중단, 재실행해도 그 파일이 다시 앞에 와서 영구 정지 | `src/phase4_parse/run.py:95-96` | `f.result()` 를 try 로 감싸 그 file_id 를 `failed`("worker crashed")로 기록, 풀이 깨지면 새 풀로 남은 작업 재제출 |
| QA-4 | 상 | 주민등록번호 꼴(`000000-0000000`)을 가리지 않음 | `src/phase5_merge/normalize.py:137-138` | `\d{6}\s?-\s?[1-4]\d{6}` 마스킹 추가 |
| QA-5 | 중 | 이메일을 가리지 않음 | `normalize.py:137-138` | `[\w.+-]+@[\w-]+(\.[\w-]+)+` 마스킹 추가 |
| QA-6 | 중 | `follow_redirects=True` 라 허용 URL → 비허용 경로(또는 다른 호스트) 리다이렉트를 robots·간격 확인 없이 따라감 | `src/http_client.py:107` | `follow_redirects=False` 로 두고 `request()` 에서 Location 을 직접 따라가며 hop 마다 `allowed`·`_wait` 적용 |
| QA-7 | 하 | ClaudeBot 그룹 규칙은 허용 판정에 쓰지만 그 그룹의 `Crawl-delay` 는 간격에 반영 안 함 | `src/http_client.py:174-176` (`allowed` 164 도 동일) | `max(crawl_delay(ua_token), crawl_delay(ROBOTS_ALSO_CHECK))` |
| QA-8 | 하 | 호스트별 마지막 요청 시각이 `HttpClient` 인스턴스 필드라, 작업자 둘이 같은 호스트(공유 첨부 서버 등)를 치면 3초 미만. 지금은 게시판 호스트로 작업자를 나눠 피하고 있고 실데이터에선 첨부 호스트 공유 0건 → 잠재 결함 | `src/http_client.py:103,114-120`, `board.py:226-228` | 모듈 전역 `dict` + `threading.Lock`(호스트별)으로 `_wait` 공유 |
| QA-9 | 하 | 직위 없이 나열된 이름(`간담회(가나다, 라마바)`, `참석: 가나다, 라마바, 사아자`)을 가리지 않음 | `normalize.py:139-149` | 괄호 안·`참석:` 뒤의 쉼표 나열에서 `_name` 통과 낱말이 2개 이상이면 모두 마스킹 |
| QA-10 | 하 | 번호 변형 미검출: `+82-10-…`, `010 - 0000 - 0000`, 점 구분 카드번호 `0000.0000.0000.0000` | `normalize.py:137-138` | 구분자 `[-.\s]*` 허용, `(\+82[-\s]?)?0?1\d` 접두, 카드 구분자에 `.` 추가 |
| QA-11 | 하 | export 에 금액 빈칸·음수(취소) 행이 들어가 찐맛에서 방문 1회로 셈(계약 "amount 정수") | `src/phase5_merge/merge.py:144-145` | 필터에 `df["amount"].notna() & (df["amount"] > 0)` 추가 |
| QA-12 | 하 | export 경로를 `paths.output` 의 `parent.parent` 로 계산 — 기본 설정에선 맞지만 `paths.output` 을 바꾸면 프로젝트 밖/없는 폴더로 감 | `src/phase5_merge/merge.py:164-165` | `load_config` 에서 `jjinmat_export.path` 도 config 위치 기준 절대경로로 바꾸고 그대로 사용 |

## 의견(결함으로 기록 안 함)
- 붙여 쓴 이름+직위(`가나다과장`, `가나다주무관`)는 `기획과장` 같은 부서+직위와 규칙으로 구별 불가 → 가려지지 않음. `position_only` 도 그대로 남김(통합 CSV 의 `executor_position`, export 엔 없음). 실명 목록 대조가 필요해지면 그때.
- `총무과 가나다` 처럼 부서명 바로 뒤 이름은 가리지 않음. 고치면 `총무과 회의` 같은 오탐이 생겨 보류 권장.
- 8.4 중복 제거가 같은 출처(BOARD-BOARD) 안에도 적용 — 같은 날 같은 가게·같은 금액의 서로 다른 집행(기관장·부기관장 각각)이 합쳐질 수 있다. 키에 `executor_position` 추가 검토.
- phase5 CSV 쓰기는 원자적이지 않음(중단 시 반쪽 `expenses_merged.csv` 를 export 가 읽을 수 있음). 임시 파일에 쓰고 `os.replace` 권장.
- `store.save` 가 파일을 쓴 뒤 커밋 전에 중단되면 재실행 때 `_해시8자리` 붙은 사본이 하나 더 생김(디스크 고아 파일, DB 는 정상).
- 원문 집행목적의 '공직자 재산등록' 같은 행정 용어는 배지 문구가 아니므로 결함 아님.
