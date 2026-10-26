"""공공 신호 목록(지정·선정 목록, 위생등급, 행정처분) 적재 공통 헬퍼.

load_designations · load_food_safety 가 같이 쓴다.
- 파일 열기: CSV 만(UTF-8/CP949 자동). xlsx·xls 는 미지원 → CSV 로 저장 안내.
  '#' 로 시작하는 행은 주석. 헤더 위의 제목 줄(예: '착한가격업소 현황')은 상호 컬럼이 보이는 첫 행까지 건너뜀.
- 헤더 해석: 필드별 별칭(_norm_header 정규화 후 완전 일치, 별칭 순서대로 첫 일치). 매핑된 컬럼만 읽음 →
  대표자명·전화 등 PII 는 읽지 않고 헤더명만 pii_dropped 에 기록.
- 매칭: 인허가번호(관리번호) 컬럼이 있으면 restaurants.license_id 정확 일치 우선 → 없으면 상호 + 주소(50m).
  RestaurantIndex 는 적재 1회당 1번만 구축(전국 64.8만 곳도 dict 조회라 수만 행이 수 분 이내).
- 적재: SAVEPOINT 안에서 INSERT OR IGNORE(UNIQUE uq_signals → 재적재 멱등). dry-run 이면 롤백.
- 미매칭 출력: 화이트리스트 컬럼 + reason 만(PII·전화 없음).
"""
from __future__ import annotations

import csv
import math
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.db import BACKEND_DIR
from app.scoring import prior

from .license import PII_COLUMNS, _norm_header
from .matcher import RestaurantIndex, _sido
from .sbiz import detect_encoding, read_head

OUT_DIR = BACKEND_DIR / "data" / "out"
XLSX_HINT = ("xlsx/xls 는 지원하지 않습니다 — 엑셀에서 '다른 이름으로 저장 → CSV UTF-8(쉼표로 분리)(*.csv)'로"
             " 저장한 뒤 그 .csv 로 다시 실행하세요")
HEADER_SCAN_ROWS = 10  # 제목 줄 건너뛰기: 이 행 수 안에서 헤더를 찾음

# 공통 필드 별칭(정규화 후 완전 일치, 앞쪽 우선). 영문 고정 컬럼(name,address,...)도 포함 → 기존 CSV 호환
NAME_ALIASES = ("name", "업소명", "상호명", "상호", "사업장명", "업체명", "가게명", "영업소명", "업소상호명", "음식점명")
ROAD_ALIASES = ("address_road", "도로명주소", "소재지도로명주소", "도로명전체주소", "소재지도로명", "도로명")
ADDR_ALIASES = ("address", "소재지", "주소", "소재지주소", "소재지전체주소", "업소주소", "영업소주소", "업소소재지", "기본주소")
JIBUN_ALIASES = ("address_jibun", "지번주소", "소재지지번주소", "지번전체주소", "소재지지번", "지번")
LAT_ALIASES = ("lat", "위도", "latitude", "y좌표값", "wgs84위도")
LNG_ALIASES = ("lng", "lon", "경도", "longitude", "x좌표값", "wgs84경도")
LICENSE_ALIASES = ("license_id", "인허가번호", "관리번호", "허가번호", "영업신고번호", "인허가관리번호", "영업신고증번호", "허가(신고)번호")
SOURCE_ALIASES = ("source", "출처")
COMMON_ALIASES = {
    "name": NAME_ALIASES,
    "address_road": ROAD_ALIASES,
    "address": ADDR_ALIASES,
    "address_jibun": JIBUN_ALIASES,
    "lat": LAT_ALIASES,
    "lng": LNG_ALIASES,
    "license_id": LICENSE_ALIASES,
    "source": SOURCE_ALIASES,
}
ADDRESS_FIELDS = ("address_road", "address", "address_jibun")  # 매칭에 쓰는 순서(도로명 우선)

# 읽지 않고 폐기하는 개인정보·연락처 컬럼(헤더명 정규화 후 일치)
PII_HEADERS = (*PII_COLUMNS, "대표자명", "대표자", "영업자명", "영업자", "성명", "대표자성명", "전화번호", "전화",
               "연락처", "소재지전화", "소재지전화번호", "업소전화번호", "휴대전화", "휴대폰", "핸드폰", "팩스",
               "팩스번호", "이메일", "email", "phone", "tel")
_PII_NORM = {_norm_header(h) for h in PII_HEADERS}

