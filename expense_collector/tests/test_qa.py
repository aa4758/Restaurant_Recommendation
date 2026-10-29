"""QA 검증 (docs/qa_report.md). QA-1~12 는 strict xfail 로 기록한 뒤 수정 → 지금은 회귀 테스트.
가상 값만 사용(실명·실번호 없음). 네트워크 없음(httpx.MockTransport)."""
import re
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest

from src import db
from src.config import load_config
from src.http_client import HttpClient, RobotsDisallowed
from src.phase3_collect.board import collect_board
from src.phase4_parse import run as p4
from src.phase5_merge import merge
from src.phase5_merge import normalize as nz
from tests.test_core import UA, FakeClock, client

ROOT = Path(__file__).resolve().parent.parent
START, END = date(2024, 11, 1), date(2026, 10, 31)


# ---------- 2. robots·요청 간격 ----------
# QA-6 (수정됨): follow_redirects=True 라 리다이렉트 대상의 robots·간격을 확인 안 함
def test_redirect_to_disallowed_path_not_followed():
    calls = []

    def h(req):
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret/\n")
        if req.url.path == "/go":
            return httpx.Response(302, headers={"location": "/secret/x"})
        return httpx.Response(200, text="ok")
    c, _ = client(h)
    try:
        c.get("https://h.example/go")
    except RobotsDisallowed:
        pass
    assert "/secret/x" not in calls


# QA-7 (수정됨): ClaudeBot 그룹의 Crawl-delay 를 간격에 반영 안 함
def test_claudebot_crawl_delay_respected():
    c, _ = client(lambda req: httpx.Response(200, text="User-agent: ClaudeBot\nCrawl-delay: 10\n"))
    assert c.interval_for("https://h.example/a") == 10


# QA-8 (수정됨): 호스트 간격이 HttpClient 인스턴스별 — 작업자 둘이 같은 호스트를 치면 3초 미만
def test_interval_across_clients_same_host():
    clk, stamps = FakeClock(), []

    def h(req):
        stamps.append(clk())
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text="ok")
    mk = lambda: HttpClient({"user_agent": UA, "min_interval_sec": 3.0, "retries": 0},
                            transport=httpx.MockTransport(h), sleep=clk.sleep, clock=clk)
    a, b = mk(), mk()  # board.run 의 호스트별 작업자 두 개가 같은 첨부 호스트를 쓰는 경우
    a.get("https://files.example/1")
    b.get("https://files.example/2")
    assert all(y - x >= 3.0 for x, y in zip(stamps, stamps[1:]))


def test_robots_txt_redirect_followed():  # 수정 후 회귀: robots.txt 자체의 리다이렉트(http→https 등)는 따라가 규칙을 읽음
    def h(req):
        if req.url.path == "/robots.txt" and req.url.scheme == "http":
            return httpx.Response(301, headers={"location": "https://h.example/robots.txt"})
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /x\n")
        return httpx.Response(200, text="ok")
    c, _ = client(h)
    assert not c.allowed("http://h.example/x/1") and c.allowed("http://h.example/y")


def test_interval_and_backoff_same_client():  # 통과 항목: 같은 클라이언트 안에서는 ≥3초 + 지수 백오프
    codes = [503, 503, 200]
    c, clk = client(lambda req: httpx.Response(404) if req.url.path == "/robots.txt"
                    else httpx.Response(codes.pop(0)))
    assert c.get("https://h.example/a").status_code == 200
    assert min(clk.slept) >= 3.0 and 3.0 * 2 in clk.slept


# ---------- 1. 이어하기 (phase3 게시판) ----------
BOARD = "https://www.gu.example/www/selectBbsNttList.do?bbsNo=1&key=2"


def _board(fail: dict):
    """게시글 1건, 첨부 a·b. fail[이름] = 남은 500 응답 횟수(-1 = 항상)."""
    def h(req):
        u = str(req.url)
        if u.endswith("/robots.txt"):
            return httpx.Response(404)
        if "selectBbsNttList" in u:
            return httpx.Response(200, text='<table><tbody><tr><td><a href="./selectBbsNttView.do?key=2&amp;nttNo=1">'
                                           '1월 업무추진비</a></td><td>2026.01.05</td></tr></tbody></table>')
        if "selectBbsNttView" in u:
            return httpx.Response(200, text='<a href="./downloadBbsFile.do?atchmnflNo=a">a.xlsx</a>'
                                           '<a href="./downloadBbsFile.do?atchmnflNo=b">b.xlsx</a>')
        n = req.url.params.get("atchmnflNo")
        if fail.get(n, 0):
            fail[n] -= 1 if fail[n] > 0 else 0
            return httpx.Response(500)
        return httpx.Response(200, content=b"PK\x03\x04 fake " + n.encode())
    return h


