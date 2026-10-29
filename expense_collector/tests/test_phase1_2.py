"""Phase 1·2 판정 함수 — 가상 HTML/메타 (네트워크 없음)."""
from datetime import date

import pandas as pd

from src.phase1_source_survey.survey import datagokr_rows, expense_links, in_period, kogl_type, scope_of
from src.phase2_board_classify.classify import (
    TERMS_BAN, attachments, cms_of, load_fingerprints, pagination, post_links,
)

S, E = date(2024, 11, 1), date(2026, 10, 31)


def test_in_period():
    assert in_period("2024.10.31 2024.11.01 2025-3-4 2026년 10월 31일 2026.11.01 2025.02.30", S, E) == [
        date(2024, 11, 1), date(2025, 3, 4), date(2026, 10, 31)]


def test_kogl():
    assert kogl_type('<img alt="공공누리 제1유형: 출처표시">') == "공공누리 1유형"
    assert kogl_type('<img src="/img/img_opentype04.png">') == "공공누리 4유형"
    assert kogl_type("<p>없음</p>") == ""


def test_scope_and_datagokr_rows():
    assert scope_of("행정안전부_지방재정365_기관운영 업무추진비").startswith("지방재정365")
    assert scope_of("부산광역시 기장군_의회 업무추진비") == "의회"
    meta = pd.DataFrame([
        {"목록키": "1", "목록명": "가군_업무추진비", "키워드": "", "제공기관코드": "X", "목록유형": "FILE", "서비스유형": "FILE", "데이터포맷": "CSV", "주기": "수시"},
        {"목록키": "2", "목록명": "행정안전부_지방재정365_업무추진비비율", "키워드": "", "제공기관코드": "X", "목록유형": "API", "서비스유형": "LINK", "데이터포맷": "XML", "주기": "실시간"},
        {"목록키": "3", "목록명": "가군_도로현황", "키워드": "", "제공기관코드": "X", "목록유형": "FILE", "서비스유형": "FILE", "데이터포맷": "CSV", "주기": "연간"},
    ])
    rows = datagokr_rows({"institution_id": "X"}, meta, lambda u: "제한 없음")
    assert [(r["url"].split("/")[-2], r["status"], r["formats"]) for r in rows] == [("1", "found", "csv"), ("2", "not_found", "xml")]
    assert datagokr_rows({"institution_id": "Y"}, meta, lambda u: "")[0]["status"] == "not_found"


def test_expense_links_skip_js_and_opengokr():
    html = ('<!-- url: https://a.go.kr/ -->\n<a href="/bbs/1">업무추진비 공개</a>'
            '<a href="javascript:void(0)">업무추진비</a><a href="https://www.open.go.kr/x">업무추진비</a>')
    assert expense_links(html) == [("업무추진비 공개", "https://a.go.kr/bbs/1")]


def test_cms_fingerprints():
    fps = load_fingerprints()
    assert cms_of("https://x.go.kr/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_01", "", fps) == "egovframe_bbs"
    assert cms_of("https://www.unikorea.go.kr/web/unikorea/bbs/bbs_0000000000000125", "", fps) == "web_bbs"
    assert cms_of("https://x.go.kr/zzz", "", fps) == "unknown"


BOARD = """<!-- url: https://a.go.kr/bbs/list.do?bbsId=7 -->
<a href="/bbs/list.do?bbsId=7&pageIndex=2">2</a>
<a href="/bbs/view.do?bbsId=7&nttId=101">2025년 10월 업무추진비 집행내역</a>
<a href="/bbs/view.do?bbsId=7&nttId=100">2025년 9월 업무추진비 집행내역</a>
<a href="/bbs/view.do?bbsId=7&nttId=99">2025년 8월 업무추진비 집행내역</a>
<a href="https://other.kr/view.do?id=1">외부 사이트 게시글 제목</a>"""


def test_pagination_and_posts():
    assert pagination(BOARD) == "pageIndex"
    assert pagination('<a href="#" onclick="fn_link_page(2)">2</a>') == "js"
    assert post_links(BOARD, "https://a.go.kr/bbs/list.do?bbsId=7") == [
        "https://a.go.kr/bbs/view.do?bbsId=7&nttId=101", "https://a.go.kr/bbs/view.do?bbsId=7&nttId=100"]


def test_attachments():
    direct = '<!-- url: https://a.go.kr/v -->\n<a href="/cmm/fileDown.do?atchFileId=F1&fileSn=0">10월.pdf</a><a href="/f/9월.xlsx">9월.xlsx</a>'
    exts, method, pdfs = attachments(direct)
    assert exts == {"pdf", "xlsx"} and method == "direct" and pdfs == ["https://a.go.kr/cmm/fileDown.do?atchFileId=F1&fileSn=0"]
    js = '<a href="javascript:void(0)" onclick="fnFileDown(\'F1\')">10월.hwp</a>'
    assert attachments(js)[:2] == ({"hwp"}, "js")


