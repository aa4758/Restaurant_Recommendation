# 업무추진비 수집기 (expense_collector) — 찐맛 하위 프로젝트

> 상위 `../CLAUDE.md`(찐맛 원칙)도 함께 로드된다. **이 폴더 작업에선 이 문서가 우선**이고, 상위 문서의 `docs/03_handoff.md` 진행 항목은 신경 쓰지 않는다.
> 진행 상태·다음 할 일은 `docs/handoff.md`, 단계별 프롬프트는 `docs/prompts.md`.

## A. 찐맛과의 관계
- 찐맛 점수 모델 v2.1 의 신호 H(업무추진비, 가중 0.25 — 가장 큼)의 원천 데이터를 만든다. (`../docs/01_planning_decision.md`, `../docs/04_data_plan.md`)
- 최종 산출물 중 찐맛으로 넘기는 것은 **13절 export CSV 하나뿐**. 백엔드(`../backend`) 코드는 이 프로젝트에서 수정하지 않는다(필요하면 제안만).
- 독립 실행: 자체 `pyproject.toml`·`.venv`·테스트. 루트에서 `python -m src.cli ...` 는 **이 폴더**(`expense_collector/`) 기준.

## B. 상위 원칙의 적용 (반드시 지킬 것)
- **문구**: 산출물·리포트·코드 주석에 "공직자 맛집" 류 표현 금지. 배지 문구는 "공공기관 업무추진비 기록 N회"만.
- **PII**: 개인 이름·전화·카드번호는 parsed 단계 이후 어디에도 남기지 않는다(8.5). `executor_position`(직위)은 통합 CSV 에만, 찐맛 export 에는 제외.
- **크롤링(결정 대기 D-1)**: 상위 원칙은 "네이버 등 크롤링 금지 — 공식 API·공공데이터·제휴·사용자 입력만". 공공기관 홈페이지의 사전공표 게시판 자동 수집이 이 원칙의 예외로 허용되는지 **사용자 승인 전**에는:
  - 허용: Phase 0·1 의 공식 목록/공공데이터포털 조회, 기관별 홈페이지 **수동 확인 수준의 저빈도 조회**(파일럿 10~15곳, 9절 준수).
  - 보류: Phase 2 전체 기관 자동 분류, Phase 3 `--source board` 대량 수집. 승인되면 `../docs/01_planning_decision.md` 에 결정을 먼저 기록한 뒤 진행.
- **결정 대기 D-2**: 카페(`vendor_category=cafe`)를 찐맛 신호에 포함할지. 기본은 `restaurant` 만 export.
- 일하는 방식(팀 분리·토론·strict xfail·요약 핸드오프·`<result>` XML·모델 티어링·최소 도구)은 상위 문서 그대로.
- 사용자는 Windows PowerShell. 명령 예시는 PowerShell 기준, `python -c` 안에 `\"` 금지(here-string 사용).

## C. 명세 대비 조정
- `src/http.py` → **`src/http_client.py`** (표준 라이브러리 `http` 와 이름 혼동 방지).
- Phase 마다 **결과 요약 보고 후 멈춤**(1절). 다음 Phase 는 사용자 확인 후.
- 커밋 전 `python -m pytest -q` 전부 통과. 파서·정규화 함수는 `tests/fixtures/` 의 작은 샘플(가상 데이터, PII 없음)로 단위 테스트.
- 원본(`data/raw`)·중간 산출물·`state.db`·`.env`·로그는 git 제외(`.gitignore`). 실데이터를 fixture 로 커밋하지 않는다.

---

# 공공기관 업무추진비 수집·통합 프로젝트 — 작업 명세서


---

## 0. 프로젝트 개요

### 목표
전국 공공기관 약 486곳의 **최근 2년간 업무추진비 집행내역**을 자동으로 수집하고, 하나의 CSV로 통합한다.
최종 활용 목적은 **공공기관이 자주 방문한 음식점 데이터** 구축이다.

### 수집 기간
- `2024-11-01` ~ `2026-10-31` (설정 파일에서 변경 가능하게 할 것)

### 대상 기관 (약 486곳)
| 유형 코드 | 기관 유형 | 예상 수 |
|---|---|---|
| `METRO_EDU` | 시·도교육청 | 17 |
| `LOCAL_EDU` | 교육지원청 | 약 176 |
| `METRO_GOV` | 광역자치단체 | 17 |
| `LOCAL_GOV` | 기초자치단체 | 226 |
| `CENTRAL` | 중앙행정기관(부·처·청 등) | 약 50 |