def _collect(tmp_path, h, conn=None):
    conn = conn or db.connect(tmp_path / "s.db")
    conn.execute("INSERT OR IGNORE INTO institutions (institution_id, name, type, updated_at) VALUES ('1','가구','LOCAL_GOV','x')")
    clk = FakeClock()
    c = HttpClient({"user_agent": UA, "min_interval_sec": 3.0, "retries": 0}, transport=httpx.MockTransport(h),
                   sleep=clk.sleep, clock=clk)
    collect_board(c, conn, tmp_path / "raw", {"institution_id": "1", "board_url": BOARD, "license": None}, START, END)
    return conn


# QA-1 (수정됨): 첨부 일부만 실패한 게시글이 posts=ok 로 남아 재실행 때 실패 첨부를 다시 받지 않음(누락)
def test_partial_failed_post_retried(tmp_path):
    h = _board({"b": 1})  # b 는 첫 시도만 500
    conn = _collect(tmp_path, h)
    _collect(tmp_path, h, conn)
    ok = {r[0] for r in conn.execute("SELECT filename FROM files WHERE status='ok'")}
    assert ok == {"a.xlsx", "b.xlsx"}


# QA-2 (수정됨): 재실행마다 같은 URL 의 failed 행이 새로 쌓임(중복 기록)
def test_failed_rows_not_duplicated(tmp_path):
    h = _board({"a": -1, "b": -1})  # 모두 항상 실패 → posts=failed → 재시도
    conn = _collect(tmp_path, h)
    _collect(tmp_path, h, conn)
    assert conn.execute("SELECT MAX(n) FROM (SELECT COUNT(*) n FROM files GROUP BY source_url)").fetchone()[0] == 1


# ---------- 1. 이어하기 (phase4) ----------
class _FakePool:
    """ProcessPoolExecutor 대역: 같은 프로세스에서 실행, POISON file_id 는 자식 프로세스가 죽은 것처럼."""
    POISON = 1

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *args):
        f = Future()
        if args[0] == self.POISON:
            f.set_exception(BrokenProcessPool("child died"))
        else:
            f.set_result(fn(*args))
        return f


# QA-3 (수정됨): 자식 프로세스를 죽이는 파일 하나가 phase4 재실행을 영구히 막음(뒤 파일 진행 불가)
def test_phase4_poison_file_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(p4, "ProcessPoolExecutor", _FakePool)
    raw = tmp_path / "raw"
    (raw / "1").mkdir(parents=True)
    conn = db.connect(tmp_path / "s.db")
    conn.execute("INSERT INTO institutions (institution_id, name, type, updated_at) VALUES ('1','가구','LOCAL_GOV','x')")
    for fid in (1, 2):
        (raw / "1" / f"{fid}.csv").write_bytes(b"a,b\n1,2\n")
        conn.execute("INSERT INTO files (file_id, institution_id, source, source_url, ext, status, path) "
                     "VALUES (?, '1', 'BOARD', ?, 'csv', 'ok', ?)", (fid, f"u{fid}", f"1/{fid}.csv"))
    conn.commit()
    cfg = {"paths": {"state_db": str(tmp_path / "s.db"), "raw": str(raw), "parsed": str(tmp_path / "parsed")}}
    for _ in range(2):  # 중단 후 재실행
        try:
            p4.run(cfg, workers=1)
        except BaseException:
            pass
    assert conn.execute("SELECT 1 FROM parsed_tables WHERE file_id=2").fetchone()


# ---------- 3. PII ----------
# QA-4 (수정됨): 주민등록번호 꼴을 가리지 않음
def test_mask_rrn():
    assert "1234567" not in nz.mask_pii("확인 900101-1234567")


# QA-5 (수정됨): 이메일 주소를 가리지 않음
def test_mask_email():
    assert "@" not in nz.mask_pii("담당 abc@test.example")


# QA-9 (수정됨): 직위 없는 이름 나열(괄호 속·'참석:' 뒤)을 가리지 않음
def test_mask_name_lists():
    for s in ("간담회(가나다, 라마바)", "참석: 가나다, 라마바, 사아자"):
        out = nz.mask_pii(s)
        assert "가나다" not in out and "라마바" not in out, s


