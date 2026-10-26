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


if __name__ == "__main__":
    app()
