"""SQLite 연결/스키마 (MVP). 경로: 환경변수 JJINMAT_DB, 기본 backend/data/jjinmat.db"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_DIR / "data" / "jjinmat.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS restaurants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    genre TEXT NOT NULL,
    price_band TEXT NOT NULL,
    moods TEXT NOT NULL DEFAULT '',
    alcohol INTEGER NOT NULL DEFAULT 0,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    address TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS review_stats (
    restaurant_id TEXT PRIMARY KEY REFERENCES restaurants(id),
    ext_rating REAL,
    ext_review_count INTEGER,
    ad_ratio REAL NOT NULL DEFAULT 0,
    ad_conf REAL NOT NULL DEFAULT 0,
    source TEXT,
    updated_at TEXT
);
-- 개인정보(집행자/카드소지자/참석자 성명 등)는 적재 전 제거됨
CREATE TABLE IF NOT EXISTS gov_expense (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    exec_date TEXT,
    agency TEXT,
    amount INTEGER,
    purpose TEXT,
    source TEXT,
    base_year INTEGER
);
CREATE TABLE IF NOT EXISTS user_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    stars REAL NOT NULL,
    text TEXT,
    tags TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    field TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("JJINMAT_DB", str(DEFAULT_DB)))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
