"""Phase 4 실행: files(status=ok) → 형식 판별(확장자보다 파일 머리 바이트 우선) → 격자 → 업무추진비 표 → parquet.

- 산출: data/parsed/{file_id}_{table_index}.parquet(원본 컬럼명, 모두 문자열) + parsed_tables 행.
- 표가 없거나 읽기 실패면 table_index=0, parse_status=failed, error 기록. 스캔 PDF·이미지는 OCR 미설치로 failed('OCR 필요').
- 이어하기: parsed_tables 에 있는 file_id 는 건너뛴다. 파일별 처리는 프로세스 풀(메모리 누수 대비 자식 프로세스 재시작).
- 자식 프로세스가 죽으면(BrokenProcessPool) 깨진 첫 파일을 혼자 다시 돌려 또 죽으면 failed 로 남기고, 나머지는 새 풀로 계속.
"""
import io
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import olefile

from src import db
from src.phase4_parse import excel, html, hwp, pdf, tables

OLE = b"\xd0\xcf\x11\xe0"
IMAGE = (b"\xff\xd8", b"\x89PNG", b"GIF8")


def kind_of(data: bytes, ext: str) -> str:
    if data[:5] == b"SCDSA":  # SoftCamp 문서보안(DRM) 암호화 — 풀지 않는다
        return "drm"
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:2] == b"PK":
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        return "xlsx" if "xl/workbook.xml" in names else "hwpx" if any(n.startswith("Contents/section") for n in names) else "zip"
    if data[:4] == OLE:
        return "hwp" if b"H\x00W\x00P\x00" in data[:4096] or ext.endswith("hwp") else "xls"
    if data.startswith(IMAGE):
        return "image"
    head = data[:2048].lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    if head.startswith((b"<", b"<!doctype")):
        return "html"
    return "csv" if ext == "csv" else "unknown"


def parse_bytes(data: bytes, ext: str) -> tuple[str, list[tuple], float]:
    """(형식, [(DataFrame, status)], 신뢰도)."""
    kind = kind_of(data, ext)
    conf = 1.0
    if kind in ("xlsx", "xls", "csv"):
        g = excel.grids(data, kind)
    elif kind == "html":
        g = html.grids(data)
    elif kind == "hwpx":
        g = hwp.hwpx_grids(data)
    elif kind == "hwp":
        g = hwp.hwp_grids(data)
    elif kind == "pdf":
        g, conf = pdf.grids(data)
    elif kind == "drm":
        raise ValueError("DRM 암호화 문서(SoftCamp) — 읽지 않음")
    elif kind == "image":
        raise pdf.ScannedPDF("이미지 — OCR 필요")
    else:
        raise ValueError(f"지원하지 않는 형식({kind})")
    return kind, tables.select(g), conf


def parse_file(file_id: int, path: str, ext: str, raw: str, out: str) -> tuple[int, str, list[tuple]]:
    """(file_id, 형식, [(table_index, path, n_rows, status, confidence, error)]) — 자식 프로세스에서 실행."""
    kind = ext
    try:
        kind, found, conf = parse_bytes((Path(raw) / path).read_bytes(), ext or "")
    except pdf.ScannedPDF as e:
        return file_id, "ocr", [(0, None, 0, "failed", None, str(e))]
    except Exception as e:  # 손상·암호·미지원 파일 하나가 전체를 멈추지 않게
        return file_id, kind, [(0, None, 0, "failed", None, f"{type(e).__name__}: {e}"[:300])]
    if not found:
        return file_id, kind, [(0, None, 0, "failed", None, "업무추진비 표 없음")]
    rows = []
    for i, (df, status) in enumerate(found):
        p = Path(out) / f"{file_id}_{i}.parquet"
        df.to_parquet(p, index=False)
        rows.append((i, p.name, len(df), status, round(conf * (0.7 if status == "flagged" else 1), 2), None))
    return file_id, kind, rows


def run(cfg: dict, workers: int = 4, limit: int | None = None) -> dict:
    conn = db.connect(cfg["paths"]["state_db"])
    out = Path(cfg["paths"]["parsed"])
    out.mkdir(parents=True, exist_ok=True)
    todo = conn.execute("""SELECT file_id, path, ext FROM files WHERE status='ok' AND path IS NOT NULL
                           AND file_id NOT IN (SELECT file_id FROM parsed_tables) ORDER BY file_id""").fetchall()
    todo = todo[:limit] if limit else todo
    run_id = db.start_run(conn, "phase4", f"workers={workers}" + (f" limit={limit}" if limit else ""))
    print(f"파싱 대상 {len(todo)}개 · 작업자 {workers}", flush=True)
    stat = Counter()
    try:
        n = 0

        def done(fid, kind, rows):
            nonlocal n
            n += 1
            conn.executemany("INSERT OR REPLACE INTO parsed_tables VALUES (?,?,?,?,?,?,?,?)",
                             [(fid, i, p, nr, st, cf, err, db.now()) for i, p, nr, st, cf, err in rows])
            stat[(kind, "ok" if rows[0][3] != "failed" else "failed")] += 1
            if n % 500 == 0:
                conn.commit()
                print(f"  {n}/{len(todo)} {dict(stat)}", flush=True)

        def submit(ex, r):
            return ex.submit(parse_file, r[0], r[1], r[2], cfg["paths"]["raw"], str(out))

        pending = list(todo)
        while pending:
            broken = []
            with ProcessPoolExecutor(workers, max_tasks_per_child=200) as ex:
                for r, f in [(r, submit(ex, r)) for r in pending]:
                    try:
                        done(*f.result())
                    except BrokenProcessPool:
                        broken.append(r)
            if broken:  # 깨진 첫 파일만 혼자 → 또 죽으면 그 파일 탓
                with ProcessPoolExecutor(1) as ex:
                    try:
                        done(*submit(ex, broken[0]).result())
                    except BrokenProcessPool:
                        done(broken[0][0], broken[0][2] or "", [(0, None, 0, "failed", 0.0, "자식 프로세스 비정상 종료")])
            pending = broken[1:]
        conn.commit()
        db.finish_run(conn, run_id, "ok", str(dict(stat)))
    except BaseException as e:
        conn.commit()
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
    print(f"파싱 끝: {dict(stat)}", flush=True)
    return dict(stat)
