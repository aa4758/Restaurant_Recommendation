"""게시판 어댑터: 지자체 공통 CMS `/{site}/selectBbsNttList.do?bbsNo=|bordCd=&key=` (구리·군포·괴산·공정위 등).

- 목록: 행의 `a[href*=selectBbsNttView.do]` 일반 링크(nttNo 또는 nttSn)
- 페이지: `pageIndex=n`
- 첨부: 상세의 `downloadBbsFile.do`(영등포는 `downloadBbsFileStr.do`) 직접 링크. 링크 안 아이콘 글자(`xlsx 문서`)는 빼고 파일명만
작성자·담당부서 칸은 읽지 않는다.
"""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, with_param

ID = "bbs_ntt"
INLINE = False
LIST_PATH = re.compile(r"/selectBbsNttList\.do")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "pageIndex", page, drop_if=1)


def last_page(html: str) -> int:
    return max((int(n) for n in re.findall(r"pageIndex=(\d+)", html)), default=1)


def list_posts(html: str, board_url: str) -> list[dict]:
    posts = []
    for a in BeautifulSoup(html, "lxml").select("tr a[href*='selectBbsNttView.do']"):
        url = urljoin(board_url, a["href"])
        q = parse_qs(urlsplit(url).query)
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(a.find_parent("tr").get_text(" ")), "url": url,
                      "ntt_sn": (q.get("nttNo") or q.get("nttSn") or [None])[0]})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    out = []
    for a in BeautifulSoup(html, "lxml").select("a[href*='downloadBbsFile.do'], a[href*='downloadBbsFileStr.do']"):
        for icon in a.select(".p-icon, .skip"):
            icon.decompose()
        name = a.get_text(" ", strip=True)
        if "." not in name and (span := a.find_previous_sibling("span")):  # 양주: 링크 문구가 '다운로드'
            name = span.get_text(" ", strip=True)
        out.append(file_entry(name, a["href"], post_url))
    return out