def test_terms_ban():
    assert TERMS_BAN.search("본 홈페이지의 게시물을 자동 수집 프로그램으로 무단 수집하는 것을 금지합니다")
    assert not TERMS_BAN.search("이메일주소 무단수집을 거부하며 위반 시 처벌됩니다")


def test_post_links_path_style():
    html = '<!-- url: https://og.kr/expense/list -->\n<a href="/expense/37223170">2026년 9월 본청 업무추진비 내역</a>'
    assert post_links(html, "https://og.kr/expense/list") == ["https://og.kr/expense/37223170"]


def test_usable_licenses():
    from src.phase2_board_classify.classify import USABLE_LICENSES
    assert {kogl_type('<img src="/img/img_opentype0%d.png">' % n) for n in range(1, 5)} == USABLE_LICENSES
    assert kogl_type("") == ""  # 표시 없음 → classify 에서 NO_KOGL 로 기록(출처 표기로 사용)


def test_post_links_prefer_board_path():
    html = ('<!-- url: https://u.kr/web/u/bbs/bbs_125 -->\n'
            '<a href="/web/u/contents/openDatedetail_a">사전정보 공표 목록 상세</a>'
            '<a href="/web/u/contents/openDatedetail_b">정보공개 목록 상세 보기</a>'
            '<a href="/web/u/bbs/bbs_125/60543?cp=1">장차관업무추진비 2026년 9월</a>')
    assert post_links(html, "https://u.kr/web/u/bbs/bbs_125")[0] == "https://u.kr/web/u/bbs/bbs_125/60543?cp=1"


def test_url_signature_clusters():
    from src.phase2_board_classify.classify import url_signature
    a = url_signature("https://a.go.kr/bbs/list.do?bbsId=12&menu=3")
    b = url_signature("https://b.go.kr/bbs/list.do?menu=9&bbsId=77")
    assert a == b == "/bbs/list.do?bbsId&menu"
    assert url_signature("https://x.kr/site/gu/BD_board.list.do?bbsCd=1") != a


def test_nav_and_row_context():
    from src.phase1_source_survey.survey import nav_links
    from src.web import PAGE_SEP, blocked_reason, main_candidates, robots_blocked
    home = """<!-- url: https://www.gu.example/main.do -->
    <a href="/info.do">정보공개</a><a href="https://www.open.go.kr">정보공개청구</a><a href="/req.do">정보공개 청구</a>
    <a href="/pre.do">사전정보공표</a><a href="/sitemap.do">사이트맵</a><a href="https://other.example/x">정보공개</a>"""
    assert nav_links(home) == ["https://www.gu.example/sitemap.do", "https://www.gu.example/pre.do", "https://www.gu.example/info.do"]
    pre = """<!-- url: https://www.gu.example/pre.do --><table><tr><td>재정</td><td>업무 추진비 사용내역</td>
    <td><a href="/go.do?id=7">바로가기</a></td></tr></table><ul><li><a href="/x.do">바로가기</a> 새소식</li></ul>"""
    assert expense_links(pre) == [("재정 업무 추진비 사용내역 바로가기", "https://www.gu.example/go.do?id=7")]
    intro = """<!-- url: https://www.gu.example -->
    <meta property="og:url" content="https://www.gu.example/gu/index.do"><link href="/css/main.css"><a href="https://other.example/main.do">x</a>"""
    assert main_candidates(intro) == ["https://www.gu.example/gu/index.do"]
    redirected = "<!-- url: https://a.example/ -->x" + PAGE_SEP + "<!-- robots disallow https://a.example/m | robots.txt 응답 없음(X) -->"
    assert robots_blocked(redirected) and blocked_reason(redirected) == "robots.txt 응답 없음(X)"


def test_foi_includes_blocked_board(tmp_path):
    from src import db
    from src.phase1_source_survey.survey import export
    conn = db.connect(tmp_path / "s.db")
    for i in "123":
        conn.execute("INSERT INTO institutions (institution_id, name, type, updated_at) VALUES (?, '가', 'LOCAL_GOV', 'x')", (i,))
    for i, src_ in [("1", "BOARD"), ("2", "BOARD"), ("3", "BOARD"), ("3", "DATAGOKR")]:
        conn.execute("INSERT INTO source_survey (institution_id, source, status) VALUES (?, ?, 'found')", (i, src_))
    for i, g in [("1", "A"), ("2", "C"), ("3", "C")]:
        conn.execute("INSERT INTO board_registry (institution_id, crawl_grade, note) VALUES (?, ?, '접근권한 오류')", (i, g))
    conn.execute("INSERT INTO files (institution_id, source, source_url, status) VALUES ('3', 'DATAGOKR', 'u', 'ok')")
    assert export(conn, tmp_path, tmp_path, None)["foi"] == ["2"]  # 3 은 공공데이터포털 파일을 받아 제외
