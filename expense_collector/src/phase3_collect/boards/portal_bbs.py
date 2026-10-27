"""게시판 어댑터: 경북 지자체 공통 CMS `/portal/bbs/list.do?ptIdx=&mId=` (칠곡·김천·과천·안동 등).

- 목록: `goTo.view('list','글번호','ptIdx','mId')` → `/portal/bbs/view.do?mId=&bIdx=&ptIdx=` (GET 확인, 2026-10-27)
- 페이지: `goPage(n)` → `page=n` (GET 확인)
- 첨부: `fn_egov_downFile('id','sn')` → `/cmm/fms/FileDown.do` (외부 EgovFileUtils.js, 직접 다운로드 확인) — egov_bbs 와 같은 방식
작성자 칸(담당부서)은 읽지 않는다.
"""
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from src.phase3_collect.boards import egov_bbs
from src.phase3_collect.boards._common import file_entry, iso_date, max_call_arg, with_param

ID = "portal_bbs"
INLINE = False
LIST_PATH = re.compile(r"/portal/bbs/list\.do")
GO_VIEW = re.compile(r"goTo\.view\(\s*'list'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "page", page, drop_if=1)


def last_page(html: str) -> int:
    return max_call_arg(html, "goPage")


def list_posts(html: str, board_url: str) -> list[dict]:
    view = urljoin(board_url, "/portal/bbs/view.do")
    posts = []
    for a in BeautifulSoup(html, "lxml").select("tr a[onclick*='goTo.view']"):
        if not (m := GO_VIEW.search(a["onclick"])):
            continue
        idx, pt, mid = m.groups()
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(a.find_parent("tr").get_text(" ")),
                      "url": f"{view}?{urlencode({'mId': mid, 'bIdx': idx, 'ptIdx': pt})}", "ntt_sn": idx})
    return posts


YH_DOWN = re.compile(r"yhLib\.file\.download\(\s*'(\w+)'\s*,\s*'(\w+)'")


def list_attachments(html: str, post_url: str) -> list[dict]:
    out = egov_bbs.list_attachments(html, post_url)
    for a in BeautifulSoup(html, "lxml").select("a[onclick*='yhLib.file.download']"):  # 경기 광주: lib.js 의 다운로드
        fid, sn = YH_DOWN.search(a["onclick"]).groups()
        out.append(file_entry(a.get_text(" ", strip=True), f"/common/file/download.do?atchFileId={fid}&fileSn={sn}", post_url))
    return out
