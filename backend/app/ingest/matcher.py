"""선정·지정 목록 행 → 기존 restaurants 매칭 (docs/01 "v2.1", docs/04 2-3).

매칭 조건: 상호 일치(정규화) AND (도로명 주소 정규화 일치 OR 좌표 50m 이내).
- 상호 정규화: (주)·㈜·주식회사·괄호 내용·공백 제거, 지점명(마지막 토큰 '○○점') 제거, 소문자.
  붙여 쓴 지점명(예: 샘플식당시청점)은 한쪽 상호 = 다른 쪽 상호 + '○○점'(1~6자) 이면 일치.
- 도로명 주소 정규화: 괄호·쉼표 이후(층·호) 제거 → (시도, 시군구, 도로명+길, 건물번호). 시도는 한쪽이 없으면 무시.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from app.scoring.recommend import haversine_m

MATCH_RADIUS_M = 50.0
_CORP_RE = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사")
_PAREN_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_BRANCH_TAIL = re.compile(r"^.{1,6}점$")
_SIDO_SUFFIX = re.compile(r"(특별자치시|특별자치도|특별시|광역시|자치시|자치도|시|도)$")
_ROAD_RE = re.compile(r"([가-힣A-Za-z0-9]+?(?:대로|로|길))((?:\d+(?:번)?(?:[가-힣]?길))?)(\d+(?:-\d+)?)")
_SIDO_SHORT = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남",
               "전북", "전남", "경북", "경남", "제주"}
_SIDO_LONG = {"충청북": "충북", "충청남": "충남", "전라북": "전북", "전북특별자치": "전북", "전라남": "전남",
              "경상북": "경북", "경상남": "경남", "강원특별자치": "강원", "제주특별자치": "제주"}


def normalize_name(name: str | None) -> str:
    s = _CORP_RE.sub(" ", name or "")
    s = _PAREN_RE.sub(" ", s)
    toks = s.split()
    if len(toks) > 1 and toks[-1].endswith("점"):
        toks = toks[:-1]  # 띄어 쓴 지점명
    return "".join(toks).lower()


def name_keys(norm: str) -> set[str]:
    """상호에서 붙여 쓴 지점명('…○○점')을 떼어 낸 후보(원형 포함)."""
    keys = {norm}
    if norm.endswith("점"):
        for k in range(2, 8):
            head = norm[:-k]
            if len(head) >= 2 and _BRANCH_TAIL.match(norm[-k:]):
                keys.add(head)
    return keys


def names_match(a: str | None, b: str | None) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    return na in name_keys(nb) or nb in name_keys(na)


def _sido(tok: str) -> str | None:
    if tok in _SIDO_SHORT:
        return tok
    base = _SIDO_SUFFIX.sub("", tok)
    base = _SIDO_LONG.get(base, base)
    return base if base in _SIDO_SHORT else None


def normalize_road_address(addr: str | None) -> tuple[str, str, str, str] | None:
    """도로명 주소 → (시도|'', 시군구, 도로명, 건물번호). 도로명 패턴이 없으면 None."""
    if not addr:
        return None
    s = _PAREN_RE.sub(" ", addr).split(",")[0]
    toks = s.split()
    if not toks:
        return None
    sido = _sido(toks[0]) or ""
    rest = toks[1:] if sido else toks
    gu = ""
    road_toks = []
    for t in rest:
        if not road_toks and re.search(r"(시|군|구)$", t) and not re.search(r"(로|길)$", t):
            gu = t  # '성남시 분당구' → 마지막 구 단위
            continue
        road_toks.append(t)
    m = _ROAD_RE.search("".join(road_toks))
    if not m:
        return None
    return sido, gu, m.group(1) + m.group(2), m.group(3)


def addresses_match(a: str | None, b: str | None) -> bool:
    ka, kb = normalize_road_address(a), normalize_road_address(b)
    if not ka or not kb:
        return False
    if ka[0] and kb[0] and ka[0] != kb[0]:
        return False
    return ka[1:] == kb[1:] and bool(ka[1])


@dataclass
class _Rest:
    id: str
    name: str
    address: str | None
    lat: float
    lng: float
    sigungu_code: str | None


class RestaurantIndex:
    """상호 정규화 키 → 가게 목록 (전국 규모에서도 행당 상수 조회)."""

    def __init__(self, conn: sqlite3.Connection):
        self.by_key: dict[str, list[_Rest]] = {}
        self.by_norm: dict[str, list[_Rest]] = {}
        for r in conn.execute("SELECT id, name, branch, address, lat, lng, sigungu_code FROM restaurants"):
            rest = _Rest(r[0], r[1], r[3], r[4], r[5], r[6])
            for full in {r[1], f"{r[1]} {r[2]}" if r[2] else r[1]}:
                norm = normalize_name(full)
                if not norm:
                    continue
                self.by_norm.setdefault(norm, []).append(rest)
                for k in name_keys(norm):
                    self.by_key.setdefault(k, []).append(rest)

    def name_candidates(self, name: str) -> list[_Rest]:
        norm = normalize_name(name)
        if not norm:
            return []
        seen: dict[str, _Rest] = {r.id: r for r in self.by_key.get(norm, [])}
        for k in name_keys(norm):
            for r in self.by_norm.get(k, []):
                seen.setdefault(r.id, r)
        return list(seen.values())

    def match(self, name: str, address: str | None, lat: float | None, lng: float | None) -> tuple[_Rest | None, str]:
        """반환: (가게 | None, 사유). 주소 일치 우선, 다음은 50m 이내 최근접."""
        cands = self.name_candidates(name)
        if not cands:
            return None, "상호 불일치"
        by_addr = [r for r in cands if addresses_match(address, r.address)]
        if by_addr:
            return by_addr[0], "주소 일치"
        if lat is not None and lng is not None:
            near = sorted((haversine_m(lat, lng, r.lat, r.lng), r.id, r) for r in cands)
            if near and near[0][0] <= MATCH_RADIUS_M:
                return near[0][2], "50m 이내"
            return None, "상호 일치·주소 불일치·50m 밖"
        return None, "상호 일치·주소 불일치(좌표 없음)"
