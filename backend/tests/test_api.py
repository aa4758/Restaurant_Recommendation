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


def test_detail_review_report(client):
    d = client.get("/restaurants/R001").json()
    assert d["distance_m"] is None and d["score_breakdown"]["k"] == 20
    before = d["star"]
    r = client.post("/restaurants/R001/reviews", json={"stars": 5, "text": "good", "tags": []})
    assert r.status_code == 201 and r.json()["final_star"] > before
    assert client.post("/restaurants/R001/reviews", json={"stars": 3.3}).status_code == 422
    assert client.post("/restaurants/R001/report", json={"field": "price", "message": "x"}).status_code == 202
    assert client.get("/restaurants/NOPE").status_code == 404
    assert client.post("/restaurants/NOPE/reviews", json={"stars": 3}).status_code == 404


def test_gov_pii_stripped(client, tmp_path):
    import sqlite3
    cols = [r[1] for r in sqlite3.connect(tmp_path / "t.db").execute("PRAGMA table_info(gov_expense)")]
    assert not {"official_name", "card_holder", "attendees"} & set(cols)
