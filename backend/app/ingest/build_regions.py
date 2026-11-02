"""리뷰 지도(I-3) 경계 자산 만들기: SGIS 행정구역 경계 → mobile/assets/regions.json (단순화 SVG 경로).

결정: docs/01 '리뷰 지도'. 지도 단위 = 가게 데이터의 (sido, 시군구) — 일반구는 시로 합침('천안시 동남구' → '천안시').
경계와 가게 데이터의 행정구역 연도가 달라도(시도 통합·구 신설) 이름 대신 **가게 좌표로 연결**:
  1) 경계 시군구마다 안에 든 가게의 지도 단위를 셈 → 한 단위가 대부분이면 그 단위
  2) 여러 단위가 섞이면(구 분리·신설) 그 시군구의 읍면동 경계를 받아 읍면동마다 다수 단위로 배정 후 합침
  3) 가게가 없는 경계는 이름이 같은 단위, 그래도 없으면 보고
북한 윤곽: Natural Earth admin-0(퍼블릭 도메인), 색칠 대상 아님.

실행(개발 PC 1회, 행정구역 바뀌면 다시):
  set SGIS_CONSUMER_KEY / SGIS_CONSUMER_SECRET  (SGIS 개발지원센터 인증키)
  python -m app.ingest.build_regions [--year 2025] [--out ../mobile/assets/regions.json]
도구 의존성: shapely, pyproj (서버 실행에는 불필요).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

SGIS = "https://sgisapi.kostat.go.kr/OpenAPI3"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
DOMINANT = 0.9  # 이 비율 이상이면 한 단위로 봄
SIMPLIFY_M = 250  # 단순화 허용 오차(m)
SCALE_M = 100  # 출력 좌표 1 = 100m


def unit_name(sigungu: str) -> str:
    """일반구는 시로 합침: '천안시 동남구' → '천안시', '수원시장안구' → '수원시'."""
    m = re.match(r"^(\S+?시)\s?\S+구$", sigungu.strip())
    return m.group(1) if m else sigungu.strip()


# --- SGIS ---------------------------------------------------------------
def _get(url: str, **params) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=30) as r:
        body = json.load(r)
    if str(body.get("errCd", "0")) != "0":
        raise RuntimeError(f"SGIS {url.rsplit('/', 1)[-1]}: {body.get('errMsg')}")
    return body


def sgis_token() -> str:
    key, secret = os.environ.get("SGIS_CONSUMER_KEY", ""), os.environ.get("SGIS_CONSUMER_SECRET", "")
    if not key or not secret:
        sys.exit("SGIS_CONSUMER_KEY / SGIS_CONSUMER_SECRET 환경변수가 필요합니다.")
    return _get(f"{SGIS}/auth/authentication.json", consumer_key=key, consumer_secret=secret)["result"]["accessToken"]


def sgis_boundary(token: str, year: int, adm_cd: str | None, low: int) -> list[dict]:
    params = {"accessToken": token, "year": year, "low_search": low}
    if adm_cd:
        params["adm_cd"] = adm_cd
    return _get(f"{SGIS}/boundary/hadmarea.geojson", **params)["features"]


def latest_year(token: str, start: int) -> int:
    for y in range(start, start - 6, -1):
        try:
            if sgis_boundary(token, y, "11", 0):
                return y
        except RuntimeError:
            continue
    sys.exit("SGIS 경계 연도를 찾지 못했습니다.")


# --- 연결 ----------------------------------------------------------------
def load_points(db: Path):
    """열린 가게의 (x, y, 지도 단위 키) — UTM-K(EPSG:5179)."""
    import numpy as np
    from pyproj import Transformer

    rows = sqlite3.connect(db).execute(
        # 세종(시군구 없음)은 시도 자체가 한 단위
        "SELECT lng, lat, sido, COALESCE(sigungu, sido) FROM restaurants WHERE status='open' AND sido IS NOT NULL"
    ).fetchall()
    tr = Transformer.from_crs(4326, 5179, always_xy=True)
    x, y = tr.transform(np.array([r[0] for r in rows]), np.array([r[1] for r in rows]))
    return x, y, np.array([f"{r[2]}|{unit_name(r[3])}" for r in rows], dtype=object)


def counts_in(geom, x, y, keys) -> Counter:
    import shapely

    inside = shapely.contains_xy(geom, x, y)
    return Counter(keys[inside].tolist())


def assign(features: list[dict], x, y, keys, fetch_children) -> tuple[dict[str, list], list[str]]:
    """경계 → {단위 키: [geometry...]}, 보고 문구. fetch_children(adm_cd) → 읍면동 features."""
    from shapely.geometry import shape

    units: dict[str, list] = {}
    report: list[str] = []
    for f in features:
        g = shape(f["geometry"])
        c = counts_in(g, x, y, keys)
        total = sum(c.values())
        name = f["properties"]["adm_nm"]
        if total and c.most_common(1)[0][1] / total >= DOMINANT:
            units.setdefault(c.most_common(1)[0][0], []).append(g)
            continue
        if not total:  # 가게 없음 → 이름으로
            hit = [k for k in set(keys.tolist()) if k.split("|")[1] == unit_name(name.split()[-1])]
            if len(hit) == 1:
                units.setdefault(hit[0], []).append(g)
            else:
                report.append(f"가게 없음·이름 불일치: {name}")
            continue
        # 여러 단위가 섞임 → 읍면동 단위로 배정
        kids = [(shape(k["geometry"]), k) for k in fetch_children(f["properties"]["adm_cd"])]
        local = {k for k, n in c.items() if n / total >= 0.02}
        pending = []
        for kg, _ in kids:
            kc = Counter({k: n for k, n in counts_in(kg, x, y, keys).items() if k in local})
            if kc:
                units.setdefault(kc.most_common(1)[0][0], []).append(kg)
            else:
                pending.append(kg)
        seeded = [(k, u) for k in local for u in list(units.get(k, []))]  # 가게로 배정된 읍면동만 기준
        for kg in pending:  # 가게 없는 읍면동 → 중심이 가장 가까운 배정 읍면동의 단위(맞닿은 것끼리 동률 방지)
            best = min(((kg.centroid.distance(u.centroid), k) for k, u in seeded), default=(0, None))[1]
            if best:
                units[best].append(kg)
        report.append(f"분할 배정: {name} → {sorted(local)}")
    return units, report


# --- 출력 ----------------------------------------------------------------
def to_path(geom, ox: float, oy: float) -> str:
    """폴리곤 → SVG 경로(상대 좌표, 정수, y 뒤집음)."""
    out = []
    polys = getattr(geom, "geoms", [geom])
    for p in polys:
        for ring in [p.exterior]:  # 구멍은 생략(지도 크기에서 안 보임)
            pts = [(round((px - ox) / SCALE_M), round((oy - py) / SCALE_M)) for px, py in ring.coords]
            dedup = [pts[0]] + [b for a, b in zip(pts, pts[1:]) if a != b]
            if len(dedup) < 4:
                continue
            seg = [f"M{dedup[0][0]} {dedup[0][1]}"]
            seg += [f"l{b[0] - a[0]} {b[1] - a[1]}" for a, b in zip(dedup, dedup[1:-1])]
            out.append("".join(seg) + "z")
    return "".join(out)


def bbox(geom, ox, oy) -> list[int]:
    x0, y0, x1, y1 = geom.bounds
    return [round((x0 - ox) / SCALE_M), round((oy - y1) / SCALE_M), round((x1 - x0) / SCALE_M), round((y1 - y0) / SCALE_M)]


def build(units: dict[str, list], north) -> dict:
    from shapely import union_all

    merged = {k: union_all(v).simplify(SIMPLIFY_M, preserve_topology=True) for k, v in units.items()}
    sidos: dict[str, list] = {}
    for k, g in merged.items():
        sidos.setdefault(k.split("|")[0], []).append(g)
    every = union_all(list(merged.values()) + ([north] if north is not None else []))
    x0, y0, x1, y1 = every.bounds
    ox, oy = x0, y1
    return {
        "scale_m": SCALE_M,
        "viewBox": [0, 0, round((x1 - x0) / SCALE_M), round((y1 - y0) / SCALE_M)],
        "north": to_path(north.simplify(SIMPLIFY_M * 4), ox, oy) if north is not None else "",
        "sido": [{"name": s, "bbox": bbox(union_all(gs), ox, oy)} for s, gs in sorted(sidos.items())],
        "units": [{"sido": k.split("|")[0], "name": k.split("|")[1], "d": to_path(g, ox, oy), "bbox": bbox(g, ox, oy)}
                  for k, g in sorted(merged.items())],
    }


def north_korea():
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    with urllib.request.urlopen(NE_URL, timeout=60) as r:
        fc = json.load(r)
    f = next(f for f in fc["features"] if f["properties"].get("ADM0_A3") == "PRK")
    tr = Transformer.from_crs(4326, 5179, always_xy=True)
    return transform(tr.transform, shape(f["geometry"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[2] / "data" / "jjinmat.db"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "mobile" / "assets" / "regions.json"))
    a = ap.parse_args()
    token = sgis_token()
    year = a.year or latest_year(token, date.today().year)
    print(f"[regions] SGIS 경계 {year}년")
    x, y, keys = load_points(Path(a.db))
    sigungu = [f for s in sgis_boundary(token, year, None, 1) for f in sgis_boundary(token, year, s["properties"]["adm_cd"], 1)]
    units, report = assign(sigungu, x, y, keys, lambda cd: sgis_boundary(token, year, cd, 1))
    missing = sorted(set(keys.tolist()) - set(units))
    data = build(units, north_korea())
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[regions] 단위 {len(data['units'])}개, {Path(a.out).stat().st_size // 1024}KB → {a.out}")
    for line in report:
        print("  " + line)
    if missing:
        print(f"  경계를 못 찾은 단위 {len(missing)}개: {missing[:20]}")


if __name__ == "__main__":
    main()
