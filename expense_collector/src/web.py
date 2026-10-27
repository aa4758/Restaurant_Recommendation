"""HTML 조회 공통: JS 리다이렉트 따라가기 + 페이지 캐시 + 링크 추출. 요청은 모두 HttpClient(9절 강제)로."""
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from src.http_client import HttpClient, RobotsDisallowed

# 따옴표로 감싼 리다이렉트 대상만(예: location.href = currentAddress 같은 변수는 무시)
REDIRECT = re.compile(r"""(?:location\.(?:href|replace)\s*[=(]\s*|NetFunnel_Action\([^,]*,\s*)["']([^"']+)["']"""
                      r"""|http-equiv=["']?refresh["']?[^>]*url=['"]?([^"'\s>]+)""", re.I)
PAGE_SEP = "\n<!-- next page -->\n"  # 문서를 이어 붙이면 lxml 이 첫 </html> 뒤를 버리므로 페이지별로 나눠 파싱
PAGE_URL = re.compile(r"^<!-- url: (\S+) -->")
ROBOTS_MARK = "<!-- robots disallow"


def fetch_followed(client: HttpClient, url: str, cache: Path, hops: int = 4) -> str:
    """JS/meta 리다이렉트를 몇 단계 따라가며 받은 페이지들을 (URL 표시와 함께) 캐시한다."""
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / (re.sub(r"\W", "_", url)[:150] + ".html")
    if f.exists():
        return f.read_text(encoding="utf-8")
    pages = []
    for _ in range(hops):
        try:
            r = client.get(url)
        except RobotsDisallowed as e:
            pages.append(f"{ROBOTS_MARK} {url} | {e} -->")
            break
        pages.append(f"<!-- url: {r.url} -->\n{r.text}")
        m = REDIRECT.search(r.text) if len(r.text) < 20000 else None
        if not m:
            break
        url = urljoin(str(r.url), m.group(1) or m.group(2))
    html = PAGE_SEP.join(pages)
    f.write_text(html, encoding="utf-8")
    return html


def robots_blocked(html: str) -> bool:
    """마지막으로 도착한 페이지가 robots 로 막혔는지(리다이렉트 도중 막힌 경우 포함)."""
    return html.split(PAGE_SEP)[-1].startswith(ROBOTS_MARK)


def blocked_reason(html: str) -> str:
    """'robots.txt 응답 없음(ConnectError)' / 'robots 규칙' 등. 막히지 않았으면 ''."""
    m = re.match(re.escape(ROBOTS_MARK) + r" \S+ \| (.+?) -->", html.split(PAGE_SEP)[-1])
    return m.group(1) if m else ("robots 규칙" if robots_blocked(html) else "")


def final_url(html: str) -> str | None:
    urls = [m.group(1) for p in html.split(PAGE_SEP) if (m := PAGE_URL.match(p))]
    return urls[-1] if urls else None


def anchors(html: str):
    """(링크 문구+title, 절대 URL, 태그) — javascript:/# 링크는 URL 없이(None) 돌려준다."""
    for page in html.split(PAGE_SEP):
        m = PAGE_URL.match(page)
        base = m.group(1) if m else ""
        for a in BeautifulSoup(page, "lxml").select("a, option[value]"):
            href = (a.get("href") or a.get("value") or "").strip()
            text = " ".join(x for x in (a.get_text(" ", strip=True), a.get("title") or "") if x)
            ok = href and not href.lower().startswith(("#", "javascript:")) and (href.startswith("http") or base)
            yield re.sub(r"\s+", " ", text), (urljoin(base, href) if ok else None), a


MAIN_HINT = re.compile(r"""(?:og:url["']\s+content\s*=|rel=["']canonical["']\s+href\s*=|["']?(?:url|href)["']?\s*[:=])\s*["']([^"'\s]+)["']""", re.I)


def main_candidates(html: str) -> list[str]:
    """링크가 거의 없는 인트로·JS 첫 화면에서 실제 메인 페이지 후보(같은 호스트, main/index/portal 경로)."""
    base = final_url(html) or ""
    host = urlsplit(base).hostname
    out = []
    for raw in MAIN_HINT.findall(html.split(PAGE_SEP)[-1]):
        u = urljoin(base, raw)
        path = urlsplit(u).path
        if (urlsplit(u).hostname == host and re.search(r"main|index|portal", path, re.I)
                and not re.search(r"\.(css|js|png|jpe?g|gif|ico|svg)$", path, re.I)
                and u.rstrip("/") != base.rstrip("/") and u not in out):
            out.append(u)
    return out