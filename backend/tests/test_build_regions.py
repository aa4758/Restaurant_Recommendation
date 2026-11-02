"""리뷰 지도 경계 연결(app/ingest/build_regions.py): 가게 좌표로 경계 ↔ 지도 단위 연결, 분할 배정, SVG 경로."""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("shapely")

from app.ingest.build_regions import assign, build, unit_name  # noqa: E402


def sq(x0, y0, s=10, cd="", nm=""):
    return {"geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s], [x0, y0]]]},
            "properties": {"adm_cd": cd, "adm_nm": nm}}


def pts(*groups):
    xs, ys, ks = [], [], []
    for x, y, k, n in groups:
        xs += [x] * n
        ys += [y] * n
        ks += [k] * n
    return np.array(xs, float), np.array(ys, float), np.array(ks, dtype=object)


def test_unit_name_merges_general_gu():
    assert unit_name("천안시 동남구") == "천안시"
    assert unit_name("수원시장안구") == "수원시"
    assert unit_name("남동구") == "남동구" and unit_name("제천시") == "제천시" and unit_name("함양군") == "함양군"


def test_assign_by_points_split_and_name_fallback():
    # A: 한 단위(시도명이 바뀌어도 좌표로 연결), B: 두 단위로 나뉨(읍면동 배정), C: 가게 없음 → 이름
    feats = [sq(0, 0, cd="1", nm="광주광역시 북구"), sq(20, 0, cd="2", nm="인천광역시 중구"), sq(40, 0, cd="3", nm="옹진군")]
    x, y, k = pts((5, 5, "전남광주통합특별시|북구", 50),
                  (22, 2, "인천광역시|영종구", 30), (28, 2, "인천광역시|제물포구", 30),
                  (60, 60, "인천광역시|옹진군", 1))  # 옹진군 가게는 경계 밖
    kids = {"2": [sq(20, 0, 5, nm="영종동"), sq(25, 0, 5, nm="신포동"), sq(20, 5, 5, nm="빈동"), sq(25, 5, 5, nm="빈동2")]}
    units, report = assign(feats, x, y, k, lambda cd: kids[cd])
    assert set(units) == {"전남광주통합특별시|북구", "인천광역시|영종구", "인천광역시|제물포구", "인천광역시|옹진군"}
    assert len(units["인천광역시|영종구"]) == 2 and len(units["인천광역시|제물포구"]) == 2  # 빈 읍면동은 가까운 쪽
    assert any("분할 배정" in r for r in report)


def test_build_outputs_paths_and_bbox():
    from shapely.geometry import shape

    units = {"서울특별시|중구": [shape(sq(0, 0, 1000)["geometry"])], "서울특별시|종로구": [shape(sq(1000, 0, 1000)["geometry"])]}
    out = build(units, None)
    assert out["viewBox"] == [0, 0, 20, 10] and [s["name"] for s in out["sido"]] == ["서울특별시"]
    u = {u["name"]: u for u in out["units"]}
    assert u["중구"]["d"].startswith("M0 ") and u["중구"]["d"].endswith("z") and u["종로구"]["bbox"] == [10, 0, 10, 10]
