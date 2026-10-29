"""게시판 어댑터: 전자정부표준프레임워크 게시판 `(common)selectBoardList.do` (행정안전부·보령·청양·산림청·개인정보위 등).

- 목록: 행의 `a[href*=electBoardArticle.do]` (href 가 실제 GET 상세 URL, nttId)
- 페이지: `fn_egov_select_noticeList(n)` / `linkPage(n)` → 목록 URL 에 `pageIndex=n` (GET 확인)
- 첨부: `a[href*=/cmm/fms/FileDown.do]` 직접 링크, 또는 `fn_egov_downFile('atchFileId','fileSn')`
  → 페이지 안 window.open 의 FileDown 경로(사이트마다 /np/·/kfsweb/ 접두)로 조립. `;jsessionid=` 는 뗀다.
  파일명은 title 의 '파일명 :' 뒤, 링크 문구, title·aria-label·alt(개인정보위) 중 확장자가 있는 것
"""
import re

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, max_call_arg, with_param

ID = "egov_bbs"
INLINE = False
LIST_PATH = re.compile(r"(?:commonS|/s)electBoardList\.do")
DOWN_FN = re.compile(r"fn_egov_downFile\(\s*'([^']+)'\s*,\s*'(\w+)'")  # fileSn 은 숫자 또는 해시(칠곡)
DOWN_PATH = re.compile(r"""["']([\w/]*/cmm/fms/FileDown\.do)""")
SESSION = re.compile(r";jsessionid=[^?#]*")
HAS_EXT = re.compile(r"\.\w{2,5}(\s*[\[(].*)?$")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "pageIndex", page, drop_if=1)


def last_page(html: str) -> int:
    return max(max_call_arg(html, "fn_egov_select_noticeList"), max_call_arg(html, "linkPage"))


def list_posts(html: str, board_url: str) -> list[dict]:
    posts = []
    for a in BeautifulSoup(html, "lxml").select("tr a[href*='electBoardArticle.do']"):  # 메뉴·이전/다음 글 제외
        m = re.search(r"nttId=(\d+)", a["href"])
        posts.append({"title": re.sub(r"\s+", " ", a.get("title") or a.get_text(" ", strip=True)),
                      "date": iso_date(a.find_parent("tr").get_text(" ")),
                      "url": file_entry("", SESSION.sub("", a["href"]), board_url)["url"],
                      "ntt_sn": m.group(1) if m else None})
    return posts


def _name(a) -> str:
    title = a.get("title") or ""
    cands = [title.split("파일명 :")[-1] if "파일명 :" in title else "", a.get_text(" ", strip=True), title, a.get("aria-label") or "", a.get("alt") or ""]
    cands = [re.sub(r"\s*다운로드$", "", c.strip()) for c in cands]
    return next((c for c in cands if HAS_EXT.search(c)), cands[1])


def list_attachments(html: str, post_url: str) -> list[dict]:
    down = (m.group(1) if (m := DOWN_PATH.search(SESSION.sub("", html))) else "/cmm/fms/FileDown.do")
    out = {}
    for a in BeautifulSoup(html, "lxml").select("a[href*='/cmm/fms/FileDown.do'], a[onclick*='fn_egov_downFile'], a[href*='fn_egov_downFile']"):
        if m := DOWN_FN.search(a.get("onclick", "") + a.get("href", "")):
            url = f"{down}?atchFileId={m.group(1)}&fileSn={m.group(2)}"
        else:
            url = SESSION.sub("", a["href"])
        f = file_entry(_name(a), url, post_url)
        out.setdefault(f["url"], f)
    return list(out.values())
