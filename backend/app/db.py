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
    alcohol_src TEXT,                  -- 'license' = 휴게음식점 인허가로 0 강제 (ingest/load_license.py)
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
    source TEXT,                       -- tourapi | good_price | receipt | owner | <지정 kind>(주된음식)
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
-- 공공 신호: hygiene_grade | sanction | model_restaurant | safe_restaurant | origin_label_excellent (지정업소)
--   | century_store (업력 보정) | good_price (점수 무관, 가성비 태그)
--   | taste_of_seoul | seoul_future_heritage | local_food | gyeonggi_best | michelin_* (외부 평판 가이드) — app/scoring/prior.py SIGNAL_KINDS
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
    components TEXT,                   -- JSON: 점수 모델 v2.1 구성요소 7개(가중 기여분, 감점은 음수)
    evidence TEXT,                     -- low | mid | high
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_stats (
    restaurant_id TEXT PRIMARY KEY REFERENCES restaurants(id),
    ext_rating REAL,                   -- 제휴 평점(1~5), NULL = 없음 → 외부 평판(reputation)에서 제외, 가이드도 없으면 중립 0.4
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
    created_at TEXT NOT NULL,
    ad_disclosed INTEGER               -- 광고·협찬 표시(prior.is_ad_text) 1/0, 작성 시 저장. NULL = 미계산 → 백필
);
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant ON user_reviews(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_gov_restaurant ON gov_expense(restaurant_id);
-- 좋아요/싫어요 (개인화 전용, 점수·순위 미사용). 기기·가게당 1행 upsert, value none = 삭제
CREATE TABLE IF NOT EXISTS reactions (
    device_id TEXT NOT NULL,           -- 기기 ID (로그인 전, 외부 비공개)
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    value TEXT NOT NULL CHECK (value IN ('like', 'dislike')),
    reason TEXT,                       -- dislike 일 때만: far | price | not_into | visited
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, restaurant_id)
);
CREATE INDEX IF NOT EXISTS idx_reviews_restaurant_created ON user_reviews(restaurant_id, created_at, id);
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
    "user_reviews": (("ad_disclosed", "INTEGER"),),
    "restaurants": (("alcohol_src", "TEXT"),),
}

# 컬럼 마이그레이션 후에 만들어야 하는 인덱스(구 DB 에는 SCHEMA 실행 시점에 컬럼이 없음)
POST_MIGRATION_INDEXES = (
    # 리뷰 시트 키셋 페이지네이션: 광고 표시 아님 먼저 → 최신순 → id 내림차순
    "CREATE INDEX IF NOT EXISTS idx_reviews_sheet ON user_reviews"
    "(restaurant_id, ad_disclosed, created_at DESC, id DESC)",
    # 백필 대상(미계산) 행만 담는 부분 인덱스 → 요청마다 확인해도 저렴
    "CREATE INDEX IF NOT EXISTS idx_reviews_ad_pending ON user_reviews(id) WHERE ad_disclosed IS NULL",
)


def _migrate(conn: sqlite3.Connection) -> set[str]:
    """없는 컬럼을 ALTER 로 추가. 반환: 컬럼이 추가된 테이블."""
    changed: set[str] = set()
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
                changed.add(table)
    return changed


def backfill_ad_disclosed(conn: sqlite3.Connection) -> int:
    """ad_disclosed 가 NULL 인 리뷰(기존 행·API 외 경로 적재분)를 본문 판별로 채움. 반환: 갱신 행 수."""
    rows = conn.execute("SELECT id, text FROM user_reviews WHERE ad_disclosed IS NULL").fetchall()
    if not rows:
        return 0
    from app.scoring.prior import is_ad_text  # 순환 import 회피

    conn.executemany("UPDATE user_reviews SET ad_disclosed=? WHERE id=?",
                     [(int(is_ad_text(r[1])), r[0]) for r in rows])
    return len(rows)


