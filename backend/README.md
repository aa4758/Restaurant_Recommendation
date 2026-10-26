# 찐맛 백엔드 (FastAPI + SQLite)

```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.ingest.load_seed          # 가상 시드 → data/jjinmat.db
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
python -m pytest -q                      # 테스트
```

- 실데이터: 상가(상권)정보 CSV를 `data/raw/sbiz/`에 넣고 `python -m app.ingest.load_seed --source real` (upsert, 리뷰 유지).
  적재 시 점수(`scores`)도 자동 계산. DB를 수동으로 고친 뒤에는 `python -m app.service` 로 재계산.
- 인허가(일반·휴게음식점): 지방행정 인허가 데이터개방 / data.go.kr 에서 일반음식점·휴게음식점 CSV를 받아
  `data/raw/license/`에 넣는다(git 제외). 상가정보 적재 **후** 아래 순서로 실행:
  ```powershell
  # 1) 좌표계 확인(적재 안 함): 후보 CRS별 매칭 표본 거리 중앙값 → "권장 --crs" 확인
  python -m app.ingest.load_license data\raw\license\일반음식점.csv data\raw\license\휴게음식점.csv --check      # 파일 점검(DB 불필요, 헤더·매핑 출력)
  # 개방서비스명 컬럼이 없는 업종별 파일: 파일 하나씩 --license-type 일반음식점 / 휴게음식점 지정
  # 휴게음식점 파일은 신규 가게를 만들지 않음 — 매칭된 기존 가게의 음주 불가·폐업 판별에만 사용
  python -m app.ingest.load_license --fix-regions    # 지역 없음 가게의 지역 키를 주소로 다시 계산(재적재 없음)
  python -m app.ingest.load_license data\raw\license\일반음식점.csv data\raw\license\휴게음식점.csv --calibrate
  # 2) 미리보기(DB 변경 없음) → 3) 적재 (권장 CRS가 기본 EPSG:5174와 다르면 --crs 지정)
  python -m app.ingest.load_license data\raw\license\일반음식점.csv data\raw\license\휴게음식점.csv --dry-run
  python -m app.ingest.load_license data\raw\license\일반음식점.csv data\raw\license\휴게음식점.csv --crs EPSG:5174
  ```
  매칭 가게에 폐업·인허가일자(업력)·일반/휴게(휴게 = 주류 불가)·면적을 반영, 미매칭 영업 중 가게는 신규(`L{관리번호}`)로 추가,
  영향 시군구 점수 자동 재계산. 모호·좌표 없음 미매칭은 `data/out/unmatched_license.csv`(수기 검토). 재적재 멱등.
  헤더가 바뀌면 `app/ingest/license.py` 의 `COL` 만 수정.
  - 반영 규칙: 같은 가게 다중 인허가는 영업 중 > 일반 > 휴게 > 최신 인허가일자 순 1건. alcohol=0 강제는 영업 중
    인허가가 모두 휴게일 때만(`alcohol_src='license'` 로 표시, 일반으로 바뀌면 NULL 복원). 이미 영업 중 인허가가 붙은
    가게에 그보다 오래된 다른 관리번호의 폐업 행은 무시. opened_at·area_m2 는 새 값이 없으면 기존 유지,
    closed_at = 기존 → 폐업일자 → 데이터갱신일자(없으면 NULL).
  - 제외 업태(카페·디저트·출장조리·이동조리·푸드트럭 등)는 신규 생성만 막고, 이미 매칭된 가게의 영업 상태·폐업은 반영.
  - `--calibrate` 표본 30건 미만이면 경고. 미매칭 0건이면 기존 `unmatched_license.csv` 삭제.
    `--dry-run` 은 SAVEPOINT 로 이 적재의 변경만 롤백.
  - `--check` 끝에 **추가 열 분포**(등급구분명 상위 10, 전통업소지정번호 있는 행 수, 전통업소주된음식 상위 10)를 출력 —
    점수 미반영, 값 확인 후 기획 결정.
