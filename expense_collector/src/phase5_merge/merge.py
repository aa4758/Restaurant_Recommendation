"""Phase 5: parsed 표 → expenses_merged.csv · unmapped_columns.csv · quality_report.md, 그리고 찐맛 export(13절)."""
from collections import Counter
from pathlib import Path

import pandas as pd

from src import db
from src.phase5_merge import normalize as nz

COLUMNS = ["record_id", "institution_id", "institution_name", "institution_type", "department", "executor_position",
           "exec_date", "exec_time", "vendor_raw", "vendor_normalized", "vendor_address", "vendor_category", "amount",
           "headcount", "purpose", "payment_method", "source", "license", "source_file_id", "parse_confidence"]
JJINMAT = ["restaurant_name", "address", "exec_date", "agency", "amount", "purpose", "source", "base_year"]
DEDUPE_KEY = ["institution_id", "exec_date", "amount", "_vendor_key"]


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """8.4: (기관, 일자, 금액, 상호) 같으면 하나만 — DATAGOKR > BOARD, 그다음 신뢰도 높은 것. 상호가 없으면 목적으로 비교."""
    df = df.assign(_vendor_key=df["vendor_normalized"].where(df["vendor_normalized"] != "", df["purpose"]),
                   _rank=(df["source"] != "DATAGOKR").astype(int))
    df = df.sort_values(["_rank", "parse_confidence"], ascending=[True, False], kind="stable")
    return df.drop_duplicates(DEDUPE_KEY).drop(columns=["_vendor_key", "_rank"]).sort_values(
        ["institution_id", "exec_date", "record_id"], kind="stable")


def build(conn, parsed_dir: str, start: str, end: str) -> tuple[pd.DataFrame, Counter, Counter, Counter]:
    q = """SELECT pt.file_id, pt.table_index, pt.path, pt.parse_confidence, f.source, f.license, f.post_date,
                  i.institution_id, i.name, i.type
           FROM parsed_tables pt JOIN files f USING(file_id) JOIN institutions i ON i.institution_id = f.institution_id
           WHERE pt.parse_status IN ('ok','flagged') AND pt.path IS NOT NULL ORDER BY pt.file_id, pt.table_index"""
    recs, unmapped, unmapped_rows, drop = [], Counter(), Counter(), Counter()
    for n, (fid, ti, path, conf, src, lic, post_date, iid, name, typ) in enumerate(conn.execute(q).fetchall(), 1):
        df = pd.read_parquet(Path(parsed_dir) / path)
        cols = nz.map_columns(df.columns)
        if cols is None:
            drop["skip_table"] += len(df)
            continue
        for c in df.columns:
            if c not in cols:
                unmapped[nz.col_key(c)] += 1
                unmapped_rows[nz.col_key(c)] += len(df)
        amt_col = next((c for c, s in cols.items() if s == "amount"), "")
        meta = dict(file_id=fid, table_index=ti, post_date=post_date, parse_confidence=conf or 0,
                    amount_thousand="천원" in amt_col)
        rows, d = nz.records(df.to_dict("records"), cols, meta)
        drop.update(d)
        for r in rows:
            r.update(institution_id=iid, institution_name=name, institution_type=typ, source=src,
                     license=lic or "공공누리 표시 없음", source_file_id=str(fid))
        recs += rows
        if n % 5000 == 0:
            print(f"  표 {n} · 레코드 {len(recs)}", flush=True)
    df = pd.DataFrame(recs, columns=COLUMNS).astype({"amount": "Int64", "headcount": "Int64"})
    in_period = df["exec_date"].between(start, end)
    drop["out_of_period"] += int((~in_period).sum())
    df = df[in_period]
    before = len(df)
    df = dedupe(df)
    drop["duplicate"] += before - len(df)
    return df, unmapped, unmapped_rows, drop


def months(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start[:7], end[:7], freq="M")]


