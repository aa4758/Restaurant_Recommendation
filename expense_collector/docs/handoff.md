# 인수인계 — 업무추진비 수집기 (2026-10-26 기준)

작업 브랜치 `claude/upbeat-gauss-m8wec0` (찐맛 `master` 에서 분기, 이 폴더만 다룸)

## 1. 로컬에서 시작하기 (PowerShell, 최초 1회)
```powershell
cd C:\Restaurant_Recommendation
git fetch
git checkout claude/upbeat-gauss-m8wec0
git pull

cd expense_collector
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # 최초 1회: activate 스크립트 실행 허용 (Y 입력)
python -m venv .venv; .venv\Scripts\activate          # 프롬프트 앞에 (.venv) 가 보여야 함
python -m pip install -e ".[dev]"
copy .env.example .env          # 공공데이터포털 서비스 키가 있으면 입력
notepad config.yaml             # http.user_agent 의 연락처(CHANGE_ME) 를 실제 이메일로
claude                          # docs/prompts.md 의 P0 부터 붙여넣기
```
- `claude` 는 반드시 `expense_collector` 폴더에서 실행(이 폴더 CLAUDE.md 가 우선 적용됨).

## 2. 현재 상태
| 항목 | 상태 |
|---|---|
| 명세(`CLAUDE.md`), 설정(`config.yaml`), 의존성(`pyproject.toml`), git 제외 규칙 | ✅ 준비 |
| `src/` 골격 (cli·config·db·http_client) + 테스트 | ✅ P1 |
| Phase 0 기관 마스터 (`data/institutions.csv`, 미커밋) | ✅ 596곳(기타 110 포함) 중 대상 389 · 제외 207(홈페이지 미확보) |
| Phase 1·2 파일럿 14곳 | ✅ P2 (2026-10-27) — 결과·문제점은 아래 |
| Phase 1·2 전체 (대상 421곳) | ✅ P3 (2026-10-27) — 아래 「P3 전체 결과」 |
| Phase 3~5 | ⬜ |

### P3 전체 결과 (2026-10-27, `logs/phase1_full.log`·`phase2_full.log`)
- Phase 1: 출처 1개 이상 found 190곳(45%) · `foi_candidates.csv` 231곳. DATAGOKR found 18, BOARD found 181.
- BOARD 미발견 240곳 사유: 링크 못 찾음 104 · robots 규칙 64 · robots.txt 응답 없음 50 · robots.txt HTTP 오류 7 · 기간 내 날짜 없음 11 · 게시판 경로 robots 3 · Crawl-delay 과다 1.
- Phase 2(181곳): 등급 A 160 · B 11 · C 10 → 수집 가능 171. CMS unknown 72 · board_do 43 · na_ntt 39 · egovframe_bbs 16 · 기타 11.
- 첨부 형식을 못 읽은 곳 119/181 (어댑터 없는 CMS는 상세 진입 실패) → 형식·공공누리 유형은 어댑터 구현 후 재분류 필요. 읽은 형식: pdf 36 · xlsx 28 · jpg 8 · hwp 6 · hwpx 3 · xls 3.
- na_ntt 39곳 중 26곳 형식 미확인 → 어댑터 매칭 실패 원인 확인 필요.

### 어댑터 확장 후 (2026-10-27)
- 어댑터 8종(`src/phase3_collect/boards/`): na_ntt(보완: RAONK·백틱 업로더, 관세청 `nttSnUrl`, 해경 일반 링크, `nttFileDownload`) · dom_board(`/board/list.*?boardId=BBS_&menuCd=DOM_`, 전북교육청 13곳 등) · kedufine(K-에듀파인 집행 건 목록, 상세 HTML 이 원본) · bbs_ntt(`selectBbsNttList.do`) · board_cnts(`/boardCnts/`, 강원교육청·교육부) · egov_bbs(`selectBoardList.do` 계열로 확장) · sen_fus · gwanak_estimate.
- 게시판 181곳: 등급 A 157 · B 7 · C 17 → 수집 가능 164. 어댑터로 읽는 A·B 86곳. A·B 중 첨부 형식 미확인 41곳(대부분 1~2곳짜리 구조).
- 새로 C 가 된 곳: robots 가 모든 봇에 `/upload/` 금지(대구교육청·교육지원청 5, 인천·충북교육청), 임실 `/board/download.imsil` 금지.
- 형식: xlsx 75 · pdf 44 · html 13 · jpg 8 · hwp 7 · hwpx 7 · xls 5. 공공누리: 표시 없음 154 · 4유형 9 · 1유형 8 · 3유형 4 · 2유형 1.
- 수원 robots `/upload/` 는 특정 봇(Yeti 등)만 금지 → 우리 수집기엔 허용(2026-10-27 사용자 확인). 경북교육청(gbe.kr)도 같은 형태라 허용.
- 보류: 의성·군위·울릉 `/ko/page.do?mnu_uid`(상세를 GET 으로 열면 본문이 비어 있음 — 세션·폼 의존 추정), 상주 상세 robots 금지.
- `data/*.csv` 3개는 2026-10-27 사용자 요청으로 커밋(검토용 export, 실행마다 갱신).

