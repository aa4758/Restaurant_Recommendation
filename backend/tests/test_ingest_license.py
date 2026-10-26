import csv
import sqlite3

import pytest
from pyproj import Transformer

from app.db import connect, init_schema
from app.ingest import load_license as ll
from app.ingest.license import (
    COL,
    DEFAULT_CRS,
    LicenseCSVAdapter,
    is_excluded,
    map_genre,
    parse_date,
    parse_status,
    tm_to_wgs84,
)
from app.scoring import prior
from app.scoring.recommend import haversine_m

HEADER = [*COL.values(), "대표자명"]  # 대표자명 = PII → 읽지 않고 폐기되어야 함
CITY_HALL = (37.5665, 126.9780)


def tm(lat, lng, crs=DEFAULT_CRS):
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lng, lat)
    return round(x, 3), round(y, 3)


def row(lid, typ, name, biz, opened, status="영업/정상", closed="", road="", jibun="", xy=("", ""),
        phone="", area="", updated="2024-01-01 00:00:00"):
    return {
        COL["license_id"]: lid, COL["license_type"]: typ, COL["opened_at"]: opened, COL["status"]: status,
        COL["status_detail"]: "폐업" if status == "폐업" else "영업", COL["closed_at"]: closed,
        COL["phone"]: phone, COL["area"]: area, COL["address_jibun"]: jibun, COL["address_road"]: road,
        COL["name"]: name, COL["biz_type"]: biz, COL["x"]: xy[0], COL["y"]: xy[1],
        COL["data_updated"]: updated, "대표자명": "홍길동",
    }


