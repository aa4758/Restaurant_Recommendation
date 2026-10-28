"""단일 진입점: python -m src.cli <command>"""
import typer

from src import db
from src.config import load_config

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def status():
    """단계별 진행 현황."""
    cfg = load_config()
    conn = db.connect(cfg["paths"]["state_db"])
    for section, rows in db.status_report(conn).items():
        typer.echo(f"[{section}]")
        for r in rows or [("(없음)",)]:
            typer.echo("  " + " | ".join("" if v is None else str(v) for v in r))


@app.command()
def phase0():
    """기관 마스터 리스트 → data/institutions.csv"""
    from src.phase0_institutions.build import run
    run(load_config())


@app.command()
def phase1(pilot: bool = typer.Option(False, "--pilot", help="config.pilot.institutions 만")):
    """기관별 수집 출처 조사 → data/source_survey.csv, data/output/foi_candidates.csv"""
    from src.phase1_source_survey.survey import run
    run(load_config(), pilot)


@app.command()
def phase2(pilot: bool = typer.Option(False, "--pilot", help="config.pilot.institutions 만")):
    """BOARD found 기관의 게시판 분류 → data/board_registry.csv"""
    from src.phase2_board_classify.classify import run
    run(load_config(), pilot)


@app.command()
def phase3(source: str = typer.Option(..., "--source", help="datagokr | board"),
           scope: str = typer.Option("adapter", "--scope", help="board: adapter(어댑터 있는 곳) | rest(나머지)"),
           workers: int = typer.Option(6, "--workers", help="board: 동시에 처리할 호스트 수(호스트당 접속 1)"),
           probe: bool = typer.Option(False, "--probe", help="board: 목록 1쪽+게시글 1건만 시험 → data/output/probe_{scope}.csv")):
    """원본 수집 → data/raw/{기관}/{출처}/, files 테이블"""
    if source == "datagokr":
        from src.phase3_collect.datagokr import run
        run(load_config())
    elif source == "board":
        from src.phase3_collect.board import run, run_probe
        (run_probe if probe else run)(load_config(), scope, workers)
    else:
        raise typer.BadParameter("datagokr | board")


@app.command()
def phase4(workers: int = typer.Option(4, "--workers", help="동시에 파싱할 프로세스 수"),
           limit: int = typer.Option(0, "--limit", help="시험용: 앞에서 N개만(0 = 전부)")):
    """원본 → 업무추진비 표 → data/parsed/{file_id}_{table_index}.parquet, parsed_tables 테이블"""
    from src.phase4_parse.run import run
    run(load_config(), workers, limit or None)


if __name__ == "__main__":
    app()
