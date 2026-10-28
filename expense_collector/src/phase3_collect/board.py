"""Phase 3-② 기관 홈페이지 게시판 수집 (6절 3.2).

대상: board_registry 의 등급 A·B + 약관상 금지 없음. `scope=adapter` 는 CMS 어댑터가 있는 게시판만,
`scope=rest` 는 나머지(어댑터 없음 → boards/generic 휴리스틱, `--probe` 로 1쪽 시험 후 사용자 승인받아 실행).
- 목록을 1쪽부터 넘기며 수집 기간 안 게시글만 처리. 한 쪽의 날짜가 모두 기간 시작보다 이르면 멈춘다.
- 게시글마다 상세를 열어 공공누리 유형을 다시 읽고(출처 표기용), 첨부를 받는다. robots 비허용 첨부는 받지 않고 blocked 로 기록.
- 첨부 URL 이 게시글(또는 목록) URL 자체면(K-에듀파인 상세·기장 목록 표 등) 이미 받은 HTML 을 원본으로 저장한다.
- 호스트별 작업자 1개(호스트당 동시 접속 1, 간격은 HttpClient 가 3초 이상 보장). 다른 호스트끼리만 병렬.
- 이어하기: posts 테이블(처리한 게시글)·collect_status(끝난 게시판)로 건너뛴다.
"""
import re
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from src import db
from src.http_client import HttpClient, RobotsDisallowed
from src.phase1_source_survey.survey import kogl_type
from src.phase3_collect import store
from src.phase3_collect.boards import adapter_for
from src.phase3_collect.boards.generic import Generic

MAX_PAGES = 400  # ponytail: 안전 상한. 기간 안 게시글이 이보다 많은 게시판이 나오면 올린다
DISPOSITION = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", re.I)
NO_KOGL = "공공누리 표시 없음"


def targets(conn, scope: str) -> list[dict]:
    rows = [dict(r) for r in conn.execute("""SELECT b.*, i.name FROM board_registry b JOIN institutions i USING (institution_id)
               WHERE b.crawl_grade IN ('A','B') AND COALESCE(b.terms_ok,'') != 'no' ORDER BY b.institution_id""")]
    has = [r for r in rows if adapter_for(r["board_url"])]
    return has if scope == "adapter" else [r for r in rows if not adapter_for(r["board_url"])]


def probed_ok(cfg: dict, rows: list[dict]) -> list[dict]:
    """scope=rest 수집은 `--probe` 에서 첨부까지 읽힌 게시판만(헛걸음 요청 줄이기)."""
    import csv
    f = Path(cfg["paths"]["output"]) / "probe_rest.csv"
    if not f.exists():
        raise SystemExit("먼저 `phase3 --source board --scope rest --probe` 로 시험하세요.")
    ok = {r["institution_id"] for r in csv.DictReader(open(f, encoding="utf-8-sig")) if r["files"] not in ("", "0")}
    return [r for r in rows if r["institution_id"] in ok]


def file_name(f: dict, resp) -> str:
    if f["ext"]:
        return f["name"]
    if d := DISPOSITION.search(resp.headers.get("content-disposition", "")):
        name = unquote(d.group(1))
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name
    return f["name"] or "download"


def fetch_file(client, conn, raw, iid, f, post, lic, page_html: dict) -> str:
    if store.seen(conn, iid, f["url"]):
        return "seen"
    kw = dict(title=post["title"], date=post["date"], license=lic, note=f"게시글 {post['url']}")
    if f["url"] in page_html:  # 원본이 HTML 페이지 자체
        return store.save(conn, raw, iid, "BOARD", f["url"], page_html[f["url"]].encode("utf-8"), f["name"], **kw)
    try:
        resp = client.get(f["url"])
    except RobotsDisallowed as e:
        store.record(conn, iid, "BOARD", f["url"], status="blocked", filename=f["name"], ext=f["ext"], **kw | {"note": f"{kw['note']} · {e}"})
        return "blocked"
    if resp.status_code != 200 or (f["ext"] != "html" and store.looks_like_html(resp.content)):
        store.record(conn, iid, "BOARD", f["url"], status="failed", filename=f["name"], ext=f["ext"],
                     **kw | {"note": f"{kw['note']} · HTTP {resp.status_code}" + (" · HTML 응답" if resp.status_code == 200 else "")})
        return "failed"
    return store.save(conn, raw, iid, "BOARD", f["url"], resp.content, file_name(f, resp), **kw)


