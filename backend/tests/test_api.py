import pytest
from fastapi.testclient import TestClient

from app.ingest.load_seed import load

CITY_HALL = {"lat": 37.5663, "lng": 126.9779}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(db))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(db)
    from app.main import app
    return TestClient(app)


def test_health_and_filters(client):
    assert client.get("/health").json() == {"status": "ok"}
    f = client.get("/meta/filters").json()
    assert set(f) == {"price", "genre", "mood", "alcohol"}


def test_recommend_contract(client):
    r = client.post("/recommend", json=CITY_HALL)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3 and isinstance(body["relaxed"], list)
    keys = {"id", "name", "genre", "price_band", "moods", "alcohol", "lat", "lng", "distance_m", "star",
            "percentile", "review_count", "gov_visits", "gov_source", "reasons", "updated_at"}
    for it in body["items"]:
        assert keys <= set(it)
        assert "공직자" not in " ".join(it["reasons"])


def test_recommend_validation(client):
    assert client.post("/recommend", json={**CITY_HALL, "alcohol": "maybe"}).status_code == 422
    assert client.post("/recommend", json={**CITY_HALL, "limit": 9}).status_code == 422


def test_seed_star_distribution(client):
    ids = [f"R{i:03d}" for i in range(1, 49)]
    stars = [client.get(f"/restaurants/{i}").json()["star"] for i in ids]
    assert abs(sum(stars) / len(stars) - 2.5) < 0.15


def test_detail_breakdown_v2_keys(client):
    keys = {"prior_star", "user_mean", "n", "k", "gov_bonus", "ad_penalty", "components", "evidence"}
    comp_keys = {"tenure", "gov", "hygiene", "designation", "partner", "sanction", "ad"}
    evidences = set()
    for i in range(1, 49):
        b = client.get(f"/restaurants/R{i:03d}").json()["score_breakdown"]
        assert keys <= set(b) and set(b["components"]) == comp_keys
        assert b["evidence"] in {"low", "mid", "high"}
        assert b["components"]["sanction"] <= 0 and b["components"]["ad"] <= 0
        assert abs(b["components"]["gov"] - b["gov_bonus"]) < 1e-3
        evidences.add(b["evidence"])
    assert evidences == {"low", "mid", "high"}  # 시드에 근거 수준 분포가 있음


def test_existing_db_gets_new_score_columns(tmp_path):
    import sqlite3
    from app import db as dbm
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE scores (restaurant_id TEXT PRIMARY KEY, prior_star REAL NOT NULL, user_mean REAL,"
              " n INTEGER NOT NULL, star REAL NOT NULL, percentile INTEGER NOT NULL, gov_visits INTEGER NOT NULL,"
              " gov_source TEXT, gov_bonus REAL NOT NULL, ad_penalty REAL, computed_at TEXT NOT NULL)")
    c.commit(); c.close()
    conn = dbm.connect(p)
    dbm.init_schema(conn)
    dbm.init_schema(conn)  # 멱등
    cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)")}
    assert {"components", "evidence"} <= cols


def test_own_review_ad_keywords_trigger_penalty(client):
    before = client.get("/restaurants/R005").json()["score_breakdown"]
    for _ in range(12):
        client.post("/restaurants/R005/reviews", json={"stars": 3, "text": "체험단으로 제공받아 작성", "tags": []})
    after = client.get("/restaurants/R005").json()["score_breakdown"]
    assert after["ad_penalty"] > before["ad_penalty"] and after["components"]["ad"] < 0


def test_detail_review_report(client):
    d = client.get("/restaurants/R001").json()
    assert d["distance_m"] is None and d["score_breakdown"]["k"] == 20
    before = d["star"]
    r = client.post("/restaurants/R001/reviews", json={"stars": 5, "text": "good", "tags": []})
    assert r.status_code == 201 and r.json()["final_star"] > before
    assert client.post("/restaurants/R001/reviews", json={"stars": 3.3}).status_code == 422
    assert client.post("/restaurants/R001/report", json={"field": "price", "message": "x"}).status_code == 202
    assert client.post("/restaurants/R001/reviews", json={"stars": 4, "text": "a" * 1001}).status_code == 422
    assert client.post("/restaurants/R001/reviews", json={"stars": 4, "tags": ["t"] * 11}).status_code == 422
    assert client.post("/restaurants/R001/report", json={"field": "price", "message": "a" * 1001}).status_code == 422
    assert client.get("/restaurants/NOPE").status_code == 404
    assert client.post("/restaurants/NOPE/reviews", json={"stars": 3}).status_code == 404


def test_gov_pii_stripped(client, tmp_path):
    import sqlite3
    cols = [r[1] for r in sqlite3.connect(tmp_path / "t.db").execute("PRAGMA table_info(gov_expense)")]
    assert not {"official_name", "card_holder", "attendees"} & set(cols)
