"""세부 분류(subtype) — docs/01 '세부 분류 필터 + 자연어 조건 입력'.

판정 순서: ① 상호명 키워드 ② 상가정보 업종 소분류(sbiz_category) ③ 메뉴(menus) 키워드 다수결
          ④ 메뉴명 분류 모델(메뉴명에만, 확신도 0.8 이상). 상호명에는 모델을 쓰지 않음(표본 검토 결과 골프장·카페 등
          음식 아닌 상호를 절반 가까이 오분류). 세부 분류의 상위 장르로 genre 보정.
점수·순위에는 쓰지 않는다(필터·표시 전용).

    python -m app.subtype train <AI-Hub '관광 음식메뉴판 데이터' 폴더>   # 모델 학습 → data/models/menu_subtype.json
    python -m app.subtype assign [--db PATH] [--dry-run]                # 가게별 subtype·genre 갱신

모델: 글자 1~3그램 다항 나이브 베이즈(표준 라이브러리). 학습 라벨 = 메뉴명에 ① 규칙 적용, 안 되면 AI-Hub 음식 분류
중 대응이 확실한 것만(아래 AIHUB_MAP), 음료·주류는 '_drink'. AI-Hub 데이터는 학습용으로만 쓰고 원본을 저장·표시하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema

MODEL_PATH = BACKEND_DIR / "data" / "models" / "menu_subtype.json"

# (세부 분류, 상위 장르, 키워드 정규식) — 위에서부터 먼저 맞는 것(구체적인 것을 앞에)
RULES = [
    ("마라/훠궈", "중식", r"마라|훠궈|양꼬치"),
    ("짜장/짬뽕", "중식", r"짜장|자장|짬뽕|탕수육|반점|중화|차이나|홍콩|딤섬|만리장성"),
    ("쌀국수/베트남", "아시안", r"쌀국수|베트남|포[보비]|분짜|반미|하노이|사이공|월남쌈"),
    ("태국/인도/기타아시안", "아시안", r"타이|태국|팟타이|똠양|인도|커리|카레|탄두리|네팔|케밥|멕시(?!카나)|타코|브리또|부리또"),
    ("초밥/스시", "일식", r"초밥|스시|오마카세|사시미"),
    ("라멘/우동/소바", "일식", r"라멘|우동|소바|메밀"),
    ("돈까스/덮밥", "일식", r"돈까스|돈가스|카츠|규동|덮밥|텐동|돈부리"),
    ("이자카야", "주점", r"이자카야|사케|오뎅바|로바다"),
    ("피자", "양식", r"피자|pizza"),
    ("버거", "양식", r"버거|burger|맥도날드|롯데리아|맘스터치"),
    ("파스타/스테이크", "양식", r"파스타|스파게티|스테이크|리조또|비스트로|트라토리아|레스토랑"),
    ("브런치/샐러드", "양식", r"브런치|샐러드|포케|샌드위치|써브웨이"),
    ("치킨", "치킨", r"치킨|통닭|닭강정|교촌|bhc|bbq|굽네|네네|페리카나|처갓집|호식이|60계|멕시카나|푸라닭"),
    ("닭요리", "한식", r"닭갈비|찜닭|닭한마리|닭볶음|삼계탕|백숙|닭곰탕|오리"),
    ("족발/보쌈", "한식", r"족발|보쌈"),
    ("곱창/막창", "고기/구이", r"곱창|막창|대창"),
    ("소고기", "고기/구이", r"한우|소갈비|등심|차돌|육회|우대갈비|소고기"),
    ("감자탕/해장국", "한식", r"감자탕|해장국|뼈해장|뼈다귀|선지|해장"),
    ("국밥/곰탕/설렁탕", "한식", r"국밥|곰탕|설렁탕|순대국|순댓국|수육|갈비탕|육개장|도가니|내장탕|소머리"),
    ("조개/해물", "해산물", r"조개|해물|새우|낙지|쭈꾸미|주꾸미|오징어|게장|대게|킹크랩|전복|꼬막|문어|해산물"),
    ("돼지고기", "고기/구이", r"삼겹|목살|돼지갈비|갈매기|항정|뒷고기|껍데기|숯불|구이|갈비|고깃집|고기|정육|연탄|생고기"),
    ("찌개/전골", "한식", r"찌개|전골|부대|짜글이|청국장|된장|김치찜|샤브|두루치기|두부"),
    ("냉면/국수/칼국수", "한식", r"냉면|면옥|밀면|막국수|칼국수|국수|수제비|콩국수"),
    ("장어", "해산물", r"장어"),
    ("복어", "해산물", r"복어|복집|복국|복요리"),
    ("아구/코다리/생선", "해산물", r"아구|아귀|코다리|생선|동태|대구탕|갈치|고등어|매운탕|민물|추어"),
    ("회/횟집", "해산물", r"횟집|회센|활어|물회|세꼬시|회수산|수산|참치"),
    ("김밥/떡볶이", "분식", r"김밥|떡볶|분식|순대|튀김|라볶|라면"),
    ("도시락", "한식", r"도시락|한솥"),
    ("백반·가정식", "한식", r"한정식|백반|정식|밥상|반상|쌈밥|보리밥|비빔밥|기사식당|집밥|가정식|한상|솥밥|정찬"),
    ("죽", "한식", r"죽$|본죽|죽이야기"),
    ("뷔페", "기타", r"뷔페|부페|애슐리|쿠우쿠우"),
    ("호프/포차", "주점", r"호프|포차|포장마차|맥주|비어|펍|pub|와인|bar$|주막|술집|소주|막걸리|전집|빈대떡|감성주점"),
]
PATTERNS = [(t, re.compile(p, re.I)) for t, _, p in RULES]
PARENT = {t: g for t, g, _ in RULES}
GENRE_ORDER = ["한식", "중식", "일식", "양식", "분식", "고기/구이", "해산물", "아시안", "치킨", "주점", "기타"]
SUBTYPES: dict[str, list[str]] = {g: [t for t, pg, _ in RULES if pg == g] for g in GENRE_ORDER}
SUBTYPES = {g: ts for g, ts in SUBTYPES.items() if ts}

# 상가정보 업종 소분류 → 세부 분류(대응이 확실한 것만. '국/탕/찌개류'는 넓어서 제외)
SBIZ_MAP = {
    "돼지고기 구이/찜": "돼지고기", "소고기 구이/찜": "소고기", "곱창 전골/구이": "곱창/막창", "닭/오리고기 구이/찜": "닭요리",
    "족발/보쌈": "족발/보쌈", "국수/칼국수": "냉면/국수/칼국수", "냉면/밀면": "냉면/국수/칼국수", "백반/한정식": "백반·가정식",
    "김밥/만두/분식": "김밥/떡볶이", "횟집": "회/횟집", "일식 회/초밥": "초밥/스시", "해산물 구이/찜": "조개/해물",
    "복 요리 전문": "복어", "중국집": "짜장/짬뽕", "마라탕/훠궈": "마라/훠궈", "일식 면 요리": "라멘/우동/소바",
    "일식 카레/돈가스/덮밥": "돈까스/덮밥", "피자": "피자", "버거": "버거", "파스타/스테이크": "파스타/스테이크",
    "토스트/샌드위치/샐러드": "브런치/샐러드", "치킨": "치킨", "베트남식 전문": "쌀국수/베트남",
    "기타 동남아식 전문": "태국/인도/기타아시안", "뷔페": "뷔페", "요리 주점": "호프/포차", "생맥주 전문": "호프/포차",
    "전/부침개": "호프/포차",
}

# AI-Hub (음식 유형, 세부 유형) → 세부 분류: 메뉴명이 규칙에 안 걸릴 때만, 대응이 확실한 것만
AIHUB_MAP = {
    ("한식", "회"): "회/횟집", ("한식", "죽"): "죽", ("한식", "찌개"): "찌개/전골", ("한식", "전골"): "찌개/전골",
    ("한식", "면"): "냉면/국수/칼국수", ("일식", "면"): "라멘/우동/소바", ("일식", "튀김"): "돈까스/덮밥",
    ("양식", "메인요리"): "파스타/스테이크", ("분식/기타", "분식"): "김밥/떡볶이",
    ("중식", "요리"): "짜장/짬뽕", ("중식", "면"): "짜장/짬뽕", ("중식", "밥"): "짜장/짬뽕",
}
DRINK = "_drink"
MODEL_MIN_P = 0.8  # 메뉴명 예측 채택 기준


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).lower()


def classify(text: str) -> str | None:
    t = norm(text)
    for sub, p in PATTERNS:
        if p.search(t):
            return sub
    return None


# --- 모델 -------------------------------------------------------------------------------
def _grams(text: str) -> list[str]:
    t = f"^{norm(text)}$"
    return [t[i:i + n] for n in (1, 2, 3) for i in range(len(t) - n + 1)]


class Model:
    def __init__(self, data: dict):
        self.classes: list[str] = data["classes"]
        self.logprior = {c: math.log(p) for c, p in data["prior"].items()}
        self.total = data["total"]
        self.v = data["vocab_size"]
        self.counts: dict[str, dict[str, int]] = data["counts"]

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "Model | None":
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def predict(self, text: str) -> tuple[str | None, float]:
        """(세부 분류 또는 '_drink', 사후확률). 아는 그램이 없으면 (None, 0)."""
        grams = [g for g in _grams(text) if g in self.counts]
        if not any(len(g) >= 2 for g in grams):
            return None, 0.0
        score = {}
        for c in self.classes:
            denom = math.log(self.total[c] + self.v)
            score[c] = self.logprior[c] + sum(math.log(self.counts[g].get(c, 0) + 1) - denom for g in grams)
        best = max(score, key=score.get)
        z = sum(math.exp(s - score[best]) for s in score.values())
        return best, 1.0 / z


def _aihub_rows(root: Path):
    for z in sorted(root.rglob("*.zip")):
        zf = zipfile.ZipFile(z, metadata_encoding="cp949")
        split = "valid" if z.name.startswith("VL") else "train"
        for n in zf.namelist():
            if not n.endswith(".json"):
                continue
            for a in json.loads(zf.read(n)).get("annotations", []):
                mi = a.get("menu_information") or {}
                if mi.get("ko"):
                    yield split, mi["ko"], mi.get("food_type") or "", mi.get("food_subtype") or ""


def label(name: str, ftype: str, fsub: str) -> str | None:
    if ftype == "음료/주류":
        return DRINK
    return classify(name) or AIHUB_MAP.get((ftype, fsub))


def train(root: Path, out: Path = MODEL_PATH, min_count: int = 3) -> dict:
    seen, data = set(), {"train": [], "valid": []}
    for split, name, ft, fs in _aihub_rows(root):
        lab = label(name, ft, fs)
        key = (norm(name), lab)
        if lab and key not in seen:  # 같은 메뉴명 중복은 1번만(체인 메뉴 쏠림 방지)
            seen.add(key)
            data[split].append((name, lab))
    counts: dict[str, Counter] = defaultdict(Counter)
    prior = Counter(lab for _, lab in data["train"])
    for name, lab in data["train"]:
        for g in _grams(name):
            counts[g][lab] += 1
    counts = {g: dict(c) for g, c in counts.items() if sum(c.values()) >= min_count}
    total = Counter()
    for c in counts.values():
        total.update(c)
    n = sum(prior.values())
    model = {"classes": sorted(prior), "prior": {c: k / n for c, k in prior.items()}, "total": dict(total),
             "vocab_size": len(counts), "counts": counts,
             "source": "한국지능정보사회진흥원 AI-Hub '관광 음식메뉴판 데이터'(학습용)"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    m = Model(model)
    ok = sum(m.predict(x)[0] == y for x, y in data["valid"])
    return {"train": len(data["train"]), "valid": len(data["valid"]), "valid_acc": ok / max(len(data["valid"]), 1),
            "vocab": len(counts), "path": str(out)}


# --- 가게별 판정 -----------------------------------------------------------------------------
BROAD_SBIZ = {"백반·가정식"}  # 상가 소분류가 넓음 → 기존 장르가 한식·기타일 때만(골뱅이집·고깃집 오분류 방지)


def decide(name: str, sbiz_category: str | None, menus: list[str], model: Model | None,
           genre: str = "기타") -> tuple[str | None, str | None]:
    if t := classify(name):
        return t, "name"
    if (t := SBIZ_MAP.get(sbiz_category or "")) and (t not in BROAD_SBIZ or genre in ("한식", "기타")):
        return t, "sbiz"
    votes = Counter(t for m in menus if (t := classify(m)))
    if votes:
        return votes.most_common(1)[0][0], "menu"
    if model:
        votes = Counter()
        for m in menus:
            t, p = model.predict(m)
            if t and t != DRINK and p >= MODEL_MIN_P:
                votes[t] += 1
        if votes:
            return votes.most_common(1)[0][0], "model_menu"
    return None, None


def assign(conn: sqlite3.Connection, model: Model | None = None, dry_run: bool = False) -> Counter:
    """모든 가게의 subtype·subtype_src 재계산, 상위 장르가 다르면 genre 보정(점수 무관 → 재계산 없음)."""
    menus: dict[str, list[str]] = defaultdict(list)
    for rid, m in conn.execute("SELECT restaurant_id, name FROM menus"):
        menus[rid].append(m)
    stats, rows = Counter(), []
    for rid, name, genre, cat in conn.execute("SELECT id, name, genre, sbiz_category FROM restaurants"):
        t, src = decide(name, cat, menus.get(rid, []), model, genre)
        stats[src or "none"] += 1
        new_genre = PARENT[t] if t else genre
        stats["genre_changed"] += new_genre != genre
        rows.append((t, src, new_genre, rid))
    conn.execute("SAVEPOINT subtype")
    conn.executemany("UPDATE restaurants SET subtype=?, subtype_src=?, genre=? WHERE id=?", rows)
    conn.execute("ROLLBACK TO subtype" if dry_run else "RELEASE subtype")
    if dry_run:
        conn.execute("RELEASE subtype")
    conn.commit()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="세부 분류: 모델 학습 / 가게별 판정")
    sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("train")
    t.add_argument("aihub_dir", help="AI-Hub '관광 음식메뉴판 데이터' 라벨링 zip 이 있는 폴더(하위 폴더 포함)")
    a = sp.add_parser("assign")
    a.add_argument("--db", default=None)
    a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "train":
        print(train(Path(args.aihub_dir)))
        return
    conn = connect(args.db or db_path())
    init_schema(conn)
    model = Model.load()
    print(f"모델: {'있음' if model else '없음(① ~ ③만)'}")
    st = assign(conn, model, args.dry_run)
    n = sum(st[k] for k in ("name", "sbiz", "menu", "model_menu", "none"))
    for k in ("name", "sbiz", "menu", "model_menu", "none"):
        print(f"  {k}: {st[k]:,} ({st[k] / max(n, 1):.1%})")
    print(f"  genre 보정: {st['genre_changed']:,}{' (dry-run)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
