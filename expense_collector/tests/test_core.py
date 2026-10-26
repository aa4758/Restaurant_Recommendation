"""config · db · http_client 단위 테스트 (네트워크 없음: httpx.MockTransport)."""
import httpx
import pytest

from src import db
from src.config import load_config
from src.http_client import HttpClient, RobotsDisallowed

UA = "JJINMAT-ExpenseCollector/0.1 (+contact: test@example.com)"


def cfg_http(**kw):
    return {"user_agent": UA, "min_interval_sec": 3.0, "retries": 2, "respect_robots": True, **kw}


class FakeClock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def client(handler, **kw):
    clk = FakeClock()
    return HttpClient(cfg_http(**kw), transport=httpx.MockTransport(handler), sleep=clk.sleep, clock=clk), clk


def site(robots: str | None = "", status=None):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(404) if robots is None else httpx.Response(200, text=robots)
        return httpx.Response(status.pop(0) if status else 200, text="ok")
    return handler, calls


# --- config ---
def test_config_bom_and_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAGOKR_API_KEY", raising=False)
    (tmp_path / "config.yaml").write_text("﻿paths:\n  state_db: data/state.db\nhttp: {}\n", encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg["paths"]["state_db"] == str(tmp_path / "data/state.db")
    assert cfg["datagokr_api_key"] is None


def test_repo_config_loads():
    cfg = load_config()
    assert cfg["http"]["min_interval_sec"] >= 3.0  # 01 결정
    assert cfg["jjinmat_export"]["categories"] == ["restaurant"]  # D-2


# --- db ---
def test_db_schema_upsert_idempotent(tmp_path):
    conn = db.connect(tmp_path / "s.db")
    row = {"institution_id": "X1", "name": "가군", "type": "LOCAL_GOV"}
    db.upsert_institution(conn, row)
    db.upsert_institution(conn, {**row, "name": "가군청", "status": "needs_review"})
    assert [tuple(r) for r in conn.execute("SELECT name, status FROM institutions")] == [("가군청", "needs_review")]
    db.connect(tmp_path / "s.db")  # 재접속해도 스키마 재생성 오류 없음
    rep = db.status_report(conn)
    assert rep["institutions"] == [("LOCAL_GOV", "needs_review", 1)]


def test_db_rejects_bad_type(tmp_path):
    conn = db.connect(tmp_path / "s.db")
    with pytest.raises(Exception):
        db.upsert_institution(conn, {"institution_id": "X", "name": "n", "type": "OTHER"})


def test_runs(tmp_path):
    conn = db.connect(tmp_path / "s.db")
    rid = db.start_run(conn, "phase0")
    db.finish_run(conn, rid, "ok", "done")
    assert db.status_report(conn)["last_runs"][0][:2] == ("phase0", "ok")


# --- http_client ---
def test_rejects_placeholder_contact():
    with pytest.raises(ValueError):
        HttpClient(cfg_http(user_agent="X/0.1 (+contact: CHANGE_ME@example.com)"))


def test_robots_disallow_and_claudebot():
    h, calls = site("User-agent: *\nDisallow: /private\n\nUser-agent: ClaudeBot\nDisallow: /bbs\n")
    c, _ = client(h)
    assert c.get("https://a.go.kr/ok").text == "ok"
    for path in ("/private/x", "/bbs/list"):
        with pytest.raises(RobotsDisallowed):
            c.get("https://a.go.kr" + path)
    assert calls.count("/robots.txt") == 1  # 호스트당 1회 캐시


def test_robots_404_allows_403_denies():
    c, _ = client(site(None)[0])
    assert c.get("https://a.go.kr/x").status_code == 200

    c2, _ = client(lambda req: httpx.Response(403))
    with pytest.raises(RobotsDisallowed):
        c2.get("https://b.go.kr/x")


def test_interval_and_crawl_delay():
    c, clk = client(site("User-agent: *\nCrawl-delay: 10\n")[0])
    c.get("https://a.go.kr/1")
    c.get("https://a.go.kr/2")
    assert clk.slept[-1] == pytest.approx(10)  # Crawl-delay 가 min_interval(3) 보다 크면 그쪽

    c, clk = client(site("")[0])
    c.get("https://a.go.kr/1")
    c.get("https://a.go.kr/2")
    assert all(s == pytest.approx(3) for s in clk.slept) and len(clk.slept) == 2  # robots→1, 1→2


def test_retry_backoff_then_success():
    h, calls = site("", status=[503, 429, 200])
    c, clk = client(h)
    assert c.get("https://a.go.kr/x").status_code == 200
    assert calls.count("/x") == 3
    assert 6 in clk.slept and 3 in clk.slept  # 지수 백오프 3·2^0, 3·2^1