def collect_board(client: HttpClient, conn, raw: Path, row: dict, start: date, end: date, log=print) -> dict:
    iid, board = row["institution_id"], row["board_url"]
    ad = adapter_for(board) or Generic()  # scope=rest: 범용 휴리스틱
    stat = defaultdict(int)
    last, prev_keys = 1, None
    for n in range(1, MAX_PAGES + 1):
        url = ad.page_url(board, n)
        html = client.get(url).text
        stat["pages"] += 1
        posts = ad.list_posts(html, board)
        keys = [(p["url"], p["ntt_sn"], p["date"]) for p in posts]
        if not posts or keys == prev_keys:  # 빈 쪽 / 쪽 번호를 무시하고 같은 목록을 주는 경우
            break
        prev_keys, last = keys, max(last, ad.last_page(html))
        dated = [date.fromisoformat(p["date"]) for p in posts if p["date"]]
        stat["undated"] += len(posts) - len(dated)
        page_html = {url: html, board: html}
        if ad.INLINE:  # 목록 HTML 자체가 원본(관악)
            inside = [d for d in dated if start <= d <= end]
            if inside:
                post = {"title": f"목록 {n}쪽", "date": max(inside).isoformat(), "url": url}
                stat[fetch_file(client, conn, raw, iid, {"name": f"list_p{n}.html", "url": url, "ext": "html"},
                                post, row["license"] or NO_KOGL, page_html)] += 1
                stat["posts"] += len(inside)
        else:
            done_here = set()
            for p in posts:
                if not p["date"] or not (start <= date.fromisoformat(p["date"]) <= end):
                    continue
                on_list = p["url"] in (board, url)  # 상세 없이 목록에 첨부(진안: 행별 첨부) / 목록 표 = 집행 건(기장)
                key = (f"{url}#{p['ntt_sn']}" if p["ntt_sn"] else url) if on_list else p["url"]
                if key in done_here or conn.execute("SELECT 1 FROM posts WHERE institution_id=? AND post_url=? AND status='ok'",
                                                    (iid, key)).fetchone():
                    continue
                done_here.add(key)
                if "files" in p:  # 범용: 상세 없이 목록 행에 첨부
                    ph, files = html, p["files"]
                elif on_list:
                    ph = html
                    files = [f | {"url": url, "name": f"list_p{n}.html"} if f["url"] in (board, url) else f
                             for f in ad.list_attachments(html, board)]
                    if p["ntt_sn"]:  # 진안: 그 행의 첨부만
                        files = [f for f in files if f"={p['ntt_sn']}&" in f["url"] + "&"]
                else:
                    ph = client.get(p["url"]).text
                    page_html[p["url"]] = ph
                    files = ad.list_attachments(ph, p["url"])
                lic = kogl_type(ph) or NO_KOGL
                results = [fetch_file(client, conn, raw, iid, f, p, lic, page_html) for f in files]
                for r in results:
                    stat[r] += 1
                bad = sum(r in ("failed", "blocked") for r in results)
                conn.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?)",
                             (iid, key, p["title"], p["date"], len(files), "failed" if bad and bad == len(results) else "ok",
                              "첨부 없음" if not files else None, db.now()))
                conn.commit()
                stat["posts"] += 1
        if dated and max(dated) < start:  # 이 쪽이 통째로 기간 이전 → 이후 쪽도 이전
            break
        if n >= last:
            break
    return dict(stat)


def worker(cfg: dict, rows: list[dict], start: date, end: date) -> list[tuple]:
    conn = db.connect(cfg["paths"]["state_db"])
    client = HttpClient(cfg["http"] | {"timeout_sec": 120})
    raw = Path(cfg["paths"]["raw"])
    out = []
    try:
        for row in rows:
            iid = row["institution_id"]
            try:
                s = collect_board(client, conn, raw, row, start, end)
                status, note = "done", ", ".join(f"{k}={v}" for k, v in sorted(s.items()))
            except Exception as e:  # 게시판 하나의 실패가 나머지를 막지 않게
                s, status, note = {}, "failed", f"{type(e).__name__}: {e}"[:300]
                traceback.print_exc()
            conn.execute("INSERT OR REPLACE INTO collect_status VALUES (?,?,?,?,?,?,?,?)",
                         (iid, "BOARD", status, s.get("pages"), s.get("posts"), s.get("ok", 0) + s.get("duplicate", 0), note, db.now()))
            conn.commit()
            print(f"  {iid} {row['name']}: {status} · {note}", flush=True)
            out.append((iid, status, s))
    finally:
        client.close()
        conn.close()
    return out