> 기관 수는 추정치다. 실제 수는 Phase 0에서 공식 목록으로 확정하고, 차이가 나면 보고할 것.

### 전체 파이프라인
```
Phase 0  기관 마스터 리스트 작성
Phase 1  기관별 수집 출처 조사 (공공데이터포털 / 기관 홈페이지 게시판 / 정보공개포털 사전공표)
Phase 2  홈페이지 게시판 상세 분류 (CMS, 파일 형식, 게시판 URL, 크롤링 가능 여부)
Phase 3  수집 — ① 공공데이터포털 → ② 기관 홈페이지 게시판 순서
Phase 4  형식별 파서로 표 추출
Phase 5  단일 CSV 스키마로 통합·정규화 + 품질 리포트
```

---

## 1. Claude Code 작업 원칙

1. **Phase 단위로 진행하고, 각 Phase 종료 시 결과 요약을 보고한 뒤 멈춘다.** 사람이 확인한 후 다음 Phase로 넘어간다.
2. 모든 단계는 **재실행 가능(idempotent)하고 중단 후 이어하기(resumable)** 가능해야 한다. 이미 처리된 기관·파일은 건너뛴다.
3. 진행 상태는 SQLite(`data/state.db`)에 기록한다. CSV 산출물은 사람이 검토하기 위한 export다.
4. 확실하지 않은 정보(예: 게시판 URL)는 추측해서 채우지 말고 `status=needs_review`로 남긴다.
5. 먼저 소수 기관(유형별 2~3곳, 총 10~15곳)으로 **파일럿**을 돌려 로직을 검증한 뒤 전체로 확장한다.
6. 외부 사이트 접근 시 아래 「9. 크롤링 윤리·법적 준수사항」을 반드시 지킨다.

---

## 2. 프로젝트 구조 (권장)

```
expense_collector/
├── CLAUDE.md                   # 이 문서 (+ docs/handoff.md, docs/prompts.md)
├── config.yaml                 # 기간, 요청 간격, User-Agent, 경로 등
├── pyproject.toml
├── src/
│   ├── cli.py                  # 단일 진입점 (typer 또는 argparse)
│   ├── db.py                   # SQLite 상태 관리
│   ├── http_client.py          # 공통 HTTP 클라이언트 (rate limit, retry, robots 체크)
│   ├── phase0_institutions/
│   ├── phase1_source_survey/
│   ├── phase2_board_classify/
│   │   └── cms_fingerprints.yaml
│   ├── phase3_collect/
│   │   ├── datagokr.py
│   │   └── boards/             # CMS별 크롤러 어댑터
│   ├── phase4_parse/
│   │   ├── excel.py
│   │   ├── pdf.py
│   │   ├── hwp.py
│   │   └── ocr.py
│   └── phase5_merge/
│       ├── column_map.yaml     # 원본 컬럼명 → 표준 컬럼 매핑
│       └── normalize.py
├── data/
│   ├── state.db
│   ├── institutions.csv
│   ├── source_survey.csv
│   ├── board_registry.csv
│   ├── raw/                    # 원본 파일: raw/{institution_id}/{source}/...
│   ├── parsed/                 # 파일별 추출 결과 (parquet 또는 csv)
│   └── output/
│       ├── expenses_merged.csv
│       └── quality_report.md
└── logs/
```

### CLI 예시
```bash
python -m src.cli phase0           # 기관 마스터 생성
python -m src.cli phase1 --pilot   # 파일럿 기관만 출처 조사
python -m src.cli phase1           # 전체
python -m src.cli phase2
python -m src.cli phase3 --source datagokr
python -m src.cli phase3 --source board
python -m src.cli phase4
python -m src.cli phase5
python -m src.cli status           # 기관별·단계별 진행 현황 출력
python -m src.cli export-jjinmat   # 찐맛 연동 CSV (13절)
```

---

## 3. Phase 0 — 기관 마스터 리스트

### 작업
- 공식 출처에서 대상 기관 목록을 만든다. 후보 출처(접근 가능 여부를 먼저 확인할 것):
  - 행정표준코드관리시스템(code.go.kr)의 행정기관 코드
  - 행정안전부 지방자치단체 현황
  - 교육부·각 시도교육청의 교육지원청 목록
  - 정부조직도(중앙행정기관)
- 각 기관의 **공식 홈페이지 URL**까지 확보한다.
- 공식 목록을 자동으로 받을 수 없으면, 해당 부분을 `needs_review`로 표시하고 사람에게 목록 파일 제공을 요청한다.

