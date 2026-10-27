"""게시판 어댑터: `/boardCnts/list.do`·`listRenew.do` (강원교육청·교육지원청, 교육부).

- 목록: `goView('게시판','글번호','lev',…,'statusYN',…)` → `view.do`(`viewRenew.do`)?boardID=&boardSeq=&lev=&statusYN=&s=&m=
- 페이지: `page=n`
- 첨부: 상세의 `/boardCnts/fileDown.do?fileSeq=` 직접 링크. 파일명은 링크 문구, 없으면(교육부: '다운로드') 감싼 li 의 글자
작성자 칸(마스킹된 이름)은 읽지 않는다.
"""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, with_param

ID = "board_cnts"
INLINE = False
LIST_PATH = re.compile(r"/boardCnts/list(Renew)?\.do")
GO_VIEW = re.compile(r"goView\(\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*[^,]*,\s*'(\w*)'")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "page", page, drop_if=1)


def last_page(html: str) -> int:
    return max((int(n) for n in re.findall(r"[?&;]page=(\d+)", html)), default=1)


def list_posts(html: str, board_url: str) -> list[dict]:
    q = {k: v[0] for k, v in parse_qs(urlsplit(board_url).query).items() if k in ("s", "m")}
    view = urljoin(board_url, "viewRenew.do" if "listRenew" in board_url else "view.do")
    posts = []
    for a in BeautifulSoup(html, "lxml").select("tr a[onclick*='goView']"):
        if not (m := GO_VIEW.search(a["onclick"])):
            continue
        bid, seq, lev, status = m.groups()
        params = {"boardID": bid, "boardSeq": seq, "lev": lev, "statusYN": status} | q
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(a.find_parent("tr").get_text(" ")),
                      "url": f"{view}?{urlencode(params)}", "ntt_sn": seq})
    return list({p["ntt_sn"]: p for p in posts}.values())  # 강원: 같은 행이 두 번 나옴(PC·모바일 표)


def list_attachments(html: str, post_url: str) -> list[dict]:
    out = []
    for a in BeautifulSoup(html, "lxml").select("a[href*='/boardCnts/fileDown.do']"):
        name = a.get_text(" ", strip=True)
        if "." not in name:
            name = " ".join(a.parent.find_all(string=True, recursive=False))
        out.append(file_entry(name, a["href"], post_url))
    return out
