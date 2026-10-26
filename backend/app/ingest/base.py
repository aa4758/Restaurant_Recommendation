"""어댑터 인터페이스: 소스를 교체 가능하게 유지."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

Record = dict[str, Any]


class SourceAdapter(ABC):
    #: 적재 대상 종류: "restaurants" | "review_stats" | "gov_expense" | "restaurant_signals"
    kind: str = ""
    name: str = ""

    def available(self) -> bool:
        """소스 사용 가능 여부(키 미설정 등이면 False → skip)."""
        return True

    @abstractmethod
    def fetch(self) -> list[Record]:
        """정규화된 레코드 목록 반환."""
