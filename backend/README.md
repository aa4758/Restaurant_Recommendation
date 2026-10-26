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
- DB 경로: `JJINMAT_DB` (기본 `data/jjinmat.db`)
- 카카오 로컬 API: `KAKAO_REST_KEY` 설정 시에만 적재(미설정 시 skip)
- API 계약·점수 모델: `docs/01_planning_decision.md`
