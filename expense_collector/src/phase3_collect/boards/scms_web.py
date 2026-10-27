"""게시판 어댑터: 경남 지자체 공통 CMS `/{메뉴번호}/…/{번호}.web` (진주·함안·거창·합천·함양).

- 목록: `li a.a1[href*=amode=view]` → `?gcode=&idx=&amode=view` (목록 URL 기준 상대 경로)
- 날짜: 같은 링크 안의 `span.t3` 중 날짜. 담당부서 칸은 날짜만 뽑으므로 따로 읽지 않는다
- 페이지: `cpage=n` (마지막 페이지 링크 title=맨끝 페이지)
- 첨부: 상세의 `a.filename[href*=/board/download.do]` 직접 링크. 문구 끝 `(15.3 KB)` 는 공통 정리로 제거
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
    for a in BeautifulSoup(html, "lxml").select("li a.a1[href*='amode=view']"):
        url = urljoin(board_url, a["href"])
        title = a.select_one(".t1")
        posts.append({"title": re.sub(r"\s+", " ", (title or a).get_text(" ", strip=True)),
                      "date": iso_date(" ".join(t.get_text() for t in a.select(".t3"))), "url": url,
                      "ntt_sn": parse_qs(urlsplit(url).query).get("idx", [None])[0]})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    return [file_entry(a.get_text(" ", strip=True), a["href"], post_url)
            for a in BeautifulSoup(html, "lxml").select("a.filename[href*='/board/download.do']")]