def probe_board(client: HttpClient, row: dict, start: date, end: date) -> dict:
    """목록 1쪽 + 기간 내 첫 게시글 1건만 열어 어댑터가 읽히는지 본다(저장 없음)."""
    board = row["board_url"]
    ad = adapter_for(board) or Generic()
    html = client.get(board).text
    posts = ad.list_posts(html, board)
    inside = [p for p in posts if p["date"] and start <= date.fromisoformat(p["date"]) <= end]
    r = {"posts": len(posts), "in_period": len(inside), "last_page": ad.last_page(html), "page_param": getattr(ad, "param", ""),
         "sample_post": "", "files": 0, "exts": ""}
    if inside:
        p = inside[0]
        files = p.get("files") or ad.list_attachments(client.get(p["url"]).text, p["url"])
        r |= {"sample_post": inside[0]["url"], "files": len(files), "exts": ",".join(sorted({f["ext"] or "?" for f in files}))}
    return r


def probe_worker(cfg: dict, rows: list[dict], start: date, end: date) -> list[dict]:
    client = HttpClient(cfg["http"] | {"timeout_sec": 60})
    out = []
    try:
        for row in rows:
            try:
                r = probe_board(client, row, start, end)
            except Exception as e:
                r = {"error": f"{type(e).__name__}: {e}"[:200]}
            r = {"institution_id": row["institution_id"], "name": row["name"], "board_url": row["board_url"]} | r
            print(f"  {r['institution_id']} {r['name']}: " + ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("institution_id", "name", "board_url")), flush=True)
            out.append(r)
    finally:
        client.close()
    return out


def run_probe(cfg: dict, scope: str, workers: int) -> None:
    import csv
    conn = db.connect(cfg["paths"]["state_db"])
    by_host = defaultdict(list)
    for r in targets(conn, scope):
        by_host[urlsplit(r["board_url"]).hostname].append(r)
    start, end = date.fromisoformat(cfg["period"]["start"]), date.fromisoformat(cfg["period"]["end"])
    with ThreadPoolExecutor(workers) as ex:
        results = [r for f in [ex.submit(probe_worker, cfg, rs, start, end) for rs in by_host.values()] for r in f.result()]
    cols = ["institution_id", "name", "board_url", "posts", "in_period", "last_page", "page_param", "sample_post", "files", "exts", "error"]
    out = Path(cfg["paths"]["output"]) / f"probe_{scope}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: r["institution_id"]))
    ok = sum(bool(r.get("files")) for r in results)
    print(f"시험 {len(results)}곳: 기간 내 게시글 읽힘 {sum(bool(r.get('in_period')) for r in results)} · 첨부까지 읽힘 {ok} · 오류 {sum('error' in r for r in results)} → {out}")


def run(cfg: dict, scope: str, workers: int) -> None:
    conn = db.connect(cfg["paths"]["state_db"])
    rows = targets(conn, scope)
    if scope == "rest":
        rows = probed_ok(cfg, rows)
    done = {r[0] for r in conn.execute("SELECT institution_id FROM collect_status WHERE source='BOARD' AND status='done'")}
    todo = [r for r in rows if r["institution_id"] not in done]
    by_host = defaultdict(list)
    for r in todo:
        by_host[urlsplit(r["board_url"]).hostname].append(r)
    start, end = date.fromisoformat(cfg["period"]["start"]), date.fromisoformat(cfg["period"]["end"])
    run_id = db.start_run(conn, "phase3", f"--source board --scope {scope}")
    print(f"게시판 {len(rows)}곳(남은 {len(todo)}곳) · 호스트 {len(by_host)}개 · 작업자 {workers}", flush=True)
    results = []
    try:
        with ThreadPoolExecutor(workers) as ex:  # 큰 호스트부터 시작해 전체 시간을 줄인다
            futs = [ex.submit(worker, cfg, rs, start, end) for rs in sorted(by_host.values(), key=len, reverse=True)]
            for f in as_completed(futs):
                results += f.result()
        summary = defaultdict(int)
        for _, status, s in results:
            summary[status] += 1
            for k in ("posts", "ok", "duplicate", "failed", "blocked"):
                summary[k] += s.get(k, 0)
        db.finish_run(conn, run_id, "ok", str(dict(summary)))
        print(f"게시판 수집 끝: {dict(summary)}", flush=True)
    except Exception as e:
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
