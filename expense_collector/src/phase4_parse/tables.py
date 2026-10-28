"""격자(행 × 칸 문자열) → 업무추진비 표 선별·헤더 찾기 → DataFrame (원본 컬럼명 유지, 7절).

- 헤더: 앞 15행 중 키워드 칸이 2개 이상이고 가장 많은 행. 바로 위(병합 머리)나 아래 행도 키워드 행이면 2단 헤더로 합친다.
- 판정: 금액 + (일자 또는 사용처) 칸이 있으면 ok, 키워드 칸이 2개 이상이지만 그 조합이 아니면 flagged(요약·합계표일 수 있음), 그 외는 버린다.
- 데이터 행: 헤더 아래 빈 행·헤더 반복 행(쪽마다 다시 나오는 머리행)을 뺀다.
"""
import re

import pandas as pd

DATE_K = re.compile(r"일자|일시|날짜|집행일|사용일|결제일|연월일")
PLACE_K = re.compile(r"사용처|장소|가맹점|상호|업소|업체|거래처")
AMT_K = re.compile(r"금액|집행액|사용액|결제액|\(원\)|\(천원\)")
OTHER_K = re.compile(r"목적|내용|인원|대상|방법|구분|부서|비고|집행자|직위|사유|건명")
KEYS = (DATE_K, PLACE_K, AMT_K, OTHER_K)


def clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def _hits(row: list[str]) -> int:
    return sum(1 for c in row if c and len(c) <= 30 and any(k.search(c) for k in KEYS))


def _ffill(row: list[str]) -> list[str]:
    out, last = [], ""
    for c in row:
        last = c or last
        out.append(last)
    return out


def header_index(grid: list[list[str]]) -> int | None:
    best = max(range(min(15, len(grid))), key=lambda i: _hits(grid[i]), default=None)
    return best if best is not None and _hits(grid[best]) >= 2 else None


def to_frame(grid: list[list[str]]) -> tuple[pd.DataFrame, str] | None:
    """(표, 'ok'|'flagged') 또는 업무추진비 표가 아니면 None."""
    grid = [[clean(c) for c in r] for r in grid if any(clean(c) for c in r)]
    if (h := header_index(grid)) is None:
        return None
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    head, start = grid[h], h + 1
    pair = None  # 2단 헤더(위·아래 행): 위 칸이 병합(빈칸)이면 왼쪽 값을 이어 받아 '위 아래'
    if h > 0 and _hits(grid[h - 1]) >= 1 and not all(head):
        pair = (grid[h - 1], head)
    elif start < len(grid) and _hits(grid[start]) >= 2 and (not all(head) or len(set(head)) < len(head)):
        pair, start = (head, grid[start]), start + 1
    if pair:
        head = [" ".join(dict.fromkeys(x for x in (a, b) if x)) for a, b in zip(_ffill(pair[0]), pair[1])]
    names, seen = [], {}
    for i, c in enumerate(head):
        c = c or f"col{i}"
        seen[c] = seen.get(c, 0) + 1
        names.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    rows = [r for r in grid[start:] if r != grid[h] and any(r)]
    joined = " ".join(head)
    status = "ok" if AMT_K.search(joined) and (DATE_K.search(joined) or PLACE_K.search(joined)) else "flagged"
    return pd.DataFrame(rows, columns=names, dtype=str), status


def select(grids: list[list[list[str]]]) -> list[tuple[pd.DataFrame, str]]:
    """여러 격자에서 업무추진비 표만. 헤더 없는 격자가 바로 앞 표와 칸 수가 같으면 이어 붙인다(PDF 쪽 넘김)."""
    out = []
    for g in grids:
        r = to_frame(g)
        if r:
            out.append(r)
        elif out and g and len(out[-1][0].columns) == max(len(x) for x in g):
            df, st = out[-1]
            rows = [[clean(c) for c in x] for x in g if any(clean(c) for c in x)]
            out[-1] = (pd.concat([df, pd.DataFrame(rows, columns=df.columns, dtype=str)], ignore_index=True), st)
    return out
