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
- DB 경로: `JJINMAT_DB` (기본 `data/jjinmat.db`)
- 카카오 로컬 API: `KAKAO_REST_KEY` 설정 시에만 적재(미설정 시 skip)
- API 계약·점수 모델: `docs/01_planning_decision.md`

## API 요약 (상세 계약: `docs/01_planning_decision.md` 'API 계약')

| 메서드 · 경로 | 요청 | 응답 | 비고 |
|---|---|---|---|
| `GET /health` | - | `{"status":"ok"}` | |
| `GET /meta/filters` | - | price·genre·mood·alcohol 목록 | |
| `POST /recommend` | lat, lng, radius_m, price?, genre?, mood?, alcohol, `limit`(1~5, 기본 3), `exclude_ids`(최대 200) | `{"items":[...],"relaxed":[...]}` | 초과 시 422. exclude_ids 는 후보에서 먼저 제외 후 기존 선정·완화·로테이션. item 에 `evidence`(low/mid/high/null) |
| `GET /restaurants/{id}` | - | item + `score_breakdown` | 없으면 404 |
| `GET /restaurants/{id}/reviews` | `limit`(1~50, 기본 20), `cursor`? | `{"items":[{"id","stars","text","tags","created_at","ad_disclosed"}],"next_cursor"}` | 광고 표시 아님 먼저 → 최신순(동일 시각 id). `ad_disclosed` = `prior.is_ad_text`(부정 표현 제외). 기기 ID 비노출. 없는 가게 404, 잘못된 커서 400 |
| `POST /restaurants/{id}/reviews` | stars(0.5~5, 0.5단위), text, tags | 201 `{"id","final_star"}` | IP 당 분당 30회 초과 429 |
| `POST /reactions` | device_id(8~64, `[A-Za-z0-9_-]`), restaurant_id, value(like/dislike/none), reason?(dislike 일 때만: far/price/not_into/visited) | 204 | 기기·가게당 1행 upsert, none = 삭제. **점수·순위 미반영**. 없는 가게 404. 기기·IP 당 분당 30회 초과 429 |
| `POST /restaurants/{id}/report` | field, message | 202 | |

레이트리밋은 프로세스 메모리 기반(`app/ratelimit.py`, `WRITE_LIMIT_PER_MIN`) — 다중 워커/인스턴스면 각자 따로 센다.
