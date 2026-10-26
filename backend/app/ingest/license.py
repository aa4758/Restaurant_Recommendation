"""행정안전부 지방행정 인허가 데이터(일반음식점·휴게음식점) CSV 어댑터 — 폐업·일반/휴게·업력(인허가일자).

출처: 지방행정 인허가 데이터개방(localdata) / data.go.kr, 업종별(일반음식점·휴게음식점) 전국 CSV.
파일은 backend/data/raw/license/*.csv 에 둔다(용량이 커서 git 제외).
- 인코딩 UTF-8/CP949 자동, 날짜 YYYYMMDD / YYYY-MM-DD 모두 처리.
- 좌표는 중부원점 TM(EPSG:5174 추정, 2097 가능성) → pyproj 로 WGS84 변환. 없음/0 이면 None(주소 매칭만).
- 컬럼명이 배포 시점마다 바뀜 → ALIASES·COORD_PREFIX 로 흡수. 적재 전 `--check` 로 헤더 확인, 못 찾으면 ALIASES 에 추가.
- 개방서비스명(일반/휴게) 컬럼이 없는 업종별 파일은 --license-type 또는 파일명(일반/휴게)으로 지정.
- 개인정보: COL 에 있는 컬럼만 읽는다. 대표자명 등 PII 컬럼이 들어오면 읽지 않고 폐기(pii_dropped 에 헤더명만 기록).
"""
from __future__ import annotations

import csv
import math
from datetime import date
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from app.scoring import prior

from .base import Record, SourceAdapter
from .sbiz import _open

COL = {
    "license_id": "관리번호",
    "license_type": "개방서비스명",       # 일반음식점 | 휴게음식점
    "opened_at": "인허가일자",
    "status": "영업상태명",               # 영업/정상 | 휴업 | 폐업 | 취소/말소/만료/정지/중지
    "status_detail": "상세영업상태명",
    "closed_at": "폐업일자",
    "phone": "소재지전화",
    "area": "소재지면적",
    "address_jibun": "소재지전체주소",
    "address_road": "도로명전체주소",
    "name": "사업장명",
    "biz_type": "업태구분명",
    "x": "좌표정보(x)",
    "y": "좌표정보(y)",
    "data_updated": "데이터갱신일자",
}
# 배포처·시점마다 다른 헤더 별칭(공백·괄호·밑줄 제거, 소문자 비교). 첫 일치 사용
ALIASES = {
    "license_type": ("서비스명", "업종명", "개방서비스"),
    "opened_at": ("인허가일", "허가일자"),
    "status": ("영업상태",),
    "status_detail": ("상세영업상태",),
    "closed_at": ("폐업일",),
    "phone": ("전화번호", "소재지전화번호", "소재지전화"),
    "area": ("면적", "시설총규모"),
    "address_jibun": ("지번주소", "소재지주소", "소재지지번주소", "지번"),
    "address_road": ("도로명주소", "소재지도로명주소", "도로명"),
    "name": ("업소명", "상호", "상호명"),
    "biz_type": ("업태", "업태명", "위생업태명"),
    "data_updated": ("데이터갱신시점", "최종수정시점", "최종수정일자", "데이터기준일자"),
}
# 좌표 컬럼은 접두 일치(예: '좌표정보X(EPSG5174)', '좌표정보(X)')
COORD_PREFIX = {"x": ("좌표정보x", "x좌표", "좌표x"), "y": ("좌표정보y", "y좌표", "좌표y")}
# --check 의 '추가 열 분포' 전용(적재·점수 미반영 — 값 확인 후 기획 결정). 필드 → 헤더 별칭
EXTRA_COLUMNS = {
    "grade_type": ("등급구분명", "등급구분"),
    "traditional_no": ("전통업소지정번호", "전통업소지정"),
    "traditional_food": ("전통업소주된음식", "주된음식"),
}
# 없으면 적재 불가인 필드(나머지는 비면 None). 좌표·주소는 둘 중 하나만 있어도 매칭 가능
REQUIRED = ("license_id", "opened_at", "status", "name", "biz_type")


def _norm_header(h: str) -> str:
    return "".join(ch for ch in h.lower() if ch not in " \t()[]_-·")


