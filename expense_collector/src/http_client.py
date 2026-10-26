"""공통 HTTP 클라이언트 — 9절(크롤링 윤리)을 여기서 강제한다.

- robots.txt 준수: 우리 UA 와 ClaudeBot 둘 다 허용일 때만 요청(이 수집기는 Claude 가 운영하므로 ClaudeBot 차단도 존중).
  '*'·'$' 와일드카드·최장 일치 우선은 Robots 가 직접 처리(표준 라이브러리는 무시함).
  robots.txt 가 404 면 전체 허용, 401/403/5xx/네트워크 오류면 전체 비허용(보수적).
- 같은 도메인 요청 간격 ≥ max(config min_interval_sec, Crawl-delay). Crawl-delay > 60초면 비허용으로 본다.
  동기 클라이언트라 동시 접속은 항상 1.
- 429/5xx/전송 오류는 지수 백오프 재시도. 로그인·CAPTCHA 우회 없음.
"""
import re
import time
from urllib.parse import unquote, urlsplit

import httpx

ROBOTS_ALSO_CHECK = "ClaudeBot"
MAX_CRAWL_DELAY = 60  # 초. 이보다 길면 비허용으로 본다


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
        self._last: dict[str, float] = {}
        self._robots: dict[str, Robots] = {}
        self._client = httpx.Client(
            headers={"User-Agent": ua}, timeout=cfg_http.get("timeout_sec", 30),
            follow_redirects=True, transport=transport,
        )

    def close(self):
        self._client.close()

    # --- 내부 ---
    def _wait(self, host: str, interval: float):
        last = self._last.get(host)
        if last is not None:
            gap = interval - (self.clock() - last)
            if gap > 0:
                self.sleep(gap)
        self._last[host] = self.clock()

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
                r = self._raw("GET", key + "/robots.txt", self.min_interval, retries=0, timeout=20)
                code = r.status_code
            except httpx.TransportError:
                code = 503
            if code == 404 or code == 410:
                rp.allow_all = True
            elif code >= 400:
                rp.disallow_all = True
            else:
                rp.parse(r.text.splitlines())
            self._robots[key] = rp
        return self._robots[key]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self.robots(url)
        if float(rp.crawl_delay(self.ua_token) or 0) > MAX_CRAWL_DELAY:
            return False  # 사실상 수집 거부(예: Crawl-delay 3600) → 비허용과 같이 취급
        return rp.can_fetch(self.ua_token, url) and rp.can_fetch(ROBOTS_ALSO_CHECK, url)

    def interval_for(self, url: str) -> float:
        delay = self.robots(url).crawl_delay(self.ua_token) if self.respect_robots else None
        return max(self.min_interval, float(delay or 0))

    # --- 공개 ---
    def request(self, method: str, url: str, **kw) -> httpx.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        return self._raw(method, url, self.interval_for(url), **kw)

    def get(self, url: str, **kw) -> httpx.Response:
        return self.request("GET", url, **kw)