### 산출물: `data/institutions.csv`
| 컬럼 | 설명 |
|---|---|
| `institution_id` | 내부 ID (행정기관코드가 있으면 사용) |
| `name` | 기관명 (예: 인천광역시 연수구) |
| `type` | `METRO_EDU` / `LOCAL_EDU` / `METRO_GOV` / `LOCAL_GOV` / `CENTRAL` |
| `parent` | 상위 기관 (교육지원청 → 시도교육청, 기초 → 광역) |
| `region` | 시도 |
| `homepage_url` | 공식 홈페이지 |
| `admin_code` | 행정기관코드 (있을 경우) |

### 완료 기준
- 유형별 기관 수를 출력하고, 예상 수(위 표)와 다르면 차이를 보고한다.

---

## 4. Phase 1 — 기관별 수집 출처 조사

각 기관에 대해 아래 3가지 출처를 **모두** 조사해 기록한다.

### 4.1 공공데이터포털 (data.go.kr)
- "업무추진비", "업추비", "집행내역" 등 키워드와 기관명으로 데이터셋을 검색한다.
- 파일데이터(CSV/XLSX 등)와 오픈API를 모두 확인한다.
- 검색 방법은 Claude Code가 먼저 확인할 것: 공공데이터포털의 목록 조회 수단(메타데이터 API, 전체 목록 파일, 검색 페이지) 중 이용약관상 허용되고 안정적인 것을 사용한다.
- 기록 항목: 데이터셋 ID, 제목, 형식, 시간범위, 업데이트 주기, 최종 수정일, 다운로드/API URL.

### 4.2 기관 홈페이지 게시판
- 홈페이지에서 "업무추진비", "사전정보공표", "행정정보공개", "정보공개" 메뉴를 탐색한다.
- 사이트맵 페이지가 있으면 우선 활용한다.
- 업무추진비 게시판 URL 후보를 찾고, 실제 게시글이 있는지 확인한다.

### 4.3 정보공개포털 사전공표 (open.go.kr)
- 기관별 사전공표 목록에서 업무추진비 항목을 찾는다.
- 대부분 기관 홈페이지로 연결되는 링크이므로, **4.2의 게시판 URL을 찾는 보조 수단**으로 활용한다.

### 산출물: `data/source_survey.csv` (기관 × 출처 단위, 1기관 여러 행 가능)
| 컬럼 | 설명 |
|---|---|
| `institution_id` | |
| `source` | `DATAGOKR` / `BOARD` / `OPENGOKR` |
| `available` | `yes` / `no` / `unknown` |
| `url` | 데이터셋·게시판·사전공표 URL |
| `coverage_from`, `coverage_to` | 확인된 데이터 기간 |
| `scope` | 공개 범위 (예: 기관장, 부기관장, 실국장, 부서별) |
| `formats` | 확인된 파일 형식 (쉼표 구분) |
| `priority` | 수집 우선순위 (DATAGOKR=1, BOARD=2) |
| `status` | `found` / `not_found` / `needs_review` / `error` |
| `note` | 특이사항 |
| `checked_at` | 조사 일시 |

### 완료 기준
- 기관별로 최소 1개 출처가 `found`인 비율, 출처 없음 기관 목록을 보고한다.
- **출처가 하나도 없는 기관은 정보공개청구 대상 후보 목록(`data/output/foi_candidates.csv`)으로 따로 내보낸다.**

---

## 5. Phase 2 — 홈페이지 게시판 상세 분류

`source=BOARD`이고 `available=yes`인 기관만 대상으로 한다.

### 5.1 조사 항목
1. **CMS / 게시판 엔진 식별**
   - URL 패턴, HTML 구조, `meta generator`, JS·CSS 경로, 파라미터 이름으로 판별한다.
   - 판별 규칙은 `cms_fingerprints.yaml`에 선언형으로 관리한다. 예시(실제 패턴은 조사하며 채울 것):
     ```yaml
     - id: egovframe_bbs
       name: 전자정부표준프레임워크 게시판
       match:
         url_regex: ["selectBbsNttList\\.do", "selectBoardList\\.do", "bbsId="]
     - id: generic_board_do
       name: 일반 board.do 계열
       match:
         url_regex: ["/board\\.do", "boardId=", "bbs\\.do"]
     - id: unknown
       name: 미분류
     ```
   - 판별 불가 시 `unknown`으로 두고, 동일 구조 사이트들을 클러스터링(HTML DOM 구조 유사도)해 새 패턴 후보를 제안한다.
