"""안심식당 오픈API 수집: 페이징·지정 취소 제외·PII(대표자명·전화) 미저장 (load_designations.fetch_mafra)."""
import io
import json

from app.ingest import load_designations as ld


def test_fetch_mafra_pages_drops_cancelled_and_pii(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.time, "sleep", lambda s: None)
    calls = []

    def opener(url, timeout):
        calls.append(url)
        start = int(url.rstrip("/").split("/")[-2])
        rows = [{"RELAX_RSTRNT_NM": f"식당{start + i}", "RELAX_ADD1": "서울특별시 중구 세종대로 110", "RELAX_ADD2": "",
                 "RELAX_RSTRNT_REG_DT": "2020-09-04", "RELAX_RSTRNT_REPRESENT": "홍길동", "RELAX_RSTRNT_TEL": "02-123-4567",
                 "RELAX_USE_YN": "N" if (start + i) % 2 else "Y"} for i in range(min(ld.MAFRA_PAGE, 1500 - start + 1))]
        body = {"Grid_20200713000000000605_1": {"totalCnt": 1500, "result": {"code": "INFO-000"}, "row": rows}}
        return io.BytesIO(json.dumps(body).encode())

    path, n = ld.fetch_mafra("KEY", tmp_path, opener=opener)
    assert len(calls) == 2 and "/1001/2000" in calls[1] and n == 750
    text = path.read_text(encoding="utf-8-sig")
    assert "홍길동" not in text and "4567" not in text and "safe_restaurant" in text
