"""추천 제외 상호(app/exclude.py): 구내식당·회사명은 점수·추천에서 빠지고, 규칙에서 빠지면 복원."""
from app import db
from app.exclude import apply, reason
from app.ingest.load_seed import load
from app.service import rebuild_scores


def test_reason_rules():
    assert reason("씨제이푸드빌(주)엔그릴") == "corporate"
    assert reason("주식회사 세계닭집") == "corporate" and reason("㈜하나에프앤비") == "corporate"
    assert reason("SK종로 구내식당") == "cafeteria" and reason("종로 함바집") == "cafeteria"
    assert reason("함바그또카레야") is None and reason("피쉬엔그릴") is None and reason("주막") is None


def test_excluded_restaurant_gets_no_score(tmp_path):
    p = tmp_path / "t.db"
    load(p)
    conn = db.connect(p)
    db.init_schema(conn)
    conn.execute("UPDATE restaurants SET name='테스트(주)구내식당' WHERE id='R001'")
    assert apply(conn) == {"cafeteria": 1}
    rebuild_scores(conn)
    assert conn.execute("SELECT 1 FROM scores WHERE restaurant_id='R001'").fetchone() is None
    conn.execute("UPDATE restaurants SET name='복원된 식당' WHERE id='R001'")
    assert apply(conn) == {"restored": 1}
    rebuild_scores(conn)
    assert conn.execute("SELECT 1 FROM scores WHERE restaurant_id='R001'").fetchone()
