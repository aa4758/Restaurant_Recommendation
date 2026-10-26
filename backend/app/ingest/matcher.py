"""선정·지정 목록 행 → 기존 restaurants 매칭 (docs/01 "v2.1", docs/04 2-3).

매칭 조건: 상호 일치(정규화) AND (도로명 주소 정규화 일치 OR 좌표 50m 이내).
- 상호 정규화: (주)·㈜·주식회사·괄호 내용·공백 제거, 소문자. 지점명은 띄어 쓴 마지막 '○○점' 토큰 또는
  restaurants.branch. '전문점'·'음식점'·'○○반점' 등 일반 접미어는 지점명으로 보지 않음.
  붙여 쓴 지점명(예: 샘플식당시청점)은 한쪽 상호 = 다른 쪽 상호 + '○○점'(1~6자) 해석도 허용.
  양쪽 지점명이 모두 있고 다르면 불일치(한쪽만 있으면 허용).
- 도로명 주소 정규화: 괄호·쉼표 이후 제거 → (시도, 시군구, 도로명+길, 건물번호 1토큰). 층·호 토큰 버림.
  지번(동+N가 번지)은 도로명 아님. 시도는 한쪽이 없으면 무시.
- 후보: status='open' 우선. 주소 일치 후보가 여러 개면 reason='ambiguous' 로 매칭 실패.
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
_SIDO_SHORT = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남",
               "전북", "전남", "경북", "경남", "제주"}
_SIDO_LONG = {"충청북": "충북", "충청남": "충남", "전라북": "전북", "전북특별자치": "전북", "전라남": "전남",
              "경상북": "경북", "경상남": "경남", "강원특별자치": "강원", "제주특별자치": "제주"}


# '○○점' 형태지만 지점이 아닌 일반 접미어(업태·상호 일부)
_GENERIC_TAILS = ("전문점", "음식점", "반점", "주점", "제과점", "할인점", "판매점", "대리점", "가맹점", "체인점",
                  "백화점", "편의점", "정육점", "상점", "매점")


def _is_branch(tok: str) -> bool:
    """지점명 토큰('시청점'·'본점')인지. '전문점'·'음식점'·'○○반점' 등 일반 접미어는 지점 아님."""
    return bool(_BRANCH_TAIL.match(tok)) and not tok.endswith(_GENERIC_TAILS)


def _strip(name: str | None) -> list[str]:
    s = _CORP_RE.sub(" ", name or "")
    s = _PAREN_RE.sub(" ", s)
    return s.lower().split()


def split_name(name: str | None, branch: str | None = None) -> tuple[str, str | None]:
    """상호 → (지점 제외 상호, 지점명|None). 지점명은 띄어 쓴 마지막 토큰 또는 명시 branch."""
    toks = _strip(name)
    br = "".join(_strip(branch)) or None
    if len(toks) > 1 and _is_branch(toks[-1]):
        tail = toks.pop()
        br = br or tail
    return "".join(toks), br


def normalize_name(name: str | None) -> str:
    return split_name(name)[0]


def name_forms(name: str | None, branch: str | None = None) -> set[tuple[str, str | None]]:
    """(상호, 지점|None) 해석 후보. 지점이 없으면 붙여 쓴 '…○○점'(1~6자)을 떼어 낸 해석도 포함."""
    base, br = split_name(name, branch)
    if not base:
        return set()
    forms = {(base, br)}
    if br is None and base.endswith("점"):
        for k in range(2, 8):
            head, tail = base[:-k], base[-k:]
            if len(head) >= 2 and _is_branch(tail):
                forms.add((head, tail))
    return forms


def _forms_compatible(fa: set, fb: set) -> bool:
    """상호가 같고, 지점명이 양쪽 다 있으면 같아야 함(한쪽만 있으면 허용)."""
    for ba, ra in fa:
        for bb, rb in fb:
            if ba == bb and (ra is None or rb is None or ra == rb):
                return True
    return False


def names_match(a: str | None, b: str | None) -> bool:
    return _forms_compatible(name_forms(a), name_forms(b))


def _sido(tok: str) -> str | None:
    if tok in _SIDO_SHORT:
        return tok
    base = _SIDO_SUFFIX.sub("", tok)
    base = _SIDO_LONG.get(base, base)
    return base if base in _SIDO_SHORT else None


_ROAD_TOK = re.compile(r"[가-힣A-Za-z0-9]*[가-힣A-Za-z](?:대로|로|길)|[가-힣A-Za-z0-9]+(?:대로|로)\d+(?:번)?[가-힣]?길")
_SUBROAD_TOK = re.compile(r"\d+(?:번)?[가-힣]?길")
_BLDG_TOK = re.compile(r"\d+(?:-\d+)?")


def normalize_road_address(addr: str | None) -> tuple[str, str, str, str] | None:
    """도로명 주소 → (시도|'', 시군구, 도로명, 건물번호). 도로명 패턴이 없으면 None.

    도로명은 '…로|길' 토큰 바로 뒤 공백 + 건물번호 토큰(숫자 또는 숫자-숫자, 뒤에 '가' 아님)일 때만.
    '을지로1가 180' 같은 지번(동+가)은 도로명이 아님 → None. 건물번호 뒤 토큰(N층·지하N층·N호)은 버림.
    """
    if not addr:
        return None
    s = _PAREN_RE.sub(" ", addr).split(",")[0]
    toks = s.split()
    if not toks:
        return None
    sido = _sido(toks[0]) or ""
    rest = toks[1:] if sido else toks
    gu = ""
    i = 0
    while i < len(rest) and re.search(r"(시|군|구)$", rest[i]) and not re.search(r"(로|길)$", rest[i]):
        gu = rest[i]  # '성남시 분당구' → 마지막 구 단위
        i += 1
    for j in range(i, len(rest)):
        if not _ROAD_TOK.fullmatch(rest[j]):
            continue
        road, k = rest[j], j + 1
        if k < len(rest) and _SUBROAD_TOK.fullmatch(rest[k]):
            road += rest[k]  # '샘플로 1길'
            k += 1
        if k < len(rest) and _BLDG_TOK.fullmatch(rest[k]):
            return sido, gu, road, rest[k]
    return None


def addresses_match(a: str | None, b: str | None) -> bool:
    return road_keys_match(normalize_road_address(a), normalize_road_address(b))


def road_keys_match(ka: tuple | None, kb: tuple | None) -> bool:
    """정규화된 도로명 키 비교(시도는 한쪽이 없으면 무시, 시군구 필수)."""
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
    status: str
    forms: frozenset
    addr_key: tuple | None = None  # normalize_road_address(address) 캐시


_CAND_CACHE_MIN = 8  # 후보가 이만큼 이상인 상호(프랜차이즈)만 후보 목록 캐시


class RestaurantIndex:
    """상호(지점 제외) 키 → 가게 목록 + (상호, 시군구, 도로명, 건물번호) → 가게 목록.

    후보 주소 정규화는 적재 시 1회(_Rest.addr_key) → 주소 일치는 dict O(1) 조회(프랜차이즈도 행당 상수).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.by_base: dict[str, list[_Rest]] = {}
        self.by_road: dict[tuple, list[_Rest]] = {}
        self._cands: dict[str, tuple[list[_Rest], list[_Rest], frozenset]] = {}
        for r in conn.execute(
            "SELECT id, name, branch, address, lat, lng, sigungu_code, status FROM restaurants"
        ):
            forms = frozenset(name_forms(r[1], r[2]))
            key = normalize_road_address(r[3])
            rest = _Rest(r[0], r[1], r[3], r[4], r[5], r[6], r[7] or "open", forms, key)
            for base in {b for b, _ in forms}:
                self.by_base.setdefault(base, []).append(rest)
                if key and key[1]:
                    self.by_road.setdefault((base, *key[1:]), []).append(rest)

    def name_candidates(self, name: str) -> list[_Rest]:
        return self._candidates(name)[0]

    def _candidates(self, name: str) -> tuple[list[_Rest], list[_Rest], frozenset]:
        """(후보, pool = open 우선 후보, pool id 집합). 대형 후보 목록은 상호별 캐시."""
        hit = self._cands.get(name)
        if hit is not None:
            return hit
        forms = name_forms(name)
        seen: dict[str, _Rest] = {}
        for base in {b for b, _ in forms}:
            for r in self.by_base.get(base, []):
                if r.id not in seen and _forms_compatible(forms, r.forms):
                    seen[r.id] = r
        cands = list(seen.values())
        pool = [r for r in cands if r.status == "open"] or cands
        out = (cands, pool, frozenset(r.id for r in pool))
        if len(cands) >= _CAND_CACHE_MIN:
            self._cands[name] = out
        return out

    def _addr_hits(self, name: str, key: tuple | None, pool_ids: frozenset) -> list[_Rest]:
        if not key or not key[1]:
            return []
        hits: dict[str, _Rest] = {}
        for base in {b for b, _ in name_forms(name)}:
            for r in self.by_road.get((base, *key[1:]), ()):
                if r.id in pool_ids and road_keys_match(key, r.addr_key):
                    hits[r.id] = r
        return list(hits.values())

    def match(self, name: str, address: str | None, lat: float | None, lng: float | None) -> tuple[_Rest | None, str]:
        """반환: (가게 | None, 사유). open 우선, 주소 일치 우선(복수면 ambiguous), 다음은 50m 이내 최근접."""
        cands, pool, pool_ids = self._candidates(name)
        if not cands:
            return None, "상호 불일치"
        by_addr = self._addr_hits(name, normalize_road_address(address), pool_ids)
        if len(by_addr) > 1:
            return None, "ambiguous"
        if by_addr:
            return by_addr[0], "주소 일치"
        if lat is not None and lng is not None:
            near = sorted((haversine_m(lat, lng, r.lat, r.lng), r.id, r) for r in pool)
            if near and near[0][0] <= MATCH_RADIUS_M:
                return near[0][2], "50m 이내"
            return None, "상호 일치·주소 불일치·50m 밖"
        return None, "상호 일치·주소 불일치(좌표 없음)"
