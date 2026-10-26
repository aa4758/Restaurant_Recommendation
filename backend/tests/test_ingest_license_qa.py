"""QA: D2 인허가 적재(license.py, load_license.py) 경계·결함 검증. 확인된 결함은 xfail(strict)."""
import sqlite3
import time

import pytest

from app.db import init_schema
from app.ingest import license as lic
from app.ingest import load_license as ll
from app.ingest.license import is_excluded, map_genre, parse_status, tm_to_wgs84
from app.ingest.matcher import RestaurantIndex
from app.scoring.recommend import haversine_m

from test_ingest_license import RESTAURANTS, fixture_rows, make_db, row, tm, write_csv


def _q(conn, sql, *a):
    return tuple(conn.execute(sql, a).fetchone())


def _load(conn, tmp_path, rows, name="l.csv", **kw):
    p = write_csv(tmp_path / name, rows)
    return ll.load_license(conn, [p], out_dir=tmp_path / "out", **kw)


@pytest.fixture
def no_rebuild(monkeypatch):
    calls = []
    monkeypatch.setattr(ll, "rebuild_scores", lambda c, reg: calls.append(reg))
    return calls


# --- 영업상태 매핑 -------------------------------------------------------------
@pytest.mark.parametrize("status,detail,exp", [
    ("폐업", "폐업", "closed"), ("폐업", "직권폐업", "closed"), ("취소/말소/만료/정지/중지", "직권말소", "closed"),
    ("취소/말소/만료/정지/중지", "취소", "closed"), ("", "말소", "closed"), ("휴업", "휴업", "open"),
    ("영업/정상", "영업", "open"), ("", "", "open"),
])
def test_status_mapping(status, detail, exp):
    assert parse_status(status, detail) == exp


# --- 좌표 -----------------------------------------------------------------------
def test_coords_zero_missing_out_of_range():
    assert tm_to_wgs84(0, 451579.85) is None and tm_to_wgs84(197986.75, 0) is None
    assert tm_to_wgs84(None, 451579.85) is None
    assert tm_to_wgs84(-1e6, -1e6) is None
    assert lic._float("nan") is None and lic._float("inf") is None and lic._float("1,234.5") == 1234.5
    # 왕복 정확도(부산·제주)
    for lat, lng in ((35.1796, 129.0756), (33.4996, 126.5312)):
        assert haversine_m(*tm_to_wgs84(*tm(lat, lng)), lat, lng) < 1.0


def test_out_of_korea_coords_not_new_store(tmp_path, no_rebuild):
    conn = make_db(tmp_path)
    res = _load(conn, tmp_path, [row("Z1", "일반음식점", "범위밖집", "한식", "20200101",
                                     road="서울특별시 중구 남대문로 99", xy=("9000000", "9000000"))])
    assert res["new"] == 0 and res["unmatched"] == 1
    assert _q(conn, "SELECT COUNT(*) FROM restaurants WHERE name='범위밖집'")[0] == 0


# --- 업태 제외·장르 -----------------------------------------------------------------
def test_genre_mapping_more_values():
    assert map_genre("냉면집") == "한식" and map_genre("탕류(보신용)") == "한식"
    assert map_genre("김밥(도시락)") == "분식" and map_genre("복어취급") == "일식"
    assert map_genre("패밀리레스트랑") == "양식" and map_genre("감성주점") == "주점"
    assert map_genre("호프/통닭", "옛날통닭") == "치킨"
    assert is_excluded(" 커피숍 ") and is_excluded("키즈카페") and not is_excluded("기타 휴게음식점")


# --- 재개업 우선순위·처리 순서 ---------------------------------------------------------
def test_reopen_priority_order_independent_single_run(tmp_path, no_rebuild):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = make_db(tmp_path / "a"), make_db(tmp_path / "b")
    rows = fixture_rows()
    _load(a, tmp_path / "a", rows)
    _load(b, tmp_path / "b", list(reversed(rows)))
    snap = lambda c: [tuple(r)[:-1] for r in c.execute(  # noqa: E731
        "SELECT id,status,license_id,opened_at,closed_at,alcohol,license_type,updated_at FROM restaurants ORDER BY id")]
    assert snap(a) == snap(b)
    assert _q(a, "SELECT status, license_id FROM restaurants WHERE id='S4'") == ("open", "A4")


