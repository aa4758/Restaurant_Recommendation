"""Phase 0 선별·매칭 — 가상 데이터."""
import pandas as pd

from src.phase0_institutions.build import match_homepages, norm, parse_govkr, select_institutions

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
    ("1015000", "대통령비서실", "대통령비서실", "1", "0000000", "중앙행정기관", "대통령직속(기타)", "0"),  # 범위 밖
]


def insts():
    return {i["institution_id"]: i for i in select_institutions(pd.DataFrame(ROWS, columns=COLS))}


def test_select():
    got = insts()
    assert {k: v["type"] for k, v in got.items()} == {
        "6410000": "METRO_GOV", "3940000": "LOCAL_GOV", "7530000": "METRO_EDU",
        "7531000": "LOCAL_EDU", "1130000": "CENTRAL", "1790634": "CENTRAL"}
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
    assert not got["7531000"].get("homepage_url") and got["7531000"]["status"] == "needs_review"
    assert "여러 개" in got["1790634"]["note"]  # 후보 둘 → 추측 안 함
