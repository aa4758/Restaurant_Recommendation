"""게시판 어댑터: 관악구 '업무추진비 공개' `/site/{site}/estimate/estimateList.do`.

첨부 없이 목록 페이지에 집행 건이 `table.view` 로 들어 있다(INLINE) → 목록 HTML 자체가 원본.
- 페이지: `doBbsFPag(n)` → `pageIndex=n` (GET 확인)
- 각 표: 비목·집행부서·집행일시·집행내역·결제방법·사용자(직위)·대상인원수·집행장소(상호(주소))·집행금액
list_posts 는 집행 건마다 날짜만 돌려준다(값 파싱은 Phase 4).
"""
import re

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import iso_date, max_call_arg, with_param

ID = "gwanak_estimate"
INLINE = True
LIST_PATH = re.compile(r"/site/\w+/estimate/estimateList\.do")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "pageIndex", page, drop_if=1)


def last_page(html: str) -> int:
    return max_call_arg(html, "doBbsFPag")


def list_posts(html: str, board_url: str) -> list[dict]:
    posts = []
    for t in BeautifulSoup(html, "lxml").select("table.view"):
        th = t.find("th", string=re.compile("집행일시"))
        td = th.find_next_sibling("td") if th else None
        posts.append({"title": "업무추진비 집행 건", "date": iso_date(td.get_text(" ")) if td else None,
                      "url": board_url, "ntt_sn": None})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    return []  # 첨부 없음 — 목록 HTML 을 원본으로 저장
