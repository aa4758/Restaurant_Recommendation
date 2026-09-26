import sqlite3

from app.ingest.load_seed import load
from app.ingest.sbiz import SbizStoresCSVAdapter, map_genre

HEADER = "상가업소번호,상호명,지점명,상권업종대분류명,상권업종중분류명,상권업종소분류명,시도명,시군구명,시군구코드,지번주소,도로명주소,층정보,경도,위도"
ROWS = [
    "A1,할매국밥,,음식,한식,국/탕/찌개류,서울특별시,중구,11140,중구 1,세종대로 1,1,126.97,37.56",
    "A2,바다횟집,본점,음식,한식,횟집,부산광역시,해운대구,26350,해운대 1,해운대로 1,,129.16,35.16",
    "A3,동네호프,,음식,주점,생맥주 전문,서울특별시,중구,11140,중구 2,,,126.98,37.57",
    "A4,별다방,,음식,비알코올,카페,서울특별시,중구,11140,중구 3,,,126.98,37.57",
    "A5,세탁소,,수리·개인,세탁,세탁소,서울특별시,중구,11140,중구 4,,,126.98,37.57",
    "A6,좌표없음,,음식,중식,중국집,서울특별시,중구,11140,중구 5,,,,",
]


def _csv(tmp_path, enc="cp949"):
    p = tmp_path / "sbiz.csv"
    p.write_text("\n".join([HEADER, *ROWS]) + "\n", encoding=enc)
    return p


def test_map_genre():
    assert map_genre("한식", "해산물 구이/찜") == "해산물"  # 구이보다 해산물 우선
    assert map_genre("한식", "돼지고기 구이/찜") == "고기/구이"
    assert map_genre("서양식", "") == "양식"
    assert map_genre("기타 간이", "버거") == "양식"
    assert map_genre("기타 외국식", "") == "기타"


def test_adapter_filters_and_maps(tmp_path):
    for enc in ("cp949", "utf-8-sig"):
        recs = {r["id"]: r for r in SbizStoresCSVAdapter(_csv(tmp_path, enc)).fetch()}
        assert set(recs) == {"SA1", "SA2", "SA3"}  # 카페·비음식·좌표없음 제외
        assert recs["SA1"]["genre"] == "한식" and recs["SA1"]["alcohol"] is None
        assert recs["SA2"]["genre"] == "해산물" and recs["SA2"]["address"] == "해운대로 1"
        assert recs["SA3"]["alcohol"] == 1 and recs["SA3"]["address"] == "중구 2"


def test_real_load_upserts_and_keeps_reviews(tmp_path):
    db = tmp_path / "t.db"
    ad = [SbizStoresCSVAdapter(_csv(tmp_path))]
    load(db, ad, reset=False)
    c = sqlite3.connect(db)
    c.execute("UPDATE restaurants SET kakao_place_id='k1' WHERE id='SA1'")
    c.execute("INSERT INTO user_reviews(restaurant_id,stars,created_at) VALUES('SA1',4,'t')")
    c.commit()
    c.close()
    load(db, ad, reset=False)  # 분기 갱신 재적재
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0] == 3
    assert c.execute("SELECT kakao_place_id FROM restaurants WHERE id='SA1'").fetchone()[0] == "k1"
    assert c.execute("SELECT COUNT(*) FROM user_reviews").fetchone()[0] == 1
