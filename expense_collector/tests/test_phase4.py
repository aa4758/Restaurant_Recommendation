"""Phase 4 파서 — 가상 표(테스트 안에서 생성, 실데이터·실명 없음)."""
import io
import struct
import zipfile

import pandas as pd
import pytest

from src.phase4_parse import hwp, pdf, tables
from src.phase4_parse.run import kind_of, parse_bytes

HEAD = ["집행일자", "사용처", "집행목적", "금액(원)"]
ROWS = [["2026-10-05", "가나식당", "간담회", "120,000"], ["2026-10-07", "다라찻집", "회의", "30,000"]]


def test_header_and_status():
    grid = [["2026년 10월 업무추진비 집행내역", "", "", ""], ["", "", "", ""], HEAD, *ROWS, HEAD]  # 끝 = 반복 머리행
    df, st = tables.to_frame(grid)
    assert st == "ok" and list(df.columns) == HEAD and df.values.tolist() == ROWS
    assert tables.to_frame([["구분", "금액"], ["합계", "150,000"]])[1] == "flagged"  # 요약표
    assert tables.to_frame([["공지", "안내"], ["a", "b"]]) is None


def test_two_row_header_and_continuation():
    grid = [["집행내역", "", "금액(원)"], ["일자", "사용처", ""], ["2026-10-05", "가나식당", "1,000"]]
    df, _ = tables.to_frame(grid)
    assert list(df.columns) == ["집행내역 일자", "집행내역 사용처", "금액(원)"]
    nxt = [["2026-10-09", "마바식당", "2,000"]]  # 다음 쪽: 머리행 없이 이어짐
    (merged, _), = tables.select([grid, nxt])
    assert merged["금액(원)"].tolist() == ["1,000", "2,000"]


def test_excel_csv_html():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame([["제목"], [None]]).to_excel(w, sheet_name="표지", header=False, index=False)
        pd.DataFrame([HEAD, *ROWS]).to_excel(w, sheet_name="내역", header=False, index=False)
    kind, found, conf = parse_bytes(buf.getvalue(), "xls")  # 확장자가 틀려도 머리 바이트로 xlsx
    assert kind == "xlsx" and len(found) == 1 and found[0][0].values.tolist() == ROWS and conf == 1.0
    csv = "\n".join(",".join(f'"{c}"' for c in r) for r in [HEAD, *ROWS]).encode("cp949")
    assert parse_bytes(csv, "csv")[1][0][0].values.tolist() == ROWS
    page = ("<table><tr><td><table><tr><th>집행일자</th><th>사용처</th><th>금액</th></tr>"
            "<tr><td rowspan=2>2026-10-05</td><td>가나식당</td><td>1,000</td></tr><tr><td>다라찻집</td><td>2,000</td></tr>"
            "</table></td></tr></table>").encode()
    kind, found, _ = parse_bytes(page, "html")
    assert kind == "html" and found[0][0].values.tolist() == [["2026-10-05", "가나식당", "1,000"], ["2026-10-05", "다라찻집", "2,000"]]


def _hwpx(cells) -> bytes:
    tcs = "".join(f'<hp:tc><hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="{rs}"/>'
                  f'<hp:subList><hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p></hp:subList></hp:tc>' for r, c, rs, t in cells)
    xml = f'<hs:sec xmlns:hs="urn:s" xmlns:hp="urn:p"><hp:p><hp:run><hp:tbl><hp:tr>{tcs}</hp:tr></hp:tbl></hp:run></hp:p></hs:sec>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", xml)
    return buf.getvalue()


def test_hwpx():
    cells = [(0, i, 1, h) for i, h in enumerate(HEAD)] + [(1, 0, 2, "2026-10-05"), (1, 1, 1, "가나식당"), (1, 2, 1, "간담회"),
                                                            (1, 3, 1, "1,000"), (2, 1, 1, "다라찻집"), (2, 2, 1, "회의"), (2, 3, 1, "2,000")]
    kind, found, _ = parse_bytes(_hwpx(cells), "hwp")
    assert kind == "hwpx" and found[0][0]["집행일자"].tolist() == ["2026-10-05", "2026-10-05"]  # 세로 병합 복제


def _rec(tag, level, data):
    return tag, level, data


def test_hwp5_records():
    def cell(col, row):
        return _rec(hwp.TAG_LIST_HEADER, 2, b"\0" * 8 + struct.pack("<4H", col, row, 1, 1))

    def text(s, ctrl=False):
        body = (struct.pack("<H", 11) + b"\0" * 14 if ctrl else b"") + s.encode("utf-16-le") + struct.pack("<H", 13)
        return _rec(hwp.TAG_PARA_TEXT, 3, body)
    recs = [_rec(hwp.TAG_CTRL_HEADER, 1, b" lbt"), _rec(hwp.TAG_TABLE, 2, b""),
            cell(0, 0), text("사용일자"), cell(1, 0), text("금액", ctrl=True), cell(0, 1), text("2026-10-05"), cell(1, 1), text("1,000"),
            _rec(hwp.TAG_PARA_TEXT, 0, "본문".encode("utf-16-le"))]
    assert hwp.record_tables(recs) == [[["사용일자", "금액"], ["2026-10-05", "1,000"]]]
    raw = struct.pack("<I", hwp.TAG_PARA_TEXT | (3 << 10) | (4 << 20)) + "가나".encode("utf-16-le")
    assert list(hwp._records(raw)) == [(hwp.TAG_PARA_TEXT, 3, "가나".encode("utf-16-le"))]


def test_kinds_and_scanned_pdf():
    blank = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
             b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    with pytest.raises(pdf.ScannedPDF):
        parse_bytes(blank, "pdf")
    assert kind_of(b"SCDSA004\0", "pdf") == "drm"
    assert kind_of(b"\xff\xd8\xff\xe0", "jpg") == "image" and kind_of(b"\xef\xbb\xbf<html>", "xls") == "html"
