"""자연어 조건 사전 보강 — 매주 Batch LLM 제안 → 사람 승인 (docs/01 '자연어 조건 입력').

    python -m app.nlp_enrich run                 # 매주(월 04:00, 작업 스케줄러): 지난 배치 결과 수거 → 90일 지난 낱말 삭제 → 새 배치 제출
    python -m app.nlp_enrich list                # 승인 대기 제안 보기
    python -m app.nlp_enrich approve <낱말...> | --all
    python -m app.nlp_enrich reject <낱말...>

- 보내는 것: 지난 7일 안에 나왔고 누적 3회 이상인 미인식 낱말 + 허용 표현 목록뿐(원문 문장·기기·위치 없음).
- Claude Haiku 5.5, Message Batches API(50% 할인, 24시간 안에 완료) — 이번 주 제출분은 다음 주 run 에서 수거.
- 키(ANTHROPIC_API_KEY)가 없거나 API 오류면 보강만 건너뜀(서비스 무관). 제안은 status='proposed', 승인한 것만 해석에 쓰임.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta

from app.constants import ALCOHOL, MOODS, PRICE_BANDS
from app.db import connect, db_path, init_schema
from app.subtype import PARENT, SUBTYPES

MODEL = "claude-haiku-5-5"
MIN_COUNT = 3
WINDOW_DAYS = 7
KEEP_DAYS = 90
CHUNK = 50  # 요청 하나에 낱말 50개

ALLOWED = {
    "genre": list(SUBTYPES),
    "subtype": list(PARENT),
    "mood": MOODS,
    "price": PRICE_BANDS,
    "alcohol": [a for a in ALCOHOL if a != "any"],
}
SYSTEM = (
    "너는 음식점 추천 앱의 검색어 사전 관리자다. 사용자가 조건을 문장으로 입력했는데 사전이 못 알아들은 낱말 목록을 받는다. "
    "각 낱말을 앱 필터 값 하나에 대응시켜라. 허용 값:\n"
    + "\n".join(f"- {k}: {', '.join(v)}" for k, v in ALLOWED.items())
    + "\n음식·맛·분위기·가격·음주 조건을 뜻하지 않거나(동사·지명·인사 등) 대응이 애매하면 field=none, value=none. "
    "맛 표현은 가장 대표적인 세부 분류 하나로(예: 얼큰한 → 찌개/전골), 음주 가능은 alcohol=yes, 음주 불가는 alcohol=no."
)
SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "field": {"type": "string", "enum": [*ALLOWED, "none"]},
            "value": {"type": "string", "enum": sorted({v for vs in ALLOWED.values() for v in vs} | {"none"})},
        },
        "required": ["term", "field", "value"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}


def due_terms(conn: sqlite3.Connection, today: date) -> list[str]:
    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    return [r[0] for r in conn.execute(
        "SELECT term FROM unknown_terms u WHERE count >= ? AND last_seen >= ?"
        " AND NOT EXISTS (SELECT 1 FROM synonyms s WHERE s.term = u.term) ORDER BY count DESC, term",
        (MIN_COUNT, since))]


def requests_for(terms: list[str]) -> list[dict]:
    return [{
        "custom_id": f"terms-{i}",
        "params": {
            "model": MODEL,
            "max_tokens": 8000,  # Haiku 5.5 는 기본으로 생각하며 생각도 max_tokens 에 포함
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "system": SYSTEM,
            "messages": [{"role": "user", "content": "\n".join(terms[i:i + CHUNK])}],
        },
    } for i in range(0, len(terms), CHUNK)]


def valid(item: dict) -> bool:
    f, v = item.get("field"), item.get("value")
    return (f == "none" and v == "none") or v in ALLOWED.get(f, ())


def save_proposals(conn: sqlite3.Connection, batch_id: str, items: list[dict], asked: set[str]) -> int:
    now = date.today().isoformat()
    rows = [(i["term"], i["field"], i["value"], batch_id, now) for i in items if i["term"] in asked and valid(i)]
    conn.executemany("INSERT OR IGNORE INTO synonyms(term,field,value,status,batch_id,updated_at)"
                     " VALUES(?,?,?,'proposed',?,?)", rows)
    return len(rows)


def _client():
    try:
        import anthropic

        return anthropic.Anthropic()
    except Exception as e:  # 패키지·키 없음 → 보강만 건너뜀
        print(f"[skip] Claude API 클라이언트 없음: {e}")
        return None


def run(conn: sqlite3.Connection, today: date | None = None, client=None) -> dict:
    today = today or date.today()
    out = {"collected": 0, "proposed": 0, "pruned": 0, "submitted_terms": 0, "batch_id": None}
    client = client or _client()
    if client is not None:
        asked = {r[0] for r in conn.execute("SELECT term FROM unknown_terms")}  # 우리가 보낸 낱말만 받음
        for (bid,) in conn.execute("SELECT batch_id FROM enrich_batches WHERE collected_at IS NULL").fetchall():
            try:
                if client.messages.batches.retrieve(bid).processing_status != "ended":
                    continue
                for res in client.messages.batches.results(bid):
                    if res.result.type != "succeeded":
                        continue
                    text = next((b.text for b in res.result.message.content if b.type == "text"), "")
                    items = json.loads(text).get("items", []) if text else []
                    out["proposed"] += save_proposals(conn, bid, items, asked)
                conn.execute("UPDATE enrich_batches SET collected_at=? WHERE batch_id=?", (today.isoformat(), bid))
                out["collected"] += 1
            except Exception as e:  # 개별 배치 실패는 다음 주에 다시
                print(f"[warn] 배치 {bid} 수거 실패: {e}")
    cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
    out["pruned"] = conn.execute("DELETE FROM unknown_terms WHERE last_seen < ?", (cut,)).rowcount
    terms = due_terms(conn, today)
    if client is not None and terms:
        try:
            batch = client.messages.batches.create(requests=requests_for(terms))
            conn.execute("INSERT INTO enrich_batches(batch_id,created_at,terms) VALUES(?,?,?)",
                         (batch.id, today.isoformat(), len(terms)))
            out.update(submitted_terms=len(terms), batch_id=batch.id)
        except Exception as e:
            print(f"[warn] 배치 제출 실패: {e}")
    conn.commit()
    return out


def set_status(conn: sqlite3.Connection, terms: list[str] | None, status: str) -> int:
    now = date.today().isoformat()
    if terms is None:
        n = conn.execute("UPDATE synonyms SET status=?, updated_at=? WHERE status='proposed'", (status, now)).rowcount
    else:
        n = sum(conn.execute("UPDATE synonyms SET status=?, updated_at=? WHERE status='proposed' AND term=?",
                             (status, now, t)).rowcount for t in terms)
    conn.commit()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="자연어 조건 사전 보강(주간 Batch LLM → 사람 승인)")
    ap.add_argument("cmd", choices=["run", "list", "approve", "reject"])
    ap.add_argument("terms", nargs="*")
    ap.add_argument("--all", action="store_true", help="approve: 대기 중인 제안 전부")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    conn = connect(a.db or db_path())
    init_schema(conn)
    if a.cmd == "run":
        print(run(conn))
    elif a.cmd == "list":
        for t, f, v, b in conn.execute(
                "SELECT term, field, value, batch_id FROM synonyms WHERE status='proposed' ORDER BY field, term"):
            print(f"{t}\t→ {f}={v}\t({b})")
    elif a.cmd == "approve":
        print(f"승인 {set_status(conn, None if a.all else a.terms, 'approved')}건")
    else:
        print(f"거절 {set_status(conn, a.terms, 'rejected')}건")


if __name__ == "__main__":
    main()