### 사이트맵 탐색 개선 (2026-10-27, `logs/phase1_sitemap.log`·`phase2_final.log`)
- 개선: 인트로·JS 첫 화면이면 `og:url`·메인 경로로 이동(`web.main_candidates`), 따옴표 meta refresh 추적, 리다이렉트 중 robots 차단 판정,
  같은 호스트 사이트맵 > 사전정보공표 > 정보공개 순 4쪽 + 하위 메뉴 1단계(청구·제도·서식·계약 등 제외), 표 행 문맥으로 '바로가기' 링크 판정, '업무 추진비' 띄어쓰기.
- '링크 못 찾음' 104곳 재조사 → 52곳 게시판 발견(기초 34·교육지원청 13·중앙 2·기타 2·광역 1). 남은 50곳은 메뉴가 JS 렌더링이거나 사이트맵에 업무추진비가 없음.
- 전체: 출처 found 240/421(57%) · foi 후보 181. 게시판 233곳: A 198 · B 10 · C 25 → 수집 가능 208. A·B 중 형식 미확인 54.
- 공공누리: 표시 없음 190 · 4유형 18 · 1유형 11 · 3유형 4 · 2유형 1.
- 묶음 어댑터 추가(2026-10-27): scms_web(경남 `.web` 9곳, 카드형·표형) · portal_bbs(`/portal/bbs/`, 칠곡·김천·경기 광주 — `fn_egov_downFile`·`yhLib.file.download`) · dom_board 변형(울진 카드형, 진안 행별 첨부+공개 월, 기장 목록 표 = 집행 건 → 목록 HTML 원본).
  공통 날짜 파싱이 `2026. 9. 3.` 처럼 띄어쓴 날짜도 읽음. → 게시판 233곳 중 A 201 · B 8 · C 24, 수집 가능 209, 어댑터로 읽는 A·B 123곳, A·B 중 형식 미확인 46(모두 1곳짜리 구조).
- 강북구는 브라우저 검사(쿠키+새로고침) 사이트 — 우회하지 않음. robots.txt 일시 응답 실패는 안전하게 '비허용' 처리되므로 C 판정이 이상하면 재분류로 확인(원주 사례).

### Phase 3 수집 (2026-10-27~28)
- 공공데이터포털 18건: 파일 ok 5 · 기관 게시판 링크 9(BOARD 가 담당) · 서울·경기 열린데이터 포털 4(OpenAPI 키 필요, 미신청). 보안문자·한도 화면은 우회 없이 failed.
- 게시판(어댑터 있는 A·B) 123곳 전부 done: 게시글 32,269 · 파일 ok 28,288(1.75GB, 115곳) · 해시 중복 2,938 · 실패 1,113.
  형식 xlsx 11,069 · pdf 10,238 · xls 2,958 · html 2,099 · hwpx 916 · hwp 855 · 이미지 126.
  공공누리(ok 파일): 표시 없음 16,307(105곳) · 4유형 7,308 · 1유형 4,322 · 3유형 256 · 2유형 100.
- 당진: 첨부 1,106건 전부 'PERMISSION-ERROR 접근권한이 없습니다' → 우회 안 함, 등급 C 로 바꾸고 foi 후보로(2026-10-28 사용자 결정).
  `foi_candidates.csv` 에 게시판 등급 C·약관 금지 기관(공공데이터포털 출처 없는 곳)도 넣도록 변경 → 205곳.