def test_reopen_after_closed_in_db(tmp_path, no_rebuild):
    conn = make_db(tmp_path)
    conn.execute("UPDATE restaurants SET status='closed', closed_at='2020-01-01' WHERE id='S1'")
    conn.commit()
    res = _load(conn, tmp_path, [row("N1", "일반음식점", "할매국밥", "한식", "20230101",
                                     road="서울특별시 중구 세종대로 110", xy=tm(37.5665, 126.9780))])
    assert res["reopened"] == 1
    assert _q(conn, "SELECT status, closed_at, license_id FROM restaurants WHERE id='S1'") == ("open", None, "N1")


@pytest.mark.xfail(strict=True, reason="별도 실행(일반/휴게 파일 따로)에서 다른 관리번호의 옛 폐업 행이 영업 중 가게를 closed 로 덮음")
def test_stale_closed_license_in_later_run_does_not_close(tmp_path, no_rebuild):
    conn = make_db(tmp_path)
    road, xy = "서울특별시 중구 세종대로 110", tm(37.5665, 126.9780)
    _load(conn, tmp_path, [row("G1", "일반음식점", "할매국밥", "한식", "20150101", road=road, xy=xy)], "general.csv")
    # 다음 실행: 휴게음식점 파일에 같은 상호·주소의 옛(2005~2010) 폐업 인허가
    _load(conn, tmp_path, [row("R1", "휴게음식점", "할매국밥", "분식", "20050101", status="폐업", closed="20100101",
                               road=road, xy=xy)], "rest.csv")
    assert _q(conn, "SELECT status, license_id FROM restaurants WHERE id='S1'") == ("open", "G1")


# --- 휴게 → alcohol 0 ------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="일반·휴게 두 인허가가 모두 영업 중이면 최신 인허가(휴게)가 이겨 일반음식점 alcohol·license_type 을 덮음")
def test_rest_license_does_not_override_open_general(tmp_path, no_rebuild):
    conn = make_db(tmp_path)  # S2 동네호프 alcohol=1
    road, xy = "서울특별시 중구 을지로 100", tm(37.5660, 126.9900)
    _load(conn, tmp_path, [
        row("G2", "일반음식점", "동네호프", "호프/통닭", "20100501", road=road, xy=xy),
        row("R2", "휴게음식점", "동네호프", "기타 휴게음식점", "20200101", road=road, xy=xy),
    ])
    assert _q(conn, "SELECT alcohol, license_type FROM restaurants WHERE id='S2'") == (1, "일반음식점")


def test_rest_closed_does_not_touch_general_store_alcohol_when_general_open(tmp_path, no_rebuild):
    conn = make_db(tmp_path)
    road, xy = "서울특별시 중구 을지로 100", tm(37.5660, 126.9900)
    _load(conn, tmp_path, [
        row("G2", "일반음식점", "동네호프", "호프/통닭", "20100501", road=road, xy=xy),
        row("R2", "휴게음식점", "동네호프", "기타 휴게음식점", "20200101", status="폐업", closed="20210101",
            road=road, xy=xy),
    ])
    assert _q(conn, "SELECT alcohol, license_type, status FROM restaurants WHERE id='S2'") == (1, "일반음식점", "open")


# --- 업태 제외가 폐업 반영을 막음 -------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="제외 업태(까페 등) 행은 매칭 전 버려져, 이미 있는 가게의 폐업이 반영되지 않음")
def test_excluded_biz_type_closure_still_applied_to_existing_store(tmp_path, no_rebuild):
    conn = make_db(tmp_path)
    _load(conn, tmp_path, [row("C1", "일반음식점", "할매국밥", "까페", "20150101", status="폐업", closed="20240101",
                               road="서울특별시 중구 세종대로 110", xy=tm(37.5665, 126.9780))])
    assert _q(conn, "SELECT status FROM restaurants WHERE id='S1'")[0] == "closed"


