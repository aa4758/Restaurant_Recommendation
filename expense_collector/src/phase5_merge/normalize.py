"""파싱 표 한 행 → 표준 레코드(8.1~8.5). 순수 함수만 — 파일·DB 는 merge.py.

- 컬럼: column_map.yaml 정규식(공백·각주 지운 이름), 위 규칙 우선.
- 날짜: 2025-03-04 / 2025.3.4. / 25-03-04 / 3.4.(화) / 2025년 3월 4일 / 20250304 / 엑셀 일련번호. 연도가 없으면 게시일 연도
  (게시일보다 45일 넘게 뒤면 전년도).
- PII: 전화·카드번호, 직위 옆·'외 N명' 앞의 사람 이름을 ○○○ 로. 참석자 칸은 저장하지 않고 인원수만.
"""
import re
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

import yaml

HERE = Path(__file__).parent
STD = ["exec_date", "exec_time", "vendor_address", "amount", "headcount", "vendor_raw", "attendees", "purpose",
       "department", "executor_position", "payment_method"]
MASK = "○○○"
TOTAL = re.compile(r"^(합계|소계|총계|총합계|누계|계)$|총계|합계\(")


@cache
def column_map() -> dict:
    m = yaml.safe_load((HERE / "column_map.yaml").read_text(encoding="utf-8"))
    return {k: [re.compile(p, re.I) for p in v] for k, v in m.items()}


@cache
def category_rules() -> dict:
    m = yaml.safe_load((HERE / "categories.yaml").read_text(encoding="utf-8"))
    return {part: [(cat, re.compile("|".join(ps), re.I)) for cat, ps in rules.items()] for part, rules in m.items()}


def col_key(name: str) -> str:
    return re.sub(r"\s|\*.*$|\d\)$", "", str(name))


def map_columns(columns) -> dict[str, str] | None:
    """{원본 컬럼: 표준 컬럼 | 'ignore'} (미매핑은 빠짐). 업무추진비 표가 아니면(skip_table) None."""
    cm, out, used = column_map(), {}, set()
    keys = {c: col_key(c) for c in columns}
    if any(p.search(k) for k in keys.values() for p in cm["skip_table"]):
        return None
    for c, k in keys.items():
        for std in [*STD, "ignore"]:
            if any(p.search(k) for p in cm[std]):
                if std == "ignore" or std not in used:
                    out[c] = std
                    used.add(std)
                else:
                    out[c] = "ignore"  # 같은 표준 컬럼 두 번째 칸
                break
    return out


TIME = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")
DATE = re.compile(r"(?:(\d{4}|\d{2})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})(?![\d:])")


def parse_time(s: str) -> str:
    s = (s or "").strip()
    if m := TIME.search(s):
        return f"{int(m[1]):02d}:{m[2]}"
    if re.fullmatch(r"0?\.\d+", s):  # 엑셀 시각(하루의 비율)
        mins = round(float(s) * 1440)
        return f"{mins // 60:02d}:{mins % 60:02d}"
    return ""


def parse_date(s: str, ref: str | None) -> tuple[str, str, bool]:
    """(YYYY-MM-DD 또는 '', HH:MM 또는 '', 연도를 추정했는지)."""
    s = re.sub(r"^[‘'`]", "", (s or "").strip())
    if re.fullmatch(r"\d{5}(\.\d+)?", s) and 30000 < float(s) < 60000:  # 엑셀 일련번호
        d = datetime(1899, 12, 30) + timedelta(days=float(s))
        return d.date().isoformat(), parse_time(f"{float(s) % 1:.6f}") if "." in s else "", False
    if m := re.match(r"(\d{4})(\d{2})(\d{2})(?!\d)", s):
        s = f"{m[1]}-{m[2]}-{m[3]}{s[8:]}"
    t = parse_time(s)
    m = DATE.search(TIME.sub(" ", s))
    if not m:
        return "", t, False
    y, mo, d = m[1], int(m[2]), int(m[3])
    guessed = not y
    try:
        if y:
            out = date(int(y) + (2000 if len(y) == 2 else 0), mo, d)
        elif ref:
            r = date.fromisoformat(ref[:10])
            out = date(r.year, mo, d)
            if out > r + timedelta(days=45):
                out = date(r.year - 1, mo, d)
        else:
            return "", t, False
    except ValueError:
        return "", t, False
    return out.isoformat(), t, guessed


