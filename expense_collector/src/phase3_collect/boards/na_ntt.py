"""게시판 어댑터: 교육청 공통 CMS `/{site}/na/ntt/selectNttList.do` (경기도교육청·경기 교육지원청 등).

- 목록: `a.nttInfoBtn[data-id]` 행. 클릭 시 폼 제출이지만 상세는 GET 으로도 열림
  → `{dir}/selectNttInfo.do?mi=&bbsId=&nttSn=`
- 페이지: `goPaging(n)` → 목록 URL 에 `currPage=n`
- 첨부: DEXT5 업로더 스크립트(수원 등) 또는 `.bbsV_file` 목록의 미리보기 원본 경로(경기도교육청) → 직접 다운로드 경로
작성자 칸(개인 이름)은 읽지 않는다(PII).
"""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

ID = "na_ntt"
LIST_PATH = re.compile(r"/na/ntt/selectNttList\.do")
DATE = re.compile(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})")
DEXT5 = re.compile(r"""AddUploadedFile\(\s*"[^"]*"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"(\d*)\"""")
PREVIEW = re.compile(r"""previewAjax\(\s*'([^']+)'""")


def matches(board_url: str) -> bool:
    return bool(LIST_PATH.search(board_url))


def page_url(board_url: str, page: int) -> str:
    p = urlsplit(board_url)
    q = {k: v[0] for k, v in parse_qs(p.query).items() if k != "currPage"}
    if page > 1:
        q["currPage"] = str(page)
    return p._replace(query=urlencode(q)).geturl()


def last_page(html: str) -> int:
    return max((int(n) for n in re.findall(r"goPaging\((\d+)\)", html)), default=1)


def list_posts(html: str, board_url: str) -> list[dict]:
    """[{title, date(YYYY-MM-DD), url, ntt_sn}] — 목록 1쪽 분."""
    p = urlsplit(board_url)
    q = parse_qs(p.query)
    base = urljoin(board_url, "selectNttInfo.do")
    posts = []
    for a in BeautifulSoup(html, "lxml").select("a.nttInfoBtn[data-id]"):
        tr = a.find_parent("tr")
        m = DATE.search(tr.get_text(" ")) if tr else None
        sn = a["data-id"]
        posts.append({
            "title": re.sub(r"\s+", " ", a.get_text(" ", strip=True)),
            "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None,
            "url": f"{base}?{urlencode({'mi': q.get('mi', [''])[0], 'bbsId': q.get('bbsId', [''])[0], 'nttSn': sn})}",
            "ntt_sn": sn,
        })
    return posts


def list_attachments(html: str, post_url: str) -> list[dict]:
    """[{name, url, ext, size}] — 직접 다운로드 경로. 두 가지 방식:
    (1) DEXT5 업로더 스크립트, (2) `.bbsV_file li` 의 파일명 + 미리보기 `previewAjax('원본 경로', ...)`
    ((2) 의 `goFileDown(key)` 는 JS 다운로드라 쓰지 않고 미리보기의 원본 경로를 쓴다)."""
    found = [(name, path, size) for name, path, size in DEXT5.findall(html)]
    for li in BeautifulSoup(html, "lxml").select(".bbsV_file li"):
        a = li.select_one("a.fileName")
        m = PREVIEW.search(str(li))
        if a and m:
            found.append((re.sub(r"\s+", " ", a.get_text(" ", strip=True)), m.group(1), ""))
    out = []
    for name, path, size in found:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        out.append({"name": name, "url": urljoin(post_url, path), "ext": ext, "size": int(size or 0)})
    return out
