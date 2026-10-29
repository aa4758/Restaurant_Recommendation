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

from app.constants import MOODS, PRICE_BANDS
from app.subtype import PARENT, PATTERNS, RULES, DRINK, Model

MAX_RADIUS_M = 20000
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
    "치킨": r"치킨|통닭",
    "주점": r"술집|주점",
}
PARTICLES = ("에서는", "으로", "에서", "하고", "이랑", "까지", "부터", "은", "는", "이", "가", "을", "를", "에", "로", "랑",
             "도", "만", "의", "집", "요")
STOP = {"근처", "주변", "맛집", "추천", "식당", "가게", "음식점", "메뉴", "음식", "요리", "오늘", "점심", "저녁", "아침", "야식",
        "먹고", "먹을", "먹기", "먹는", "싶어", "싶은", "싶다", "좋은", "좋아", "괜찮은", "해줘", "찾아줘", "알려줘", "어디",
        "있는", "곳", "거", "것", "데", "좀", "그리고", "회사", "우리", "같이", "갈", "가고", "원", "정도", "이하", "미만",
        "이내", "아래", "안쪽", "분", "도보", "걸어서", "가까운", "가까이", "곳으로", "메뉴로", "먹을만한", "괜찮", "거리",
        "하기", "마셔", "마실", "땡겨", "땡기는", "당기는", "먹지", "뭐", "할", "수", "있는", "없을까", "어때", "갈만한"}


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
            f["alcohol"] = value
        elif field in f and value not in f[field]:
            f[field].append(value)

    def take(pattern, fn):
        nonlocal t
        for m in list(re.finditer(pattern, t)):
            fn(m)
        t = re.sub(pattern, " ", t)

    for term, field, value in _approved(conn):
        if field != "none" and term in t:
            add(field, value)
            t = t.replace(term, " ")
    take(ALCOHOL_NO, lambda m: add("alcohol", "no"))
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
    for sub, p in PATTERNS:
        take(p, lambda m, sub=sub: add("subtype", sub))

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
    if conn is not None and unknown:
        _record_unknown(conn, unknown)
    out = {k: v for k, v in f.items() if v and v != "any"}
    out["alcohol"] = f["alcohol"]
    if radius:
        out["radius_m"] = int(min(radius, MAX_RADIUS_M))
    out["price"] = [b for b in PRICE_BANDS if b in out.get("price", [])] or out.pop("price", None) or []
    out["mood"] = [m for m in MOODS if m in out.get("mood", [])]
    return {"filters": {k: v for k, v in out.items() if v or k == "alcohol"}, "unknown": list(dict.fromkeys(unknown))}


def _record_unknown(conn: sqlite3.Connection, terms: list[str]) -> None:
    today = date.today().isoformat()
    conn.executemany(
        "INSERT INTO unknown_terms(term,count,first_seen,last_seen) VALUES(?,1,?,?)"
        " ON CONFLICT(term) DO UPDATE SET count=count+1, last_seen=excluded.last_seen",
        [(x[:40], today, today) for x in dict.fromkeys(terms)])
    conn.commit()


def subtype_parent(sub: str) -> str:
    return PARENT[sub]
