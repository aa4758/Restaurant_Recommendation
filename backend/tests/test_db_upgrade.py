"""구버전(v1) DB 를 현재 스키마로 자동 업그레이드 — 로컬에 남아 있던 v1 jjinmat.db 에서 init_schema 가 실패하던 문제."""
import sqlite3

from app.db import connect, init_schema

V1_SCHEMA = """
CREATE TABLE restaurants (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, genre TEXT NOT NULL, price_band TEXT NOT NULL,
    moods TEXT NOT NULL DEFAULT '', alcohol INTEGER NOT NULL DEFAULT 0,
    lat REAL NOT NULL, lng REAL NOT NULL, address TEXT, updated_at TEXT
);
CREATE TABLE review_stats (
    restaurant_id TEXT PRIMARY KEY REFERENCES restaurants(id), ext_rating REAL, ext_review_count INTEGER,
    ad_ratio REAL NOT NULL DEFAULT 0, ad_conf REAL NOT NULL DEFAULT 0, source TEXT, updated_at TEXT
);
CREATE TABLE gov_expense (
    id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    exec_date TEXT, agency TEXT, amount INTEGER, purpose TEXT, source TEXT, base_year INTEGER
);
CREATE TABLE user_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    stars REAL NOT NULL, text TEXT, tags TEXT, created_at TEXT NOT NULL
);
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
    field TEXT NOT NULL, message TEXT, created_at TEXT NOT NULL
);
"""


def test_v1_db_upgrades_and_keeps_data(tmp_path):
    p = tmp_path / "old.db"
    old = sqlite3.connect(p)
    old.executescript(V1_SCHEMA)
    old.execute("INSERT INTO restaurants VALUES('R1','옛가게','한식','1~2만','',1,37.56,126.97,'서울 중구 세종대로 1','2025-01-01')")
    old.execute("INSERT INTO user_reviews(restaurant_id,stars,text,tags,created_at) VALUES('R1',3.5,'좋음','','2025-01-02')")
    old.commit()
    old.close()

    conn = connect(p)
    init_schema(conn)
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(restaurants)")}
    assert {"sigungu_code", "sbiz_id", "status", "alcohol_src"} <= set(cols)
    assert cols["price_band"][3] == 0 and cols["alcohol"][3] == 0  # NOT NULL 해제(가격·음주 미확인 허용)
    r = conn.execute("SELECT name, alcohol, status FROM restaurants WHERE id='R1'").fetchone()
    assert tuple(r) == ("옛가게", 1, "open")
    # 리뷰 FK 가 새 restaurants 를 가리키고, 신규 컬럼 백필
    assert conn.execute("SELECT ad_disclosed FROM user_reviews").fetchone()[0] == 0
    fk = conn.execute("PRAGMA foreign_key_list(user_reviews)").fetchone()
    assert fk[2] == "restaurants"
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '%__old'").fetchone()
    # v2 가 허용하는 NULL 가격·UNIQUE sbiz_id 동작
    conn.execute("INSERT INTO restaurants(id,name,genre,price_band,lat,lng,sbiz_id) VALUES('S1','새가게','한식',NULL,37.5,127.0,'X')")
    try:
        conn.execute("INSERT INTO restaurants(id,name,genre,lat,lng,sbiz_id) VALUES('S2','중복','한식',37.5,127.0,'X')")
        raise AssertionError("sbiz_id UNIQUE 미적용")
    except sqlite3.IntegrityError:
        pass
    # 두 번째 실행은 아무것도 바꾸지 않음
    init_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0] == 2
