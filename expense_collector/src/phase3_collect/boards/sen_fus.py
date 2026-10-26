"""게시판 어댑터: 서울시교육청 정보공개 `open.sen.go.kr/fus/{메뉴}/board/{게시판}/{분류}/list0010v.do`.

- 목록: `a[href^="javascript:fncDetailView('seq')"]` → 같은 경로의 `view0010v.do?board_seq=seq` (GET 확인)
- 페이지: `fncSearch(n)` → `pageIndex=n` (GET 확인)
- 첨부: `a[href*="/fus/file/down0010f.do"]`, 파일명은 title 에서 ' 파일 다운로드' 제거
  (robots 가 `.xls$`·`.pdf$`·`.hwp$` 로 끝나는 URL 을 막지만 down0010f.do 는 확장자로 끝나지 않아 허용)
작성자 칸(개인 이름)은 읽지 않는다(PII).
"""
import re

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, max_call_arg, with_param

ID = "sen_fus"
INLINE = False
LIST_PATH = re.compile(r"open\.sen\.go\.kr/fus/\w+/board/\w+/\w+/list0010v\.do")
DETAIL = re.compile(r"fncDetailView\(\s*'(\d+)'")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "pageIndex", page, drop_if=1)


def last_page(html: str) -> int:
    return max_call_arg(html, "fncSearch")


def list_posts(html: str, board_url: str) -> list[dict]:
    view = board_url.split("?")[0].replace("list0010v.do", "view0010v.do")
    posts = []
    for a in BeautifulSoup(html, "lxml").select("a[href*='fncDetailView']"):
        m = DETAIL.search(a["href"])
        tr = a.find_parent("tr")
        if not m or not tr:
            continue
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(tr.select("td")[-1].get_text(" ")) if tr.select("td") else None,
                      "url": f"{view}?board_seq={m.group(1)}", "ntt_sn": m.group(1)})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    return [file_entry((a.get("title") or a.get_text(" ")).removesuffix(" 파일 다운로드"), a["href"], post_url)
            for a in BeautifulSoup(html, "lxml").select("a[href*='/fus/file/down0010f.do']")]
