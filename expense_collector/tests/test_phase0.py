"""Phase 0 선별·매칭 — 가상 데이터."""
import pandas as pd

from src.web import PAGE_SEP, REDIRECT
from src.phase0_institutions.build import (
    collapse, edu_links, exclude_without_homepage, match_homepages, norm, parse_govkr, select_institutions, short_edu_name,
)

COLS = ["기관코드", "전체기관명", "최하위기관명", "차수", "차상위기관코드", "유형분류_중_의미", "유형분류_소_의미", "존폐여부"]
ROWS = [
    ("6410000", "경기도", "경기도", "1", "0000000", "광역자치단체", "도", "0"),
    ("3940000", "경기도 고양시", "고양시", "2", "6410000", "기초자치단체", "일반시", "0"),
    ("3940100", "경기도 고양시 덕양구", "덕양구", "3", "3940000", "기초자치단체", "일반시", "0"),  # 행정구 제외
    ("3999999", "경기도 폐지시", "폐지시", "2", "6410000", "기초자치단체", "일반시", "1"),  # 폐지 제외
    ("7530000", "경기도교육청", "경기도교육청", "1", "0000000", "시.도 교육청", None, "0"),
    ("7531000", "경기도교육청 경기도수원교육지원청", "경기도수원교육지원청", "2", "7530000", "지역교육청", None, "0"),
    ("1130000", "공정거래위원회", "공정거래위원회", "1", "0000000", "중앙행정기관", "국무총리직속(위원회)", "0"),
    ("1790634", "대통령직인수위원회", "대통령직인수위원회", "1", "0000000", "중앙행정기관", "부", "0"),
    ("1015000", "대통령비서실", "대통령비서실", "1", "0000000", "중앙행정기관", "대통령직속(기타)", "0"),  # 기타 범위
]


def frame(rows=ROWS):
    df = pd.DataFrame(rows, columns=COLS)
    df["유형분류_대_의미"] = "국가행정조직"
    return df


def insts():
    return {i["institution_id"]: i for i in select_institutions(frame())}


def test_select():
    got = insts()
    assert {k: v["type"] for k, v in got.items()} == {
        "6410000": "METRO_GOV", "3940000": "LOCAL_GOV", "7530000": "METRO_EDU",
        "7531000": "LOCAL_EDU", "1130000": "CENTRAL", "1790634": "CENTRAL", "1015000": "OTHER"}
    assert got["3940000"]["parent"] == "경기도"
    assert got["7531000"]["name"] == "경기도수원교육지원청" and got["7531000"]["region"] == "경기도"
    assert got["1130000"]["status"] == "ok"
    assert got["1790634"]["status"] == "needs_review"


def test_norm():
    assert norm("서울특별시 종로구청") == "서울특별시종로구"
    assert norm("경기도청") == "경기도"
    assert norm("고양특례시") == "고양시"
    assert norm("경찰청 대표 누리집") == "경찰청"
    assert norm("대한민국 국방부") == "국방부"
    assert norm("경찰청") == "경찰청"  # '찰청' 은 시군구도+청 아님


HTML = """<ul class="gov-web">
<li><dt><a onclick="fncGoSite('https://www.gg.go.kr', 'x')"><b>경기도청</b></a></dt><span>(경기도)</span></li>
<li><dt><a onclick="fncGoSite('https://www.goyang.go.kr', 'x')"><b>고양특례시</b></a></dt><span>(경기도)</span></li>
<li><dt><a onclick="fncGoSite('https://www.goe.go.kr', 'x')"><b>경기교육</b></a></dt><span>(경기도교육청)</span></li>
<li><dt><a onclick="fncGoSite('https://www.ftc.go.kr', 'x')"><b>공정거래위원회</b></a></dt><span>(공정거래위원회)</span></li>
<li><dt><a onclick="fncGoSite('https://a.go.kr', 'x')"><b>대통령직인수위원회</b></a></dt><span>(x)</span></li>
<li><dt><a onclick="fncGoSite('https://b.go.kr', 'x')"><b>대통령직인수위원회 대표</b></a></dt><span>(x)</span></li>
</ul><a href="?pageIndex=1">1</a><a href="?pageIndex=7">7</a>"""


