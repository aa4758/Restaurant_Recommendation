"""범용 게시판 어댑터 — 전용 어댑터가 없는 1곳짜리 구조(`phase3 --scope rest`)용 휴리스틱.

- 목록: 본문 영역의 `tr`/`li` 중 날짜가 있는 행의 첫 일반 링크(같은 호스트). JS(onclick) 링크만 있는 게시판은 못 읽는다.
- 페이지: 목록의 쪽 링크에서 쪽 파라미터(page·pageIndex 등)를 찾아 그 값을 바꾼다. 못 찾으면 1쪽만.
- 첨부: 머리·꼬리·메뉴를 뺀 상세에서 확장자가 보이거나 다운로드 경로인 링크(href, 또는 onclick 의 window.open('URL')).
  미리보기·뷰어 링크는 뺀다. 함수 호출형(fn_download('id') 등)은 못 읽는다.
- 상세 링크 없이 목록 행에 첨부만 있으면 그 행을 게시글로 보고 첨부를 바로 받는다(post['files']).
  첨부가 없고 본문에 집행 표가 있으면 상세 HTML 자체를 원본으로(6절 3.2).
작성자·담당자 칸은 읽지 않는다. adapter_for 에는 걸리지 않게 matches 가 없고, board.py 가 게시판마다 만든다.
"""
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.phase2_board_classify.classify import DOWNLOAD, PAGE_PARAM
from src.phase3_collect.boards._common import file_entry, iso_date, with_param

EXTS = {"xlsx", "xls", "xlsm", "csv", "pdf", "hwp", "hwpx", "zip", "jpg", "png"}
EXT_IN = re.compile(r"\.(xlsx|xlsm|xls|csv|pdf|hwpx|hwp|zip|jpg|png)\b", re.I)
VIEWER = re.compile(r"미리\s*보기|바로\s*보기|뷰어|preview|viewer", re.I)
DROP_WORDS = re.compile(r"\s*(다운로드|내려받기|다운받기|첨부파일)\s*", re.I)
EXPENSE_TABLE = re.compile(r"사용처|집행\s*(일자|장소|금액|내역)|사용\s*(일자|금액)")
CHROME = "header, footer, nav, #header, #footer, #gnb, .gnb, #lnb, .lnb, #snb, .snb, .quick, #quick, .skip"
OPEN_URL = re.compile(r"""(?:window\.open|location\.href\s*=)\s*\(?\s*['"]([^'"]+)['"]""")


def _main(html: str):
    """머리·꼬리·메뉴를 뺀 문서(꼬리말의 '개인정보처리방침.pdf' 같은 링크 제외)."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup.select(CHROME):
        t.decompose()
    return soup


def _href(a) -> str:
    """일반 href, 아니면 onclick 의 window.open('/경로') 처럼 함수 없이 URL 이 그대로 있는 경우만."""
    href = (a.get("href") or "").strip()
    if href and not href.lower().startswith(("#", "javascript:", "mailto:")):
        return href
    m = OPEN_URL.search(a.get("onclick") or "")
    return m.group(1) if m else ""


def _is_file(text: str, href: str) -> bool:
    return bool(EXT_IN.search(text) or EXT_IN.search(href.split("?")[0]) or DOWNLOAD.search(href))


class Generic:
    ID = "generic"
    INLINE = False

    def __init__(self):
        self.param = None

    def page_url(self, board_url: str, page: int) -> str:
        return board_url if page == 1 or not self.param else with_param(board_url, self.param, page)

    def last_page(self, html: str) -> int:
        nums = {}
        for a in BeautifulSoup(html, "lxml").select("a[href]"):
            if m := PAGE_PARAM.search(a["href"]):
                if (v := re.search(rf"[?&]{m.group(1)}=(\d+)", a["href"])) and m.group(1) != "pageUnit":
                    nums.setdefault(m.group(1), set()).add(int(v.group(1)))
        if not nums:
            return 1
        self.param = max(nums, key=lambda k: len(nums[k]))  # 쪽 링크가 가장 많은 파라미터
        return max(nums[self.param])

    def list_posts(self, html: str, board_url: str) -> list[dict]:
        host, posts, seen = urlsplit(board_url).netloc, [], set()
        for row in _main(html).select("tr, li"):
            if row.name == "li" and row.find("li"):  # 메뉴 묶음
                continue
            d = iso_date(row.get_text(" "))
            if not d:
                continue
            files = [] if row.find("tr") else self._files(row, board_url)  # 목록 행에 바로 붙은 첨부(금융위·대전 구 등)
            for a in row.select("a[href]"):
                href = a["href"].strip()
                url = urljoin(board_url, href)
                title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                if (href.lower().startswith(("#", "javascript:")) or urlsplit(url).netloc != host or _is_file(title, href)
                        or url.rstrip("/") == board_url.rstrip("/") or len(title) < 4 or url in seen):
                    continue
                q = parse_qs(urlsplit(url).query)
                if PAGE_PARAM.search(url) and set(q) <= set(parse_qs(urlsplit(board_url).query)) | {self.param or "", "pageIndex", "page"}:
                    continue  # 쪽 링크
                seen.add(url)
                posts.append({"title": title, "date": d, "url": url, "ntt_sn": None})
                break
            else:
                if files and files[0]["url"] not in seen:  # 상세 링크 없이 첨부만 있는 행
                    seen.add(files[0]["url"])
                    cells = [c.get_text(" ", strip=True) for c in row.select("td, span, p")]
                    title = max(cells, key=len, default="") or files[0]["name"]
                    posts.append({"title": re.sub(r"\s+", " ", title)[:200], "date": d, "url": files[0]["url"], "ntt_sn": None, "files": files})
        return posts

    def list_attachments(self, html: str, post_url: str) -> list[dict]:
        body = _main(html)
        out = self._files(body, post_url)
        if not out and any(EXPENSE_TABLE.search(t.get_text(" ")) for t in body.select("table")):
            out.append({"name": "본문.html", "url": post_url, "ext": "html", "size": 0})
        return out

    @staticmethod
    def _files(node, base: str) -> list[dict]:
        out, seen = [], set()
        for a in node.select("a, button"):
            href = _href(a)
            text = re.sub(r"\s+", " ", " ".join(x for x in (a.get_text(" ", strip=True), a.get("title") or "") if x))
            if not href or VIEWER.search(text + href) or not _is_file(text, href):
                continue
            m = EXT_IN.search(text)
            name = text[: m.end()] if m else (href.split("?")[0].rsplit("/", 1)[-1] if EXT_IN.search(href.split("?")[0]) else DROP_WORDS.sub("", text))
            f = file_entry(DROP_WORDS.sub(" ", unquote(name)).strip() or "download", href, base)
            if f["ext"] not in EXTS:
                f["ext"] = ""  # board.file_name 이 Content-Disposition 으로 이름을 정한다
            if f["url"] not in seen:
                seen.add(f["url"])
                out.append(f)
        return out