- 별점 근거 신호(지정·선정 목록, 위생등급, 행정처분): 인허가 적재 **후** 실행. 원본 공공 CSV 를 그대로 넣는다(헤더 별칭 자동 해석,
  UTF-8/CP949 자동, 제목 줄 건너뜀). **xlsx 는 미지원** → 엑셀에서 "다른 이름으로 저장 → CSV UTF-8(쉼표로 분리)".
  파일 위치(git 제외): 지정·선정 목록 `data/raw/designations/`, 위생등급·행정처분 `data/raw/food_safety/`.
  항상 `--check`(DB 불필요: 인코딩·헤더·매핑·필수 누락·행 수·시도 분포·폐기할 PII 열) → `--dry-run`(DB 변경 없음, 통계·미매칭 파일) → 적재 순.
  ```powershell
  # 모범음식점·안심식당 등(파일에 kind 열이 없으면 --kind 로 파일 전체 지정, 날짜 열이 없으면 --base-date)
  python -m app.ingest.load_designations data\raw\designations\모범음식점.csv --kind model_restaurant --source "행정안전부 모범음식점" --check
  python -m app.ingest.load_designations data\raw\designations\모범음식점.csv --kind model_restaurant --source "행정안전부 모범음식점" --dry-run
  python -m app.ingest.load_designations data\raw\designations\모범음식점.csv --kind model_restaurant --source "행정안전부 모범음식점"
  python -m app.ingest.load_designations data\raw\designations\안심식당.csv --kind safe_restaurant --source "농림축산식품부 안심식당" --check
  # 착한가격업소: 대표메뉴·가격(대표메뉴1·가격1 … 포함)은 menus 에 source='good_price', 대표메뉴로 upsert
  python -m app.ingest.load_designations data\raw\designations\착한가격업소.csv --kind good_price --source "행정안전부 착한가격업소" --check
  python -m app.ingest.load_designations data\raw\designations\착한가격업소.csv --kind good_price --source "행정안전부 착한가격업소" --dry-run
  python -m app.ingest.load_designations data\raw\designations\착한가격업소.csv --kind good_price --source "행정안전부 착한가격업소"
  # 백년가게(업력 보정)·향토음식점 등도 같은 패턴: --kind century_store / local_food / seoul_future_heritage / taste_of_seoul
  python -m app.ingest.load_designations data\raw\designations\백년가게.csv --kind century_store --source "중소벤처기업부 백년가게" --base-date 2025-01-01 --dry-run

  # 위생등급(매우우수|우수|좋음 정규화, 지정취소 행 제외)
  python -m app.ingest.load_food_safety data\raw\food_safety\위생등급.csv --type hygiene --check
  python -m app.ingest.load_food_safety data\raw\food_safety\위생등급.csv --type hygiene --dry-run
  python -m app.ingest.load_food_safety data\raw\food_safety\위생등급.csv --type hygiene
  # 행정처분(식품접객업): 인허가번호 열이 있으면 관리번호 정확 일치 우선 → 상호+주소
  python -m app.ingest.load_food_safety data\raw\food_safety\행정처분.csv --type sanction --check
  python -m app.ingest.load_food_safety data\raw\food_safety\행정처분.csv --type sanction --dry-run
  python -m app.ingest.load_food_safety data\raw\food_safety\행정처분.csv --type sanction
  ```
  - kind 허용값(`load_designations`): model_restaurant · safe_restaurant · origin_label_excellent · century_store · good_price ·
    taste_of_seoul · seoul_future_heritage · local_food · michelin_*(기본 보류, `--allow-michelin`). `--kind` 는 kind 열보다 우선.
    기존 고정 컬럼 CSV(name,address,lat,lng,kind,base_date,source)도 그대로 동작.
  - 매칭: 인허가번호(인허가번호/관리번호/허가번호/영업신고번호) 일치 → 상호 + 도로명주소 일치 또는 좌표 50m. 통계에 방법별 건수,
    신호 추가·중복 무시·미매칭(사유별)·보류(미슐랭)·제외(지정취소) 출력.
  - 미매칭: `data/out/unmatched_<출처>.csv`(지정 목록), `data/out/unmatched_food_safety_<type>.csv` — 화이트리스트 열 + reason,
    대표자·전화 등 PII 없음. 원본의 대표자명·전화 열은 읽지 않고 폐기.
  - 행정처분은 처분일자 기준 최근 3년(정확히 3년 전 당일 포함) 건당 0.05, 상한 0.15 감점(prior). 같은 날 다른 처분은 처분내용으로 구분.
  - 재적재 멱등(UNIQUE 신호 인덱스). 적재 후 영향 시군구만 점수 재계산. 헤더를 못 찾으면 `--check` 출력의 헤더를
    `app/ingest/signal_common.py`(상호·주소·좌표·인허가번호) 또는 각 적재기의 `ALIASES` 에 추가.
