"""Phase 3-① 공공데이터포털 파일데이터 수집.

- FILE 형: 상세 페이지 JSON-LD 의 `contentUrl`(/cmm/cmm/fileDownload.do) 을 직접 받는다.
  응답이 HTML 이면(다운로드 한도·보안문자 화면 등) 우회하지 않고 failed 로 남긴다.
- LINK 형: 원본이 외부에 있다. 기관 게시판으로 연결되면 BOARD 수집이 맡으므로 status=link 로만 기록,
  서울·경기 열린데이터 포털은 화면 스크립트 없이 받으려면 각 포털 OpenAPI 키가 필요 → status=needs_key.
"""
import re
from pathlib import Path
from urllib.parse import unquote

from src import db
from src.http_client import HttpClient, RobotsDisallowed
from src.phase1_source_survey.survey import kogl_type
from src.phase3_collect import store
from src.web import fetch_followed

CONTENT_URL = re.compile(r'"contentUrl"\s*:\s*"([^"]+)"')
LINK = re.compile(r'<strong class="key">URL</strong>\s*<div class="value">(.*?)</div>', re.S)
KEY_PORTALS = re.compile(r"data\.seoul\.go\.kr|data\.gg\.go\.kr")
KOGL_N = re.compile(r"제?\s*([1-4])\s*유형")
DISPOSITION = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", re.I)


def run(cfg: dict) -> dict:
    raw = Path(cfg["paths"]["raw"])
    conn = db.connect(cfg["paths"]["state_db"])
    rows = [dict(r) for r in conn.execute("""SELECT s.institution_id, s.url, s.license, s.note FROM source_survey s
                JOIN institutions i USING (institution_id) WHERE s.source='DATAGOKR' AND s.status='found'""")]
    run_id = db.start_run(conn, "phase3", "--source datagokr")
    client = HttpClient(cfg["http"] | {"timeout_sec": 120})
    out = {"ok": 0, "duplicate": 0, "link": 0, "needs_key": 0, "failed": 0, "blocked": 0}
    try:
        for r in rows:
            iid, page_url = r["institution_id"], r["url"]
            if conn.execute("SELECT 1 FROM files WHERE institution_id=? AND note LIKE ? AND status!='failed'",
                            (iid, f"%{page_url}%")).fetchone():
                continue  # 이어하기
            title = (r["note"] or "").split(" · ")[0]
            html = fetch_followed(client, page_url, raw / "_phase1" / "pages")
            k = KOGL_N.search(r["license"] or "")  # Phase 1 에서 읽은 이용허락범위(예: '출처표시 (제 1유형)')
            lic = kogl_type(html) or (f"공공누리 {k.group(1)}유형" if k else "공공누리 표시 없음")
            note = f"데이터셋 {page_url}" + (f" · 이용허락범위 {r['license'].split(' 이 페이지')[0]}" if r["license"] else "")
            if m := CONTENT_URL.search(html):
                url = m.group(1)
                try:
                    resp = client.get(url)
                except RobotsDisallowed as e:
                    store.record(conn, iid, "DATAGOKR", url, status="blocked", title=title, license=lic, note=f"{note} · {e}")
                    out["blocked"] += 1
                    continue
                if resp.status_code != 200 or store.looks_like_html(resp.content):
                    store.record(conn, iid, "DATAGOKR", url, status="failed", title=title, license=lic,
                                 note=f"{note} · HTTP {resp.status_code} · HTML 응답(다운로드 한도·보안문자 화면 가능) — 우회 안 함")
                    out["failed"] += 1
                    continue
                d = DISPOSITION.search(resp.headers.get("content-disposition", ""))
                name = unquote(d.group(1)) if d else f"{title}.csv"
                try:
                    name = name.encode("latin-1").decode("utf-8")  # 일부 서버는 UTF-8 이름을 latin-1 헤더로 보냄
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                out[store.save(conn, raw, iid, "DATAGOKR", url, resp.content, name, title=title, license=lic, note=note)] += 1
            else:
                link = re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip().replace("&amp;", "&") if (m := LINK.search(html)) else ""
                status = "needs_key" if KEY_PORTALS.search(link) else "link"
                why = "열린데이터 포털 — OpenAPI 키 필요" if status == "needs_key" else "기관 게시판 링크 — BOARD 수집이 담당"
                store.record(conn, iid, "DATAGOKR", link or page_url, status=status, title=title, license=lic, note=f"{note} · {why}")
                out[status] += 1
            print(f"  {iid} {title}: {conn.execute('SELECT status FROM files ORDER BY file_id DESC LIMIT 1').fetchone()[0]}", flush=True)
        db.finish_run(conn, run_id, "ok", str(out))
    except Exception as e:
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
    finally:
        client.close()
    print(f"공공데이터포털 {len(rows)}건: {out}")
    return out
