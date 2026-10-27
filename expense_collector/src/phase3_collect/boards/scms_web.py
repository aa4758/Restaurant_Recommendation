"""게시판 어댑터: 경남 지자체 공통 CMS `/{메뉴번호}/…/{번호}.web` (진주·함안·거창·합천·함양).

- 목록: 카드형 `li a.a1[href*=amode=view]` 또는 표형(창원) `tr a[href*=amode=view]` → `?gcode=&idx=&amode=view`
- 날짜: 카드형은 링크 안 `span.t3`, 표형은 행 글자에서 날짜만 뽑는다(담당부서 칸은 따로 읽지 않음)
- 페이지: `cpage=n` (마지막 페이지 링크 title=맨끝 페이지)
- 첨부: 상세의 `a.filename` 직접 링크(`/board/download.do`, 창원 `/cwportal/cmsfile/download.do`). 문구 끝 `(15.3 KB)` 는 공통 정리로 제거
"""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, with_param

ID = "scms_web"
INLINE = False
LIST_PATH = re.compile(r"/\d{5}/(\d{5}/)*\d{5}\.web")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "cpage", page, drop_if=1)


def last_page(html: str) -> int:
    return max((int(n) for n in re.findall(r"cpage=(\d+)", html)), default=1)


def list_posts(html: str, board_url: str) -> list[dict]:
    posts = []
    for a in BeautifulSoup(html, "lxml").select("li a.a1[href*='amode=view'], tr a[href*='amode=view']"):
        url = urljoin(board_url, a["href"])
        for x in a.select(".ic1"):  # '새 글' 표시
            x.decompose()
        title = a.select_one(".t1") if "a1" in a.get("class", []) else a
        when = " ".join(t.get_text() for t in a.select(".t3")) if "a1" in a.get("class", []) else a.find_parent("tr").get_text(" ")
        posts.append({"title": re.sub(r"\s+", " ", title.get_text(" ", strip=True)), "date": iso_date(when), "url": url,
                      "ntt_sn": parse_qs(urlsplit(url).query).get("idx", [None])[0]})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    return [file_entry(a.get_text(" ", strip=True), a["href"], post_url)
            for a in BeautifulSoup(html, "lxml").select("a.filename[href*='download.do']")]
