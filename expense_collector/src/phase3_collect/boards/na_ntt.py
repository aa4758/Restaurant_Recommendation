"""게시판 어댑터: 교육청 공통 CMS `/{site}/na/ntt/selectNttList.do` (경기도교육청·경기 교육지원청 등).

- 목록: `a.nttInfoBtn[data-id]` 행. 클릭 시 폼 제출이지만 상세는 GET 으로도 열림
  → `{dir}/selectNttInfo.do?mi=&bbsId=&nttSn=` (+`data-url` 이 있으면 `nttSnUrl`, 관세청).
  일반 링크 `a[href*=selectNttInfo.do]` 형(해양경찰청)도 있다.
- 페이지: `goPaging(n)` → 목록 URL 에 `currPage=n`
- 첨부: DEXT5/RAONK 업로더 스크립트(따옴표 " ' ` 혼용), `.bbsV_file` 목록의 미리보기 원본 경로(경기도교육청),
  `nttFileDownload.do?fileKey=` 직접 링크(관세청) → 직접 다운로드 경로
작성자 칸(개인 이름)은 읽지 않는다(PII).
"""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase3_collect.boards._common import file_entry, iso_date, max_call_arg, with_param

ID = "na_ntt"
INLINE = False
LIST_PATH = re.compile(r"/na/ntt/selectNttList\.do")
Q = "[\"'`]"
DEXT5 = re.compile(rf"AddUploadedFile\(\s*{Q}[^\"'`]*{Q}\s*,\s*{Q}([^\"'`]+){Q}\s*,\s*{Q}([^\"'`]+){Q}\s*,\s*{Q}?(\d*)")
PREVIEW = re.compile(r"""previewAjax\(\s*'([^']+)'""")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    return with_param(board_url, "currPage", page, drop_if=1)


def last_page(html: str) -> int:
    return max_call_arg(html, "goPaging")


def list_posts(html: str, board_url: str) -> list[dict]:
    """[{title, date(YYYY-MM-DD), url, ntt_sn}] — 목록 1쪽 분."""
    q = parse_qs(urlsplit(board_url).query)
    base = urljoin(board_url, "selectNttInfo.do")
    posts = []
    for a in BeautifulSoup(html, "lxml").select("a.nttInfoBtn[data-id], tr a[href*='selectNttInfo.do']"):
        tr = a.find_parent("tr")
        if a.get("data-id"):
            sn = a["data-id"]
            params = {"mi": q.get("mi", [""])[0], "bbsId": q.get("bbsId", [""])[0], "nttSn": sn}
            if a.get("data-url"):
                params["nttSnUrl"] = a["data-url"]
            url = f"{base}?{urlencode(params)}"
        else:
            url = urljoin(board_url, a["href"])
            sn = parse_qs(urlsplit(url).query).get("nttSn", [None])[0]
        posts.append({"title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
                      "date": iso_date(tr.get_text(" ")) if tr else None, "url": url, "ntt_sn": sn})
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    """[{name, url, ext, size}] — 직접 다운로드 경로. 두 가지 방식:
    (1) DEXT5 업로더 스크립트, (2) `.bbsV_file li` 의 파일명 + 미리보기 `previewAjax('원본 경로', ...)`
    ((2) 의 `goFileDown(key)` 는 JS 다운로드라 쓰지 않고 미리보기의 원본 경로를 쓴다)."""
    out = [file_entry(name, path, post_url, int(size or 0)) for name, path, size in DEXT5.findall(html)]
    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("a[href*='nttFileDownload.do']"):
        out.append(file_entry(re.sub(r"\s*다운로드$", "", a.get("title") or a.get_text(" ", strip=True)), a["href"], post_url))
    for li in soup.select(".bbsV_file li"):
        a = li.select_one("a.fileName")
        m = PREVIEW.search(str(li))
        if a and m:
            out.append(file_entry(a.get_text(" ", strip=True), m.group(1), post_url))
    return list({f["url"]: f for f in out}.values())  # 같은 파일 링크가 여러 번 나오면 하나로
