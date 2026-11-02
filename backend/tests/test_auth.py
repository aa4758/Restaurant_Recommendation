"""소셜 로그인(docs/01 L-1~L-8): 공급자 호출(fetch_subject)만 가짜로 바꾸고 전체 흐름 검증."""
import base64
import hashlib
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.ingest.load_seed import load

APP = "http://localhost:8081/auth"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


@pytest.fixture()
def dbp(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(p))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(p)
    monkeypatch.setenv("AUTH_SECRET", "test-secret-0123456789")
    monkeypatch.setenv("KAKAO_REST_KEY", "kakao-test")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-test")
    monkeypatch.delenv("AUTH_REDIRECTS", raising=False)
    from app import auth
    monkeypatch.setattr(auth, "fetch_subject", lambda provider, code: f"subject-{code}")
    return p


@pytest.fixture()
def client(dbp):
    from app.main import app
    return TestClient(app, follow_redirects=False)


def _login(client, provider="kakao", subject_code="123", verifier=VERIFIER, challenge=CHALLENGE):
    r = client.get(f"/auth/{provider}/start", params={"redirect": APP, "challenge": challenge})
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == [f"http://localhost:8000/auth/{provider}/callback"]
    assert ("scope" in q) == (provider == "google")  # 카카오는 동의 항목 없음(L-8)
    cb = client.get(f"/auth/{provider}/callback", params={"state": q["state"][0], "code": subject_code})
    assert cb.status_code == 302 and cb.headers["location"].startswith(APP + "?code=")
    code = parse_qs(urlparse(cb.headers["location"]).query)["code"][0]
    return code, client.post("/auth/token", json={"code": code, "verifier": verifier})


def test_full_flow_review_logout(client, dbp):
    code, r = _login(client)
    assert r.status_code == 200 and r.json()["provider"] == "kakao"
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/auth/me", headers=h).json()["provider"] == "kakao"
    assert client.post("/restaurants/R001/reviews", json={"stars": 4}, headers=h).status_code == 201
    # 1회용 code 재사용 불가
    assert client.post("/auth/token", json={"code": code, "verifier": VERIFIER}).status_code == 400
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/auth/me", headers=h).status_code == 401
    # DB 에 고유번호·토큰 원문 없음
    dump = "\n".join(sqlite3.connect(dbp).iterdump())
    assert "subject-123" not in dump and r.json()["token"] not in dump


def test_review_requires_login(client):
    assert client.post("/restaurants/R001/reviews", json={"stars": 4}).status_code == 401
    assert client.post("/restaurants/R001/reviews", json={"stars": 4},
                       headers={"Authorization": "Bearer nope"}).status_code == 401


def test_same_subject_same_account_other_provider_new_account(client, dbp):
    _login(client, "kakao", "1")
    _login(client, "kakao", "1")
    _login(client, "google", "1")  # 계정 연결 없음(L-3)
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_wrong_verifier_rejected(client):
    _, r = _login(client, verifier="w" * 43)
    assert r.status_code == 400


def test_redirect_allowlist_and_bad_provider(client):
    bad = client.get("/auth/kakao/start", params={"redirect": "https://evil.example/x", "challenge": CHALLENGE})
    assert bad.status_code == 400
    assert client.get("/auth/naver/start", params={"redirect": APP, "challenge": CHALLENGE}).status_code == 404
    assert client.get("/auth/kakao/callback", params={"state": "forged", "code": "x"}).status_code == 400


def test_not_configured_is_503(client, monkeypatch):
    monkeypatch.delenv("AUTH_SECRET")
    assert client.get("/auth/kakao/start", params={"redirect": APP, "challenge": CHALLENGE}).status_code == 503


def test_cancel_returns_error_to_app(client):
    r = client.get("/auth/kakao/start", params={"redirect": APP, "challenge": CHALLENGE})
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    cb = client.get("/auth/kakao/callback", params={"state": state, "error": "access_denied"})
    assert cb.headers["location"] == APP + "?error=cancelled"


def test_delete_account_removes_reviews_and_rescores(client, dbp):
    before = client.get("/restaurants/R001").json()["star"]
    _, r = _login(client)
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    for _ in range(3):
        client.post("/restaurants/R001/reviews", json={"stars": 0.5}, headers=h)
    assert client.get("/restaurants/R001").json()["star"] != before
    assert client.delete("/auth/me", headers=h).status_code == 204
    c = sqlite3.connect(dbp)
    assert [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("users", "identities", "sessions", "user_reviews")] == [0, 0, 0, 0]
    assert client.get("/restaurants/R001").json()["star"] == before
