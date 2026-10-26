"""QA: 공공 신호 적재(load_designations · load_food_safety · signal_common) 경계·결함 검증.

확인된 결함은 xfail(strict=True) — 고쳐지면 XPASS 로 실패해 표시가 갱신되도록.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import date

import pytest

from app import db as appdb
from app.ingest import license as lic
from app.ingest import signal_common as sc
from app.ingest.load_designations import load_designations, parse_price
from app.ingest.load_food_safety import is_cancelled, load_food_safety, normalize_grade
from app.ingest.sbiz import detect_encoding
from app.service import rebuild_scores

LID1 = "3000000-101-2000-00001"
LID_OLD = "3000000-101-1990-00009"
RESTAURANTS = [
    # id, name, branch, address, lat, lng, sigungu, code, license_id, status
    ("S1", "할매국밥", None, "서울특별시 중구 세종대로 110", 37.5665, 126.9780, "중구", "11140", LID1, "open"),
    ("S5", "할매국밥", None, "서울특별시 중구 세종대로 110", 37.5665, 126.9780, "중구", "11140", LID_OLD, "closed"),
    ("S2", "착한분식", None, "서울특별시 중구 을지로 100", 37.5660, 126.9900, "중구", "11140", None, "open"),
    ("S4", "할매국밥", None, "서울특별시 종로구 종로 1", 37.5700, 126.9800, "종로구", "11110", None, "open"),
    ("F1", "김밥천국", "시청점", "서울특별시 중구 세종대로 120", 37.5670, 126.9775, "중구", "11140", None, "open"),
    ("F2", "김밥천국", "을지로점", "서울특별시 중구 을지로 120", 37.5662, 126.9920, "중구", "11140", None, "open"),
]


@pytest.fixture
def conn(tmp_path):
    c = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(c)
    c.executemany(
        "INSERT INTO restaurants(id,name,branch,address,lat,lng,sido,sigungu,sigungu_code,license_id,genre,status)"
        " VALUES(?,?,?,?,?,?,'서울특별시',?,?,?,'한식',?)", RESTAURANTS)
    c.commit()
    rebuild_scores(c)
    yield c
    c.close()


def write(path, header, rows, enc="cp949", title=None):
    with open(path, "w", encoding=enc, newline="") as f:
        w = csv.writer(f)
        for t in ([title] if isinstance(title, str) else (title or [])):
            w.writerow([t])
        w.writerow(header)
        w.writerows(rows)
    return path


def sig(conn, kind):
    return sorted(tuple(r) for r in conn.execute(
        "SELECT restaurant_id, value, base_date FROM restaurant_signals WHERE kind=?", (kind,)))


def comp(conn, rid):
    row = conn.execute("SELECT components FROM scores WHERE restaurant_id=?", (rid,)).fetchone()
    return json.loads(row[0]) if row else None


# --- 인허가번호 우선 매칭 -------------------------------------------------------------
@pytest.mark.parametrize("raw", [LID1, LID1.replace("-", ""), " 3000000 101 2000 00001 ", "3000000-1012000-00001"])
def test_license_key_normalization(conn, tmp_path, raw):
    src = write(tmp_path / "a.csv", ["인허가번호", "업소명", "주소"], [[raw, "전혀다른상호", ""]])
    res = load_designations(conn, src, tmp_path / "out", kind="model_restaurant")
    assert res["by_method"] == {"license_id": 1}
    assert sig(conn, "model_restaurant")[0][0] == "S1"


def test_license_exact_match_hits_closed_store_not_open_namesake(conn, tmp_path):
    """옛 인허가번호(폐업) → 폐업 가게에 붙고(점수 대상 아님), 같은 상호·주소의 영업 가게로 새지 않음."""
    src = write(tmp_path / "a.csv", ["관리번호", "업소명", "도로명주소"],
                [[LID_OLD, "할매국밥", "서울특별시 중구 세종대로 110"]])
    load_designations(conn, src, tmp_path / "out", kind="safe_restaurant")
    assert [r[0] for r in sig(conn, "safe_restaurant")] == ["S5"]


def test_unknown_license_falls_back_open_first(conn, tmp_path):
    src = write(tmp_path / "a.csv", ["관리번호", "업소명", "도로명주소"],
                [["9999999-101-0000-00000", "할매국밥", "서울특별시 중구 세종대로 110"]])
    res = load_designations(conn, src, tmp_path / "out", kind="safe_restaurant")
    assert res["by_method"] == {"name+address": 1}
    assert [r[0] for r in sig(conn, "safe_restaurant")] == ["S1"]  # 폐업 S5 아님, 종로구 S4 아님


# --- 상호+주소 폴백: 프랜차이즈·흔한 상호 ---------------------------------------------------
def test_fallback_franchise_and_common_name(conn, tmp_path):
    src = write(tmp_path / "a.csv", ["업소명", "도로명주소", "위도", "경도"], [
        ["김밥천국", "서울특별시 중구 세종대로 120", "", ""],           # 주소 → F1
        ["김밥천국 강남점", "서울특별시 중구 세종대로 120", "", ""],      # 지점 다름 → 불일치
        ["김밥천국", "", "37.5000", "127.0500"],                       # 50m 밖
        ["김밥천국", "", "", ""],                                     # 필수 누락
        ["할매국밥", "서울특별시 강남구 세종대로 110", "", ""],          # 같은 상호·다른 구 → 불일치
        ["할매국밥", "서울 종로구 종로 1", "", ""],                     # → S4
    ])
    res = load_designations(conn, src, tmp_path / "out", kind="model_restaurant")
    assert sorted(r[0] for r in sig(conn, "model_restaurant")) == ["F1", "S4"]
    assert res["matched"] == 2 and res["unmatched"] == 4


# --- 위생등급 ------------------------------------------------------------------------
HY = ["업소명", "도로명주소", "위생등급", "지정일자", "지정취소일자"]
ADDR1 = "서울특별시 중구 세종대로 110"


def test_hygiene_downgrade_latest_wins(conn, tmp_path):
    src = write(tmp_path / "h.csv", HY, [
        ["할매국밥", ADDR1, "매우우수", "2022-01-01", ""],
        ["할매국밥", ADDR1, "좋음", "2024-06-01", ""],
        ["할매국밥", ADDR1, "우수", "", ""],  # 날짜 없는 행은 최신으로 보지 않음
    ])
    load_food_safety(conn, src, "hygiene", tmp_path / "out")
    assert comp(conn, "S1")["hygiene"] == pytest.approx(0.15 * 0.4)


@pytest.mark.xfail(strict=True, reason="지정취소 행은 건너뛰기만 → 이전 적재된 같은 지정 신호가 남아 등급 유지")
def test_hygiene_cancel_after_previous_load_removes_grade(conn, tmp_path):
    out = tmp_path / "out"
    load_food_safety(conn, write(tmp_path / "h1.csv", HY, [["할매국밥", ADDR1, "매우우수", "2023-01-01", ""]]),
                     "hygiene", out)
    assert comp(conn, "S1")["hygiene"] == pytest.approx(0.15)
    load_food_safety(conn, write(tmp_path / "h2.csv", HY,
                                 [["할매국밥", ADDR1, "매우우수", "2023-01-01", "2025-03-01"]]), "hygiene", out)
    assert comp(conn, "S1")["hygiene"] == 0


@pytest.mark.parametrize("rec", [
    pytest.param({"cancel_flag": "미취소"}, marks=pytest.mark.xfail(strict=True, reason="'취소' 부분일치 → 미취소도 취소")),
    pytest.param({"cancel_date": "-"}, marks=pytest.mark.xfail(strict=True, reason="빈값 표기 '-' 를 취소일로 봄")),
    pytest.param({"cancel_date": "0000-00-00"}, marks=pytest.mark.xfail(strict=True, reason="무효 날짜를 취소일로 봄")),
    {"cancel_flag": "정상"}, {"cancel_flag": "N"}, {"cancel_flag": "재지정"},
])
def test_cancel_false_positives(rec):
    assert not is_cancelled(rec)


@pytest.mark.xfail(strict=True, reason="등급 열에 취소 표기가 섞이면 등급으로 해석")
def test_grade_with_cancel_text_not_a_grade():
    assert normalize_grade("우수(지정취소)") is None


# --- 행정처분: UNIQUE 요약 값·중복/과다 집계·3년 경계 -------------------------------------
SA = ["업소명", "도로명주소", "처분일자", "처분내용", "위반내용"]


def test_sanction_same_disposition_multiple_rows_counted_once(conn, tmp_path):
    src = write(tmp_path / "s.csv", SA, [
        ["할매국밥", ADDR1, "2025-01-10", "영업정지 7일", "위반 A"],
        ["할매국밥", ADDR1, "2025.01.10", "영업정지  7일", "위반 B"],   # 같은 처분(표기·공백 차이)
    ])
    res = load_food_safety(conn, src, "sanction", tmp_path / "out", today=date(2026, 1, 1))
    assert res["inserted"] == 1 and res["duplicate"] == 1
    assert comp(conn, "S1")["sanction"] == pytest.approx(-0.05)


@pytest.mark.xfail(strict=True, reason="value=처분내용 원문 요약 → 파일마다 표기가 다르면 같은 처분이 중복 감점")
def test_sanction_same_disposition_across_files_not_double_counted(conn, tmp_path):
    out, today = tmp_path / "out", date(2026, 1, 1)
    load_food_safety(conn, write(tmp_path / "a.csv", SA, [["할매국밥", ADDR1, "2025-01-10", "영업정지 7일", ""]]),
                     "sanction", out, today=today)
    load_food_safety(conn, write(tmp_path / "b.csv", ["업소명", "도로명주소", "처분일자", "처분명"],
                                 [["할매국밥", ADDR1, "20250110", "영업정지(7일)"]]), "sanction", out, today=today)
    load_food_safety(conn, write(tmp_path / "c.csv", ["업소명", "도로명주소", "처분일자"],
                                 [["할매국밥", ADDR1, "2025-01-10"]]), "sanction", out, today=today)
    assert comp(conn, "S1")["sanction"] == pytest.approx(-0.05)


@pytest.mark.parametrize("d,counted", [("2023-03-01", True), ("2023-02-28", False), ("2026-03-02", False)])
def test_sanction_three_year_boundary(conn, tmp_path, d, counted):
    src = write(tmp_path / "s.csv", SA, [["할매국밥", ADDR1, d, "과태료", ""]])
    load_food_safety(conn, src, "sanction", tmp_path / "out", today=date(2026, 3, 1))
    assert comp(conn, "S1")["sanction"] == pytest.approx(-0.05 if counted else 0.0)


# --- 착한가격 메뉴 가격 파싱 -------------------------------------------------------------
@pytest.mark.parametrize("raw,want", [
    ("8,000원", 8000), ("8000", 8000), ("₩ 8,000", 8000), ("7,000~8,000원", 7000), ("", None), ("시가", None),
    pytest.param("8천원", 8000, marks=pytest.mark.xfail(strict=True, reason="'천' 단위 무시 → 8")),
    pytest.param("1만2천원", 12000, marks=pytest.mark.xfail(strict=True, reason="'만·천' 단위 무시 → 1")),
    pytest.param("1만원", 10000, marks=pytest.mark.xfail(strict=True, reason="'만' 단위 무시 → 1")),
])
def test_parse_price(raw, want):
    assert parse_price(raw) == want


def test_good_price_no_score_effect_and_menu_idempotent(conn, tmp_path):
    before = comp(conn, "S2")
    src = write(tmp_path / "gp.csv", ["업소명", "도로명주소", "대표메뉴", "가격", "메뉴1", "가격1"],
                [["착한분식", "서울특별시 중구 을지로 100", "라면", "3,000원", " 라 면", "3500"]])
    load_designations(conn, src, tmp_path / "out", kind="good_price")
    load_designations(conn, src, tmp_path / "out", kind="good_price")
    assert [tuple(r) for r in conn.execute("SELECT name, price FROM menus WHERE restaurant_id='S2'")] == [("라면", 3000)]
    assert comp(conn, "S2") == before  # 점수 무관


# --- --kind 덮어쓰기 · 미슐랭 게이트 ------------------------------------------------------
def test_michelin_held_by_default_label_and_kind(conn, tmp_path):
    src = write(tmp_path / "m.csv", ["업소명", "도로명주소", "kind"], [
        ["할매국밥", ADDR1, "미슐랭 가이드 스타"], ["할매국밥", ADDR1, "michelin_bib"],
        ["할매국밥", ADDR1, "미쉐린 빕구르망"]])  # 미매핑 표기 → 알 수 없는 kind(적재 안 됨)
    res = load_designations(conn, src, tmp_path / "out")
    assert res["michelin_held"] == 2 and res["inserted"] == 0
    res = load_designations(conn, src, tmp_path / "out", kind="michelin_star")
    assert res["michelin_held"] == 3 and res["inserted"] == 0


@pytest.mark.xfail(strict=True, reason="--kind 가 kind 열을 무조건 덮어씀 → 미슐랭 행이 다른 가이드로 적재(게이트 우회)")
def test_kind_override_does_not_bypass_michelin_gate(conn, tmp_path):
    src = write(tmp_path / "m.csv", ["업소명", "도로명주소", "kind"], [["할매국밥", ADDR1, "michelin_star"]])
    res = load_designations(conn, src, tmp_path / "out", kind="taste_of_seoul")
    assert res["inserted"] == 0


# --- 미매칭 파일 PII · dry-run · 멱등 ----------------------------------------------------
def test_unmatched_no_pii_variants(conn, tmp_path):
    src = write(tmp_path / "p.csv", ["업소명", "주소", "대표자 성명", "소재지 전화", "휴대폰", "e-mail", "지정일자"],
                [["없는집", "서울특별시 중구 없는로 1", "홍길동", "02-111-2222", "010-9999-8888", "a@b.c", "2024-01-01"]])
    res = load_designations(conn, src, tmp_path / "out", kind="model_restaurant")
    text = "".join(p.read_text(encoding="utf-8-sig") for p in res["unmatched_files"])
    assert all(v not in text for v in ("홍길동", "02-111-2222", "010-9999-8888", "a@b.c"))


def test_dry_run_no_db_change_food_and_designations(conn, tmp_path):
    snap = lambda: (conn.execute("SELECT COUNT(*) FROM restaurant_signals").fetchone()[0],  # noqa: E731
                    conn.execute("SELECT COUNT(*) FROM menus").fetchone()[0],
                    conn.execute("SELECT group_concat(computed_at) FROM scores").fetchone()[0])
    before = snap()
    load_food_safety(conn, write(tmp_path / "h.csv", HY, [["할매국밥", ADDR1, "우수", "2024-01-01", ""]]),
                     "hygiene", tmp_path / "out", dry_run=True)
    load_designations(conn, write(tmp_path / "g.csv", ["업소명", "도로명주소", "대표메뉴", "가격"],
                                  [["착한분식", "서울특별시 중구 을지로 100", "라면", "3000"]]),
                      tmp_path / "out", kind="good_price", dry_run=True)
    assert snap() == before
    assert not conn.in_transaction


# --- 제목 줄 · 위경도 뒤바뀜 -------------------------------------------------------------
def test_title_rows_and_swapped_coords(conn, tmp_path):
    src = write(tmp_path / "t.csv", ["번호", "업소명", "위도", "경도"],
                [["1", "할매국밥", "126.9780", "37.5665"],      # 뒤바뀜 → 교정 후 50m
                 ["2", "착한분식", "1990000", "450000"]],        # TM 좌표 → 무시(미매칭)
                title=["2024년 안심식당 현황", "기준일: 2024-12-31", "(단위: 개소)"])
    t = sc.Table(src, {**sc.COMMON_ALIASES})
    recs = list(t.rows())
    assert t.skipped_title_rows == 3 and len(recs) == 2
    res = load_designations(conn, src, tmp_path / "out", kind="safe_restaurant")
    assert [r[0] for r in sig(conn, "safe_restaurant")] == ["S1"] and res["unmatched"] == 1


def test_title_row_with_name_like_word_not_header(tmp_path):
    src = write(tmp_path / "t.csv", ["업소명", "주소"], [["할매국밥", ADDR1]], title=["업소 목록(상호명 기준)"])
    t = sc.Table(src, {**sc.COMMON_ALIASES})
    assert [r["name"] for r in t.rows()] == ["할매국밥"] and t.skipped_title_rows == 1


# --- detect_encoding ------------------------------------------------------------------
def test_detect_encoding_basic():
    assert detect_encoding("업소명,주소\n".encode("cp949")) == "cp949"
    assert detect_encoding("업소명,주소\n".encode("utf-8")) == "utf-8-sig"
    assert detect_encoding(b"\xef\xbb\xbf" + "가".encode()) == "utf-8-sig"
    u = ("a" * 65534 + "가").encode()  # UTF-8 3바이트 문자가 64KB 경계에 걸림
    assert detect_encoding(u[:65536]) == "utf-8-sig"
    assert detect_encoding(b"") == "utf-8-sig"


@pytest.mark.xfail(strict=True, reason="앞 64KB 가 ASCII 이고 CP949 선두바이트(0xC0~)가 경계에 걸리면 UTF-8 로 오판")
def test_detect_encoding_cp949_char_on_boundary():
    data = b"a" * 65535 + "한".encode("cp949")  # 0xC7 0xD1 — 0xC7 이 마지막 바이트
    assert detect_encoding(data[:65536]) == "cp949"


# --- license.py 추가 열(--check 전용) -----------------------------------------------------
def test_license_extra_columns_not_in_load_records(tmp_path):
    header = [*lic.COL.values(), "등급구분명", "전통업소주된음식"]
    row = {h: "" for h in header}
    row.update({lic.COL["license_id"]: "L1", lic.COL["opened_at"]: "20000101", lic.COL["status"]: "영업/정상",
                lic.COL["name"]: "가게", lic.COL["biz_type"]: "한식", "등급구분명": "모범", "전통업소주된음식": "국밥"})
    p = tmp_path / "lic.csv"
    with open(p, "w", encoding="cp949", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerow(row)
    plain = list(lic.LicenseCSVAdapter(p, license_type="일반음식점").iter_records())
    assert plain and "grade_type" not in plain[0] and "traditional_food" not in plain[0]
    extra = list(lic.LicenseCSVAdapter(p, license_type="일반음식점", extra=True).iter_records())
    assert extra[0]["grade_type"] == "모범" and extra[0]["traditional_food"] == "국밥"


# --- 규모(N+1 없음) ----------------------------------------------------------------------
def test_scale_no_n_plus_one(tmp_path):
    c = appdb.connect(tmp_path / "big.db")
    appdb.init_schema(c)
    rows = []
    for i in range(30000):
        nm = "김밥천국" if i % 10 == 0 else f"식당{i}"
        rows.append((f"R{i}", nm, f"{i}호점" if nm == "김밥천국" else None, f"서울특별시 중구 샘플로 {i}",
                     37.5 + i * 1e-5, 126.9 + i * 1e-5, f"LIC-{i}"))
    c.executemany("INSERT INTO restaurants(id,name,branch,address,lat,lng,sido,sigungu,sigungu_code,license_id,genre,"
                  "status) VALUES(?,?,?,?,?,?,'서울특별시','중구','11140',?,'한식','open')", rows)
    c.commit()
    data = []
    for i in range(0, 30000, 6):
        nm = "김밥천국" if i % 10 == 0 else f"식당{i}"
        data.append(["" if i % 4 else f"LIC{i}", nm, f"서울특별시 중구 샘플로 {i}", "", ""])
    src = write(tmp_path / "big.csv", ["인허가번호", "업소명", "도로명주소", "위도", "경도"], data)
    queries = [0]
    # SELECT 만 센다(executemany 의 행별 INSERT 는 트레이스에 행마다 찍히므로 제외)
    c.set_trace_callback(lambda q: queries.__setitem__(0, queries[0] + q.lstrip().upper().startswith("SELECT")))
    t0 = time.perf_counter()
    res = load_designations(c, src, tmp_path / "out", kind="model_restaurant", dry_run=True)
    elapsed = time.perf_counter() - t0
    c.set_trace_callback(None)
    assert res["matched"] == len(data)
    assert queries[0] < 50, queries[0]
    assert elapsed < 20, elapsed
    c.close()
