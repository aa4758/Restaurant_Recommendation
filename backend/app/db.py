"""SQLite 연결/스키마 (MVP). 경로: 환경변수 JJINMAT_DB, 기본 backend/data/jjinmat.db"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_DIR / "data" / "jjinmat.db"

SCHEMA = """
-- 데이터 사전·출처: docs/04_data_plan.md
CREATE TABLE IF NOT EXISTS restaurants (
    id TEXT PRIMARY KEY,               -- 샘플 R###, 상가정보 S{상가업소번호}
    name TEXT NOT NULL,
    branch TEXT,                       -- 지점명
    genre TEXT NOT NULL,
    genre_detail TEXT,                 -- 원본 소분류 (예: 국/탕/찌개류)
    price_band TEXT,                   -- NULL = 미확인
    moods TEXT NOT NULL DEFAULT '',
    alcohol INTEGER,                   -- 1/0, NULL = 미확인
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    address TEXT,                      -- 도로명 우선
    address_jibun TEXT,
    floor TEXT,
    sido TEXT,
    sigungu TEXT,
    sigungu_code TEXT,                 -- 엄격 별점 분위수 계산 단위
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- open | closed
    opened_at TEXT,                    -- 인허가일자 (업력)
    closed_at TEXT,
    license_type TEXT,                 -- 일반음식점 | 휴게음식점 (휴게 = 주류 판매 불가)
    franchise_brand TEXT,
    seats INTEGER,
    area_m2 REAL,
    parking INTEGER,
    reservation INTEGER,
    takeout INTEGER,
    holiday_note TEXT,                 -- 정기휴무 자유기술 (예: 매월 둘째 화요일)
    sbiz_id TEXT UNIQUE,               -- 소상공인 상가업소번호
    license_id TEXT UNIQUE,            -- 인허가 관리번호
    kakao_place_id TEXT UNIQUE,        -- 지도 링크 place.map.kakao.com/{id}
    tour_content_id TEXT UNIQUE,       -- 한국관광공사 TourAPI
    source TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_restaurants_lat_lng ON restaurants(lat, lng);
CREATE INDEX IF NOT EXISTS idx_restaurants_sigungu ON restaurants(sigungu_code, status);
CREATE TABLE IF NOT EXISTS menus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    name TEXT NOT NULL,
    price INTEGER,                     -- 원
    is_signature INTEGER NOT NULL DEFAULT 0,
    source TEXT,                       -- tourapi | good_price | receipt | owner
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_menus_restaurant ON menus(restaurant_id);
-- 요일별 1행, 행이 없는 요일 = 휴무(데이터가 있는 가게에 한함)
CREATE TABLE IF NOT EXISTS opening_hours (
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0=월
    open_time TEXT,                    -- HH:MM
    close_time TEXT,                   -- 자정 넘기면 25:30 처럼 표기
    break_start TEXT,
    break_end TEXT,
    last_order TEXT,
    source TEXT,
    updated_at TEXT,
    PRIMARY KEY (restaurant_id, weekday)
);
-- 공공 신호: hygiene_grade | sanction | model_restaurant | good_price | safe_restaurant | century_store
CREATE TABLE IF NOT EXISTS restaurant_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    kind TEXT NOT NULL,
    value TEXT,
    detail TEXT,
    base_date TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_restaurant ON restaurant_signals(restaurant_id, kind);
-- value: hygiene_grade = 매우우수|우수|좋음, 그 외 자유기술. base_date: 지정일·처분일(YYYY-MM-DD)
-- 점수 배치 결과 (app/service.py rebuild_scores). 영업 중인 가게만, 시군구 단위로 재계산
CREATE TABLE IF NOT EXISTS scores (
    restaurant_id TEXT PRIMARY KEY REFERENCES restaurants(id),
    prior_star REAL NOT NULL,
    user_mean REAL,
    n INTEGER NOT NULL,
    star REAL NOT NULL,
    percentile INTEGER NOT NULL,
    gov_visits INTEGER NOT NULL,
    gov_source TEXT,
    gov_bonus REAL NOT NULL,
    ad_penalty REAL,                   -- NULL = 광고 리뷰 통계 없음
    components TEXT,                   -- JSON: 점수 모델 v2 구성요소 7개(가중 기여분, 감점은 음수)
    evidence TEXT,                     -- low | mid | high
    computed_at TEXT NOT NULL
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
    user_id TEXT,                      -- 기기 ID (로그인 전)
    verified INTEGER NOT NULL DEFAULT 0,  -- 영수증 인증 = 1
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant ON user_reviews(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_gov_restaurant ON gov_expense(restaurant_id);
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


# 기존 DB 호환: CREATE TABLE IF NOT EXISTS 는 컬럼을 추가하지 않으므로 없으면 ALTER
MIGRATIONS = {
    "scores": (("components", "TEXT"), ("evidence", "TEXT")),
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
