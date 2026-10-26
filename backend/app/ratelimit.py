"""간단한 메모리 기반 레이트리밋(고정 1분 창 아닌 슬라이딩 60초). 프로세스 단위 — 다중 워커면 워커별로 따로 셈.

ponytail: 운영 다중 인스턴스에서는 Redis 등 공유 저장소로 교체.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WRITE_LIMIT_PER_MIN = 30  # reactions·리뷰 작성: 기기/IP 당 분당 최대 횟수
WINDOW_S = 60.0


class RateLimiter:
    def __init__(self, limit: int = WRITE_LIMIT_PER_MIN, window_s: float = WINDOW_S) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, keys: list[str], now: float | None = None) -> bool:
        """keys 모두 한도 이내면 기록하고 True. 하나라도 초과면 기록 없이 False."""
        now = time.monotonic() if now is None else now
        with self._lock:
            for k in keys:
                q = self._hits[k]
                while q and now - q[0] >= self.window_s:
                    q.popleft()
                if len(q) >= self.limit:
                    return False
            for k in keys:
                self._hits[k].append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


write_limiter = RateLimiter()