def report(conn, df: pd.DataFrame, drop: Counter, start: str, end: str, low: float, foi_path: Path) -> str:
    L = ["# 업무추진비 통합 품질 리포트", "",
         f"- 기간 {start} ~ {end} · 레코드 **{len(df):,}** · 기관 {df['institution_id'].nunique()}곳",
         f"- 버린 행: " + ", ".join(f"{k} {v:,}" for k, v in sorted(drop.items())),
         f"- `parse_confidence < {low}` 레코드: **{int((df['parse_confidence'] < low).sum()):,}**", ""]
    L += ["## 출처·이용조건", "", "| 출처 | 공공누리 | 레코드 | 비중 |", "|---|---|---:|---:|"]
    for (s, lic), n in df.groupby(["source", "license"]).size().items():
        L.append(f"| {s} | {lic} | {n:,} | {n / len(df):.1%} |")
    L += ["", "## 분류", "", "| vendor_category | 레코드 | 비중 |", "|---|---:|---:|"]
    for c, n in df["vendor_category"].value_counts().items():
        L.append(f"| {c} | {n:,} | {n / len(df):.1%} |")
    L += ["", "## 결측률(컬럼별)", "", "| 컬럼 | 결측률 |", "|---|---:|"]
    for c in COLUMNS:
        miss = df[c].isna() | (df[c].astype(str).str.strip() == "")
        L.append(f"| {c} | {miss.mean():.1%} |")
    pos = (df["executor_position"] != "").mean()
    dep = (df["department"] != "").mean()
    L += ["", f"- 범위(11절): 직위가 있는 레코드 {pos:.1%}, 부서가 있는 레코드 {dep:.1%}. 공개 범위는 주로 기관장·부기관장·실국장 단위라 "
          "특정 부서 단위 분석은 부서 칸이 있는 기관으로 한정된다."]
    inst = pd.read_sql("SELECT institution_id, name, type, region FROM institutions WHERE status != 'excluded'", conn).fillna({"region": "(시도 없음·중앙)"})
    have = set(df["institution_id"])
    L += ["", "## 시도별 커버리지", "", "| 시도 | 대상 기관 | 레코드 있는 기관 | 비율 | 레코드 |", "|---|---:|---:|---:|---:|"]
    per_region = df.merge(inst[["institution_id", "region"]], on="institution_id").groupby("region").size()
    for reg, g in inst.groupby("region"):
        k = g["institution_id"].isin(have).sum()
        L.append(f"| {reg} | {len(g)} | {k} | {k / len(g):.0%} | {int(per_region.get(reg, 0)):,} |")
    all_m = months(start, end)
    L += ["", "## 기관별 레코드", "", f"빈 달 = 기간 {len(all_m)}개월 중 레코드가 없는 달 수.", "",
          "| 기관 | 유형 | 레코드 | 처음 | 마지막 | 빈 달 |", "|---|---|---:|---|---|---:|"]
    for (iid, name, typ), g in df.groupby(["institution_id", "institution_name", "institution_type"]):
        got = set(g["exec_date"].str[:7])
        L.append(f"| {name} | {typ} | {len(g):,} | {g['exec_date'].min()} | {g['exec_date'].max()} | "
                 f"{sum(m not in got for m in all_m)} |")
    foi = pd.read_csv(foi_path, dtype=str) if foi_path.exists() else pd.DataFrame(columns=["institution_id"])
    collected = {r[0] for r in conn.execute("SELECT DISTINCT institution_id FROM files WHERE status='ok'")}
    no_rec = inst[inst["institution_id"].isin(collected - have)]
    L += ["", "## 수집 실패·미수집 기관", "",
          f"- 정보공개청구 후보(`foi_candidates.csv`): **{len(foi)}곳**",
          f"- 파일은 받았지만 통합 레코드가 없는 기관 {len(no_rec)}곳(스캔·DRM·표 없음 등): "
          + (", ".join(no_rec["name"]) or "없음"),
          f"- 대상 기관 중 레코드 없음: {len(inst) - len(have & set(inst['institution_id']))}곳"]
    rest = df[(df["vendor_category"] == "restaurant") & (df["vendor_normalized"] != "")]
    top = (rest.groupby("vendor_normalized")
           .agg(visits=("record_id", "size"), total=("amount", "sum"), agencies=("institution_id", "nunique"))
           .sort_values(["visits", "total"], ascending=False).head(50))
    L += ["", "## 상위 방문 음식점 Top 50 (vendor_normalized 기준, 미리보기)", "",
          "같은 이름의 다른 가게(체인·지역)가 합쳐져 있을 수 있다. 찐맛 매칭은 이름+주소로 따로 한다.", "",
          "| # | 상호 | 방문 | 총액(원) | 기관 수 |", "|---:|---|---:|---:|---:|"]
    for k, (v, r) in enumerate(top.iterrows(), 1):
        L.append(f"| {k} | {v} | {r['visits']:,} | {int(r['total'] or 0):,} | {r['agencies']} |")
    return "\n".join(L) + "\n"


