"""게시판 어댑터: 전자정부표준프레임워크 게시판 `commonSelectBoardList.do?bbsId=BBSMSTR_...` (행정안전부 등).

- 목록: `a[href*=commonSelectBoardArticle.do]` (href 가 실제 GET 상세 URL)
- 페이지: `fn_egov_select_noticeList(n)` → 목록 URL 에 `pageIndex=n` (GET 확인)
- 첨부: `a[href*="/cmm/fms/FileDown.do"]` 직접 링크. 문구 끝의 `[ 13.2 KB ]` 는 제거
"""
import re

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, max_call_arg, with_param

ID = "egov_bbs"
INLINE = False
LIST_PATH = re.compile(r"commonSelectBoardList\.do\?.*bbsId=BBSMSTR_")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "pageIndex", page, drop_if=1)


def last_page(html: str) -> int:
    return max_call_arg(html, "fn_egov_select_noticeList")


def list_posts(html: str, board_url: str) -> list[dict]:
    posts = []
    for a in BeautifulSoup(html, "lxml").select("a[href*='commonSelectBoardArticle.do']"):
        tr = a.find_parent("tr")
        if not tr:  # 메뉴·이전/다음 글 링크 제외
            continue
        m = re.search(r"nttId=(\d+)", a["href"])
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(tr.get_text(" ")),
                      "url": file_entry("", a["href"], board_url)["url"],
                      "ntt_sn": m.group(1) if m else None})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    out = []
    for a in BeautifulSoup(html, "lxml").select("a[href*='/cmm/fms/FileDown.do']"):
        name = re.sub(r"\[\s*[\d.,]+\s*[KMG]?B\s*\]\s*$", "", a.get_text(" ", strip=True))
        out.append(file_entry(name, a["href"], post_url))
    return out
