"""공통 HTTP 클라이언트 — 9절(크롤링 윤리)을 여기서 강제한다.

- robots.txt 준수: 우리 UA 와 ClaudeBot 둘 다 허용일 때만 요청(이 수집기는 Claude 가 운영하므로 ClaudeBot 차단도 존중).
  '*'·'$' 와일드카드·최장 일치 우선은 Robots 가 직접 처리(표준 라이브러리는 무시함).
  robots.txt 가 404 면 전체 허용, 401/403/5xx/네트워크 오류면 전체 비허용(보수적).
- 같은 도메인 요청 간격 ≥ max(config min_interval_sec, 우리 UA·ClaudeBot Crawl-delay 중 큰 값). Crawl-delay > 60초면 비허용.
  마지막 요청 시각은 프로세스 안 모든 클라이언트가 공유(잠금) → 작업자 스레드가 같은 호스트를 쳐도 간격 유지.
- 리다이렉트는 직접 따라가며 hop 마다 robots·간격을 다시 확인한다(최대 10회).
- 429/5xx/전송 오류는 지수 백오프 재시도. 로그인·CAPTCHA 우회 없음.
"""
import re
import threading
import time
from urllib.parse import unquote, urljoin, urlsplit

import httpx

ROBOTS_ALSO_CHECK = "ClaudeBot"
MAX_CRAWL_DELAY = 60  # 초. 이보다 길면 비허용으로 본다
MAX_REDIRECTS = 10
_LAST: dict = {}  # clock → {host: 다음 요청 가능 기준 시각} (클라이언트 간 공유. clock 별로 나눠 테스트 가짜 시계끼리 섞이지 않게)
_LOCK = threading.Lock()


class RobotsDisallowed(Exception):
    pass


def _rule_regex(path: str) -> re.Pattern:
    """robots 경로 패턴 → 정규식. '*' = 임의 문자열, 끝의 '$' = URL 끝 (RFC 9309)."""
    end = path.endswith("$")
    body = re.escape(unquote(path[:-1] if end else path)).replace(r"\*", ".*")
    return re.compile(body + ("$" if end else ""))


