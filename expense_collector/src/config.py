"""config.yaml + .env 로더. 경로는 프로젝트 루트(expense_collector/) 기준 절대경로로 바꿔 돌려준다."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | str = ROOT / "config.yaml") -> dict:
    path = Path(path)
    # 메모장 저장 시 BOM 이 붙을 수 있어 utf-8-sig
    cfg = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    root = path.parent
    cfg["paths"] = {k: str(root / v) for k, v in cfg["paths"].items()}
    if "jjinmat_export" in cfg:
        cfg["jjinmat_export"]["path"] = str(root / cfg["jjinmat_export"]["path"])
    load_dotenv(root / ".env")
    cfg["datagokr_api_key"] = os.getenv("DATAGOKR_API_KEY") or None
    return cfg
