"""공공 신호 원본 파일 적재: 지정목록(별칭 헤더)·착한가격 메뉴·위생등급·행정처분 (load_designations, load_food_safety)."""
from __future__ import annotations

import csv
import json
import sys
from datetime import date

import pytest

from app import db as appdb
from app.ingest import load_license as ll
from app.ingest import signal_common as sc
from app.ingest.license import COL
from app.ingest.load_designations import check_files as check_designations
from app.ingest.load_designations import load_designations
from app.ingest.load_food_safety import check_files as check_food, is_cancelled, load_food_safety, normalize_grade
from app.service import rebuild_scores

LID1 = "3000000-101-2000-00001"
RESTAURANTS = [
    # id, name, address, lat, lng, sido, sigungu, code, license_id
    ("S1", "할매국밥", "서울특별시 중구 세종대로 110", 37.5665, 126.9780, "서울특별시", "중구", "11140", LID1),
    ("S2", "착한분식", "서울특별시 중구 을지로 100", 37.5660, 126.9900, "서울특별시", "중구", "11140", None),
    ("S3", "청결식당", "부산광역시 해운대구 해운대로 10", 35.1630, 129.1630, "부산광역시", "해운대구", "26350", None),
    ("S4", "다른구식당", "서울특별시 종로구 종로 1", 37.5700, 126.9800, "서울특별시", "종로구", "11110", None),
]
PII_VALUES = ("홍길동", "010-1234-5678", "02-123-4567")


@pytest.fixture
def conn(tmp_path):
    c = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(c)
    c.executemany(
        "INSERT INTO restaurants(id,name,address,lat,lng,sido,sigungu,sigungu_code,license_id,genre,status)"
        " VALUES(?,?,?,?,?,?,?,?,?,'한식','open')", RESTAURANTS)
    c.commit()
    rebuild_scores(c)
    yield c
    c.close()


def write(path, header, rows, enc="cp949", title=None):
    with open(path, "w", encoding=enc, newline="") as f:
        w = csv.writer(f)
        if title:
            w.writerow([title])
        w.writerow(header)
        w.writerows(rows)
    return path


def signals(conn, kind):
    return sorted(tuple(r) for r in conn.execute(
        "SELECT restaurant_id, value, base_date, source FROM restaurant_signals WHERE kind=?", (kind,)))


def unmatched_text(res):
    assert res["unmatched_files"]
    return "".join(p.read_text(encoding="utf-8-sig") for p in res["unmatched_files"])


# --- 지정 목록: 별칭 헤더 · --kind · --source ----------------------------------------
def test_designation_alias_cp949_kind_source(conn, tmp_path):
    src = write(tmp_path / "모범음식점.csv", ["연번", "업소명", "소재지도로명주소", "지정일자", "대표자명", "전화번호"], [
        ["1", "할매국밥", "서울특별시 중구 세종대로 110", "2024.03.05", "홍길동", "02-123-4567"],
        ["2", "없는가게", "서울특별시 중구 없는로 1", "2024-03-05", "홍길동", "010-1234-5678"],
        ["3", "", "서울특별시 중구 세종대로 110", "2024-03-05", "홍길동", ""],
    ], title="모범음식점 지정 현황(가상)")
    out = tmp_path / "out"
    res = load_designations(conn, src, out, kind="model_restaurant", source="모범음식점(테스트)")
    assert res["total"] == 3 and res["matched"] == 1 and res["inserted"] == 1
    assert res["by_method"]["name+address"] == 1
    assert res["unmatched_reasons"]["상호 불일치"] == 1 and res["unmatched_reasons"][sc.REASON_MISSING] == 1
    assert signals(conn, "model_restaurant") == [("S1", "지정", "2024-03-05", "모범음식점(테스트)")]
    assert res["regions"] == {"11140"}
    text = unmatched_text(res)
    assert all(v not in text for v in PII_VALUES)
    with open(res["unmatched_files"][0], encoding="utf-8-sig") as f:
        assert tuple(csv.DictReader(f).fieldnames) == sc.UNMATCHED_COLUMNS
    assert {"대표자명", "전화번호"} <= {h.split(":")[1] for h in res["pii_dropped"]}