class Robots:
    """RFC 9309 robots.txt. 표준 urllib.robotparser 는 '*'·'$' 를 무시하고(예: 'Disallow: /*?*')
    '*' 그룹을 특정 UA 그룹보다 먼저 고를 수 있어 직접 구현한다. 최장 일치 우선, 동률이면 Allow."""

    def __init__(self):
        self.allow_all = self.disallow_all = False
        self.reason = ""  # 전체 비허용일 때 사유(응답 없음·HTTP 오류)
        self.groups: list[tuple[set[str], list[tuple[str, bool]], float | None]] = []

    def parse(self, lines) -> None:
        agents, rules, delay, in_rules = set(), [], None, False
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:  # 규칙 뒤의 user-agent 는 새 그룹 시작
                    self.groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = set(), [], None, False
                agents.add(val.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                if val:  # 'Disallow:' 빈 값 = 제한 없음
                    rules.append((val, key == "allow"))
            elif key == "crawl-delay":
                in_rules = True
                try:
                    delay = float(val)
                except ValueError:
                    pass
        if agents:
            self.groups.append((agents, rules, delay))

    def _group(self, agent: str):
        agent = agent.lower()
        specific = [g for g in self.groups if any(a != "*" and a in agent for a in g[0])]
        chosen = specific or [g for g in self.groups if "*" in g[0]]
        if not chosen:
            return [], None
        delays = [g[2] for g in chosen if g[2] is not None]
        return [r for g in chosen for r in g[1]], (max(delays) if delays else None)

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        p = urlsplit(url)
        target = unquote(p.path or "/") + (f"?{p.query}" if p.query else "")
        best = None  # (경로 길이, allow) — 길이가 같으면 allow(True)가 이김
        for path, allow in self._group(agent)[0]:
            if _rule_regex(path).match(target):
                key = (len(path), allow)
                best = key if best is None or key > best else best
        return True if best is None else best[1]

    def crawl_delay(self, agent: str) -> float | None:
        return self._group(agent)[1]

    def max_delay(self, agent: str) -> float:
        return max(float(self.crawl_delay(agent) or 0), float(self.crawl_delay(ROBOTS_ALSO_CHECK) or 0))


class HttpClient:
    def __init__(self, cfg_http: dict, transport=None, sleep=time.sleep, clock=time.monotonic):
        ua = cfg_http["user_agent"]
        if "CHANGE_ME" in ua:
            raise ValueError("config.yaml http.user_agent 의 연락처(CHANGE_ME)를 실제 값으로 바꾸세요 (9절)")
        self.ua_token = ua.split("/")[0]
        self.min_interval = float(cfg_http["min_interval_sec"])
        self.retries = int(cfg_http.get("retries", 4))
        self.respect_robots = cfg_http.get("respect_robots", True)
        self.sleep, self.clock = sleep, clock
        self._last = _LAST.setdefault(clock, {})
        self._robots: dict[str, Robots] = {}
        self._client = httpx.Client(
            headers={"User-Agent": ua}, timeout=cfg_http.get("timeout_sec", 30),
            follow_redirects=False, transport=transport,
        )

    def close(self):
        self._client.close()

    # --- 내부 ---
    def _wait(self, host: str, interval: float):
        with _LOCK:  # 자리를 먼저 잡고(마지막 시각 = 이번 요청 시각) 잠금 밖에서 잔다
            now, last = self.clock(), self._last.get(host)
            gap = 0.0 if last is None else max(0.0, interval - (now - last))
            self._last[host] = now + gap
        if gap > 0:
            self.sleep(gap)

    def _raw(self, method: str, url: str, interval: float, retries: int | None = None, **kw) -> httpx.Response:
        host = urlsplit(url).netloc
        retries = self.retries if retries is None else retries
        for attempt in range(retries + 1):
            self._wait(host, interval)
            try:
                r = self._client.request(method, url, **kw)
                if r.status_code != 429 and r.status_code < 500:
                    return r
            except httpx.TransportError:
                if attempt == retries:
                    raise
                r = None
            if attempt < retries:
                self.sleep(interval * 2 ** attempt)
        return r

    def robots(self, url: str) -> Robots:
        p = urlsplit(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self._robots:
            rp = Robots()
            try:
                # 1회만 시도(응답 없는 서버에서 재시도로 수 분 묶이지 않게). 실패 = 전체 비허용
                r = self._follow("GET", key + "/robots.txt", None, retries=0, timeout=20)
                code = r.status_code
            except httpx.TransportError as e:
                code, rp.reason = 503, f"robots.txt 응답 없음({type(e).__name__})"
            if code == 404 or code == 410:
                rp.allow_all = True
            elif code >= 400:
                rp.disallow_all = True
                rp.reason = rp.reason or f"robots.txt HTTP {code}"
            else:
                rp.parse(r.text.splitlines())
            self._robots[key] = rp
        return self._robots[key]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self.robots(url)
        if rp.max_delay(self.ua_token) > MAX_CRAWL_DELAY:
            return False  # 사실상 수집 거부(예: Crawl-delay 3600) → 비허용과 같이 취급
        return rp.can_fetch(self.ua_token, url) and rp.can_fetch(ROBOTS_ALSO_CHECK, url)

    def why_blocked(self, url: str) -> str:
        """비허용 사유: 'robots.txt 응답 없음(...)' / 'robots.txt HTTP 403' / 'Crawl-delay N초' / 'robots 규칙'"""
        rp = self.robots(url)
        delay = rp.max_delay(self.ua_token)
        return rp.reason or (f"Crawl-delay {delay:g}초" if delay > MAX_CRAWL_DELAY else "robots 규칙")

    def interval_for(self, url: str) -> float:
        delay = self.robots(url).max_delay(self.ua_token) if self.respect_robots else 0
        return max(self.min_interval, delay)

    def _follow(self, method: str, url: str, check, **kw) -> httpx.Response:
        """리다이렉트를 hop 마다 check(url)(robots) → 간격 대기로 따라간다. check=None 은 robots.txt 자체."""
        for _ in range(MAX_REDIRECTS + 1):
            if check:
                check(url)
            r = self._raw(method, url, self.interval_for(url) if check else self.min_interval, **kw)
            if not r.is_redirect or "location" not in r.headers:
                return r
            url = urljoin(str(r.url), r.headers["location"])
            if r.status_code == 303 or (r.status_code in (301, 302) and method not in ("GET", "HEAD")):
                method = "GET"
                for k in ("data", "content", "files", "json"):
                    kw.pop(k, None)
        raise httpx.TooManyRedirects(f"리다이렉트 {MAX_REDIRECTS}회 초과: {url}")

    def _check(self, url: str) -> None:
        if not self.allowed(url):
            raise RobotsDisallowed(self.why_blocked(url))

    # --- 공개 ---
    def request(self, method: str, url: str, **kw) -> httpx.Response:
        return self._follow(method, url, self._check, **kw)

    def get(self, url: str, **kw) -> httpx.Response:
        return self.request("GET", url, **kw)
