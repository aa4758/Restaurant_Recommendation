"""게시판 어댑터: K-에듀파인 재정공개 '업무추진비' `/kedufine/ir/selectJobPrtnCtList.do` (경상북도교육청·교육지원청).

게시판이 아니라 집행 건 목록이다(회계연도·기관(부서)·사용내용·금액·일자). 사용장소는 건별 상세에만 있어
상세 HTML 자체를 원본 파일로 취급한다(list_attachments 가 상세 URL 을 html 파일로 돌려줌).
- 목록·상세 모두 폼 POST 지만 GET 으로도 열림(2026-10-27 확인)
- 기본 조회기간이 최근 2개월이라 `inpBdt`/`inpEdt` 를 넓게 줘서 전체를 받고, 날짜 필터는 호출 쪽에서
- 페이지: `goPaging(n)` → `currPage=n` / 상세: `selectDetailView(건번호, 연계번호)` → selectJobPrtnCtView.do
"""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import iso_date, max_call_arg, with_param

ID = "kedufine"
INLINE = False
LIST_PATH = re.compile(r"/kedufine/ir/selectJobPrtnCtList\.do")
DETAIL = re.compile(r"selectDetailView\(\s*'(\d+)'\s*,\s*'(\d+)'")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    url = with_param(with_param(board_url, "inpBdt", "2000/01/01"), "inpEdt", "2099/12/31")
    return with_param(url, "currPage", page)


def last_page(html: str) -> int:
    return max_call_arg(html, "goPaging")


def list_posts(html: str, board_url: str) -> list[dict]:
    mi = parse_qs(urlsplit(board_url).query).get("mi", [""])[0]
    base = urljoin(board_url, "selectJobPrtnCtView.do")
    posts = []
    for a in BeautifulSoup(html, "lxml").select("tbody tr a[onclick*='selectDetailView']"):
        sn, esb = DETAIL.search(a["onclick"]).groups()
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(a.find_parent("tr").get_text(" ")),
                      "url": f"{base}?{urlencode({'mi': mi, 'jobPrtnCtSn': sn, 'ifEsbSeqNo': esb})}", "ntt_sn": sn})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    sn = parse_qs(urlsplit(post_url).query).get("jobPrtnCtSn", ["detail"])[0]
    return [{"name": f"{sn}.html", "url": post_url, "ext": "html", "size": 0}]  # 상세 HTML 이 원본