2. **파일 형식**: 최근 게시글 몇 건의 첨부파일 확장자 (xlsx, xls, csv, pdf, hwp, hwpx, 이미지 등)
3. **PDF 성격**: 텍스트 PDF인지 스캔 이미지 PDF인지 (샘플 1~2개로 텍스트 추출 시도)
4. **크롤링 가능 여부**
   - robots.txt 허용 여부
   - 로그인 필요 여부
   - JS 렌더링 필요 여부 (정적 HTML에 목록이 없으면 Playwright 필요로 분류)
   - 첨부파일 다운로드 방식 (직접 링크 / POST / JS 함수 호출)
   - CAPTCHA 또는 차단 징후

### 5.2 크롤링 가능 등급
| 등급 | 의미 |
|---|---|
| `A` | 정적 HTML + 직접 다운로드 링크. requests만으로 가능 |
| `B` | JS 렌더링 또는 POST/함수 호출 다운로드. Playwright 필요 |
| `C` | 로그인, robots 비허용, CAPTCHA 등으로 자동 수집 부적합 → 수집하지 않고 정보공개청구 후보로 이동 |

> CAPTCHA나 로그인을 우회하는 코드는 작성하지 않는다. 해당 기관은 `C`로 분류한다.

### 산출물: `data/board_registry.csv`
| 컬럼 | 설명 |
|---|---|
| `institution_id` | |
| `board_url` | 업무추진비 게시판 목록 URL |
| `cms_id` | `cms_fingerprints.yaml`의 id |
| `list_pagination` | 페이지 파라미터 방식 |
| `file_formats` | 확인된 확장자 |
| `pdf_kind` | `text` / `scanned` / `mixed` / `n/a` |
| `robots_allowed` | `yes` / `no` |
| `needs_js` | `yes` / `no` |
| `download_method` | `direct` / `post` / `js` |
| `crawl_grade` | `A` / `B` / `C` |
| `posts_in_period` | 수집 기간 내 게시글 수 추정 |
| `note` | |

### 완료 기준
- CMS별 기관 수, 등급별 기관 수, 파일 형식 분포를 보고한다.
- 기관 수가 많은 CMS부터 크롤러 어댑터를 구현하는 계획을 제안한다.

---

## 6. Phase 3 — 데이터 수집

### 순서
1. **공공데이터포털** (`source=DATAGOKR`)
2. **기관 홈페이지 게시판** (`crawl_grade` A → B 순)

한 기관이 두 출처를 모두 가진 경우 둘 다 수집하고, 중복 제거는 Phase 5에서 처리한다.

### 3.1 공공데이터포털
- 파일데이터는 직접 다운로드, 오픈API는 서비스키가 필요하면 `.env`의 `DATAGOKR_API_KEY`를 사용한다 (키가 없으면 사람에게 요청하고 파일데이터만 수집).
- 주기성 데이터셋은 수집 기간에 해당하는 모든 회차를 받는다.

### 3.2 기관 홈페이지 게시판
- CMS별 어댑터 구조로 구현한다: `list_posts(board) → [post]`, `list_attachments(post) → [file]`, `download(file)`.
- 게시글 제목·작성일로 수집 기간 내 게시글만 선별한다.
- 게시글 본문에 표가 HTML로 들어있는 경우도 있으므로, 첨부파일이 없으면 본문 HTML도 저장한다.

### 공통 규칙
- 원본 파일 저장 경로: `data/raw/{institution_id}/{source}/{yyyy-mm}_{원본파일명}`
- 파일마다 SHA-256 해시를 기록해 중복 다운로드를 방지한다.
- `files` 테이블에 기록: `file_id, institution_id, source, source_url, post_title, post_date, filename, ext, sha256, size, downloaded_at, status`

### 완료 기준
- 기관별 수집 파일 수, 기간 커버리지(월별 빈 구간), 실패 목록을 보고한다.

---

## 7. Phase 4 — 형식별 파서로 표 추출

| 형식 | 도구 (우선순위 순) | 비고 |
|---|---|---|
| `xlsx` / `xls` / `csv` | pandas + openpyxl / xlrd | CSV 인코딩은 `utf-8-sig`, `cp949` 순으로 시도. 병합 셀·다중 헤더·시트 여러 개 처리 |
| `pdf` (텍스트) | pdfplumber → camelot | 페이지에 걸친 표 이어붙이기 |
| `pdf` (스캔) | OCR (Tesseract `kor` 또는 PaddleOCR) | 정확도 낮음 → `parse_confidence` 낮게 표시 |
| `hwpx` | zip 해제 후 XML 표 파싱 | |
| `hwp` | pyhwp(hwp5html) → HTML 표 파싱, 실패 시 LibreOffice 변환 | |
| HTML 본문 | pandas.read_html / BeautifulSoup | |
| 이미지 | OCR | |

