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
- DB 경로: `JJINMAT_DB` (기본 `data/jjinmat.db`)
- 카카오 로컬 API: `KAKAO_REST_KEY` 설정 시에만 적재(미설정 시 skip)
- API 계약·점수 모델: `docs/01_planning_decision.md`
