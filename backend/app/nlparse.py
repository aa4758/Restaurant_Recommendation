"""자연어 조건 → 필터 (규칙 기반, docs/01 '자연어 조건 입력'). 요청 처리 경로에 LLM 없음.

순서: 승인된 동의어(synonyms) → 음주 → 가격 → 거리 → 분위기 → 장르 → 세부 분류(app.subtype 규칙)
     → 남은 낱말: 조사 제거 → 자모 편집거리 1 이내 오타 허용 → 메뉴명 모델(확신도 0.99, 음식명 보조) → 미인식.
미인식 낱말만 unknown_terms 에 집계(원문·기기·위치 저장 안 함).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date
from functools import cache

from app.constants import ALCOHOL, MOODS, PRICE_BANDS
from app.subtype import PARENT, PATTERNS, RULES, DRINK, Model

MAX_RADIUS_M = 20000
PLACE_RADIUS_M = {"dong": 1000, "sigungu": 3000, "landmark": 1000}  # 지역 검색 기본 반경(2026-11-12)
PLACE_MIN_COUNT = 20  # 가게가 이보다 적은 동은 지명으로 안 봄(오인식 방지)
PLACE_RE = re.compile(r"[가-힣0-9]+?(?:동|가|읍|면|구|군|시)(?=[가-힣]{0,3}(?:\s|$|,))")
NEAR_RADIUS_M = 500
WALK_M_PER_MIN = 80
MODEL_MIN_P = 0.99

ALCOHOL_NO = re.compile(r"술\s*(은|는)?\s*(안|없|못|빼|말고)|안\s*마[시셔셨]|논\s*알[콜코]|무\s*알[콜코]|금주")
ALCOHOL_YES = re.compile(r"술|한\s*잔|소주|맥주|와인|막걸리|하이볼|반주")
MOOD_SYN = {
    "조용한": r"조용|차분|한적",
    "회식": r"회식|단체|모임",
    "데이트": r"데이트|기념일|분위기\s*좋",
    "혼밥": r"혼밥|혼자|1인|나\s*혼자",
    "가성비": r"가성비|저렴|싸게|싼|착한\s*가격",
    "노포": r"노포|오래된|전통|옛날",
}
GENRE_SYN = {
    "한식": r"한식|한국\s*음식|(?<![가-힣])밥집",
    "중식": r"중식|중국집|중화\s*요리|중국\s*음식",
    "일식": r"일식|일본\s*음식",
    "양식": r"양식|서양\s*음식|이탈리안|이태리",
    "분식": r"분식",
    "고기/구이": r"고깃집|고기집|고기|구이집",
    "해산물": r"해산물|해물|생선",
    "아시안": r"아시안|동남아",
    "국밥/탕/찌개": r"국물\s*요리|탕\s*집|찌개\s*집",
    "면요리": r"면\s*요리|면\s*집|국수\s*집",
    "패스트푸드": r"패스트\s*푸드|햄버거\s*집",
    "세계음식": r"세계\s*음식|외국\s*음식|이국\s*음식",
    "카페/디저트": r"카페|디저트|빵집",
    "치킨": r"치킨|통닭",
    "주점": r"술집|주점",
    "뷔페": r"뷔페|부페",
}
PARTICLES = ("에서는", "으로", "에서", "하고", "이랑", "까지", "부터", "은", "는", "이", "가", "을", "를", "에", "로", "랑",
             "도", "만", "의", "집", "요")
STOP = {"근처", "주변", "맛집", "추천", "식당", "가게", "음식점", "메뉴", "음식", "요리", "오늘", "점심", "저녁", "아침", "야식",
        "먹고", "먹을", "먹기", "먹는", "싶어", "싶은", "싶다", "좋은", "좋아", "괜찮은", "해줘", "찾아줘", "알려줘", "어디",
        "있는", "곳", "거", "것", "데", "좀", "그리고", "회사", "우리", "같이", "갈", "가고", "원", "정도", "이하", "미만",
        "이내", "아래", "안쪽", "분", "도보", "걸어서", "가까운", "가까이", "곳으로", "메뉴로", "먹을만한", "괜찮", "거리",
        "하기", "마셔", "마실", "맛있는", "맛있게", "유명한", "핫한", "인기", "인기있는", "새로운", "분위기",
        # 시도 이름 — 지역 좁히기에만 쓰고 음식 오타로 보지 않음(부산 → 수산 X)
        "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북",
        "경남", "제주", "땡겨", "땡기는", "당기는", "먹지", "뭐", "할", "수", "있는", "없을까", "어때", "갈만한"}


@cache
def _places(db_file: str) -> dict[str, list[dict]]:
    """지명 → 후보 목록(가게 많은 순). 지번 주소의 동·가·읍·면과 시군구 이름, 가게 좌표 평균(2026-11-12).
    같은 이름이 여러 지역에 있으면 후보가 여럿 → 앱이 고르게 함(place_options).
    ponytail: 프로세스당 1회 전체 스캔(수 초, 서버 시작 시 미리) — 느려지면 적재 시 places 테이블로."""
    import sqlite3 as _sq

    if not db_file:
        return {}
    acc: dict[tuple[str, str, str], list[float]] = {}
    conn = _sq.connect(db_file)
    for jibun, sido, sg, lat, lng in conn.execute(
        "SELECT address_jibun, sido, sigungu, lat, lng FROM restaurants"
        " WHERE status='open' AND lat IS NOT NULL AND address_jibun IS NOT NULL AND sido IS NOT NULL"):
        toks = jibun.split()
        dong = next((x for x in toks[2:4] if re.fullmatch(r"[가-힣0-9]{2,}(동|가|읍|면)", x)), None)
        names = []
        if dong:
            names.append(("dong", f"{sido} {sg} {dong}", dong))
            if m := re.fullmatch(r"(.+동)\d+가", dong):  # 성수동1가 → 성수동 도 같이
                names.append(("dong", f"{sido} {sg} {m.group(1)}", m.group(1)))
        names += [("sigungu", f"{sido} {p}", p) for p in (sg or "").split()]  # '수원시 팔달구' → 수원시·팔달구
        for kind, label, name in names:
            a = acc.setdefault((kind, label, name), [0, 0.0, 0.0])
            a[0] += 1; a[1] += lat; a[2] += lng
    conn.close()
    out: dict[str, list[dict]] = {}
    for (kind, label, name), (n, slat, slng) in sorted(acc.items(), key=lambda kv: -kv[1][0]):
        if n >= PLACE_MIN_COUNT:
            out.setdefault(name, []).append(
                {"name": name, "kind": kind, "label": label, "lat": round(slat / n, 6), "lng": round(slng / n, 6)})
    return out


KAKAO_KEYWORD = "https://dapi.kakao.com/v2/local/search/keyword.json"
# 역·관광명소·학교·문화시설·공공기관만 지명으로 인정(음식점·카페 등 가게 이름은 제외)
KAKAO_PLACE_CATS = {"SW8", "AT4", "SC4", "CT1", "PO3"}


@cache
def _kakao_places(token: str) -> tuple[dict, ...]:
    """역·랜드마크(홍대·강남역 등) → 후보(도시별 1개). 카카오 로컬 키워드 검색(공식 API). 검색어만 보내고 위치는 안 보냄.
    키 없음·실패 → 빈 결과(지명 없이 진행). ponytail: 프로세스 메모리 캐시 — 서버 여러 대면 공용 캐시로."""
    import json
    import os
    import urllib.parse
    import urllib.request

    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not key:
        return ()
    req = urllib.request.Request(f"{KAKAO_KEYWORD}?{urllib.parse.urlencode({'query': token, 'size': 15})}",
                                 headers={"Authorization": f"KakaoAK {key}"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 (공식 API)
            docs = json.load(resp).get("documents", [])
    except Exception:  # 403(콘솔에서 지도/로컬 미사용)·타임아웃 등
        return ()
    seen: dict[str, dict] = {}
    for d in docs:
        # 분류(그룹 코드 또는 "여행 > 관광"·"교통" 분류, 숙박 제외) + 이름이나 주소에 검색어 포함
        # (홍대 → 홍대입구역 O·홍익대 세종캠퍼스 X, 잠실 → 잠실동 명소 O, '데이트' → CGV X)
        cat = d.get("category_name") or ""
        place_ok = (d.get("category_group_code") in KAKAO_PLACE_CATS or cat.startswith(("여행 > 관광", "교통"))) and "휴게소" not in cat
        named = token in (d.get("place_name") or "").replace(" ", "") or token in (d.get("address_name") or "")
        if not (place_ok and named):
            continue
        city = " ".join((d.get("address_name") or "").split()[:2])
        if city and city not in seen:
            seen[city] = {"name": d["place_name"], "kind": "landmark", "label": f"{d['place_name']} ({city})",
                          "lat": round(float(d["y"]), 6), "lng": round(float(d["x"]), 6)}
    return tuple(seen.values())[:8]


def _narrow(cands: list[dict], text: str) -> list[dict]:
    """문장에 시도 이름(서울·부산…)이 있으면 그 시도 후보만."""
    def sido(c: dict) -> str:  # "서울특별시 중구" → 서울 · "시청역 1호선 (부산 연제구)" → 부산
        return (c["label"].rsplit("(", 1)[-1] if c["kind"] == "landmark" else c["label"]).split()[0][:2]

    hit = [c for c in cands if sido(c) in text]
    return hit or cands


def _db_file(conn: sqlite3.Connection | None) -> str:
    if conn is None:
        return ""
    return next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "") or ""


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").lower()


def _price(n: float, kind: str) -> list[str]:
    """n 만원. kind='대'면 그 구간, 아니면 n 이하 구간 전부."""
    uppers = [(1, "~1만"), (2, "1~2만"), (4, "2~4만"), (float("inf"), "4만+")]
    if kind == "대":
        return ["~1만" if n < 1 else "1~2만" if n < 2 else "2~4만" if n < 4 else "4만+"]
    return [b for i, (u, b) in enumerate(uppers) if i == 0 or uppers[i - 1][0] < n] if n > 0 else []


PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)?\s*(만|천)\s*원\s*(대|이하|미만|아래|안쪽|이내|정도|선|까지)?|(\d+(?:\.\d+)?)\s*(만|천)(?=\s*(대|이하|미만|아래|안쪽|이내|정도|선|까지))")
KM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(km|킬로)")
M_RE = re.compile(r"(\d+)\s*(m|미터)(?![a-z])")
WALK_RE = re.compile(r"(도보|걸어서)\s*(\d+)\s*분")
NEAR_RE = re.compile(r"근처|가까운|가까이|코앞|주변")


# --- 자모 오타 허용 --------------------------------------------------------------------------
def _jamo(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch) - 0xAC00
        if 0 <= o < 11172:
            out += [chr(0x1100 + o // 588), chr(0x1161 + o % 588 // 28)] + ([chr(0x11A7 + o % 28)] if o % 28 else [])
        else:
            out.append(ch)
    return "".join(out)


def _within1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    i = j = diff = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i, j = i + 1, j + 1
            continue
        diff += 1
        if diff > 1:
            return False
        if len(a) > len(b):
            i += 1
        elif len(b) > len(a):
            j += 1
        else:
            i, j = i + 1, j + 1
    return diff + (len(a) - i) + (len(b) - j) <= 1


@cache
def _vocab() -> list[tuple[str, str, str, str]]:
    """(낱말, 자모, field, value) — 규칙·동의어 정규식의 순수 한글 대안만."""
    out = []
    groups = [(p, "subtype", t) for t, _, p in RULES] + [(p, "genre", g) for g, p in GENRE_SYN.items()] + \
             [(p, "mood", m) for m, p in MOOD_SYN.items()]
    for pat, field, value in groups:
        for alt in pat.split("|"):
            if re.fullmatch(r"[가-힣]{2,}", alt):
                out.append((alt, _jamo(alt), field, value))
    return out


@cache
def _model() -> Model | None:
    return Model.load()


def _strip(tok: str) -> str:
    for p in PARTICLES:
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[: -len(p)]
    return tok


def _approved(conn: sqlite3.Connection | None) -> list[tuple[str, str, str]]:
    if conn is None:
        return []
    return [tuple(r) for r in conn.execute("SELECT term, field, value FROM synonyms WHERE status='approved'")]


def parse(text: str, conn: sqlite3.Connection | None = None, use_model: bool = True) -> dict:
    t = _norm(text)[:200]
    f: dict = {"price": [], "genre": [], "subtype": [], "mood": [], "alcohol": "any"}

    def add(field: str, value: str):
        if field == "alcohol":
            if value in ALCOHOL:  # 숨긴 값(no)은 무시(constants.ALCOHOL)
                f["alcohol"] = value
        elif field in f and value not in f[field]:
            f[field].append(value)

    def take(pattern, fn):
        nonlocal t
        for m in list(re.finditer(pattern, t)):
            fn(m)
        t = re.sub(pattern, " ", t)

    raw = t
    places: list[dict] = []  # 지역 + 음식 검색(2026-11-12): 지명을 먼저 떼어 다른 규칙에 안 걸리게
    if conn is not None:
        idx = _places(_db_file(conn))
        for m in PLACE_RE.finditer(t):
            if m.group(0) in idx:
                places = _narrow(idx[m.group(0)], raw)
                t = t[: m.start()] + " " + t[m.end():]
                break

    for term, field, value in _approved(conn):
        if field != "none" and term in t:
            add(field, value)
            t = t.replace(term, " ")
    take(ALCOHOL_NO, lambda m: add("alcohol", "no"))  # 무시되지만 '술' 이 YES 로 잡히지 않게 문구는 소비
    if f["alcohol"] == "any":
        take(ALCOHOL_YES, lambda m: add("alcohol", "yes"))
    def price(m):
        num, unit = (m.group(1), m.group(2)) if m.group(2) else (m.group(4), m.group(5))
        n = float(num or 1) / (10 if unit == "천" else 1)  # '만원 이하' = 1만
        for b in _price(n, m.group(3) or m.group(6) or ""):
            add("price", b)

    take(PRICE_RE, price)
    radius = None
    for rx, conv in ((KM_RE, lambda m: float(m.group(1)) * 1000), (M_RE, lambda m: float(m.group(1))),
                     (WALK_RE, lambda m: float(m.group(2)) * WALK_M_PER_MIN)):
        if (m := rx.search(t)) and radius is None:
            radius = conv(m)
        t = rx.sub(" ", t)
    if radius is None and NEAR_RE.search(t):
        radius = NEAR_RADIUS_M
    for mood, p in MOOD_SYN.items():
        take(p, lambda m, mood=mood: add("mood", mood))
    for genre, p in GENRE_SYN.items():
        take(p, lambda m, genre=genre: add("genre", genre))
    take(r"(?<![가-힣])회(?![가-힣])", lambda m: add("subtype", "회/횟집"))  # 한 글자 '회'(해운대 회)
    for sub, p in PATTERNS:  # 장르와 같은 이름의 세부 분류(뷔페)는 장르로
        take(p, lambda m, sub=sub: add("genre" if sub in GENRE_SYN else "subtype", sub))

    unknown = []
    for tok in re.findall(r"[가-힣a-z]{2,}", t):
        tok = _strip(tok)
        if tok in STOP or len(tok) < 2:
            continue
        j = _jamo(tok)
        hit = next(((fl, v) for w, wj, fl, v in _vocab() if len(w) >= 2 and _within1(j, wj)), None)
        if hit:
            add(*hit)
            continue
        model = _model() if use_model else None
        if model and re.fullmatch(r"[가-힣]{2,}", tok):
            sub, p = model.predict(tok)
            if sub == DRINK and p >= MODEL_MIN_P:
                continue
            if sub and p >= MODEL_MIN_P:
                add("subtype", sub)
                continue
        unknown.append(tok)
    if not places:  # 주소에 없는 역·랜드마크 → 카카오(남은 낱말 앞 2개만)
        for tok in unknown[:2]:
            if found := _kakao_places(tok):
                places = _narrow(list(found), raw)
                unknown.remove(tok)
                break
    if conn is not None and unknown:
        _record_unknown(conn, unknown)
    out = {k: v for k, v in f.items() if v and v != "any"}
    out["alcohol"] = f["alcohol"]
    if places and not radius:
        radius = PLACE_RADIUS_M[places[0]["kind"]]
    if radius:
        out["radius_m"] = int(min(radius, MAX_RADIUS_M))
    if len(places) == 1:
        out["place"] = places[0]
    out["price"] = [b for b in PRICE_BANDS if b in out.get("price", [])] or out.pop("price", None) or []
    out["mood"] = [m for m in MOODS if m in out.get("mood", [])]
    res = {"filters": {k: v for k, v in out.items() if v or k == "alcohol"}, "unknown": list(dict.fromkeys(unknown))}
    if len(places) > 1:  # 같은 이름이 여러 곳 → 앱이 먼저 고르게(2026-11-12)
        res["place_options"] = places[:8]
    return res


def _record_unknown(conn: sqlite3.Connection, terms: list[str]) -> None:
    today = date.today().isoformat()
    conn.executemany(
        "INSERT INTO unknown_terms(term,count,first_seen,last_seen) VALUES(?,1,?,?)"
        " ON CONFLICT(term) DO UPDATE SET count=count+1, last_seen=excluded.last_seen",
        [(x[:40], today, today) for x in dict.fromkeys(terms)])
    conn.commit()


def subtype_parent(sub: str) -> str:
    return PARENT[sub]
