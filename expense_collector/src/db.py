"""SQLite 상태 DB (data/state.db). CSV 는 사람 검토용 export 이고 진실의 원천은 여기다."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions (
    institution_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('METRO_EDU','LOCAL_EDU','METRO_GOV','LOCAL_GOV','CENTRAL','OTHER')),
    parent TEXT,
    region TEXT,
    homepage_url TEXT,
    admin_code TEXT,
    source TEXT,                      -- 목록을 얻은 출처
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','needs_review','excluded')),  -- excluded: 홈페이지 미확보로 대상 제외
    note TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_survey (
    institution_id TEXT NOT NULL REFERENCES institutions(institution_id),
    source TEXT NOT NULL CHECK (source IN ('DATAGOKR','BOARD','OPENGOKR')),
    url TEXT NOT NULL DEFAULT '',
    available TEXT CHECK (available IN ('yes','no','unknown')),
    coverage_from TEXT, coverage_to TEXT, scope TEXT, formats TEXT,
    license TEXT,                     -- 공공누리 유형·이용허락범위 (01 결정: 1유형 외 적재 보류)
    priority INTEGER,
    status TEXT CHECK (status IN ('found','not_found','needs_review','error')),
    note TEXT,
    checked_at TEXT,
    PRIMARY KEY (institution_id, source, url)
);
CREATE TABLE IF NOT EXISTS board_registry (
    institution_id TEXT PRIMARY KEY REFERENCES institutions(institution_id),
    board_url TEXT, cms_id TEXT, list_pagination TEXT, file_formats TEXT,
    pdf_kind TEXT CHECK (pdf_kind IN ('text','scanned','mixed','n/a')),
    robots_allowed TEXT CHECK (robots_allowed IN ('yes','no')),
    terms_ok TEXT CHECK (terms_ok IN ('yes','no','unknown')),  -- 약관상 자동수집 금지 없음
    license TEXT,
    needs_js TEXT CHECK (needs_js IN ('yes','no')),
    download_method TEXT CHECK (download_method IN ('direct','post','js')),
    crawl_grade TEXT CHECK (crawl_grade IN ('A','B','C')),
    posts_in_period INTEGER,
    note TEXT,
    checked_at TEXT
);
CREATE TABLE IF NOT EXISTS files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(institution_id),
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    post_title TEXT, post_date TEXT,
    filename TEXT, ext TEXT,
    sha256 TEXT UNIQUE,
    size INTEGER,
    downloaded_at TEXT,
    status TEXT,                      -- ok / duplicate(같은 내용 이미 있음) / failed / blocked(robots) / link(외부 링크만) / needs_key
    license TEXT,                     -- 게시글·데이터셋마다 다시 읽은 공공누리 유형(출처 표기용)
    path TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS posts (     -- Phase 3 게시판: 처리한 게시글(이어하기용)
    institution_id TEXT NOT NULL,
    post_url TEXT NOT NULL,
    title TEXT, post_date TEXT,
    n_files INTEGER,
    status TEXT,                      -- ok / failed / blocked
    note TEXT,
    collected_at TEXT,
    PRIMARY KEY (institution_id, post_url)
);
CREATE TABLE IF NOT EXISTS collect_status (  -- Phase 3 기관·출처 단위 결과
    institution_id TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT,                      -- done / failed
    pages INTEGER, posts INTEGER, files INTEGER,
    note TEXT,
    finished_at TEXT,
    PRIMARY KEY (institution_id, source)
);
CREATE TABLE IF NOT EXISTS parsed_tables (
    file_id INTEGER NOT NULL REFERENCES files(file_id),
    table_index INTEGER NOT NULL,
    path TEXT,
    n_rows INTEGER,
    parse_status TEXT CHECK (parse_status IN ('ok','failed','flagged')),
    parse_confidence REAL,
    error TEXT,
    parsed_at TEXT,
    PRIMARY KEY (file_id, table_index)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT NOT NULL,
    args TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','failed')),
    summary TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Phase 3 는 호스트별 작업자가 동시에 기록
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    for col in ("license", "path", "note"):  # 이전 스키마 DB 이어 쓰기
        if col not in have:
            conn.execute(f"ALTER TABLE files ADD COLUMN {col} TEXT")
    return conn


def start_run(conn, phase: str, args: str = "") -> int:
    cur = conn.execute("INSERT INTO runs (phase, args, started_at) VALUES (?,?,?)", (phase, args, now()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, status: str, summary: str = "") -> None:
    conn.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE run_id=?", (now(), status, summary, run_id))
    conn.commit()


def upsert_institution(conn, row: dict) -> None:
    """같은 institution_id 면 덮어쓴다(재실행 안전)."""
    cols = ["institution_id", "name", "type", "parent", "region", "homepage_url", "admin_code", "source", "status", "note"]
    vals = [row.get(c) for c in cols]
    vals[cols.index("status")] = row.get("status") or "ok"
    conn.execute(
        f"INSERT INTO institutions ({','.join(cols)}, updated_at) VALUES ({','.join('?' * len(cols))}, ?) "
        f"ON CONFLICT(institution_id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in cols[1:])}, updated_at=excluded.updated_at",
        [*vals, now()],
    )


def status_report(conn) -> dict:
    q = lambda sql: [tuple(r) for r in conn.execute(sql)]
    return {
        "institutions": q("SELECT type, status, COUNT(*) FROM institutions GROUP BY type, status ORDER BY type, status"),
        "source_survey": q("SELECT source, status, COUNT(*) FROM source_survey GROUP BY source, status ORDER BY source, status"),
        "board_registry": q("SELECT crawl_grade, COUNT(*) FROM board_registry GROUP BY crawl_grade ORDER BY crawl_grade"),
        "files": q("SELECT source, status, COUNT(*) FROM files GROUP BY source, status ORDER BY source, status"),
        "parsed_tables": q("SELECT parse_status, COUNT(*) FROM parsed_tables GROUP BY parse_status ORDER BY parse_status"),
        "last_runs": q("SELECT phase, status, started_at, summary FROM runs ORDER BY run_id DESC LIMIT 5"),
    }