def test_parse_and_match():
    entries, last = parse_govkr(HTML)
    assert last == 7 and len(entries) == 6 and entries[0] == {"name": "경기도청", "span": "경기도", "url": "https://www.gg.go.kr"}
    got = insts()
    match_homepages(list(got.values()), entries)
    assert got["6410000"]["homepage_url"] == "https://www.gg.go.kr"
    assert got["3940000"]["homepage_url"] == "https://www.goyang.go.kr"  # span + 특례시
    assert got["7530000"]["homepage_url"] == "https://www.goe.go.kr"     # span 유일 매칭
    assert got["1130000"]["status"] == "ok"
    assert not got["7531000"].get("homepage_url")  # 교육지원청은 정부24 에서 찾지 않음
    assert "여러 개" in got["1790634"]["note"]  # 후보 둘 → 추측 안 함
    exclude_without_homepage(list(got.values()))
    assert got["1790634"]["status"] == "excluded" and got["7531000"]["status"] == "excluded"
    assert got["6410000"]["status"] == "ok"


def test_other_scope():
    rows = ROWS + [("1040000", "감사원", "감사원", "1", "0000000", "중앙행정기관", "대통령직속(기타)", "0"),
                   ("1092000", "국무조정실", "국무조정실", "1", "0000000", None, None, "0")]
    got = {i["institution_id"]: i["type"] for i in select_institutions(frame(rows))}
    assert got["1040000"] == got["1092000"] == got["1015000"] == "OTHER"


def test_edu_links_and_short_name():
    assert short_edu_name("서울특별시동부교육지원청") == "동부교육지원청"
    assert short_edu_name("경상북도구미교육지원청") == "구미교육지원청"
    assert short_edu_name("전남광주통합특별시목포교육지원청") == "목포교육지원청"
    html = """<a href="http://dbedu.sen.go.kr">동부교육지원청(동대문구, 중랑구) 새창열림</a>
    <a href="https://news.example/1">"수업 나눔"... 동부교육지원청 소식</a>
    <a href="/local">서부교육지원청</a>
    <select><option value="http://gm.example">구미교육지원청</option></select>"""
    assert edu_links(html) == [("동부교육지원청(동대문구,중랑구)새창열림", "http://dbedu.sen.go.kr"),
                               ("구미교육지원청", "http://gm.example")]
    redirect_then_main = "<html><script>location.href='/m'</script></html>" + PAGE_SEP + \
        '<html><a href="http://gm.example">구미교육지원청</a></html>'
    assert edu_links(redirect_then_main) == [("구미교육지원청", "http://gm.example")]


def test_edu_links_relative_news_and_collapse():
    page = ('<!-- url: https://www.gbe.example/main/main.do -->\n'
            '<a href="/ph/main.do" title="포항교육지원청 (새창 열기)">포항교육지원청</a>'
            '<a href="/news/1">목포교육지원청, 학생 안전교육 실시!</a>'
            '<a href="javascript:void(0)">경주교육지원청</a>')
    assert edu_links(page) == [("포항교육지원청", "https://www.gbe.example/ph/main.do"),
                               ("포항교육지원청(새창열기)", "https://www.gbe.example/ph/main.do")]
    assert collapse({"http://h/seobu/", "http://h/seobu/main.do"}) == {"http://h/seobu/"}
    assert collapse({"http://a", "http://b"}) == {"http://a", "http://b"}


def test_redirect_requires_quoted_target():
    assert REDIRECT.search('location.href = currentAddress; location.href="/cbe/index.do"').group(1) == "/cbe/index.do"
    assert REDIRECT.search('<meta http-equiv="refresh" content="0;url=/main.do">').group(2) == "/main.do"