- DB 경로: `JJINMAT_DB` (기본 `data/jjinmat.db`)
- 카카오 로컬 API: `KAKAO_REST_KEY` 설정 시에만 적재(미설정 시 skip)
- API 계약·점수 모델: `docs/01_planning_decision.md`

## API 요약 (상세 계약: `docs/01_planning_decision.md` 'API 계약')

| 메서드 · 경로 | 요청 | 응답 | 비고 |
|---|---|---|---|
| `GET /health` | - | `{"status":"ok"}` | |
| `GET /meta/filters` | - | price·genre·mood·alcohol 목록 | |
| `POST /recommend` | lat, lng, radius_m, price?, genre?, mood?, alcohol, `limit`(1~5, 기본 3), `exclude_ids`(최대 200) | `{"items":[...],"relaxed":[...]}` | 초과 시 422. exclude_ids 는 후보에서 먼저 제외 후 기존 선정·완화·로테이션. item 에 `evidence`(low/mid/high/null), `relaxed`(그 가게가 원래 조건 distance/mood/price/genre 중 충족 못한 항목) |
| `GET /restaurants/{id}` | - | item + `score_breakdown` | 없으면 404 |
| `GET /restaurants/{id}/reviews` | `limit`(1~50, 기본 20), `cursor`? | `{"items":[{"id","stars","text","tags","created_at","ad_disclosed"}],"next_cursor"}` | 광고 표시 아님 먼저 → 최신순(동일 시각 id). `ad_disclosed` = `prior.is_ad_text`(부정 표현 제외), 작성 시 `user_reviews.ad_disclosed` 에 저장(기존 행 자동 백필) → SQL 키셋 페이지네이션. 기기 ID 비노출. 없는 가게 404, 잘못된 커서 400 |
| `POST /restaurants/{id}/reviews` | stars(0.5~5, 0.5단위), text, tags, device_id?(8~64) | 201 `{"id","final_star"}` | device_id 는 `user_reviews.user_id` 저장·응답 비노출. 있으면 기기 분당 30 + IP 분당 300, 없으면 IP 분당 300 초과 429 |
| `POST /reactions` | device_id(8~64, `[A-Za-z0-9_-]`), restaurant_id, value(like/dislike/none), reason?(dislike 일 때만: far/price/not_into/visited) | 204 | 기기·가게당 1행 upsert, none = 삭제. **점수·순위 미반영**. 없는 가게 404. 기기 분당 30회 / IP 분당 300회 초과 429 |
| `POST /restaurants/{id}/report` | field, message | 202 | |

레이트리밋은 프로세스 메모리 기반(`app/ratelimit.py`, 기기 `WRITE_LIMIT_PER_MIN`=30 · IP `IP_LIMIT_PER_MIN`=300, 키 상한 10만) — 다중 워커/인스턴스면 각자 따로 센다.
LB/리버스 프록시 뒤에서는 `FORWARDED_ALLOW_IPS` 에 LB 대역을 설정해야 실제 클라이언트 IP 로 센다(예: `FORWARDED_ALLOW_IPS=10.0.0.0/8`, Docker CMD 가 `--proxy-headers` 로 전달).