# QA-10 (수정됨): 전화·카드번호 변형(+82, ' - ' 구분, 점 구분 카드번호)을 가리지 않음
def test_mask_number_variants():
    for s in ("+82-10-0000-0000", "010 - 0000 - 0000", "카드 1234.5678.9012.3456"):
        assert not re.search(r"\d{4}", nz.mask_pii(s)), s


def test_vendor_list_not_masked():  # QA-9 수정의 오탐 방지: 상호 나열·일반 낱말은 그대로
    for s in ("(가나식당, 다라커피)", "(오찬, 만찬)", "참석: 직원, 기자"):
        assert nz.mask_pii(s) == s


def test_mask_phone_variants_ok():  # 통과 항목
    for s in ("010 0000 0000", "010.0000.0000", "01000000000", "(02)000-0000", "1234 5678 9012 3456"):
        assert not re.search(r"\d{4}", nz.mask_pii(s)), s


# ---------- 5. export 계약 ----------
def _df(rows):
    base = {c: "" for c in merge.COLUMNS}
    return pd.DataFrame([{**base, **r} for r in rows])


# QA-11 (수정됨): 금액 없음·음수(취소) 행이 export 에 들어가 방문 횟수로 셈
def test_export_amount_positive_int():
    common = dict(institution_name="가상시", exec_date="2025-10-05", source="BOARD", license="공공누리 1유형",
                  vendor_normalized="가나식당", vendor_category="restaurant", parse_confidence=0.9)
    df = _df([{**common, "amount": 60000}, {**common, "amount": None}, {**common, "amount": -60000}])
    df["amount"] = pd.to_numeric(df["amount"])
    ex = merge.to_jjinmat(df, ["restaurant"], 0.7)
    assert ex["amount"].notna().all() and (ex["amount"] > 0).all()


# QA-12 (수정됨): export 경로를 paths.output 의 parent.parent 로 계산 — output 위치를 바꾸면 엉뚱한 곳
def test_export_path_relative_to_config(tmp_path):
    (tmp_path / "config.yaml").write_text("paths:\n  output: out\nparse:\n  low_confidence: 0.7\n"
                                          "jjinmat_export:\n  path: out/gov.csv\n  categories: [restaurant]\n", encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml")
    (tmp_path / "out").mkdir()
    _df([dict(institution_name="가상시", exec_date="2025-10-05", amount=1000, source="BOARD", license="공공누리 1유형",
              vendor_normalized="가나식당", vendor_category="restaurant", parse_confidence=0.9)]
        ).to_csv(tmp_path / "out" / "expenses_merged.csv", index=False, encoding="utf-8-sig")
    merge.export_jjinmat(cfg)
    assert (tmp_path / "out" / "gov.csv").exists()


def test_export_contract_and_no_pii_columns():  # 통과 항목: 헤더·source 형식·restaurant 만·≥0.7·base_year
    common = dict(institution_name="가상시", exec_date="2025-10-05", amount=60000, executor_position="부시장",
                  department="총무과", headcount=6, payment_method="법인카드")
    df = _df([{**common, "vendor_normalized": "가나식당", "vendor_category": "restaurant", "parse_confidence": 0.7,
               "source": "DATAGOKR", "license": "공공누리 표시 없음"},
              {**common, "vendor_normalized": "다라커피", "vendor_category": "cafe", "parse_confidence": 0.9,
               "source": "BOARD", "license": "공공누리 1유형"},
              {**common, "vendor_normalized": "마바식당", "vendor_category": "restaurant", "parse_confidence": 0.69,
               "source": "BOARD", "license": "공공누리 1유형"}])
    ex = merge.to_jjinmat(df, ["restaurant"], 0.7)
    assert ",".join(ex.columns) == "restaurant_name,address,exec_date,agency,amount,purpose,source,base_year"
    assert ex["restaurant_name"].tolist() == ["가나식당"]
    assert ex["source"].iloc[0] == "가상시 업무추진비 공개(DATAGOKR, 공공누리 표시 없음)"
    assert "부시장" not in ex.to_csv(index=False) and "법인카드" not in ex.to_csv(index=False)


# ---------- 4. 문구 ----------
def test_no_forbidden_wording_in_code():  # 통과 항목: 코드·설정·리포트 템플릿에 '공직자' 표현 없음
    hits = [p for p in (ROOT / "src").rglob("*") if p.suffix in (".py", ".yaml") and "공직자" in p.read_text(encoding="utf-8")]
    assert hits == []
