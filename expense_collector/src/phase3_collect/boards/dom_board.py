"""게시판 어댑터: 지자체·교육청 공통 CMS `/board/list.{ext}?boardId=BBS_…&menuCd=DOM_…`
(전북교육청·임실·의령·해운대구의회 등. 확장자는 사이트마다 .do/.jbe/.imsil 처럼 다름).

- 목록: 표 행의 `a[href*=/board/view.]` (dataSid=) — 메뉴의 다른 게시판 링크는 행(tr) 밖이라 제외.
  울진은 카드형 `li > a` (작성자가 섞인 `em.info` 에서 날짜만 뽑음). 진안은 상세 없이 행마다 첨부 직접 링크와
  '2026년 9월 업무추진비 내역' 같은 공개 월 문구뿐 → 그 달 1일을 날짜로, 목록 페이지 자체를 게시글로 본다.
  기장은 목록 표 행이 곧 집행 건(첨부 없음) → 행 날짜를 게시글로, 목록 HTML 을 원본 파일(html)로 돌려준다
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
YEAR_MONTH = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "startPage", page, drop_if=1)


def last_page(html: str) -> int:
    return max((int(n) for n in re.findall(r"startPage=(\d+)", html)), default=1)


def _date(text: str) -> str | None:
    if d := iso_date(text):
        return d
    if m := SHORT_DATE.search(text):  # 26.10.08
        return f"20{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = YEAR_MONTH.search(text)  # 진안: 공개 월만 있음
    return f"{m.group(1)}-{int(m.group(2)):02d}-01" if m else None


def list_posts(html: str, board_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    posts = []
    for a in soup.select("tr a[href*='/board/view.'][href*='dataSid='], li > a[href*='/board/view.'][href*='dataSid=']"):
        url = urljoin(board_url, a["href"])
        card = a.parent.name == "li"
        if card and not a.select_one("strong"):  # 메뉴의 다른 게시판 링크(li > a)는 제외 — 카드형은 제목이 strong
            continue
        strong = a.select_one("strong") if card else None
        title = strong.get_text(" ", strip=True) if strong else a.get("title") or a.get_text(" ", strip=True)
        posts.append({"title": re.sub(r"\s+", " ", title),
                      "date": _date(a.get_text(" ") if card else a.find_parent("tr").get_text(" ")), "url": url,
                      "ntt_sn": parse_qs(urlsplit(url).query)["dataSid"][0]})
    if not posts:  # 진안형: 상세 없이 행마다 첨부만
        for tr in soup.select("tr:has(a[href*='/board/download.'])"):
            label = tr.find("td").get_text(" ", strip=True)
            down = tr.select_one("a[href*='/board/download.']")["href"]
            posts.append({"title": label, "date": _date(label), "url": board_url,
                          "ntt_sn": parse_qs(urlsplit(down).query).get("dataSid", [None])[0]})
    if not posts:  # 기장형: 목록 표 행 = 집행 건. 날짜만 읽는다(직위·이름 칸은 Phase 4 에서 처리)
        posts = [{"title": "업무추진비 집행 건", "date": d, "url": board_url, "ntt_sn": None}
                 for tr in soup.select("tbody tr") if (d := iso_date(tr.get_text(" ")))]
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    out = {}
    for a in BeautifulSoup(html, "lxml").select("a[href*='/board/download.'][href*='fileSid=']:not(.ico_viewer)"):
        name = re.sub(r"\s*(\([\d.,]+\s*[kmg]?b\)|다운받기|다운로드|내려받기)\s*$", "", a.get("title") or a.get_text(" ", strip=True), flags=re.I)
        f = file_entry(re.sub(r"\s+\.(\w+)$", r".\1", name), a["href"], post_url)
        out.setdefault(f["url"], f)  # 같은 파일 중복 제거(바로보기 링크는 위에서 제외)
    if not out and matches(post_url) and any(iso_date(tr.get_text(" ")) for tr in BeautifulSoup(html, "lxml").select("tbody tr")):
        return [{"name": "list.html", "url": post_url, "ext": "html", "size": 0}]  # 기장형: 목록 표 자체가 집행 건 → 페이지가 원본
    return list(out.values())