### 규칙
- 파일 하나에서 여러 표가 나오면 모두 추출하고 `table_index`를 붙인다.
- 업무추진비 표가 아닌 표(요약, 합계표 등)는 헤더 키워드로 걸러내되, 판단이 애매하면 남기고 플래그를 단다.
- 파일별 추출 결과는 원본 컬럼명을 그대로 유지해 `data/parsed/{file_id}_{table_index}.parquet`로 저장한다.
- 파싱 실패 파일은 `parse_status=failed`와 오류 메시지를 기록한다.

### 완료 기준
- 형식별 성공률, 실패 파일 목록, OCR 처리 파일 수를 보고한다.

---

## 8. Phase 5 — 단일 CSV 스키마로 통합

### 8.1 표준 스키마 (`data/output/expenses_merged.csv`)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| `record_id` | str | 고유 ID |
| `institution_id` | str | |
| `institution_name` | str | |
| `institution_type` | str | |
| `department` | str | 집행 부서 (있을 경우) |
| `executor_position` | str | 집행자 직위 (기관장, 부기관장 등. **개인 이름은 저장하지 않음**) |
| `exec_date` | date | 집행일자 (`YYYY-MM-DD`) |
| `exec_time` | str | 집행 시간 (있을 경우) |
| `vendor_raw` | str | 사용처 원문 |
| `vendor_normalized` | str | 정규화된 상호명 |
| `vendor_address` | str | 사용처 주소 (있을 경우) |
| `vendor_category` | str | `restaurant` / `cafe` / `other` / `unknown` |
| `amount` | int | 금액(원) |
| `headcount` | int | 대상 인원 |
| `purpose` | str | 집행 목적 |
| `payment_method` | str | 카드/현금 등 |
| `source` | str | `DATAGOKR` / `BOARD` |
| `source_file_id` | str | 원본 파일 추적용 |
| `parse_confidence` | float | 0~1 (OCR, 컬럼 매핑 불확실성 반영) |

### 8.2 컬럼 매핑
- `column_map.yaml`에 원본 컬럼명 → 표준 컬럼 매핑을 선언한다. 예:
  ```yaml
  exec_date: [집행일자, 일자, 사용일자, 집행일, 날짜, 사용일시]
  vendor_raw: [사용처, 집행장소, 장소, 가맹점명, 상호]
  amount: [금액, 집행금액, 사용금액, 집행액(원)]
  headcount: [인원, 대상인원, 참석인원]
  purpose: [집행목적, 목적, 사용목적, 내용]
  ```
- 매핑되지 않은 컬럼명은 빈도순으로 `data/output/unmapped_columns.csv`에 내보내 사람이 검토·추가할 수 있게 한다.

### 8.3 정규화
- 날짜: `2025.3.4`, `25-03-04`, `3.4.(화)` 등 다양한 형식 처리. 연도가 없으면 게시글·파일의 연월로 보완.
- 금액: 쉼표, "원", 공백 제거 후 정수화.
- 상호명: 괄호·법인 표기(`(주)`, `주식회사`) 제거, 공백 정리, 지점명 분리. 동일 상호 판정은 상호명 + 주소(시군구) 기준.
- 음식점 분류: 상호명·목적 키워드 기반 1차 분류(규칙은 설정 파일로), 애매하면 `unknown`.

### 8.4 중복 제거
- 같은 기관에서 공공데이터포털과 게시판 데이터가 겹치면 `(institution_id, exec_date, amount, vendor_normalized)` 기준으로 중복 제거하고, 남는 레코드의 출처 우선순위는 `DATAGOKR > BOARD`.

### 8.5 개인정보 처리
- 함께 식사한 사람 이름, 휴대전화번호, 카드번호 등 개인 식별 정보 컬럼은 **통합 CSV에 포함하지 않는다.**
- 사용처 원문에 개인 이름이 섞여 있으면 마스킹한다.

