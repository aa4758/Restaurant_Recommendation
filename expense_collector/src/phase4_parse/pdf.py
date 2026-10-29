"""PDF → 쪽별 표 격자(pdfplumber). 괘선 표를 먼저, 없으면 글자 정렬 기준으로(신뢰도 낮춤).
글자가 거의 없으면 스캔 PDF → OCR 필요(ScannedPDF)."""
import io

import pdfplumber

TEXT = {"vertical_strategy": "text", "horizontal_strategy": "text"}


class ScannedPDF(Exception):
    pass


def grids(data: bytes) -> tuple[list[list[list[str]]], float]:
    """(격자들, 신뢰도)"""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if sum(len((p.extract_text() or "").strip()) for p in pdf.pages[:3]) < 30:
            raise ScannedPDF("스캔 PDF(글자 없음) — OCR 필요")
        lined = [t for p in pdf.pages for t in p.extract_tables()]
        if lined:
            return lined, 0.9
        return [t for p in pdf.pages for t in p.extract_tables(TEXT)], 0.6
