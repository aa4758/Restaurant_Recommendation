"""소셜 로그인(카카오·구글) — 서버 중계 방식. 결정: docs/01 '소셜 로그인 세부' L-1~L-8.

흐름: 앱이 브라우저로 GET /auth/{provider}/start?redirect=&challenge= 를 연다 → 공급자 로그인 →
GET /auth/{provider}/callback 에서 서버가 code 를 교환해 고유번호만 얻음 → 앱 주소로 1회용 code 전달 →
앱이 POST /auth/token {code, verifier} 로 세션 토큰을 받음(verifier 는 앱만 알아서 code 를 가로채도 못 씀).

환경변수: AUTH_SECRET(필수, 고유번호 HMAC 키), KAKAO_REST_KEY, KAKAO_CLIENT_SECRET(콘솔에서 켰을 때만),
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, PUBLIC_BASE_URL(서버 외부 주소, 기본 http://localhost:8000),
AUTH_REDIRECTS(돌아갈 앱 주소 접두어 허용 목록, 쉼표 구분).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query as Q, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.db import get_conn

SESSION_DAYS = 90
FLOW_MINUTES = 10
CODE_MINUTES = 5
DEFAULT_REDIRECTS = "jjinmat://,exp://,http://localhost:8081/"  # 배포 시 AUTH_REDIRECTS=jjinmat:// 로 좁힘

PROVIDERS = {
    "kakao": {
        "authorize": "https://kauth.kakao.com/oauth/authorize",
        "token": "https://kauth.kakao.com/oauth/token",
        "id_env": "KAKAO_REST_KEY",
        "secret_env": "KAKAO_CLIENT_SECRET",
        "scope": None,  # 동의 항목 없음(L-8): 고유번호만
    },
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
        "scope": "openid",
    },
}

router = APIRouter(prefix="/auth")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _secret() -> bytes:
    s = os.environ.get("AUTH_SECRET", "")
    if len(s) < 16:
        raise HTTPException(status_code=503, detail="login not configured")
    return s.encode()


def subject_hash(provider: str, subject: str) -> str:
    return hmac.new(_secret(), f"{provider}:{subject}".encode(), hashlib.sha256).hexdigest()


def _client(provider: str) -> tuple[str, str]:
    p = PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail="unknown provider")
    cid = os.environ.get(p["id_env"], "").strip()
    if not cid:
        raise HTTPException(status_code=503, detail="login not configured")
    return cid, os.environ.get(p["secret_env"], "").strip()


def _callback_url(provider: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/auth/{provider}/callback"


def _redirect_ok(url: str) -> bool:
    allowed = [a.strip() for a in os.environ.get("AUTH_REDIRECTS", DEFAULT_REDIRECTS).split(",") if a.strip()]
    return any(url.startswith(a) for a in allowed)


def _with_params(url: str, **params: str) -> str:
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)


def _post_form(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_subject(provider: str, code: str) -> str:
    """공급자 code → 고유번호(문자열). 테스트에서 monkeypatch."""
    cid, secret = _client(provider)
    form = {"grant_type": "authorization_code", "client_id": cid, "redirect_uri": _callback_url(provider), "code": code}
    if secret:
        form["client_secret"] = secret
    tok = _post_form(PROVIDERS[provider]["token"], form)
    if provider == "kakao":
        req = urllib.request.Request("https://kapi.kakao.com/v2/user/me",
                                     headers={"Authorization": f"Bearer {tok['access_token']}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return str(json.load(r)["id"])
    # 구글: 토큰 엔드포인트에서 TLS 로 직접 받은 id_token 이라 서명 검증 생략 가능(구글 문서). aud 만 확인
    payload = tok["id_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    if claims.get("aud") != cid:
        raise ValueError("aud mismatch")
    return str(claims["sub"])


@router.get("/{provider}/start")
def start(provider: str, redirect: str, challenge: str = Q(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$"),
          conn=Depends(get_conn)) -> RedirectResponse:
    cid, _ = _client(provider)
    _secret()  # 설정 누락이면 공급자로 보내기 전에 503
    if not _redirect_ok(redirect):
        raise HTTPException(status_code=400, detail="redirect not allowed")
    now = _now()
    conn.execute("DELETE FROM auth_flows WHERE expires_at < ?", (now.isoformat(),))
    state = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO auth_flows(state,provider,redirect,challenge,expires_at) VALUES(?,?,?,?,?)",
                 (state, provider, redirect, challenge, (now + timedelta(minutes=FLOW_MINUTES)).isoformat()))
    conn.commit()
    params = {"client_id": cid, "redirect_uri": _callback_url(provider), "response_type": "code", "state": state}
    if PROVIDERS[provider]["scope"]:
        params["scope"] = PROVIDERS[provider]["scope"]
    return RedirectResponse(_with_params(PROVIDERS[provider]["authorize"], **params), status_code=302)


@router.get("/{provider}/callback")
def callback(provider: str, state: str = "", code: str = "", error: str = "", conn=Depends(get_conn)) -> RedirectResponse:
    flow = conn.execute("SELECT * FROM auth_flows WHERE state=? AND provider=? AND code IS NULL AND expires_at >= ?",
                        (state, provider, _now().isoformat())).fetchone()
    if flow is None:
        raise HTTPException(status_code=400, detail="invalid or expired login")
    fail = lambda reason: RedirectResponse(_with_params(flow["redirect"], error=reason), status_code=302)  # noqa: E731
    if error or not code:
        conn.execute("DELETE FROM auth_flows WHERE state=?", (state,))
        conn.commit()
        return fail("cancelled")
    try:
        h = subject_hash(provider, fetch_subject(provider, code))
    except HTTPException:
        raise
    except Exception:  # 공급자 응답 오류·네트워크
        conn.execute("DELETE FROM auth_flows WHERE state=?", (state,))
        conn.commit()
        return fail("provider")
    row = conn.execute("SELECT user_id FROM identities WHERE provider=? AND subject_hash=?", (provider, h)).fetchone()
    if row:
        uid = row["user_id"]
    else:
        uid = conn.execute("INSERT INTO users(created_at) VALUES(?)", (_now().isoformat(),)).lastrowid
        conn.execute("INSERT INTO identities(provider,subject_hash,user_id) VALUES(?,?,?)", (provider, h, uid))
    one_time = secrets.token_urlsafe(24)
    conn.execute("UPDATE auth_flows SET code=?, user_id=?, expires_at=? WHERE state=?",
                 (one_time, uid, (_now() + timedelta(minutes=CODE_MINUTES)).isoformat(), state))
    conn.commit()
    return RedirectResponse(_with_params(flow["redirect"], code=one_time), status_code=302)


class TokenIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    verifier: str = Field(min_length=43, max_length=128)


@router.post("/token")
def token(body: TokenIn, conn=Depends(get_conn)) -> dict:
    flow = conn.execute("SELECT * FROM auth_flows WHERE code=? AND expires_at >= ?",
                        (body.code, _now().isoformat())).fetchone()
    conn.execute("DELETE FROM auth_flows WHERE code=?", (body.code,))  # 성공·실패 무관 1회용
    conn.commit()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(body.verifier.encode()).digest()).decode().rstrip("=")
    if flow is None or not hmac.compare_digest(challenge, flow["challenge"]):
        raise HTTPException(status_code=400, detail="invalid code")
    tok = secrets.token_urlsafe(32)
    exp = (_now() + timedelta(days=SESSION_DAYS)).isoformat()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
    conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (_sha256(tok), flow["user_id"], exp))
    conn.commit()
    return {"token": tok, "expires_at": exp, "provider": flow["provider"]}


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def current_user(authorization: str | None = Header(default=None), conn=Depends(get_conn)) -> int:
    """Bearer 토큰 → user_id. 없거나 만료면 401."""
    tok = _bearer(authorization)
    row = tok and conn.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at >= ?",
                               (_sha256(tok), _now().isoformat())).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="login required")
    return row["user_id"]


@router.get("/me")
def me(uid: int = Depends(current_user), conn=Depends(get_conn)) -> dict:
    u = conn.execute("SELECT u.created_at, i.provider FROM users u JOIN identities i ON i.user_id=u.id WHERE u.id=?",
                     (uid,)).fetchone()
    return {"provider": u["provider"], "created_at": u["created_at"]}


@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), uid: int = Depends(current_user),
           conn=Depends(get_conn)) -> Response:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_sha256(_bearer(authorization)),))
    conn.commit()
    return Response(status_code=204)


@router.delete("/me", status_code=204)
def delete_me(uid: int = Depends(current_user), conn=Depends(get_conn)) -> Response:
    """회원 탈퇴(L-7): 계정·로그인 수단·토큰·그 계정의 리뷰 삭제 후 영향받은 시군구 점수 재계산."""
    from app.reviews import aggregate  # 순환 import 회피
    from app.service import rebuild_scores, region_of

    rids = [r[0] for r in conn.execute("SELECT DISTINCT restaurant_id FROM user_reviews WHERE user_id=?", (str(uid),))]
    conn.execute("DELETE FROM user_reviews WHERE user_id=?", (str(uid),))  # review_menus 는 CASCADE
    conn.execute("DELETE FROM review_deletions WHERE user_id=?", (str(uid),))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))  # identities·sessions 는 ON DELETE CASCADE
    for rid in rids:
        aggregate(conn, rid)  # 확정 메뉴·가격대·분위기 다시 계산
    conn.commit()
    for region in {region_of(conn, rid) for rid in rids}:
        rebuild_scores(conn, region)
    return Response(status_code=204)
