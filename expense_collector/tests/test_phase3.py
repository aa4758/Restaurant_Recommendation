"""Phase 3 게시판 수집 — 가상 게시판(MockTransport, 실데이터 없음)."""
from datetime import date

import httpx

from src import db
from src.http_client import HttpClient
from src.phase3_collect.board import collect_board
from tests.test_core import UA, FakeClock

BOARD = "https://www.gu.example/www/selectBbsNttList.do?bbsNo=1&key=2"
ROW = '<tr><td><a href="./selectBbsNttView.do?key=2&amp;nttNo={n}">{t}</a></td><td>{d}</td></tr>'
PAGES = {
    1: "".join(ROW.format(n=n, t=f"{n}월 업무추진비", d=d) for n, d in [(9, "2026.10.05"), (8, "2026.09.03")]) + '<a href="?pageIndex=3">끝</a>',
    2: ROW.format(n=1, t="오래된 글", d="2024.10.02") + ROW.format(n=2, t="경계 글", d="2024.11.01"),
    3: ROW.format(n=0, t="더 오래된 글", d="2023.01.01"),
}


def handler(req: httpx.Request) -> httpx.Response:
    u = str(req.url)
    if u.endswith("/robots.txt"):
        return httpx.Response(200, text="User-agent: *\nDisallow: /secret/\n")
    if "selectBbsNttList" in u:
        page = int(req.url.params.get("pageIndex", 1))
        return httpx.Response(200, text=f"<table><tbody>{PAGES[page]}</tbody></table>")
    if "selectBbsNttView" in u:
        n = req.url.params["nttNo"]
        links = f'<a href="./downloadBbsFile.do?atchmnflNo={n}">내역{n}.xlsx</a>'
        if n == "8":
            links += '<a href="/secret/downloadBbsFile.do?atchmnflNo=99">비공개.xlsx</a>'
        return httpx.Response(200, text=f"<p>공공누리 제4유형</p>{links}")
    if "downloadBbsFile" in u:
        return httpx.Response(200, content=b"PK\x03\x04 fake xlsx " + req.url.params["atchmnflNo"].encode())
    return httpx.Response(404)


def test_collect_board(tmp_path):
    conn = db.connect(tmp_path / "s.db")
    conn.execute("INSERT INTO institutions (institution_id, name, type, updated_at) VALUES ('1','가구','LOCAL_GOV','x')")
    clk = FakeClock()
    client = HttpClient({"user_agent": UA, "min_interval_sec": 3.0, "retries": 0}, transport=httpx.MockTransport(handler),
                        sleep=clk.sleep, clock=clk)
    row = {"institution_id": "1", "board_url": BOARD, "license": None}
    s = collect_board(client, conn, tmp_path / "raw", row, date(2024, 11, 1), date(2026, 10, 31))
    assert s["pages"] == 3 and s["posts"] == 3  # 2쪽 경계 글(11-01)까지 수집, 3쪽이 통째로 이전이라 거기서 멈춤
    files = conn.execute("SELECT filename, status, license, post_date, path FROM files ORDER BY file_id").fetchall()
    assert [(f[0], f[1]) for f in files] == [("내역9.xlsx", "ok"), ("내역8.xlsx", "ok"), ("비공개.xlsx", "blocked"), ("내역2.xlsx", "ok")]
    assert files[0][2] == "공공누리 4유형" and files[0][4] == "1/BOARD/2026-10_내역9.xlsx"
    assert (tmp_path / "raw" / files[0][4]).read_bytes().startswith(b"PK")
    assert min(clk.slept) >= 3.0  # 같은 호스트 요청 간격
    again = collect_board(client, conn, tmp_path / "raw", row, date(2024, 11, 1), date(2026, 10, 31))  # 이어하기
    assert again.get("posts", 0) == 0 and conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 4
