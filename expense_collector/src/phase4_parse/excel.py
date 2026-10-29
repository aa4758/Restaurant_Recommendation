"""xlsx·xlsm·xls·csv → 시트별 격자. 병합 셀은 왼쪽 위에만 값이 있으므로 그대로 두고 헤더 쪽에서 이어 받는다."""
import io
import zipfile

import pandas as pd


def _without_custom_props(data: bytes) -> bytes:
    """openpyxl 이 일부 사용자 정의 속성(docProps/custom.xml)에서 TypeError → 그 부분만 뺀 사본."""
    src, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            if n != "docProps/custom.xml":
                z.writestr(n, src.read(n))
    return out.getvalue()


def grids(data: bytes, kind: str) -> list[list[list]]:
    if kind == "csv":
        for enc in ("utf-8-sig", "cp949"):
            try:
                return [pd.read_csv(io.BytesIO(data), header=None, dtype=str, encoding=enc).values.tolist()]
            except UnicodeDecodeError:
                continue
        raise ValueError("CSV 인코딩(utf-8-sig·cp949) 판별 실패")
    engine = "xlrd" if kind == "xls" else "openpyxl"
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=str, engine=engine)
    except TypeError:
        if kind == "xls":
            raise
        sheets = pd.read_excel(io.BytesIO(_without_custom_props(data)), sheet_name=None, header=None, dtype=str, engine=engine)
    return [df.values.tolist() for df in sheets.values()]
