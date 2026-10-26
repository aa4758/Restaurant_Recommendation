"""소상공인시장진흥공단 상가(상권)정보 CSV 어댑터 — 전국 음식점 뼈대(이름·장르·좌표·주소).

출처: 공공데이터포털(data.go.kr) '소상공인시장진흥공단_상가(상권)정보', 분기 갱신, 시도별 CSV.
파일은 backend/data/raw/sbiz/*.csv 에 둔다(용량이 커서 git 제외).
좌표는 WGS84 경도/위도라 변환 불필요. 인코딩은 UTF-8/CP949 모두 처리.
컬럼명이 배포 시점마다 바뀔 수 있음 → 적재 전 헤더 확인, 다르면 COL 만 수정.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .base import Record, SourceAdapter

COL = {
    "id": "상가업소번호",
    "name": "상호명",
    "branch": "지점명",
    "cat1": "상권업종대분류명",
    "cat2": "상권업종중분류명",
    "cat3": "상권업종소분류명",
    "sido": "시도명",
    "sigungu": "시군구명",
    "sigungu_code": "시군구코드",
    "jibun": "지번주소",
    "road": "도로명주소",
    "floor": "층정보",
    "lng": "경도",
    "lat": "위도",
}

FOOD = "음식"
# 음식점 추천 대상이 아닌 업종(카페·디저트·구내식당·유흥)
EXCLUDE = ("카페", "비알코올", "빵", "도넛", "떡", "한과", "아이스크림", "빙수", "구내식당", "유흥", "무도")
ALCOHOL_HINT = ("주점", "호프", "맥주", "이자카야", "포차", "와인바", "요리 주점")
# 소분류 키워드 우선(순서 중요: 해산물 구이가 고기/구이로 가지 않게), 그다음 중분류
DETAIL_GENRE = (
    (("해산물", "횟집", "생선", "조개", "장어", "아귀", "복 요리", "대게"), "해산물"),
    (("고기", "곱창", "갈비", "삼겹", "구이", "족발", "보쌈"), "고기/구이"),
    (("김밥", "분식", "떡볶이", "만두"), "분식"),
    (("치킨",), "치킨"),
    (("피자", "버거", "파스타", "스테이크", "샌드위치"), "양식"),
)
MID_GENRE = {"한식": "한식", "중식": "중식", "일식": "일식", "서양식": "양식", "동남아시아": "아시안", "주점": "주점"}


def map_genre(mid: str, detail: str) -> str:
    for keys, genre in DETAIL_GENRE:
        if any(k in detail for k in keys):
            return genre
    return MID_GENRE.get(mid, "기타")


HEAD_BYTES = 65536


def detect_encoding(head: bytes, more: bytes | None = None) -> str:
    """앞부분 바이트로 UTF-8(BOM 포함)/CP949 판별.

    읽은 범위 끝에서 멀티바이트 문자가 잘린 경우(UTF-8 의심):
    - more(경계 뒤 최대 4바이트)가 주어지면 head+more 로 다시 판별(빈 bytes = 파일 끝 → 잘린 UTF-8 아님 → CP949).
    - 없으면 잘린 꼬리에 연속 바이트(0x80~0xBF)가 있거나 앞부분에 비ASCII 가 있을 때만 UTF-8.
      ASCII 뒤 선두바이트 하나만 걸린 경우(CP949 선두바이트 0xC7 등)는 증거가 없어 CP949.
    """
    try:
        head.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError as e:
        if not (e.start >= len(head) - 3 and e.reason == "unexpected end of data"):
            return "cp949"
        if more is not None:
            if not more:
                return "cp949"
            try:
                (head + more).decode("utf-8-sig")
                return "utf-8-sig"
            except UnicodeDecodeError as e2:
                if e2.start > e.start and e2.reason == "unexpected end of data":
                    return "utf-8-sig"  # 다음 문자가 또 잘림 — 경계 문자는 유효
                return "cp949"
        tail = head[e.start:]
        if len(tail) > 1 or not head[:e.start].isascii():
            return "utf-8-sig"
        return "cp949"


def read_head(f, n: int = HEAD_BYTES) -> tuple[bytes, bytes]:
    """앞 n 바이트와 경계 재판별용 뒤 4바이트."""
    head = f.read(n)
    return head, f.read(4) if len(head) == n else b""


def _open(path: Path):
    with open(path, "rb") as f:
        head, more = read_head(f)
    enc = detect_encoding(head, more)
    return open(path, encoding=enc, errors="replace", newline="")


class SbizStoresCSVAdapter(SourceAdapter):
    kind = "restaurants"
    name = "sbiz_stores_csv"

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def available(self) -> bool:
        return self.path.exists()

    def fetch(self) -> list[Record]:
        today = date.today().isoformat()
        out: list[Record] = []
        with _open(self.path) as f:
            for r in csv.DictReader(f):
                g = lambda k: (r.get(COL[k]) or "").strip()  # noqa: E731
                if g("cat1") != FOOD:
                    continue
                mid, detail = g("cat2"), g("cat3")
                kind = f"{mid} {detail}"
                if any(x in kind for x in EXCLUDE):
                    continue
                try:
                    lat, lng = float(g("lat")), float(g("lng"))
                except ValueError:
                    continue  # 좌표 없는 행은 위치 추천 불가
                out.append(
                    {
                        "id": f"S{g('id')}",
                        "name": g("name"),
                        "branch": g("branch") or None,
                        "genre": map_genre(mid, detail),
                        "genre_detail": detail or mid or None,
                        # 주점 업종만 확정. 나머지는 인허가(일반/휴게) 연계 전까지 미확인
                        "alcohol": 1 if any(x in kind for x in ALCOHOL_HINT) else None,
                        "lat": lat,
                        "lng": lng,
                        "address": g("road") or g("jibun") or None,
                        "address_jibun": g("jibun") or None,
                        "floor": g("floor") or None,
                        "sido": g("sido") or None,
                        "sigungu": g("sigungu") or None,
                        "sigungu_code": g("sigungu_code") or None,
                        "sbiz_id": g("id"),
                        "source": self.name,
                        "updated_at": today,
                    }
                )
        return out