def parse_amount(s: str, thousand: bool = False) -> int | None:
    v = re.sub(r"[\s,원₩]|\\", "", s or "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", v):  # 점을 천 단위 구분으로 쓴 경우
        v = v.replace(".", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", v):
        return None
    n = round(float(v) * (1000 if thousand else 1))
    return n if 0 < abs(n) < 10**9 else None  # 10억 이상 = 번호·합친 숫자


def parse_headcount(s: str, need_unit: bool = False) -> int | None:
    m = re.search(r"(\d+)\s*(명|인)" if need_unit else r"(\d+)", s or "")
    return int(m[1]) if m and 0 < int(m[1]) <= 10000 else None


POS = r"[가-힣]*(?:장|관|감|지사|군수|위원|주무관|주사|사무관|서기관|비서|대표|의원|교사|담당|팀원)"
ORG_END = re.compile(r"(과|팀|실|국|청|회|단|소|부|처|센터|면|동|읍|군|시|구|도|원)$")
ORG_NOT_NAME = re.compile(r"(과|팀|실|청|회|단|소|부|처|센터|면|읍)$")  # 이름에 흔한 끝(국·원·동…)은 뺌 → 가리는 쪽으로
NOT_NAME = re.compile(r"^(직원|직원들|전직원|관계자|기자|주민|일행|간부|내빈|손님|시민|학생|교사|교직원|임원|회원|단체|참석자|"
                      r"외부|관내|유관기관|위원|의원|선생님|어르신|가족|봉사자|강사|민원인|동료|업무|격려|간담회|오찬|만찬|"
                      r"직원격려|부서원|팀원|과원|실무자|담당자|대상자|관련자|공무원|선생|고객|여러분)$")
SEP = re.compile(r"(\s+|[,·/()\[\]])")
WORD = re.compile(r"([가-힣]{2,4}?)(님|씨|외|등)?")


def _name(tok: str) -> bool:
    return bool(re.fullmatch(r"[가-힣]{2,4}", tok)) and not NOT_NAME.match(tok) and not re.search(POS + "$", tok) \
        and not ORG_NOT_NAME.search(tok) and not re.search(r"(에|을|를|의|로|께|서)$", tok)  # 조사로 끝나면 낱말


def _pos(tok: str) -> bool:
    return bool(re.fullmatch(r"[가-힣\dⅠⅡⅢ]*" + POS + r"[ⅠⅡⅢ\d]*", tok))


def mask_pii(s: str) -> str:
    """전화·카드번호와 사람 이름(직위 바로 앞뒤 낱말, 'OOO 외 N명', 'OOO님')을 가린다."""
    if not s:
        return ""
    s = re.sub(r"\d{4}[-\s]?[\d*]{4}[-\s]?[\d*]{4}[-\s]?\d{3,4}", MASK, s)  # 카드번호(일부 가림 포함)
    s = re.sub(r"0\d{1,2}[-.\s)]\s?\d{3,4}[-.\s]\d{4}|01\d{8,9}", MASK, s)  # 전화
    parts = SEP.split(s)
    words = [i for i, p in enumerate(parts) if p and not SEP.fullmatch(p)]
    for k, i in enumerate(words):
        m = WORD.fullmatch(parts[i])
        if not m or not _name(m[1]):
            continue
        prev, nxt, nxt2 = (parts[words[j]] if 0 <= j < len(words) else "" for j in (k - 1, k + 1, k + 2))
        outer = m[2] == "외" and re.match(r"\d", nxt) or nxt == "외" and re.match(r"\d", nxt2)
        if m[2] in ("님", "씨") or _pos(prev) or _pos(nxt) or outer:
            parts[i] = MASK + (m[2] or "")
    return "".join(parts)


def position_only(s: str) -> str:
    """직위만 남긴다: 이름을 가린 뒤 직위·조직 꼴(…장·…관·…과 등)이 아닌 낱말은 버림."""
    # ponytail: 낱말 끝 글자 규칙이라 '…장'으로 끝나는 이름은 못 거른다 — 실명 목록 대조가 필요해지면 그때.
    toks = re.split(r"[\s,·/]+", mask_pii(s))
    keep = [t for t in toks if t and t != MASK and (re.search(POS + r"[ⅠⅡⅢ\d]*$", t) or ORG_END.search(t))]
    return " ".join(keep)


POS_WORD = re.compile(r"(부|주무)?(과장|국장|팀장|실장|시장|군수|구청장|교육장|교육감|주무관|담당|소장|동장|면장|읍장|청장|지사)")
CORP = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|사단법인|\(재\)|재단법인|농업회사법인|영농조합법인|\(합\)")


def normalize_vendor(s: str) -> str:
    v = CORP.sub(" ", s or "").replace(MASK, " ")
    v = re.sub(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）", " ", v)
    v = re.sub(r"\s*외\s*\d+\s*(곳|건|개소|명)?$", "", v.strip())  # '가나식당 외 1곳'
    v = re.sub(r"\s+[가-힣A-Za-z0-9]+점$", "", v.strip())  # 지점명
    v = re.sub(r"\s+", " ", v).strip(" -·,.")
    only_pos = all(POS_WORD.fullmatch(t) for t in re.split(r"[\s,·/]+", v))  # '과장, 주무팀장' 처럼 칸이 밀린 값
    return "" if only_pos or TOTAL.search(v.replace(" ", "")) else v


def categorize(vendor: str, purpose: str) -> str:
    r = category_rules()
    key = (vendor or "").replace(" ", "")
    for cat, pat in r["vendor"] if key else []:
        if pat.search(key):
            return cat
    for cat, pat in r["purpose"]:
        if pat.search(purpose or ""):
            return cat
    return "unknown"


def records(rows: list[dict], cols: dict[str, str], meta: dict) -> tuple[list[dict], dict]:
    """한 표의 행들 → 표준 레코드. meta: file_id, table_index, post_date, parse_confidence, amount_thousand 등.
    돌려줌: (레코드, 버린 사유별 수)."""
    by = {}
    for c, std in cols.items():
        if std != "ignore":
            by[std] = c
    out, drop = [], {"total": 0, "no_date": 0, "empty": 0}
    for i, row in enumerate(rows):
        g = {std: str(row.get(c) or "").strip() for std, c in by.items()}
        if any(TOTAL.search(g.get(k, "").replace(" ", "")) for k in ("exec_date", "vendor_raw", "purpose", "executor_position")):
            drop["total"] += 1
            continue
        d, t, guessed = parse_date(g.get("exec_date", ""), meta.get("post_date"))
        amount = parse_amount(g.get("amount", ""), meta.get("amount_thousand", False))
        vendor_raw = mask_pii(g.get("vendor_raw", ""))
        vendor = normalize_vendor(vendor_raw)
        if not d and not g.get("exec_date") and amount and out:  # 병합 칸(한 날짜에 여러 건): 윗 행 날짜
            d, guessed = out[-1]["exec_date"], True
        if not d:
            drop["no_date"] += 1
            continue
        if not (amount or vendor):
            drop["empty"] += 1
            continue
        purpose = mask_pii(g.get("purpose", ""))
        conf = meta["parse_confidence"] * (0.9 if guessed else 1)
        out.append({
            "record_id": f"{meta['file_id']}-{meta['table_index']}-{i}",
            "department": mask_pii(g.get("department", "")),
            "executor_position": position_only(g.get("executor_position", "")),
            "exec_date": d,
            "exec_time": parse_time(g.get("exec_time", "")) or t,
            "vendor_raw": vendor_raw,
            "vendor_normalized": vendor,
            "vendor_address": mask_pii(g.get("vendor_address", "")),
            "vendor_category": categorize(vendor, purpose),
            "amount": amount,
            "headcount": parse_headcount(g.get("headcount", "")) or parse_headcount(g.get("attendees", ""), True),
            "purpose": purpose,
            "payment_method": mask_pii(g.get("payment_method", ""))[:20],
            "parse_confidence": round(conf, 3),
        })
    return out, drop