def resolve_columns(header: list[str]) -> dict[str, str]:
    """필드 → 실제 헤더명. COL 기본명 우선, 그다음 별칭, 좌표는 접두 일치."""
    norm = {_norm_header(h): h for h in header}
    out: dict[str, str] = {}
    for k, primary in COL.items():
        if primary in header:
            out[k] = primary
            continue
        if k in COORD_PREFIX:
            hit = next((h for n, h in norm.items() if n.startswith(COORD_PREFIX[k])), None)
        else:
            hit = next((norm[_norm_header(a)] for a in (primary, *ALIASES.get(k, ())) if _norm_header(a) in norm), None)
        if hit:
            out[k] = hit
    return out


def infer_license_type(path: Path | str) -> str | None:
    """개방서비스명 컬럼이 없을 때 파일명으로 추정(휴게/rest → 휴게, 일반/general → 일반). 모르면 None."""
    n = Path(path).name.lower()
    if "휴게" in n or "rest_" in n or n.startswith("rest") or "snack" in n:
        return "휴게음식점"
    if "일반" in n or "general" in n:
        return "일반음식점"
    return None


LICENSE_TYPES = ("일반음식점", "휴게음식점")
REST_TYPE = "휴게음식점"  # 주류 판매 불가(식품위생법 시행령) → alcohol=0

# 읽지 않고 폐기하는 개인정보 컬럼(헤더에 있으면 경고만)
PII_COLUMNS = ("대표자명", "대표자", "대표자성명", "성명", "대표자전화", "휴대전화", "주민등록번호", "생년월일")

# 좌표계: 기본 5174(Korean 1985 / Modified Central Belt). 불확실 → --crs 로 변경, --calibrate 로 검증
DEFAULT_CRS = "EPSG:5174"
CANDIDATE_CRS = ("EPSG:5174", "EPSG:2097", "EPSG:5181")
_KOREA_BOUNDS = (32.5, 39.5, 123.5, 132.5)  # lat_min, lat_max, lng_min, lng_max

# 추천 대상이 아닌 업태(카페·디저트 등). 업태구분명 공백 제거 후 정확히 일치할 때 제외('라이브카페'는 주점이라 유지)
EXCLUDE_BIZ_TYPES = ("커피숍", "까페", "카페", "다방", "제과점영업", "아이스크림", "떡카페", "전통찻집", "키즈카페",
                     "편의점", "철도역구내", "과자점",
                     # 비고정 영업(고정 매장 아님 → 추천 불가)
                     "출장조리", "이동조리", "푸드트럭", "이동판매", "이동음식점")
# 업태 키워드 → 앱 장르(순서 중요). '호프/통닭' 은 상호에 치킨·통닭이 있으면 치킨, 아니면 주점
_CHICKEN_NAME = ("치킨", "통닭", "닭강정")
BIZ_GENRE = (
    (("호프",), "주점"),
    (("통닭", "치킨"), "치킨"),
    (("정종", "대포", "소주방", "감성주점", "라이브카페", "주점"), "주점"),
    (("중국식",), "중식"),
    (("일식", "복어"), "일식"),
    (("경양식", "패밀리레스트랑", "패밀리레스토랑", "패스트푸드"), "양식"),
    (("분식", "김밥"), "분식"),
    (("횟집", "해산물"), "해산물"),
    (("식육", "숯불"), "고기/구이"),
    (("외국음식",), "아시안"),
    (("한식", "냉면", "탕류"), "한식"),
)


def map_genre(biz_type: str | None, name: str | None = None) -> str:
    bt = (biz_type or "").replace(" ", "")
    for keys, genre in BIZ_GENRE:
        if any(k in bt for k in keys):
            if keys == ("호프",) and "통닭" in bt and any(k in (name or "") for k in _CHICKEN_NAME):
                return "치킨"
            return genre
    return "기타"


def is_excluded(biz_type: str | None) -> bool:
    return (biz_type or "").replace(" ", "") in EXCLUDE_BIZ_TYPES


def parse_status(status: str | None, detail: str | None = None) -> str:
    """영업상태 → 'open' | 'closed'. 폐업·취소·말소·만료 = closed, 영업/정상·휴업 = open."""
    s = f"{status or ''} {detail or ''}"
    return "closed" if any(k in s for k in ("폐업", "취소", "말소", "만료")) else "open"


def parse_date(s: str | None) -> str | None:
    d = prior.parse_date(s)
    return d.isoformat() if d else None


