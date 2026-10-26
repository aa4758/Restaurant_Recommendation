"""간단한 메모리 기반 레이트리밋(고정 1분 창 아닌 슬라이딩 60초). 프로세스 단위 — 다중 워커면 워커별로 따로 셈.

정책: 기기 키 우선(분당 WRITE_LIMIT_PER_MIN), IP 버킷은 NAT/프록시 공유를 감안해 분당 IP_LIMIT_PER_MIN.
메모리: 거부된 요청은 키를 만들지 않음, 창이 지난 키는 즉시 삭제, 총 키 수는 max_keys 상한(초과 시 오래된 키부터 정리).

ponytail: 운영 다중 인스턴스에서는 Redis 등 공유 저장소로 교체.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Iterable, Union

WRITE_LIMIT_PER_MIN = 30  # reactions·리뷰 작성: 기기 당 분당 최대 횟수
IP_LIMIT_PER_MIN = 300  # 같은 IP(통신사 NAT·사내 프록시 공유 감안) 분당 최대 횟수
WINDOW_S = 60.0
MAX_KEYS = 100_000

Key = Union[str, tuple[str, int]]  # "키" (기본 limit) 또는 ("키", 키별 limit)


class RateLimiter:
    def __init__(self, limit: int = WRITE_LIMIT_PER_MIN, window_s: float = WINDOW_S, max_keys: int = MAX_KEYS) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        # 마지막 기록 시각 순(앞 = 가장 오래 전에 기록된 키) → 만료 키를 앞에서부터 O(1) 상각으로 정리
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._hits:
            k, q = next(iter(self._hits.items()))
            if q and now - q[-1] < self.window_s:
                break
            del self._hits[k]

    def allow(self, keys: Iterable[Key], now: float | None = None) -> bool:
        """keys 모두 한도 이내면 기록하고 True. 하나라도 초과면 기록(키 생성 포함) 없이 False."""
        now = time.monotonic() if now is None else now
        pairs = [(k, self.limit) if isinstance(k, str) else (k[0], int(k[1])) for k in keys]
        with self._lock:
            self._expire(now)
            for k, limit in pairs:
                q = self._hits.get(k)
                if q is None:
                    continue
                while q and now - q[0] >= self.window_s:
                    q.popleft()
                if not q:
                    del self._hits[k]
                elif len(q) >= limit:
                    return False
            for k, _ in pairs:
                q = self._hits.get(k)
                if q is None:
                    q = self._hits[k] = deque()
                q.append(now)
                self._hits.move_to_end(k)
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


write_limiter = RateLimiter()