- 파일 0개 3곳: 칠곡(portal_bbs)·군위교육지원청(na_ntt) 목록 1쪽에서 게시글 0건, 영양교육지원청 기간 내 게시글 없음 → 확인 필요.
- 빈 달(24개월 중) 0~1개 60곳. 경북·경기 교육지원청 다수가 15~16개월 비어 있음(포항교육지원청은 2026-01 이후만) — 게시 기간이 1년 남짓인 게시판으로 보임, 과거분은 정보공개청구 대상.
- 어댑터 없는 86곳(2026-10-28~29): 범용 어댑터 `boards/generic.py`(날짜 있는 행의 링크·행 첨부·`window.open` 경로, 머리/꼬리/메뉴·뷰어·바로가기·인쇄 링크 제외)
  → `phase3 --source board --scope rest --probe`(목록 1쪽+게시글 1건, `data/output/probe_rest.csv`) 에서 첨부까지 읽힌 38곳만 `--scope rest` 수집(사용자 승인).
  결과: 파일 ok 3,242(34곳) · pdf 1,366 · hwpx 788 · xlsx 551 · hwp 505. 쪽 넘기기가 JS 인 곳(약 20곳)은 1쪽(~10건)만.
  0개: 서울시(원문 다운로드 robots 비허용 405) · 단양(첨부 robots 비허용 231) · 대전 서구(첨부 13건 HTTP 404). 울산 남구는 보도자료 게시판으로 잘못 등록 → 파일 삭제, needs_review·등급 C.
  읽히지 않은 48곳: JS 목록·함수형 다운로드(문체부·농진청 등)·소개 페이지 URL(경북 교육지원청 5곳 등).
- Phase 3 전체: 파일 ok 31,535(BOARD 31,530 · DATAGOKR 5, 1.94GB) · 기관 157곳 · 공공누리 표시 없음 17,659 · 4유형 9,131 · 1유형 4,388 · 3유형 257 · 2유형 100.
- 실행: `phase3 --source board --scope adapter` 는 호스트별 작업자.

### Phase 4 파싱 (2026-10-29)
- `phase4 --workers 4`(프로세스 풀, 31,535개 약 30분). 형식은 확장자보다 머리 바이트로 판별(xls 라벨의 xlsx·html 등). 표 선별은 `phase4_parse/tables.py`(헤더 키워드: 금액 + 일자·사용처 → ok, 그 외 키워드 표 → flagged).
- 결과(파일 기준 성공): xlsx 11,447/11,633 · xls 2,927/2,965 · pdf 10,600/10,698(+ 스캔 905) · html 2,100/2,124 · hwpx 1,624/1,725 · hwp 1,244/1,343 · csv 3/5.
  표 ok 42,347(52만 행) · flagged 4,655(6만 행) · 신뢰도 0.7 미만 564표(PDF 글자 정렬 추출 등).
- 실패 1,590: OCR 필요 1,033(스캔 PDF 905 — 창원 360·성북 116·전북 114·삼척 114 …, 이미지 128) · 업무추진비 표 없음 360 · DRM(SoftCamp) 105(전주) · 미지원·손상 92. 목록 `data/output/parse_failed.csv`.
- 파싱 결과 `data/parsed/*.parquet` 는 원본 컬럼명·실명 칸 포함 가능 → git 제외, Phase 5 에서 PII 제거. 메모리 부족으로 세션이 백그라운드 작업을 죽인 적 있음 → 같은 명령 재실행으로 이어 받음. 게시판이 큰 곳(창원 3,167건·영등포 1,356건·전북 2,535건)은 3초 간격이라 각 반나절.

### Phase 0 출처 (2026-10-26)
- 기관 목록: code.go.kr 기관코드 전체자료(공공데이터포털 15092039 링크) → `data/raw/_phase0/` 캐시. 존폐여부=0, 차수·유형분류로 선별.
- 홈페이지: 정부24 `gov.kr/portal/orgSite`(robots 명시 허용, 92쪽). 교육지원청은 목록에 없음.
- 교육지원청 홈페이지: 시도교육청 홈페이지의 '○○교육지원청' 바로가기 링크(2026-10-27 사용자 승인 (b)). 대전·울산·충남·제주 robots 비허용, 경남·전남광주 미확보 → 제외.
- 기타 범위 `OTHER`(2026-10-27 사용자 결정): 국가행정조직 1차 중 대통령직속(기타)·분류 없음 110곳. 홈페이지 있는 6곳만 대상.
- 실제 수가 예상과 다른 이유: 전남광주통합특별시(2026-05 출범)로 광역·시도교육청 16, 인천 행정체제 개편(2026-07)으로 기초 227, 중앙 51(대통령직인수위원회 포함 — 검토).