def _float(s: str | None) -> float | None:
    try:
        v = float((s or "").replace(",", "").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


@lru_cache(maxsize=8)
def _transformer(crs: str):
    from pyproj import Transformer

    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)


def tm_to_wgs84(x: float | None, y: float | None, crs: str = DEFAULT_CRS) -> tuple[float, float] | None:
    """TM(x=동향, y=북향) → (lat, lng). 없음·0·국내 범위 밖이면 None."""
    if not x or not y:
        return None
    lng, lat = _transformer(crs).transform(x, y)
    lo_lat, hi_lat, lo_lng, hi_lng = _KOREA_BOUNDS
    if not (lo_lat <= lat <= hi_lat and lo_lng <= lng <= hi_lng):
        return None
    return lat, lng


class LicenseCSVAdapter(SourceAdapter):
    kind = "restaurants"
    name = "license_csv"

    def __init__(self, path: Path | str, crs: str = DEFAULT_CRS, license_type: str | None = None,
                 extra: bool = False):
        self.path = Path(path)
        self.extra = extra  # True 면 EXTRA_COLUMNS 값도 레코드에 포함(--check 분포용)
        self.extra_colmap: dict[str, str] = {}
        self.crs = crs
        # 개방서비스명 컬럼이 없을 때 쓸 값(인자 > 파일명 추정)
        self.default_license_type = license_type or infer_license_type(path)
        self.header: list[str] = []
        self.colmap: dict[str, str] = {}
        self.pii_dropped: list[str] = []
        self.missing_columns: list[str] = []  # 필수 필드 중 못 찾은 것(COL 기본명으로 표기)
        self.missing_optional: list[str] = []

    def available(self) -> bool:
        return self.path.exists()

    def fetch(self) -> list[Record]:
        return list(self.iter_records())

    def iter_records(self) -> Iterator[Record]:
        """행 단위 스트리밍(전국 CSV 를 메모리에 올리지 않음). pii_dropped·missing_columns 는 헤더를 읽은 뒤 채워짐."""
        today = date.today().isoformat()
        with _open(self.path) as f:
            reader = csv.DictReader(f)
            header = [(h or "").strip().lstrip("﻿") for h in (reader.fieldnames or [])]
            reader.fieldnames = header
            self.header = header
            self.pii_dropped = [h for h in header if h in PII_COLUMNS]
            cm = self.colmap = resolve_columns(header)
            self.missing_columns = [COL[k] for k in REQUIRED if k not in cm]
            self.missing_optional = [COL[k] for k in COL if k not in cm and k not in REQUIRED]
            if self.extra:
                norm = {_norm_header(h): h for h in header}
                self.extra_colmap = {k: hit for k, names in EXTRA_COLUMNS.items()
                                     if (hit := next((norm[_norm_header(a)] for a in names
                                                      if _norm_header(a) in norm), None))}
            ex = self.extra_colmap
            if self.missing_columns:
                return
            for r in reader:
                g = lambda k: (r.get(cm[k]) or "").strip() if k in cm else ""  # noqa: E731 — 매핑 외 컬럼(PII 포함)은 읽지 않음
                lid = g("license_id")
                if not lid or not g("name"):
                    continue
                x, y = _float(g("x")), _float(g("y"))
                ll = tm_to_wgs84(x, y, self.crs)
                area = _float(g("area"))
                rec = (
                    {
                        "license_id": lid,
                        "license_type": g("license_type") or self.default_license_type,
                        "opened_at": parse_date(g("opened_at")),
                        "status": parse_status(g("status"), g("status_detail")),
                        "status_raw": g("status") or g("status_detail") or None,
                        "closed_at": parse_date(g("closed_at")),
                        "phone": g("phone") or None,
                        "area_m2": area if area else None,
                        "address_road": g("address_road") or None,
                        "address_jibun": g("address_jibun") or None,
                        "name": g("name"),
                        "biz_type": g("biz_type") or None,
                        "x": x or None,
                        "y": y or None,
                        "lat": ll[0] if ll else None,
                        "lng": ll[1] if ll else None,
                        "data_updated": parse_date(g("data_updated")),
                        "source": self.name,
                        "updated_at": today,
                    }
                )
                for k, h in ex.items():
                    rec[k] = (r.get(h) or "").strip()
                yield rec
