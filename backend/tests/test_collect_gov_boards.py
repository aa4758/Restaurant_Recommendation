"""구청 업무추진비 게시판 수집: robots 판정·간격·캐시·PII 버림·목록 파싱 (collect_gov_boards)."""
from __future__ import annotations

import io

import pytest

from app.ingest import collect_gov_boards as cg

GWANAK_CARD = """<table class="view"><tbody>
<tr><th scope="row">비목</th><td>시책추진</td><th scope="row">집행부서</th><td>건축과</td>
<th scope="row">집행일시</th><td colspan="5">2026-10-26&nbsp;&nbsp;&nbsp;&nbsp;11:42</td></tr>
<tr><th scope="row">집행내역</th><td colspan="4">홍길동 과장 격려 간담회</td><th scope="row">결제방법</th><td>신용카드</td></tr>
<tr><th scope="row">사용자</th><td>홍길동 외 5</td><th scope="row">대상인원수(명)</th><td>6</td>
<th scope="row">집행장소</th><td colspan="3">육전국밥(서울 관악구 관악로 163, 1층 1호)</td>
<th scope="row">집행금액(원)</th>
   <td>91,000</td></tr></tbody></table>"""

GURO_ROW = """<tr><td>10958</td><td class="p-subject"><a href="./selectBbsNttView.do?bbsNo=655&amp;nttNo=241403" target="_self" >
 2026년 9월 아동청소년과 시책업무추진비 사용내역 </a></td><td>청소년복지팀</td><td><time datetime="2026-10-20">2026.10.20</time></td>
<td>79</td><td><a title="첨부파일 다운로드 새창" target="_blank" href="downloadBbsFile.do?atchmnflNo=356521&amp;bbsNo=655"><span class="p-icon p-icon__pdf">pdf</span></a></td></tr>"""


def test_robots_wildcards_and_longest_rule():
    txt = "User-Agent : *\nDisallow : /\nAllow: /portal/bbs/\nDisallow: /*bbsId=BBSMSTR_0661\n\nUser-agent: Googlebot\nAllow: /\n"
    assert cg.robots_allowed(txt, "/portal/bbs/list.do?a=1")
    assert not cg.robots_allowed(txt, "/portal/bbs/list.do?bbsId=BBSMSTR_0661")
    assert not cg.robots_allowed(txt, "/other")
    seocho = "User-agent:*\nAllow:/site/*.do\nDisallow:/common/*\nDisallow:/site/*/ex/bbs/View.do?*cbIdx=12*\n"
    assert not cg.robots_allowed(seocho, "/common/board/Download.do?x=1")
    assert not cg.robots_allowed(seocho, "/site/seocho/ex/bbs/View.do?cbIdx=12&b=1")
    assert cg.robots_allowed("<pre>User-agent: *\nDisallow: /\nAllow: /$\n</pre>", "/")
    assert cg.crawl_delay("User-agent: *\nCrawl-delay: 10\n") == 10


def test_fetcher_respects_robots_delay_and_cache(tmp_path):
    calls, sleeps = [], []

    def opener(req, timeout):
        calls.append(req.full_url)
        assert req.get_header("User-agent") == cg.UA
        return io.BytesIO(b"User-agent: *\nDisallow: /private\nCrawl-delay: 5\n" if req.full_url.endswith("robots.txt") else b"ok")

    f = cg.Fetcher("https://x.go.kr", tmp_path, opener=opener, sleep=sleeps.append)
    assert f.delay == 5
    assert f.get("/list?a=1&amp;b=2") == b"ok" and calls[-1] == "https://x.go.kr/list?a=1&b=2"
    assert f.get("/list?a=1&b=2") == b"ok" and len(calls) == 2  # 캐시 → 재요청 없음
    f.get("/list?a=1&b=2", cache=False)  # 목록은 매번 새로
    with pytest.raises(PermissionError):
        f.get("/private/a")
    assert len(calls) == 3 and sleeps[-1] > 4  # 실요청 사이 간격 대기


def test_parse_gwanak_drops_pii():
    [r] = cg.parse_gwanak(GWANAK_CARD)
    assert r == {"exec_dt": "2026-10-26 11:42", "agency": "서울특별시 관악구", "dept": "건축과",
                 "place": "육전국밥(서울 관악구 관악로 163, 1층 1호)", "amount": "91000", "category": "시책추진",
                 "source": cg.GWANAK_SOURCE}
    assert "홍길동" not in str(r)


def test_parse_guro_list_and_dept():
    [p] = cg.parse_guro_list(GURO_ROW)
    assert p["posted"] == "2026-10-20" and p["files"] == [("/www/downloadBbsFile.do?atchmnflNo=356521&amp;bbsNo=655", "pdf")]
    assert cg.guro_dept(p["title"]) == "아동청소년과"