## 3. 사용자 결정·준비 대기
| ID | 항목 | 상태 |
|---|---|---|
| D-1 | 기관 홈페이지 게시판 자동 수집 | ✅ 2026-10-26 승인: 전국 기관 단위 판정, 간격 ≥3초 · 2026-10-27 개정: 공공누리 1~4유형·표시 없음 모두 출처 표기 조건 사용 (`../docs/01` 업무추진비 전국 확장) |
| D-2 | 카페를 찐맛 신호에 포함할지 | ✅ 2026-10-26 승인: export 제외, 통합 CSV 엔 보존 |
| — | `config.yaml` User-Agent 연락처 | ✅ 입력됨 |
| — | 공공데이터포털 오픈API 서비스 키(`DATAGOKR_API_KEY`) | 필요 시 신청 |
| — | Tesseract(kor) 설치 — 스캔 PDF 905·이미지 128 | 사용자 확인 대기. `winget install UB-Mannheim.TesseractOCR` → 설치 중 'Additional language data'에서 Korean 선택(또는 `kor.traineddata` 를 `C:\Program Files\Tesseract-OCR\tessdata\` 에) → `.venv\Scripts\pip install pytesseract pypdfium2` |
| — | LibreOffice | 불필요 — HWP5 는 `olefile` 로 직접 읽음(1,244/1,343) |

## 4. 다음 할 일
1. ~~P0~~ → ~~P1~~ → ~~P2~~ → P3(공공데이터포털 ✅ · 어댑터 게시판 123곳 ✅) → 어댑터 없는 86곳 중 38곳 ✅ → 51곳 foi ✅ → P4 파싱 ✅(OCR 미설치분 제외) → **OCR 설치 여부 확인 후 P5 통합** (`docs/prompts.md`)

### P2 파일럿에서 나온 수정 과제 (P3 전에)
- 게시글 링크 대부분이 JS(onclick/form) → 상세 페이지를 못 열어 첨부 형식·공공누리 유형을 못 읽음(관악·행안부·서울시교육청·경기교육청). CMS별 어댑터 필요.
- '업무추진비' 메뉴 탐색 실패: 감사원(JS 렌더링, 링크 0), 국세청(정보공개 하위 메뉴 2단계), 동부교육지원청('행정정보 공개' 띄어쓰기 미일치).
- 목록 1쪽 '기간 내 날짜' 수는 게시글 외 날짜(새소식 등)도 섞일 수 있음 → posts_in_period 는 추정치.
- robots.txt 응답 없음(부산 연결 리셋·포항 타임아웃)도 비허용으로 처리 — 메모가 '비허용'으로만 남음, 구분 필요.
- 공공데이터포털 이용허락범위 문구 추출이 거침(메모 수준).
- (해결 2026-10-27) 표준 `urllib.robotparser` 가 `*`·`$` 와일드카드를 무시해 통일부 `Disallow: /*?*` 등을 놓쳤음 → `http_client.Robots`(RFC 9309) 로 교체, 캐시 90쪽 재점검 위반 0. 통일부 게시판은 등급 C.
- 공공누리 표시 없음도 출처 표기로 사용(2026-10-27 (나)) → 파일럿 수집 가능 6곳(통일부만 등급 C). 단 관악·행안부·서울시교육청의 '표시 없음'은 상세 페이지를 못 열어 생긴 값일 수 있음 → Phase 3 수집 때 게시글마다 유형을 다시 읽어 출처 표기에 써야 함(어댑터 필요).
- 어댑터 `na_ntt`(2026-10-27, `src/phase3_collect/boards/`): `/na/ntt/selectNttList.do` 교육청 CMS. 목록 `nttInfoBtn[data-id]` → 상세 GET, `currPage` 페이징, 첨부 2방식(DEXT5 스크립트 / `.bbsV_file` 미리보기 원본 경로). 경기도교육청(pdf 텍스트)·수원(xlsx) 모두 등급 A, 게시글 확인 결과 공공누리 표시 없음 → 보류.
- 공공누리 판정 개정(2026-10-27): 1~4유형 사용(출처 표기), 미표시만 보류 → 파일럿 수집 가능 1곳(서울시 4유형). 나머지는 대부분 상세 페이지 미진입으로 '미표시'.