### 8.6 품질 리포트: `data/output/quality_report.md`
- 기관별 레코드 수, 기간 커버리지, 결측률(컬럼별), 출처별 비중
- `parse_confidence < 0.7` 레코드 수
- 수집 실패·미수집 기관 목록 (→ 정보공개청구 후보)
- 상위 방문 음식점 Top 50 미리보기 (`vendor_normalized` 기준 방문 횟수·총액)

---

## 9. 크롤링 윤리·법적 준수사항

- **robots.txt를 준수한다.** 비허용 경로는 수집하지 않는다.
- **요청 간격**: 같은 도메인에 기본 2초 이상(설정 가능), 동시 접속 1개. 오류 시 지수 백오프.
- User-Agent에 프로젝트명과 연락처를 명시한다 (`config.yaml`에서 설정).
- 로그인, CAPTCHA, 접근 제한을 우회하지 않는다.
- 공공데이터포털 데이터는 각 데이터셋의 이용허락범위(출처표시 등)를 기록해 둔다.
- 수집 데이터에서 개인 식별 정보는 제거한다 (8.5).

---

## 10. 기술 스택 (권장)

- Python 3.11+
- HTTP: `httpx` 또는 `requests`, 재시도는 `tenacity`
- HTML 파싱: `beautifulsoup4`, `lxml`
- JS 렌더링: `playwright` (등급 B 사이트만)
- 표 처리: `pandas`, `openpyxl`, `xlrd`, `pyarrow`
- PDF: `pdfplumber`, `camelot-py`
- HWP: `pyhwp`, LibreOffice(헤드리스 변환 대체 수단)
- OCR: `pytesseract`(+ `tesseract-ocr-kor`) 또는 `paddleocr`
- 상태 관리: SQLite (`sqlite3` 또는 `sqlmodel`)
- 로깅: `logging` → `logs/`에 단계별 로그
- 테스트: `pytest` — 파서와 정규화 함수는 샘플 파일로 단위 테스트 작성

---

## 11. 알려진 한계 (작업 중 염두에 둘 것)

- 사전공개 업무추진비는 주로 **기관장·부기관장·실국장 단위**다. 특정 부서(예: 공무직 관련 부서) 단위 자료는 없을 가능성이 높다. `department` 컬럼으로 구분 가능한 범위를 품질 리포트에 명시한다.
- 기관마다 공개 형식·항목이 달라 일부 컬럼(주소, 인원 등)은 결측이 많을 수 있다.
- 자동 수집이 불가능하거나 자료가 없는 기관은 정보공개청구로 보완한다. 해당 목록은 `foi_candidates.csv`로 관리한다.

---

## 12. 첫 실행 시 Claude Code가 할 일

1. 이 문서를 읽고 프로젝트 골격(디렉터리, `pyproject.toml`, `config.yaml`, CLI, SQLite 스키마)을 만든다.
2. Phase 0을 실행해 기관 마스터를 만들고 결과를 보고한다.
3. 파일럿 기관 10~15곳을 선정해 Phase 1~2를 실행하고, 발견한 CMS 패턴과 문제점을 보고한다.
4. 사람의 확인을 받은 뒤 전체 기관으로 확장한다.

---

## 13. 찐맛 연동 export (Phase 5 이후)

`python -m src.cli export-jjinmat` → `data/output/gov_expense_for_jjinmat.csv`

| 컬럼 | 출처 | 비고 |
|---|---|---|
| `restaurant_name` | `vendor_normalized` | |
| `address` | `vendor_address` | 없으면 빈칸. 찐맛 쪽 매칭(이름+주소) 보조용 |
| `exec_date` | `exec_date` | `YYYY-MM-DD` |
| `agency` | `institution_name` | |
| `amount` | `amount` | 정수(원) |
| `purpose` | `purpose` | 개인 이름이 섞이면 마스킹 |
| `source` | `"{기관명} 업무추진비 공개({DATAGOKR 또는 BOARD})"` | |
| `base_year` | `exec_date` 의 연도 | |

- `vendor_category in config.jjinmat_export.categories` 인 레코드만, `parse_confidence >= 0.7` 만.
- **개인 이름·직위·인원 명단 컬럼 없음.** 찐맛 `GovExpenseCSVAdapter` 의 화이트리스트(`restaurant_name, exec_date, agency, amount, purpose, source, base_year`)와 호환. `address` 는 현재 어댑터가 무시하므로, 이름+주소 매칭 로더는 찐맛 백엔드 쪽 별도 작업으로 제안만 한다.
- export 테스트: 출력 헤더가 위 표와 정확히 같고 PII 패턴(이름 마스킹 전 문자열, 전화번호, 카드번호)이 없음을 검사.