def write_csv(path, rows, enc="cp949"):
    with open(path, "w", encoding=enc, newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    return path


RESTAURANTS = [
    # id, name, address, lat, lng, alcohol, phone
    ("S1", "할매국밥", "서울특별시 중구 세종대로 110", 37.5665, 126.9780, None, None),
    ("S2", "동네호프", "서울특별시 중구 을지로 100", 37.5660, 126.9900, 1, "02-111-1111"),
    ("S3", "분식왕", "서울특별시 중구 명동길 10", 37.5630, 126.9850, 1, None),
    ("S4", "재개업식당", "서울특별시 중구 퇴계로 20", 37.5600, 126.9800, None, None),
    ("S5", "폐업식당", "서울특별시 중구 삼일대로 30", 37.5650, 126.9880, None, None),
    ("S6", "쌍둥이식당", "서울특별시 중구 충무로 5", 37.5610, 126.9920, None, None),
    ("S7", "쌍둥이식당", "서울특별시 중구 충무로 5", 37.5611, 126.9921, None, None),
]


def make_db(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    conn.executemany(
        "INSERT INTO restaurants(id,name,genre,lat,lng,address,sido,sigungu,sigungu_code,alcohol,phone)"
        " VALUES(?,?,'한식',?,?,?,'서울특별시','중구','11140',?,?)",
        [(i, n, la, lo, a, al, ph) for i, n, a, la, lo, al, ph in RESTAURANTS],
    )
    conn.commit()
    return conn


def fixture_rows(crs=DEFAULT_CRS):
    p = {r[0]: tm(r[3], r[4], crs) for r in RESTAURANTS}
    return [
        row("A1", "일반음식점", "할매국밥", "한식", "19950301", road="서울특별시 중구 세종대로 110 (태평로1가)",
            xy=p["S1"], phone="02-222-2222", area="85.5"),
        row("A2", "일반음식점", "동네호프", "호프/통닭", "2010-05-01", road="서울특별시 중구 을지로 100", xy=p["S2"],
            phone="02-999-9999"),
        row("A3", "휴게음식점", "분식왕", "분식", "20180101", road="서울특별시 중구 명동길 10", xy=p["S3"]),
        # 재개업: 폐업 행의 인허가일자가 더 최신이어도 영업 중 행 우선
        row("A4", "일반음식점", "재개업식당", "한식", "20150101", road="서울특별시 중구 퇴계로 20", xy=p["S4"]),
        row("A5", "일반음식점", "재개업식당", "한식", "20210101", status="폐업", closed="20220101",
            road="서울특별시 중구 퇴계로 20", xy=p["S4"]),
        row("A6", "일반음식점", "폐업식당", "한식", "20000101", status="폐업", closed="2023-06-30",
            road="서울특별시 중구 삼일대로 30", xy=p["S5"]),
        row("A7", "일반음식점", "쌍둥이식당", "한식", "20000101", road="서울특별시 중구 충무로 5", xy=p["S6"]),
        row("A8", "일반음식점", "신규한식", "한식", "20190101", road="서울특별시 중구 남대문로 50",
            xy=tm(37.5640, 126.9770, crs), area="40"),
        row("A9", "일반음식점", "좌표없는집", "중국식", "20190101", road="서울특별시 중구 남대문로 60", xy=("0", "0")),
        row("A10", "일반음식점", "망한집", "한식", "20000101", status="폐업", closed="20100101",
            road="서울특별시 중구 남대문로 70", xy=tm(37.5641, 126.9771, crs)),
        row("A11", "휴게음식점", "별다방", "커피숍", "20190101", road="서울특별시 중구 남대문로 80",
            xy=tm(37.5642, 126.9772, crs)),
        row("A12", "휴게음식점", "신규분식", "분식", "20200101", road="서울특별시 중구 남대문로 90",
            xy=tm(37.5643, 126.9773, crs)),
    ]


def test_dates_status_and_genre():
    assert parse_date("20010305") == parse_date("2001-03-05") == "2001-03-05"
    assert parse_date("2001-03-05 10:00:00") == "2001-03-05" and parse_date("") is None
    assert parse_status("폐업", "폐업") == "closed" and parse_status("영업/정상", "영업") == "open"
    assert parse_status("휴업", "휴업") == "open" and parse_status("취소/말소/만료/정지/중지") == "closed"
    for b in ("커피숍", "까페", "다방", "제과점영업", "아이스크림", "떡카페", "전통찻집"):
        assert is_excluded(b)
    assert not is_excluded("라이브카페") and not is_excluded("한식")
    cases = {"한식": "한식", "중국식": "중식", "일식": "일식", "경양식": "양식", "분식": "분식", "횟집": "해산물",
             "식육(숯불구이)": "고기/구이", "외국음식전문점(인도,태국등)": "아시안", "통닭(치킨)": "치킨",
             "정종/대포집/소주방": "주점", "뷔페식": "기타", "": "기타", None: "기타"}
    for b, g in cases.items():
        assert map_genre(b) == g, b
    assert map_genre("호프/통닭", "동네호프") == "주점"
    assert map_genre("호프/통닭", "바삭치킨") == "치킨"


def test_crs_conversion_city_hall():
    # 서울시청 근처 중부원점 TM(EPSG:5174) 좌표 ≈ (197987, 451580)
    lat, lng = tm_to_wgs84(197986.75, 451579.85, "EPSG:5174")
    assert abs(lat - CITY_HALL[0]) < 1e-5 and abs(lng - CITY_HALL[1]) < 1e-5
    # pyproj 역변환으로 검증(왕복 오차 1m 미만)
    x, y = tm(*CITY_HALL, "EPSG:2097")
    lat2, lng2 = tm_to_wgs84(x, y, "EPSG:2097")
    assert haversine_m(lat2, lng2, *CITY_HALL) < 1.0
    # 같은 TM 값을 다른 CRS 로 해석하면 수백 m 어긋남 → calibrate 필요성
    a, b = tm_to_wgs84(x, y, "EPSG:5174"), (lat2, lng2)
    assert 100 < haversine_m(*a, *b) < 500
    assert tm_to_wgs84(0, 0) is None and tm_to_wgs84(None, None) is None
    assert tm_to_wgs84(5e6, 5e6) is None  # 국내 범위 밖


def test_adapter_cp949_utf8_and_pii(tmp_path):
    for enc in ("cp949", "utf-8-sig"):
        p = write_csv(tmp_path / f"l_{enc}.csv", fixture_rows(), enc)
        ad = LicenseCSVAdapter(p)
        recs = {r["license_id"]: r for r in ad.fetch()}
        assert ad.pii_dropped == ["대표자명"] and ad.missing_columns == []
        assert all("홍길동" not in str(v) for r in recs.values() for v in r.values())
        a1 = recs["A1"]
        assert a1["name"] == "할매국밥" and a1["opened_at"] == "1995-03-01" and a1["area_m2"] == 85.5
        assert haversine_m(a1["lat"], a1["lng"], 37.5665, 126.9780) < 1.0
        assert recs["A6"]["status"] == "closed" and recs["A6"]["closed_at"] == "2023-06-30"
        assert recs["A9"]["lat"] is None


def test_calibrate_picks_true_crs(tmp_path):
    conn = make_db(tmp_path)
    for true_crs in ("EPSG:2097", "EPSG:5174"):
        p = write_csv(tmp_path / "c.csv", fixture_rows(true_crs))
        recs, _ = ll.read_records([p])
        res = ll.calibrate(conn, recs)
        assert res["best"] == true_crs
        assert res["n"] == 6  # 쌍둥이(복수)·신규·커피숍 제외, 상호+도로명 단일 매칭만
        assert res["medians"][true_crs] < 1.0
        assert max(res["medians"].values()) > 100


def test_load_license(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    calls = []
    monkeypatch.setattr(ll, "rebuild_scores", lambda c, reg: calls.append(reg))
    p = write_csv(tmp_path / "l.csv", fixture_rows())
    out = tmp_path / "out"
    res = ll.load_license(conn, [p], out_dir=out)
    q = lambda sql, *a: tuple(conn.execute(sql, a).fetchone())  # noqa: E731

    assert res["excluded"] == 1 and res["new"] == 2 and res["unmatched"] == 2 and res["ignored_closed"] == 1
    assert res["matched"] == 6 and res["updated"] == 5 and res["closed_applied"] == 1
    # 매칭 갱신: 업력·인허가·면적, 전화는 비어 있을 때만
    r = q("SELECT license_id, opened_at, license_type, area_m2, phone, status FROM restaurants WHERE id='S1'")
    assert tuple(r) == ("A1", "1995-03-01", "일반음식점", 85.5, "02-222-2222", "open")
    assert q("SELECT phone, alcohol FROM restaurants WHERE id='S2'") == ("02-111-1111", 1)  # 일반 → 기존값 유지
    assert q("SELECT alcohol, license_type FROM restaurants WHERE id='S3'") == (0, "휴게음식점")
    # 재개업: 영업 중 행 우선, 폐업 행이 덮지 않음
    assert tuple(q("SELECT license_id, status, closed_at, opened_at FROM restaurants WHERE id='S4'")) == (
        "A4", "open", None, "2015-01-01")
    assert tuple(q("SELECT status, closed_at FROM restaurants WHERE id='S5'")) == ("closed", "2023-06-30")
    # 신규: 영업 중 + 좌표 있음만, 시군구코드는 기존 (시도, 시군구) 매핑
    new = conn.execute("SELECT id, genre, sigungu_code, alcohol, sigungu, opened_at FROM restaurants"
                       " WHERE id LIKE 'L%' ORDER BY id").fetchall()
    assert [tuple(x) for x in new] == [("LA12", "분식", "11140", 0, "중구", "2020-01-01"),
                                       ("LA8", "한식", "11140", None, "중구", "2019-01-01")]
    assert q("SELECT COUNT(*) FROM restaurants WHERE name IN ('망한집','별다방','좌표없는집')")[0] == 0
    # 재계산: 영향받은 시군구
    assert set(calls) == {"11140"}
    # 미매칭 파일: 화이트리스트 컬럼만, PII 없음
    text = (out / ll.UNMATCHED_FILE).read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    assert tuple(rows[0]) == ll.UNMATCHED_COLUMNS
    assert {x["license_id"]: x["reason"].split("·")[0] for x in rows} == {"A7": "ambiguous", "A9": "좌표 없음"}
    assert "홍길동" not in text and "대표자" not in text and "02-" not in text

    # 멱등 재적재: 행 수·값 동일, 신규 생성 없음
    snap = conn.execute("SELECT * FROM restaurants ORDER BY id").fetchall()
    res2 = ll.load_license(conn, [p], out_dir=out)
    assert res2["new"] == 0 and res2["closed_applied"] == 0 and res2["matched"] == 8
    snap2 = conn.execute("SELECT * FROM restaurants ORDER BY id").fetchall()
    strip = lambda rs: [tuple(v for k, v in zip(r.keys(), r) if k != "updated_at") for r in rs]  # noqa: E731
    assert strip(snap) == strip(snap2)
    assert q("SELECT COUNT(*) FROM restaurants")[0] == len(RESTAURANTS) + 2


def test_dry_run_and_real_rebuild(tmp_path):
    conn = make_db(tmp_path)
    p = write_csv(tmp_path / "l.csv", fixture_rows())
    res = ll.load_license(conn, [p], out_dir=tmp_path / "out", dry_run=True)
    assert res["new"] == 2
    assert conn.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0] == len(RESTAURANTS)
    assert conn.execute("SELECT license_id FROM restaurants WHERE id='S1'").fetchone()[0] is None
    ll.load_license(conn, [p], out_dir=tmp_path / "out")
    ids = {r[0] for r in conn.execute("SELECT restaurant_id FROM scores")}
    assert "S5" not in ids and {"S1", "LA8", "LA12"} <= ids  # 폐업 제외, 신규 포함


def test_tenure_uses_opened_at():
    from datetime import date

    assert prior.tenure_years("1995-03-01", date(2025, 3, 1)) == pytest.approx(30.0, abs=0.01)


def test_cli_calibrate(tmp_path, monkeypatch, capsys):
    db = tmp_path / "t.db"
    make_db(tmp_path).close()
    p = write_csv(tmp_path / "l.csv", fixture_rows("EPSG:2097"))
    monkeypatch.setattr("sys.argv", ["load_license", str(p), "--db", str(db), "--calibrate"])
    ll.main()
    out = capsys.readouterr().out
    assert "권장 --crs EPSG:2097" in out
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM restaurants WHERE license_id IS NOT NULL").fetchone()[0] == 0
