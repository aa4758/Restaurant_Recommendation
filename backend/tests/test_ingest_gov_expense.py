"""업무추진비 적재: 장소 파싱·PII 화이트리스트·기간·중복·매칭·멱등·Open API 페이징 (load_gov_expense)."""
from __future__ import annotations

import csv
import io
import json
from datetime import date

import pytest

from app import db as appdb
from app.ingest import load_gov_expense as lg
from app.service import rebuild_scores

RESTAURANTS = [
    ("S1", "영덕막회", "서울특별시 중구 을지로3길 33", 37.5665, 126.9880, "서울특별시", "중구", "11140"),
    ("S2", "오드하우스", "서울특별시 중구 정동길 33", 37.5660, 126.9700, "서울특별시", "중구", "11140"),
]
TODAY = date(2026, 10, 26)


@pytest.fixture
def conn(tmp_path):
    c = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(c)
    c.executemany("INSERT INTO restaurants(id,name,address,lat,lng,sido,sigungu,sigungu_code,genre,status)"
                  " VALUES(?,?,?,?,?,?,?,?,'한식','open')", RESTAURANTS)
    c.commit()
    rebuild_scores(c)
    yield c
    c.close()


def write(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lg.COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({"agency": "서울특별시", "dept": "언론담당관", "category": "시책", "source": lg.SEOUL_SOURCE, **r})
    return path


def test_parse_place():
    assert lg.parse_place("바른고기정육점 광화문 SFC점(서울 중구 세종대로 136)") == ("바른고기정육점 광화문 SFC점", "서울 중구 세종대로 136")
    assert lg.parse_place("놀부(주)(서울 종로구 종로 1)") == ("놀부(주)", "서울 종로구 종로 1")
    assert lg.parse_place("할매국밥(본점)") == ("할매국밥(본점)", None)
    assert lg.parse_place("구내식당") == ("구내식당", None)
    # 실데이터 형식: 쉼표·괄호 없음·중첩/안 닫힌 괄호·붙여 쓴 건물번호·시도 생략
    assert lg.parse_place("정동집, 서울 중구 정동길 41-3") == ("정동집", "서울 중구 정동길 41-3")
    assert lg.parse_place("옥된장 충무로역점 서울 중구 퇴계로44길 34 1층")[0] == "옥된장 충무로역점"
    assert lg.parse_place("대가일식(서울 중구 서소문로 101-1, 지하1층 (서소문동, 대건빌딩)")[0] == "대가일식"
    assert lg.parse_place("(주)아리연 (서울특별시 중구 세종대로12길 12 지하1층(남대문로4가))")[0] == "(주)아리연"
    assert lg.parse_place("반포식스(서울 중구 서소문로11길6-1)") == ("반포식스", "서울 중구 서소문로11길 6-1")
    assert lg.parse_place("등촌샤브칼국수(중구 서소문로115)") == ("등촌샤브칼국수", "중구 서소문로 115")
    assert lg.parse_place("전설의 우대갈비(중구 다동 155)") == ("전설의 우대갈비(중구 다동 155)", None)
    assert lg.parse_place("어정 (경기 고양시 덕양구 원당로33번길 32)") == ("어정", "경기 고양시 덕양구 원당로33번길 32")
    assert lg.parse_place("나주곰탕하얀집(전남광주 나주시 금성관길 6-1)")[0] == "나주곰탕하얀집"
    assert lg.parse_place("원조 부산 어묵(서울 중구 을지로 1)") == ("원조 부산 어묵", "서울 중구 을지로 1")


def test_default_since_two_years():
    assert lg.default_since(TODAY) == "2024-10-01"


def test_seoul_row_drops_pii():
    r = lg.seoul_row({"EXEC_DT": "2026-09-17 21:00", "DEPT_NM_FULL": "대변인 언론담당관", "EXEC_LOC": "오드하우스(서울 중구 정동길 33)",
                      "EXEC_AMOUNT": "220000", "BIMOK": "시책", "WRITER": "홍길동", "TELNO": "02-2133-6230",
                      "TARGET_NM": "홍길동 외 4인", "EXEC_PURPOSE": "홍길동 국장 격려"})
    assert set(r) == set(lg.COLUMNS)
    assert "홍길동" not in json.dumps(r, ensure_ascii=False) and "2133" not in json.dumps(r)


def test_load_matches_filters_and_is_idempotent(conn, tmp_path):
    p = write(tmp_path / "g.csv", [
        {"exec_dt": "2026-09-18 13:09", "place": "영덕막회(서울 중구 을지로3길 33)", "amount": "361000"},
        {"exec_dt": "2026-09-18 13:09", "place": "영덕막회(서울 중구 을지로3길 33)", "amount": "361000"},  # 중복
        {"exec_dt": "2026-08-01 12:00", "place": "영덕막회(서울 중구 을지로3길 33)", "amount": "90000"},
        {"exec_dt": "2026-09-17 21:04", "place": "오드하우스(서울 중구 정동길 33)", "amount": "-220000"},  # 취소
        {"exec_dt": "2024-09-30 12:00", "place": "오드하우스(서울 중구 정동길 33)", "amount": "50000"},  # 기간 밖
        {"exec_dt": "2026-09-01 12:00", "place": "구내식당", "amount": "30000"},  # 주소 없음
    ])
    res = lg.load_gov_expense(conn, p, out_dir=tmp_path / "out", today=TODAY)
    assert res["matched"] == 2 and res["unmatched"] == 1 and res["stores"] == 1
    assert res["excluded_reasons"] == {"기간 밖": 1, "금액 0 이하": 1, "중복": 1}
    rows = conn.execute("SELECT restaurant_id, exec_date, amount, purpose, base_year FROM gov_expense ORDER BY exec_date").fetchall()
    assert [tuple(r) for r in rows] == [("S1", "2026-08-01", 90000, "시책", 2026), ("S1", "2026-09-18", 361000, "시책", 2026)]
    assert conn.execute("SELECT gov_visits FROM scores WHERE restaurant_id='S1'").fetchone()[0] == 2
    lg.load_gov_expense(conn, p, out_dir=tmp_path / "out", today=TODAY)  # 재적재 = 같은 결과
    assert conn.execute("SELECT COUNT(*) FROM gov_expense").fetchone()[0] == 2


def test_dry_run_writes_nothing(conn, tmp_path):
    p = write(tmp_path / "g.csv", [{"exec_dt": "2026-09-18 13:09", "place": "영덕막회(서울 중구 을지로3길 33)", "amount": "1"}])
    res = lg.load_gov_expense(conn, p, out_dir=tmp_path / "out", dry_run=True, today=TODAY)
    assert res["matched"] == 1 and conn.execute("SELECT COUNT(*) FROM gov_expense").fetchone()[0] == 0


def test_fetch_seoul_pages_until_total(tmp_path):
    calls = []

    def opener(url, timeout):
        calls.append(url)
        start = int(url.rstrip("/").split("/")[-2])
        rows = [{"EXEC_DT": "2026-09-01 12:00", "EXEC_LOC": f"식당{start + i}(서울 중구 세종대로 1)", "EXEC_AMOUNT": "1000",
                 "WRITER": "홍길동"} for i in range(min(lg.PAGE, 1500 - start + 1))]
        body = {"odExpense": {"list_total_count": 1500, "RESULT": {"CODE": "INFO-000"}, "row": rows}}
        return io.BytesIO(json.dumps(body).encode())

    path, n = lg.fetch_seoul("KEY", tmp_path, opener=opener)
    assert n == 1500 and len(calls) == 2 and "/1001/2000/" in calls[1]
    assert "홍길동" not in path.read_text(encoding="utf-8-sig")


def test_gu_board_name_only_matches_by_city(conn, tmp_path):
    p = write(tmp_path / "g.csv", [{"exec_dt": "2026-09-02 12:16", "agency": "서울특별시 중구", "place": "영덕막회", "amount": "74000"},
                                   {"exec_dt": "2026-09-02 12:16", "agency": "서울특별시 종로구", "place": "오드하우스", "amount": "1"},
                                   {"exec_dt": "2026-09-03 12:16", "agency": "서울특별시 중구", "place": "오드하우스(정동길33)", "amount": "1"}])
    res = lg.load_gov_expense(conn, p, out_dir=tmp_path / "out", today=TODAY)
    assert res["matched"] == 2 and res["by_method"]["name+city"] == 1  # 다른 구 동명 가게는 안 붙음
    assert res["by_method"]["name+address"] == 1  # 시군구 빠진 도로명은 기관 시군구로 보충


def test_gu_board_address_mismatch_not_matched_by_city(conn, tmp_path):
    p = write(tmp_path / "g.csv", [{"exec_dt": "2026-09-02 12:16", "agency": "서울특별시 중구", "place": "영덕막회(퇴계로 999)",
                                    "amount": "1"}])
    assert lg.load_gov_expense(conn, p, out_dir=tmp_path / "out", today=TODAY)["matched"] == 0  # 주소가 다르면 다른 가게