# --- 멱등 -------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="폐업일자·갱신일자가 없으면 closed_at=적재일 → 재적재마다 값이 바뀜(비멱등)")
def test_closed_at_idempotent_without_dates(tmp_path, no_rebuild, monkeypatch):
    import datetime as dt

    conn = make_db(tmp_path)
    r = row("A6", "일반음식점", "폐업식당", "한식", "20000101", status="폐업", closed="",
            road="서울특별시 중구 삼일대로 30", xy=tm(37.5650, 126.9880), updated="")

    class D1(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2026, 1, 1)

    class D2(D1):
        @classmethod
        def today(cls):
            return dt.date(2026, 2, 1)

    monkeypatch.setattr(lic, "date", D1)
    _load(conn, tmp_path, [r])
    first = _q(conn, "SELECT closed_at FROM restaurants WHERE id='S5'")[0]
    monkeypatch.setattr(lic, "date", D2)
    _load(conn, tmp_path, [r])
    assert _q(conn, "SELECT closed_at FROM restaurants WHERE id='S5'")[0] == first


def test_duplicate_license_rows_across_files_no_unique_error(tmp_path, no_rebuild):
    conn = make_db(tmp_path)
    rows = fixture_rows()
    p1 = write_csv(tmp_path / "a.csv", rows)
    p2 = write_csv(tmp_path / "b.csv", rows)  # 전국 + 서울 파일 겹침
    res = ll.load_license(conn, [p1, p2], out_dir=tmp_path / "out")
    assert res["new"] == 2
    assert _q(conn, "SELECT COUNT(*) FROM restaurants")[0] == len(RESTAURANTS) + 2
    assert _q(conn, "SELECT COUNT(DISTINCT license_id), COUNT(license_id) FROM restaurants") == (7, 7)


# --- 신규 가게 시군구코드 -----------------------------------------------------------------
def test_new_store_unknown_region_code_none(tmp_path, no_rebuild):
    conn = make_db(tmp_path)  # 서울 중구만 존재
    res = _load(conn, tmp_path, [row("B1", "일반음식점", "부산밀면", "냉면집", "20200101",
                                     road="부산광역시 중구 중앙대로 10", xy=tm(35.1030, 129.0360))])
    assert res["new"] == 1
    assert _q(conn, "SELECT sido, sigungu, sigungu_code FROM restaurants WHERE id='LB1'") == ("부산광역시", "중구", None)
    assert None in res["regions"]


# --- dry-run ------------------------------------------------------------------------
def test_dry_run_keeps_db_and_scores(tmp_path):
    conn = make_db(tmp_path)
    ll.rebuild_scores(conn, "11140")
    before = conn.execute("SELECT * FROM restaurants ORDER BY id").fetchall()
    scores = conn.execute("SELECT restaurant_id, star FROM scores ORDER BY 1").fetchall()
    _load(conn, tmp_path, fixture_rows(), dry_run=True)
    assert conn.execute("SELECT * FROM restaurants ORDER BY id").fetchall() == before
    assert conn.execute("SELECT restaurant_id, star FROM scores ORDER BY 1").fetchall() == scores


# --- 점수 재계산: 폐업 가게 점수 제거 --------------------------------------------------------
def test_closed_store_removed_from_scores(tmp_path):
    conn = make_db(tmp_path)
    ll.rebuild_scores(conn, "11140")
    assert _q(conn, "SELECT COUNT(*) FROM scores WHERE restaurant_id='S5'")[0] == 1
    _load(conn, tmp_path, fixture_rows())
    assert _q(conn, "SELECT COUNT(*) FROM scores WHERE restaurant_id='S5'")[0] == 0


# --- 성능 ----------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="matcher: 같은 상호(프랜차이즈) 후보마다 주소 정규화 반복 → O(행×후보) 이차 비용")
def test_matcher_common_name_scales():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    k = 800
    conn.executemany("INSERT INTO restaurants(id,name,genre,lat,lng,address) VALUES(?,?,?,?,?,?)",
                     [(f"S{i}", "김밥천국", "분식", 37.5 + i * 1e-3, 127.0, f"서울특별시 중구 테스트로 {i}")
                      for i in range(k)])
    idx = RestaurantIndex(conn)
    t = time.perf_counter()
    for i in range(k):
        idx.match("김밥천국", f"서울특별시 중구 테스트로 {i}", None, None)
    assert time.perf_counter() - t < 1.0
