"""원본 파일 저장 + files 테이블 기록 (6절 공통 규칙).

경로: data/raw/{institution_id}/{source}/{yyyy-mm}_{원본파일명}. SHA-256 이 이미 있으면 파일은 쓰지 않고 status=duplicate.
"""
import hashlib
import re
import sqlite3
from pathlib import Path

from src import db

HTML_START = re.compile(rb"^\s*(<!doctype html|<html|<\?xml|<script)", re.I)


def safe_name(name: str, limit: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" .") or "file"
    stem, dot, ext = name.rpartition(".")
    return (stem[: limit - len(ext) - 1] + dot + ext) if dot and len(ext) <= 6 else name[:limit]


def looks_like_html(content: bytes) -> bool:
    return bool(HTML_START.match(content[:200]))


def seen(conn: sqlite3.Connection, inst_id: str, source_url: str) -> bool:
    return conn.execute("SELECT 1 FROM files WHERE institution_id=? AND source_url=? AND status IN ('ok','duplicate')",
                        (inst_id, source_url)).fetchone() is not None


def _forget_failed(conn, inst_id: str, source_url: str) -> None:
    """같은 URL 의 이전 failed/blocked 등 상태 행은 지운다 — 재실행해도 URL 당 상태 1행."""
    conn.execute("DELETE FROM files WHERE institution_id=? AND source_url=? AND status NOT IN ('ok','duplicate')",
                 (inst_id, source_url))


def record(conn, inst_id: str, source: str, source_url: str, *, status: str, title=None, date=None,
           filename=None, ext=None, license=None, note=None) -> None:
    """내용 없이 상태만 남긴다(failed / blocked / link / needs_key)."""
    _forget_failed(conn, inst_id, source_url)
    conn.execute("""INSERT INTO files (institution_id, source, source_url, post_title, post_date, filename, ext,
                    downloaded_at, status, license, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 (inst_id, source, source_url, title, date, filename, ext, db.now(), status, license, note))
    conn.commit()


def save(conn, raw: Path, inst_id: str, source: str, source_url: str, content: bytes, filename: str, *,
         title=None, date=None, license=None, note=None) -> str:
    """저장하고 status(ok/duplicate)를 돌려준다."""
    sha = hashlib.sha256(content).hexdigest()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    status, rel = "duplicate", None
    _forget_failed(conn, inst_id, source_url)
    if not conn.execute("SELECT 1 FROM files WHERE sha256=?", (sha,)).fetchone():
        d = raw / inst_id / source
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{(date or 'unknown')[:7]}_{safe_name(filename)}"
        if f.exists():  # 같은 이름 다른 내용(예: '다운로드') → 해시 앞자리 붙임
            f = f.with_name(f"{f.stem}_{sha[:8]}{f.suffix}")
        f.write_bytes(content)
        status, rel = "ok", f.relative_to(raw).as_posix()
    conn.execute("""INSERT INTO files (institution_id, source, source_url, post_title, post_date, filename, ext,
                    sha256, size, downloaded_at, status, license, path, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (inst_id, source, source_url, title, date, filename, ext, sha if status == "ok" else None,
                  len(content), db.now(), status, license, rel, note))
    conn.commit()
    return status
