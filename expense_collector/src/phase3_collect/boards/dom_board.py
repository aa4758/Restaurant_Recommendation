"""게시판 어댑터: 지자체·교육청 공통 CMS `/board/list.{ext}?boardId=BBS_…&menuCd=DOM_…`
(전북교육청·임실·의령·해운대구의회 등. 확장자는 사이트마다 .do/.jbe/.imsil 처럼 다름).

- 목록: 표 행의 `a[href*=/board/view.]` (dataSid=) — 메뉴의 다른 게시판 링크는 행(tr) 밖이라 제외
- 페이지: `startPage=n` (마지막 페이지 링크 class=next2)
- 첨부: 상세의 `a[href*=/board/download.]` 직접 링크(fileSid=), 파일명은 title 또는 링크 문구
작성자 칸은 읽지 않는다(PII). 날짜는 행 전체에서(전북교육청은 제목이 집행기준일).
"""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, with_param

ID = "dom_board"
INLINE = False
LIST_PATH = re.compile(r"/board/list\.\w+\?(?=.*boardId=BBS_)(?=.*menuCd=DOM_)")
SHORT_DATE = re.compile(r"\b(\d{2})\.(\d{1,2})\.(\d{1,2})\b")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "startPage", page, drop_if=1)


def last_page(html: str) -> int:
    return max((int(n) for n in re.findall(r"startPage=(\d+)", html)), default=1)


def _date(text: str) -> str | None:
    if d := iso_date(text):
        return d
    m = SHORT_DATE.search(text)  # 26.10.08
    return f"20{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def list_posts(html: str, board_url: str) -> list[dict]:
    posts = []
    for a in BeautifulSoup(html, "lxml").select("tr a[href*='/board/view.'][href*='dataSid=']"):
        url = urljoin(board_url, a["href"])
        posts.append({"title": re.sub(r"\s+", " ", a.get("title") or a.get_text(" ", strip=True)),
                      "date": _date(a.find_parent("tr").get_text(" ")), "url": url,
                      "ntt_sn": parse_qs(urlsplit(url).query)["dataSid"][0]})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    out = {}
    for a in BeautifulSoup(html, "lxml").select("a[href*='/board/download.'][href*='fileSid=']:not(.ico_viewer)"):
        name = re.sub(r"\s*(\([\d.,]+\s*[kmg]?b\)|다운받기|다운로드|내려받기)\s*$", "", a.get("title") or a.get_text(" ", strip=True), flags=re.I)
        f = file_entry(re.sub(r"\s+\.(\w+)$", r".\1", name), a["href"], post_url)
        out.setdefault(f["url"], f)  # 같은 파일 중복 제거(바로보기 링크는 위에서 제외)
    return list(out.values())
