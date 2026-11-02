import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """메모리 레이트리밋은 프로세스 전역 → 테스트 간 누적 방지."""
    from app.ratelimit import write_limiter
    write_limiter.reset()
    yield
    write_limiter.reset()


@pytest.fixture()
def login(monkeypatch):
    """계정 + 세션을 DB(JJINMAT_DB)에 바로 만들고 Authorization 헤더를 돌려줌. 리뷰 작성은 로그인 필수(docs/01 L-5)."""
    import secrets
    from datetime import datetime, timedelta, timezone

    from app import db
    from app.auth import _sha256

    monkeypatch.setenv("AUTH_SECRET", "test-secret-0123456789")

    def make() -> dict:
        conn = db.connect()
        db.init_schema(conn)
        now = datetime.now(timezone.utc)
        uid = conn.execute("INSERT INTO users(created_at) VALUES(?)", (now.isoformat(),)).lastrowid
        conn.execute("INSERT INTO identities(provider,subject_hash,user_id) VALUES('kakao',?,?)", (secrets.token_hex(8), uid))
        tok = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                     (_sha256(tok), uid, (now + timedelta(days=1)).isoformat()))
        conn.commit()
        conn.close()
        return {"Authorization": f"Bearer {tok}"}

    return make