def run(cfg: dict) -> dict:
    conn = db.connect(cfg["paths"]["state_db"])
    out = Path(cfg["paths"]["output"])
    out.mkdir(parents=True, exist_ok=True)
    start, end = cfg["period"]["start"], cfg["period"]["end"]
    run_id = db.start_run(conn, "phase5")
    try:
        df, unmapped, unmapped_rows, drop = build(conn, cfg["paths"]["parsed"], start, end)
        df.to_csv(out / "expenses_merged.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([(k, v, unmapped_rows[k]) for k, v in unmapped.most_common()],
                     columns=["column", "tables", "rows"]).to_csv(out / "unmapped_columns.csv", index=False, encoding="utf-8-sig")
        md = report(conn, df, drop, start, end, cfg["parse"]["low_confidence"], out / "foi_candidates.csv")
        (out / "quality_report.md").write_text(md, encoding="utf-8")
        summary = {"records": len(df), "institutions": int(df["institution_id"].nunique()), **drop}
        db.finish_run(conn, run_id, "ok", str(summary))
    except BaseException as e:
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
    print(f"통합 끝: {summary}", flush=True)
    return summary


def to_jjinmat(df: pd.DataFrame, categories: list[str], min_conf: float) -> pd.DataFrame:
    """13절: 음식점·신뢰도 기준 통과분만, 개인 이름·직위·인원 칸 없이."""
    df = df[df["vendor_category"].isin(categories) & (df["parse_confidence"] >= min_conf)
            & (df["vendor_normalized"].fillna("") != "")]
    return pd.DataFrame({
        "restaurant_name": df["vendor_normalized"],
        "address": df["vendor_address"].fillna(""),
        "exec_date": df["exec_date"],
        "agency": df["institution_name"],
        "amount": df["amount"].astype("Int64"),
        "purpose": df["purpose"].fillna("").map(nz.mask_pii),
        "source": df["institution_name"] + " 업무추진비 공개(" + df["source"] + ", " + df["license"] + ")",
        "base_year": df["exec_date"].str[:4],
    }, columns=JJINMAT)


def export_jjinmat(cfg: dict) -> int:
    out = Path(cfg["paths"]["output"])
    df = pd.read_csv(out / "expenses_merged.csv", dtype=str, keep_default_na=False)
    df["parse_confidence"] = pd.to_numeric(df["parse_confidence"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    ex = to_jjinmat(df, cfg["jjinmat_export"]["categories"], cfg["parse"]["low_confidence"])
    path = Path(cfg["jjinmat_export"]["path"])
    path = path if path.is_absolute() else Path(cfg["paths"]["output"]).parent.parent / path
    ex.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"찐맛 export {len(ex):,}행 → {path}", flush=True)
    return len(ex)