def test_designation_requires_kind_and_valid_kind(conn, tmp_path):
    src = write(tmp_path / "a.csv", ["상호명", "주소"], [["할매국밥", "서울특별시 중구 세종대로 110"]])
    with pytest.raises(ValueError, match="--kind"):
        load_designations(conn, src, tmp_path / "out")
    with pytest.raises(ValueError):
        load_designations(conn, src, tmp_path / "out", kind="hygiene_grade")  # LIST_KINDS 아님


def test_base_date_default_and_korean_kind_label(conn, tmp_path):
    src = write(tmp_path / "b.csv", ["가게명", "도로명주소", "지정구분"], [
        ["할매국밥", "서울특별시 중구 세종대로 110", "안심식당"],
    ], enc="utf-8")
    res = load_designations(conn, src, tmp_path / "out", base_date="2025-01-02")
    assert res["inserted"] == 1
    assert signals(conn, "safe_restaurant") == [("S1", "지정", "2025-01-02", "안심식당")]


def test_xlsx_not_supported(conn, tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_bytes(b"PK\x03\x04dummy")
    with pytest.raises(ValueError, match="CSV"):
        load_designations(conn, p, tmp_path / "out", kind="model_restaurant")
    fake = tmp_path / "fake.csv"
    fake.write_bytes(b"PK\x03\x04dummy")
    assert "CSV" in check_designations([fake])[0]["error"]


# --- 착한가격업소 메뉴 upsert ----------------------------------------------------------
def test_good_price_menus_upsert(conn, tmp_path):
    conn.execute("INSERT INTO menus(restaurant_id,name,price,is_signature,source) VALUES('S2','김 밥',3000,0,'tourapi')")
    conn.commit()
    header = ["업소명", "도로명주소", "위도", "경도", "대표메뉴1", "가격1", "대표메뉴2", "가격2", "전화번호"]
    src = write(tmp_path / "gp.csv", header, [
        ["착한분식", "서울특별시 중구 을지로 100", "37.5660", "126.9900", "떡볶이", "4,000원", "김밥", "2500", "02-123-4567"],
    ])
    res = load_designations(conn, src, tmp_path / "out", kind="good_price", source="착한가격업소(테스트)")
    assert res["inserted"] == 1 and res["menus"] == 2
    rows = sorted(tuple(r) for r in conn.execute(
        "SELECT name, price, is_signature, source FROM menus WHERE restaurant_id='S2'"))
    # 같은 이름(공백 무시) 다른 출처 메뉴는 중복 생성 없이 대표메뉴 표시만, 가격 유지
    assert rows == [("김 밥", 3000, 1, "tourapi"), ("떡볶이", 4000, 1, "good_price")]
    # 재적재 + 가격 변경 → 중복 없이 갱신
    write(src, header, [["착한분식", "서울특별시 중구 을지로 100", "", "", "떡볶이", "4500", "", "", ""]])
    again = load_designations(conn, src, tmp_path / "out", kind="good_price", source="착한가격업소(테스트)")
    assert again["inserted"] == 0 and again["duplicate"] == 1
    assert tuple(conn.execute("SELECT COUNT(*), MAX(price) FROM menus WHERE restaurant_id='S2' AND name='떡볶이'").fetchone()) == (1, 4500)


def test_designation_main_dish_menus(conn, tmp_path):
    header = ["업소명", "도로명주소", "위도", "경도", "주된음식"]
    src = write(tmp_path / "mr.csv", header, [
        ["착한분식", "서울특별시 중구 을지로 100", "37.5660", "126.9900", "돼지갈비, 삼겹살/돼지갈비"],
    ])
    res = load_designations(conn, src, tmp_path / "out", kind="model_restaurant", source="모범음식점(테스트)")
    assert res["inserted"] == 1 and res["menus"] == 2
    rows = sorted(tuple(r) for r in conn.execute(
        "SELECT name, price, is_signature, source FROM menus WHERE restaurant_id='S2'"))
    assert rows == [("돼지갈비", None, 1, "model_restaurant"), ("삼겹살", None, 1, "model_restaurant")]
    load_designations(conn, src, tmp_path / "out", kind="model_restaurant", source="모범음식점(테스트)")
    assert conn.execute("SELECT COUNT(*) FROM menus WHERE restaurant_id='S2'").fetchone()[0] == 2  # 재적재 멱등


# --- 위생등급 ------------------------------------------------------------------------
@pytest.mark.parametrize("raw,want", [
    ("매우우수", "매우우수"), ("매우 우수(★★★)", "매우우수"), ("★★★", "매우우수"), ("★3", "매우우수"),
    ("별3개", "매우우수"), ("3단계", "매우우수"), ("3", "매우우수"), ("우수(★★)", "우수"), ("★★", "우수"),
    ("2", "우수"), ("좋음", "좋음"), ("★", "좋음"), ("AAA", "매우우수"), ("기타", None), ("", None), ("1등급", None),
])
def test_normalize_grade(raw, want):
    assert normalize_grade(raw) == want


def test_cancel_detection():
    assert is_cancelled({"cancel_flag": "Y"}) and is_cancelled({"cancel_flag": "지정취소"})
    assert is_cancelled({"cancel_date": "2025-01-01"})
    assert not is_cancelled({"cancel_flag": "N"}) and not is_cancelled({"cancel_flag": "지정"}) and not is_cancelled({})


def test_hygiene_alias_cp949_cancel_excluded(conn, tmp_path):
    src = write(tmp_path / "위생등급.csv", ["업소명", "소재지", "지정등급", "지정일", "지정취소여부", "대표자명"], [
        ["할매국밥", "서울특별시 중구 세종대로 110", "★★★", "20240101", "N", "홍길동"],
        ["청결식당", "부산광역시 해운대구 해운대로 10", "우수(★★)", "2024-02-01", "", "홍길동"],
        ["착한분식", "서울특별시 중구 을지로 100", "매우우수", "2024-02-01", "Y", "홍길동"],
        ["다른구식당", "서울특별시 종로구 종로 1", "기타", "2024-02-01", "", "홍길동"],
    ])
    out = tmp_path / "out"
    res = load_food_safety(conn, src, "hygiene", out)
    assert res["total"] == 4 and res["excluded"] == 1 and res["matched"] == 2 and res["inserted"] == 2
    assert res["unmatched_reasons"]["등급 불명"] == 1
    assert [(r[0], r[1], r[2]) for r in signals(conn, "hygiene_grade")] == [
        ("S1", "매우우수", "2024-01-01"), ("S3", "우수", "2024-02-01")]
    assert res["regions"] == {"11140", "26350"}
    comp = json.loads(conn.execute("SELECT components FROM scores WHERE restaurant_id='S1'").fetchone()[0])
    assert comp["hygiene"] == 0.15
    assert all(v not in unmatched_text(res) for v in PII_VALUES)
    assert (out / "unmatched_food_safety_hygiene.csv").exists()


# --- 행정처분 ------------------------------------------------------------------------
SANCTION_HEADER = ["인허가번호", "업소명", "소재지", "처분확정일자", "처분내용", "위반내용", "대표자명", "소재지전화"]


def test_sanction_license_first_and_three_year_boundary(conn, tmp_path):
    today = date(2026, 5, 10)
    rows = [
        # 인허가번호 일치(표기 차이·상호 다름) → license_id 매칭
        [LID1.replace("-", ""), "할매국밥 본점(구상호)", "서울 중구 어딘가 1", "2023-05-10", "영업정지 7일", "위생기준 위반", "홍길동", "02-123-4567"],
        [LID1, "할매국밥", "", "20230509", "시정명령", "", "홍길동", ""],          # 3년 + 1일 전 → 감점 제외
        ["", "착한분식", "서울특별시 중구 을지로 100", "2026-01-01", "과태료 10만원", "", "홍길동", ""],
        ["", "착한분식", "서울특별시 중구 을지로 100", "2025-06-01", "시정명령", "", "", ""],
        ["", "착한분식", "서울특별시 중구 을지로 100", "2025-06-01", "영업정지 3일", "", "", ""],  # 같은 날 다른 처분
        ["", "착한분식", "서울특별시 중구 을지로 100", "2024-01-01", "과징금", "", "", ""],
        ["", "착한분식", "서울특별시 중구 을지로 100", "", "과징금", "", "", ""],  # 처분일자 없음
        ["9999999-000", "모르는집", "서울특별시 중구 없는로 1", "2025-01-01", "과태료", "", "홍길동", "010-1234-5678"],
    ]
    src = write(tmp_path / "행정처분.csv", SANCTION_HEADER, rows)
    out = tmp_path / "out"
    res = load_food_safety(conn, src, "sanction", out, today=today)
    assert res["matched"] == 6 and res["inserted"] == 6
    assert res["by_method"] == {"license_id": 2, "name+address": 4}
    assert res["unmatched_reasons"]["처분일자 없음"] == 1 and res["unmatched_reasons"]["상호 불일치"] == 1
    got = {(r[0], r[2]) for r in signals(conn, "sanction")}
    assert ("S1", "2023-05-10") in got and ("S1", "2023-05-09") in got
    detail = conn.execute("SELECT detail FROM restaurant_signals WHERE kind='sanction' AND base_date='2023-05-10'").fetchone()[0]
    assert "영업정지 7일" in detail and "위생기준 위반" in detail and "홍길동" not in detail
    comp = {r[0]: json.loads(r[1]) for r in conn.execute("SELECT restaurant_id, components FROM scores")}
    assert comp["S1"]["sanction"] == -0.05   # 정확히 3년 전 당일 포함, 3년+1일 전 제외
    assert comp["S2"]["sanction"] == -0.15   # 4건 → 상한 0.15
    assert comp["S3"]["sanction"] == 0
    text = unmatched_text(res)
    assert all(v not in text for v in PII_VALUES)


def test_dry_run_unchanged_and_idempotent(conn, tmp_path):
    src = write(tmp_path / "s.csv", SANCTION_HEADER, [
        ["", "착한분식", "서울특별시 중구 을지로 100", "2026-01-01", "과태료", "", "홍길동", ""]])
    before_scores = conn.execute("SELECT restaurant_id, computed_at FROM scores ORDER BY 1").fetchall()
    dry = load_food_safety(conn, src, "sanction", tmp_path / "out", dry_run=True)
    assert dry["dry_run"] and dry["inserted"] == 1
    assert conn.execute("SELECT COUNT(*) FROM restaurant_signals").fetchone()[0] == 0
    assert conn.execute("SELECT restaurant_id, computed_at FROM scores ORDER BY 1").fetchall() == before_scores
    gp = write(tmp_path / "gp.csv", ["업소명", "도로명주소", "대표메뉴", "가격"],
               [["착한분식", "서울특별시 중구 을지로 100", "라면", "3000"]])
    load_designations(conn, gp, tmp_path / "out", kind="good_price", dry_run=True)
    assert conn.execute("SELECT COUNT(*) FROM menus").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM restaurant_signals").fetchone()[0] == 0
    # 실제 적재 → 영향 지역(중구)만 재계산, 다른 구(종로) 점수 행은 그대로
    first = load_food_safety(conn, src, "sanction", tmp_path / "out")
    assert first["inserted"] == 1 and first["regions"] == {"11140"}
    after = dict(conn.execute("SELECT restaurant_id, computed_at FROM scores").fetchall())
    assert after["S4"] == dict(before_scores)["S4"] and after["S2"] != dict(before_scores)["S2"]
    again = load_food_safety(conn, src, "sanction", tmp_path / "out")
    assert again["inserted"] == 0 and again["duplicate"] == 1
    assert conn.execute("SELECT COUNT(*) FROM restaurant_signals").fetchone()[0] == 1
    # 미매칭 0건 → 지난 미매칭 파일 없음
    assert not (tmp_path / "out" / "unmatched_food_safety_sanction.csv").exists()


def test_designation_license_id_match(conn, tmp_path):
    src = write(tmp_path / "c.csv", ["관리번호", "업소명", "주소"], [[LID1, "할매국밥(구)", ""]])
    res = load_designations(conn, src, tmp_path / "out", kind="century_store", source="백년가게")
    assert res["by_method"] == {"license_id": 1} and signals(conn, "century_store")[0][0] == "S1"


# --- --check (DB 불필요) -------------------------------------------------------------
def test_check_files_food_and_designations(tmp_path):
    h = write(tmp_path / "h.csv", ["업소명", "소재지", "위생등급", "지정일자", "지정취소일자", "대표자명", "전화번호"], [
        ["가", "서울특별시 중구 세종대로 110", "★★★", "2024-01-01", "", "홍길동", "02-1"],
        ["나", "부산광역시 해운대구 해운대로 10", "좋음", "2024-01-01", "2025-01-01", "홍길동", "02-1"],
        ["다", "서울 종로구 종로 1", "이상값", "2024-01-01", "", "홍길동", "02-1"],
    ])
    info = check_food([h], "hygiene")[0]
    assert info["encoding"] == "cp949" and info["rows"] == 3 and not info["missing_fields"]
    assert dict(info["sido"]) == {"서울": 2, "부산": 1}
    assert set(info["pii"]) == {"대표자명", "전화번호"}
    assert info["dists"]["등급 분포(정규화)"] == {"매우우수": 1}
    assert info["colmap"]["grade"] == "위생등급" and "phone" not in info["colmap"]
    s = write(tmp_path / "s.csv", SANCTION_HEADER, [["1", "가", "서울 중구 세종대로 1", "2024-01-01", "과태료", "", "", ""]],
              enc="utf-8")
    si = check_food([s], "sanction")[0]
    assert si["encoding"] == "utf-8-sig" and si["license_rows"] == 1 and "처분일자 범위" in si["dists"]
    d = write(tmp_path / "d.csv", ["사업장명", "지번주소"], [["가", "서울특별시 중구 태평로1가 31"]])
    di = check_designations([d])[0]
    assert "[err] kind" in di["dists"]
    sc.print_check(di, "x")  # 출력 오류 없음


def test_cli_check_runs_without_db(tmp_path, monkeypatch, capsys):
    from app.ingest import load_food_safety as lfs
    h = write(tmp_path / "h.csv", ["상호", "주소", "등급"], [["가", "서울특별시 중구 세종대로 110", "우수"]])
    monkeypatch.setenv("JJINMAT_DB", str(tmp_path / "nope" / "x.db"))
    monkeypatch.setattr(sys, "argv", ["x", str(h), "--type", "hygiene", "--check"])
    lfs.main()
    outp = capsys.readouterr().out
    assert "인코딩 cp949" in outp and "등급 분포" in outp and "서울 1" in outp
    assert not (tmp_path / "nope").exists()


# --- 인허가 --check 추가 열 분포 --------------------------------------------------------
def test_license_check_extra_columns(tmp_path, capsys):
    header = [*COL.values(), "등급구분명", "전통업소지정번호", "전통업소주된음식"]
    base = {h: "" for h in header}
    rows = []
    for i, (grade, no, food) in enumerate([("모범", "", ""), ("모범", "T-1", "비빔밥"), ("", "T-2", "비빔밥")]):
        rows.append({**base, COL["license_id"]: f"L{i}", COL["opened_at"]: "20000101", COL["status"]: "영업/정상",
                     COL["name"]: f"가게{i}", COL["biz_type"]: "한식", "등급구분명": grade, "전통업소지정번호": no,
                     "전통업소주된음식": food})
    p = tmp_path / "lic.csv"
    with open(p, "w", encoding="cp949", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    info = ll.check_files([p], license_type="일반음식점")[0]
    assert info["grade_type_top"] == [("모범", 2), ("(빈 값)", 1)]
    assert info["traditional_no_rows"] == 2 and info["traditional_food_top"] == [("비빔밥", 2)]
    ll._print_check([info])
    assert "추가 열 분포" in capsys.readouterr().out


def test_city_match_for_list_without_address(conn, tmp_path):
    """주소·좌표 없는 목록(경기 모범음식점): 같은 시도·시군 영업 중 후보 정확히 1곳일 때만 매칭."""
    conn.executemany(
        "INSERT INTO restaurants(id,name,address,lat,lng,sido,sigungu,sigungu_code,genre,status)"
        " VALUES(?,?,?,?,?,'경기도',?,?,'한식',?)", [
            ("G1", "늘봄", "경기도 가평군 가평읍 문화로 1", 37.83, 127.51, "가평군", "41820", "open"),
            ("G2", "두집", "경기도 고양시 덕양구 원당로 1", 37.65, 126.83, "고양시", "41281", "open"),
            ("G3", "두집", "경기도 고양시 일산동구 중앙로 1", 37.66, 126.77, "고양시", "41285", "open"),
            ("G4", "닫힌집", "경기도 가평군 가평읍 문화로 2", 37.83, 127.51, "가평군", "41820", "closed"),
        ])
    conn.commit()
    p = write(tmp_path / "g.csv", ["집계년도", "시군명", "업소명", "전화번호", "소재지도로명주소"], [
        ["2026", "가평군", "늘   봄", "031-000-0000", ""],   # 유일 → 매칭
        ["2026", "고양시", "두집", "", ""],                 # 같은 시군 2곳 → 미매칭
        ["2026", "가평군", "닫힌집", "", ""],               # 영업 중 아님 → 미매칭
        ["2026", "고양시", "늘봄", "", ""],                 # 다른 시군 → 미매칭
    ])
    res = load_designations(conn, p, tmp_path / "out", kind="model_restaurant", source="경기도 모범음식점",
                            sido="경기")
    assert res["by_method"] == {"name+city": 1}
    assert [r[0] for r in signals(conn, "model_restaurant")] == ["G1"]
    # 시도를 모르면 시군만으로는 매칭하지 않음(고성군 등 시도 간 동명 시군)
    res = load_designations(conn, p, tmp_path / "out2", kind="model_restaurant", source="x", dry_run=True)
    assert res["matched"] == 0


def test_city_match_skips_franchise_names(conn):
    for i in range(sc.CITY_MAX_CANDS):
        conn.execute("INSERT INTO restaurants(id,name,address,lat,lng,genre,status) VALUES(?,?,?,?,?,'한식','open')",
                     (f"F{i}", "체인국밥", f"경기도 수원시 팔달구 정조로 {i + 1}" if i == 0 else f"부산광역시 중구 중앙대로 {i}",
                      35.1, 129.0))
    conn.commit()
    rid, _, reason = sc.SignalMatcher(conn).match_city("체인국밥", "경기", "수원시")
    assert rid is None and "프랜차이즈" in reason


def test_gyeonggi_best_is_guide_kind():
    from app.scoring import prior
    assert prior.GUIDE_SCORES["gyeonggi_best"] == 0.7
    assert prior.reputation_score(["gyeonggi_best"], None) == 0.7
    assert prior.designation_score(["gyeonggi_best"]) == 0.0


def test_wgs84_coordinate_headers():
    cm = sc.resolve(["음식점명", "WGS84위도", "WGS84경도"], sc.COMMON_ALIASES)
    assert cm["lat"] == "WGS84위도" and cm["lng"] == "WGS84경도"