# 미매칭 출력 화이트리스트(PII·전화 없음)
UNMATCHED_COLUMNS = ("name", "address", "lat", "lng", "kind", "value", "detail", "base_date", "source",
                     "license_id", "reason")
REASON_MISSING = "필수 누락(상호·주소/좌표)"
_KOREA = (32.5, 39.5, 123.5, 132.5)


def is_pii(header: str) -> bool:
    return _norm_header(header) in _PII_NORM


def resolve(header: list[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """필드 → 실제 헤더명. 정규화 후 완전 일치, 별칭 순서대로 첫 일치. 한 헤더는 한 필드에만, PII 헤더는 매핑 안 함."""
    norm: dict[str, str] = {}
    for h in header:
        n = _norm_header(h)
        if n and n not in norm and not is_pii(h):
            norm[n] = h
    out: dict[str, str] = {}
    used: set[str] = set()
    for f, names in aliases.items():
        for a in names:
            h = norm.get(_norm_header(a))
            if h is not None and h not in used:
                out[f] = h
                used.add(h)
                break
    return out


def check_xlsx(path: Path) -> None:
    if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        raise ValueError(f"{path.name}: {XLSX_HINT}")
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic.startswith(b"PK\x03\x04") or magic.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError(f"{path.name}: 엑셀 파일로 보입니다(확장자만 .csv). {XLSX_HINT}")


@dataclass
class Table:
    """CSV 하나. rows() 는 매핑된 필드만 담은 dict 를 스트리밍(원본 행 전체를 들고 다니지 않음)."""

    path: Path
    aliases: dict[str, tuple[str, ...]]
    encoding: str = ""
    header: list[str] = field(default_factory=list)
    colmap: dict[str, str] = field(default_factory=dict)
    pii_dropped: list[str] = field(default_factory=list)
    skipped_title_rows: int = 0
    # 번호 붙은 반복 컬럼(예: 대표메뉴1·가격1): 필드 → 정규화 헤더 정규식(비어 있지 않은 첫 group = 순번). rec[f"{필드}#{순번}"]
    numbered: dict[str, re.Pattern] = field(default_factory=dict)

    def __post_init__(self):
        self.path = Path(self.path)
        if not self.path.exists():
            raise FileNotFoundError(f"파일 없음: {self.path}")
        check_xlsx(self.path)
        with open(self.path, "rb") as f:
            self.encoding = detect_encoding(*read_head(f))

    def _open(self):
        return open(self.path, encoding=self.encoding, errors="replace", newline="")

    def rows(self) -> Iterator[dict[str, str]]:
        with self._open() as f:
            reader = csv.reader(f)
            pending: list[list[str]] = []
            header = None
            for row in reader:
                if not row or not any(c.strip() for c in row) or row[0].lstrip().startswith("#"):
                    continue
                cand = [(c or "").strip().lstrip("﻿") for c in row]
                cm = resolve(cand, self.aliases)
                if "name" in cm:
                    header = cand
                    self.colmap = cm
                    break
                pending.append(cand)
                if len(pending) >= HEADER_SCAN_ROWS:
                    break
            if header is None:
                # 상호 컬럼을 못 찾음 → 첫 행을 헤더로 보고 매핑만 기록(필수 누락으로 보고)
                header = pending[0] if pending else []
                self.colmap = resolve(header, self.aliases)
                self.header = header
                self.pii_dropped = [h for h in header if is_pii(h)]
                return
            self.skipped_title_rows = len(pending)
            self.header = header
            self.pii_dropped = [h for h in header if is_pii(h)]
            idx = {f: header.index(h) for f, h in self.colmap.items()}
            numbered = []
            mapped = set(self.colmap.values())
            for i, h in enumerate(header):
                if h in mapped or is_pii(h):
                    continue
                for f, pat in self.numbered.items():
                    m = pat.fullmatch(_norm_header(h))
                    if m:
                        numbered.append((f, next(g for g in m.groups() if g), i))
                        break
            for row in reader:
                if not row or row[0].lstrip().startswith("#") or not any(c.strip() for c in row):
                    continue
                rec = {f: (row[i].strip() if i < len(row) else "") for f, i in idx.items()}
                for f, n, i in numbered:
                    rec[f"{f}#{n}"] = row[i].strip() if i < len(row) else ""
                yield rec


def chain(first, it):
    """next() 로 헤더를 먼저 읽게 한 뒤(colmap 확정) 첫 행을 되돌려 이어 붙임."""
    if first is not None:
        yield first
    yield from it


def to_float(s: str | None) -> float | None:
    try:
        v = float((s or "").replace(",", "").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def coords(rec: dict) -> tuple[float | None, float | None]:
    lat, lng = to_float(rec.get("lat")), to_float(rec.get("lng"))
    if lat is not None and lng is not None and not (_KOREA[0] <= lat <= _KOREA[1] and _KOREA[2] <= lng <= _KOREA[3]):
        if _KOREA[0] <= lng <= _KOREA[1] and _KOREA[2] <= lat <= _KOREA[3]:
            lat, lng = lng, lat  # 위도·경도 열이 뒤바뀐 파일
        else:
            return None, None
    if lat is None or lng is None:
        return None, None
    return lat, lng


def pick_address(rec: dict) -> str | None:
    for f in ADDRESS_FIELDS:
        if rec.get(f):
            return rec[f]
    return None


def sido_of(addr: str | None) -> str:
    toks = (addr or "").split()
    return (_sido(toks[0]) if toks else None) or "(시도 없음)"


def iso_date(s: str | None) -> str | None:
    d = prior.parse_date(s)
    return d.isoformat() if d else None


def license_key(s: str | None) -> str | None:
    """관리번호 비교 키: 공백·하이픈 제거(배포처마다 '3000000-101-...' / '3000000101...' 혼재)."""
    k = re.sub(r"[\s-]", "", s or "")
    return k or None


CITY_MAX_CANDS = 8  # 상호+시군 매칭: 전국 동명 후보가 이 수 이상이면 프랜차이즈로 보고 매칭 안 함


def _in_city(addr: str | None, sido: str, city: str) -> bool:
    toks = (addr or "").split()
    return bool(toks) and _sido(toks[0]) == sido and city in toks[1:3]


class SignalMatcher:
    """인허가번호 정확 일치 → 상호 + 주소/50m(RestaurantIndex). 적재 1회당 1번 구축."""

    def __init__(self, conn: sqlite3.Connection):
        self.index = RestaurantIndex(conn)
        self.region: dict[str, str | None] = {}
        self.by_license: dict[str, str] = {}
        for rid, lid, sg in conn.execute("SELECT id, license_id, sigungu_code FROM restaurants"):
            self.region[rid] = sg
            k = license_key(lid)
            if k:
                self.by_license[k] = rid

    def match(self, name: str, address: str | None, lat: float | None, lng: float | None,
              license_id: str | None = None) -> tuple[str | None, str | None, str]:
        """반환: (가게 id | None, 방법 'license_id'|'name+address'|None, 사유)."""
        k = license_key(license_id)
        if k and k in self.by_license:
            return self.by_license[k], "license_id", "인허가번호 일치"
        if not name:
            return None, None, REASON_MISSING
        rest, reason = self.index.match(name, address, lat, lng)
        if rest is None:
            return None, None, reason
        return rest.id, "name+address", reason

    def match_city(self, name: str, sido: str | None, city: str | None) -> tuple[str | None, str | None, str]:
        """주소·좌표 없는 목록(경기 모범음식점) 전용: 같은 시도·시군의 영업 중 후보가 정확히 1곳이고
        전국 후보가 CITY_MAX_CANDS 미만(프랜차이즈 제외)일 때만 매칭."""
        sd, city = _sido(sido or ""), (city or "").strip()
        if not name or not sd or not city:
            return None, None, REASON_MISSING
        cands = self.index.name_candidates(name)
        if not cands:
            return None, None, "상호 불일치"
        if len(cands) >= CITY_MAX_CANDS:
            return None, None, "상호+시군: 동명 후보 많음(프랜차이즈)"
        hits = [r for r in cands if r.status == "open" and _in_city(r.address, sd, city)]
        if len(hits) != 1:
            return None, None, f"상호+시군: 후보 {len(hits)}곳"
        return hits[0].id, "name+city", "상호+시군 유일"


def new_stats() -> dict:
    return {"total": 0, "matched": 0, "by_method": Counter(), "inserted": 0, "duplicate": 0, "unmatched": 0,
            "unmatched_reasons": Counter(), "michelin_held": 0, "excluded": 0, "menus": 0}


def apply_signals(conn: sqlite3.Connection, rows: list[tuple], menus: list[tuple] | None = None,
                  dry_run: bool = False, savepoint: str = "load_signals", *,
                  deletes: list[tuple] | None = None) -> tuple:
    """rows: (restaurant_id, kind, value, detail, base_date, source). menus: (restaurant_id, name, price, source, updated_at).
    deletes: (restaurant_id, kind, value, base_date|None) — 추가 후 삭제(base_date None 이면 value 만 일치).

    반환 (신호 추가 수, 메뉴 upsert 수[, 삭제 수 — deletes 를 넘겼을 때]). dry_run 이면 SAVEPOINT 롤백.
    """
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO restaurant_signals(restaurant_id,kind,value,detail,base_date,source)"
            " VALUES(?,?,?,?,?,?)", rows)
        inserted = conn.total_changes - before
        n_menu = upsert_menus(conn, menus or [])
        n_del = 0
        for rid, kind, value, bd in deletes or ():
            if bd:
                cur = conn.execute("DELETE FROM restaurant_signals WHERE restaurant_id=? AND kind=? AND value=?"
                                   " AND base_date=?", (rid, kind, value, bd))
            else:
                cur = conn.execute("DELETE FROM restaurant_signals WHERE restaurant_id=? AND kind=? AND value=?",
                                   (rid, kind, value))
            n_del += max(cur.rowcount, 0)
    except BaseException:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    if dry_run:
        conn.execute(f"ROLLBACK TO {savepoint}")
    conn.execute(f"RELEASE {savepoint}")
    if not dry_run:
        conn.commit()
    return (inserted, n_menu, n_del) if deletes is not None else (inserted, n_menu)


def _menu_key(name: str) -> str:
    return re.sub(r"\s+", "", name or "").lower()


def upsert_menus(conn: sqlite3.Connection, menus: list[tuple]) -> int:
    """가게당 메뉴명(공백 무시) 중복 없이 upsert. 같은 이름이 있으면 대표메뉴 표시, 출처가 같으면 가격 갱신."""
    if not menus:
        return 0
    rids = {m[0] for m in menus}
    have: dict[tuple[str, str], tuple[int, str | None]] = {}
    for chunk in _chunks(sorted(rids), 500):
        for mid, rid, name, src in conn.execute(
            f"SELECT id, restaurant_id, name, source FROM menus WHERE restaurant_id IN ({','.join('?' * len(chunk))})",
            chunk,
        ):
            have.setdefault((rid, _menu_key(name)), (mid, src))
    n = 0
    for rid, name, price, src, updated in menus:
        key = (rid, _menu_key(name))
        hit = have.get(key)
        if hit is None:
            cur = conn.execute(
                "INSERT INTO menus(restaurant_id,name,price,is_signature,source,updated_at) VALUES(?,?,?,1,?,?)",
                (rid, name, price, src, updated))
            have[key] = (cur.lastrowid, src)
        elif hit[1] == src:
            conn.execute("UPDATE menus SET price=COALESCE(?, price), is_signature=1, updated_at=? WHERE id=?",
                         (price, updated, hit[0]))
        else:
            conn.execute("UPDATE menus SET is_signature=1 WHERE id=?", (hit[0],))  # 다른 출처 가격은 유지
        n += 1
    return n


def _chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def rebuild_regions(conn: sqlite3.Connection, regions: set, today=None) -> None:
    from app.service import rebuild_scores  # 순환 import 회피

    for reg in regions:
        rebuild_scores(conn, reg, today=today)


def safe_name(s: str | None) -> str:
    out = re.sub(r"[^\w가-힣.-]+", "_", s or "unknown").strip("_")
    return out or "unknown"


def write_unmatched(path: Path, items: list[dict]) -> Path:
    """화이트리스트 컬럼(UNMATCHED_COLUMNS)만 출력. items 는 UNMATCHED_COLUMNS 키를 가진 dict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=UNMATCHED_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for it in items:
            w.writerow({k: "" if it.get(k) is None else it.get(k) for k in UNMATCHED_COLUMNS})
    return path


def unmatched_item(rec: dict, reason: str, **extra) -> dict:
    lat, lng = coords(rec)
    return {"name": rec.get("name", ""), "address": pick_address(rec) or "", "lat": lat, "lng": lng,
            "license_id": rec.get("license_id", ""), **extra, "reason": reason}


# --- 점검(--check, DB 불필요) ---------------------------------------------------
def check_table(table: Table, extra=None) -> dict:
    """공통 점검: 인코딩·헤더·매핑·필수 누락·행 수·시도 분포·PII 폐기 목록. extra(rec, info) 로 종류별 집계 추가."""
    info: dict = {"path": str(table.path), "encoding": table.encoding}
    sido: Counter = Counter()
    n = missing = with_coords = with_license = 0
    for rec in table.rows():
        n += 1
        addr = pick_address(rec)
        lat, _ = coords(rec)
        if not rec.get("name") or not (addr or lat is not None):
            missing += 1
        with_coords += lat is not None
        with_license += bool(rec.get("license_id"))
        sido[sido_of(addr)] += 1
        if extra:
            extra(rec, info)
    info.update(header=table.header, colmap=table.colmap, pii=table.pii_dropped, rows=n, missing_rows=missing,
                coords=with_coords, license_rows=with_license, sido=sido.most_common(10),
                title_rows=table.skipped_title_rows,
                missing_fields=[f for f in ("name",) if f not in table.colmap]
                + ([] if any(f in table.colmap for f in (*ADDRESS_FIELDS, "lat")) else ["address"]))
    return info


def print_check(info: dict, alias_hint: str) -> None:
    print(f"=== {info['path']}")
    if info.get("error"):
        print(f"[err]  {info['error']}")
        return
    print(f"[info] 인코딩 {info['encoding']}, 행 {info['rows']:,}건")
    if info["title_rows"]:
        print(f"[info] 헤더 위 제목 줄 {info['title_rows']}행 건너뜀")
    print(f"[info] 헤더: {', '.join(info['header'])}")
    print(f"[info] 매핑: {', '.join(f'{k}←{v}' for k, v in info['colmap'].items()) or '(없음)'}")
    if info["missing_fields"]:
        print(f"[err]  필수 컬럼 없음: {', '.join(info['missing_fields'])} → {alias_hint} 의 별칭에 실제 헤더 추가 필요")
    else:
        print("[ok]   필수 컬럼(상호 + 주소/좌표) 있음")
    if info["missing_rows"]:
        print(f"[warn] 상호 또는 주소·좌표가 빈 행 {info['missing_rows']:,}건(미매칭 처리)")
    print(f"[info] 좌표 있는 행 {info['coords']:,}건, 인허가번호 있는 행 {info['license_rows']:,}건")
    print(f"[info] 시도 분포 상위: {', '.join(f'{k} {v:,}' for k, v in info['sido']) or '(없음)'}")
    for h in info["pii"]:
        print(f"[info] 개인정보·연락처 컬럼(읽지 않고 폐기): {h}")
    for label, items in info.get("dists", {}).items():
        if isinstance(items, Counter):
            items = items.most_common(10)
        if isinstance(items, list):
            print(f"[info] {label}: {', '.join(f'{k} {v:,}' for k, v in items) or '(없음)'}")
        else:
            print(f"[info] {label}: {items}")


def print_stats(res: dict, label: str) -> None:
    tag = "[dry]" if res.get("dry_run") else "[ok] "
    m = res["by_method"]
    print(f"{tag} {label} 전체 {res['total']:,}건: 매칭 {res['matched']:,}건"
          f" (인허가번호 {m.get('license_id', 0):,} / 상호+주소 {m.get('name+address', 0):,}"
          + (f" / 상호+시군 {m['name+city']:,}" if m.get("name+city") else "") + "),"
          f" 신호 추가 {res['inserted']:,}건, 중복 무시 {res['duplicate']:,}건,"
          f" 미매칭 {res['unmatched'] - res['michelin_held']:,}건, 보류(미슐랭) {res['michelin_held']:,}건"
          + (f", 제외 {res['excluded']:,}건" if res.get("excluded") else "")
          + (f", 취소 반영 {res['cancel_applied']:,}건" if "cancel_applied" in res else "")
          + (f", 메뉴 upsert {res['menus']:,}건" if res.get("menus") else ""))
    for reason, n in res["unmatched_reasons"].most_common():
        print(f"       미매칭 사유 · {reason}: {n:,}건")
    for k, v in res.get("excluded_reasons", {}).items():
        print(f"       제외 · {k}: {v:,}건")
    if not res.get("dry_run"):
        print(f"[ok]   재계산 시군구 {len(res['regions'])}곳")
    for h in res.get("pii_dropped", []):
        print(f"[info] 개인정보·연락처 컬럼 폐기(미적재): {h}")
    for p in res.get("unmatched_files", []):
        print(f"[warn] 미매칭 목록(수기 검토) → {p}")