def _dedupe_signals(conn: sqlite3.Connection) -> None:
    """기존 DB 의 restaurant_signals 중복(재적재 누적) 정리 후 UNIQUE 인덱스 생성."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'uq_signals'").fetchone():
        return
    conn.execute(
        "DELETE FROM restaurant_signals WHERE id NOT IN (SELECT MIN(id) FROM restaurant_signals"
        " GROUP BY restaurant_id, kind, IFNULL(value, ''), IFNULL(base_date, ''))"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_signals ON restaurant_signals"
        "(restaurant_id, kind, IFNULL(value, ''), IFNULL(base_date, ''))"  # NULL 도 같은 값으로 취급
    )


# PRAGMA user_version: 마이그레이션 완료 기록. 1 = v2.1(partner→reputation 키 재계산 완료)
SCHEMA_VERSION = 1


def _table_info(conn: sqlite3.Connection, table: str) -> dict[str, tuple]:
    """컬럼명 → (type, notnull, default, pk)."""
    return {r[1]: (r[2], r[3], r[4], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")}


def _unique_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    out: set[str] = set()
    for idx in conn.execute(f"PRAGMA index_list({table})"):
        if idx[3] == "u":  # 컬럼 정의의 UNIQUE 제약
            out.update(r[2] for r in conn.execute(f"PRAGMA index_info({idx[1]})"))
    return out


def _upgrade_tables(conn: sqlite3.Connection) -> set[str]:
    """구버전 DB(v1 등)를 현재 SCHEMA 로 맞춤. SCHEMA 실행 전에 호출(없는 컬럼에 인덱스를 만들다 실패하지 않게).

    - 없는 컬럼이 ALTER 로 추가 가능하면(UNIQUE 아님, NOT NULL 이면 기본값 있음) ALTER.
    - 아니면(예: v1 restaurants 의 price_band·alcohol NOT NULL, sbiz_id UNIQUE 추가) 테이블 재생성 후 공통 컬럼 복사.
    반환: 바뀐 테이블.
    """
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    have_tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    changed: set[str] = set()
    for table, ddl in ref.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table not in have_tables:
            continue
        want, have = _table_info(ref, table), _table_info(conn, table)
        missing = [c for c in want if c not in have]
        uniq = _unique_cols(ref, table)
        notnull_mismatch = any(have[c][1] and not want[c][1] for c in want if c in have)
        alterable = all(c not in uniq and (not want[c][1] or want[c][2] is not None) for c in missing)
        if not missing and not notnull_mismatch:
            continue
        if alterable and not notnull_mismatch:
            for c in missing:
                typ, notnull, dflt, _ = want[c]
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {c} {typ}"
                             + (f" NOT NULL DEFAULT {dflt}" if notnull else (f" DEFAULT {dflt}" if dflt is not None else "")))
        else:
            common = ",".join(c for c in want if c in have)
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA legacy_alter_table = ON")  # 다른 테이블의 FK 참조가 __old 로 바뀌지 않게
            try:
                conn.execute(f"ALTER TABLE {table} RENAME TO {table}__old")
                conn.execute(ddl)
                conn.execute(f"INSERT INTO {table}({common}) SELECT {common} FROM {table}__old")
                conn.execute(f"DROP TABLE {table}__old")
                conn.commit()
            finally:
                conn.execute("PRAGMA legacy_alter_table = OFF")
                conn.execute("PRAGMA foreign_keys = ON")
        changed.add(table)
    ref.close()
    return changed


def init_schema(conn: sqlite3.Connection) -> None:
    upgraded = _upgrade_tables(conn)  # 구버전 DB 보강(현재 DB 면 PRAGMA 몇 번으로 끝남)
    conn.executescript(SCHEMA)
    changed = _migrate(conn) | upgraded  # PRAGMA table_info 만(저렴) — 누락 컬럼 보강
    for ddl in POST_MIGRATION_INDEXES:
        conn.execute(ddl)
    backfill_ad_disclosed(conn)  # 부분 인덱스로 미계산 행만 조회
    _dedupe_signals(conn)
    conn.commit()
    done = conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION
    # scores 에 v2 컬럼을 막 추가했다면 기존 행은 NULL → 즉시 재계산(근거 부족 오표시 방지)
    # v2 → v2.1: components 에 구 키 partner 가 남아 있으면 재계산(reputation 키로 갱신).
    #   이 전체 스캔은 user_version 기록 전(최초 1회)에만 수행.
    stale = not done and conn.execute(
        "SELECT 1 FROM scores WHERE components LIKE '%\"partner\"%' LIMIT 1").fetchone()
    if stale or ("scores" in changed and conn.execute("SELECT 1 FROM scores LIMIT 1").fetchone()):
        from app.service import rebuild_scores  # 순환 import 회피

        rebuild_scores(conn)
    if not done:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
