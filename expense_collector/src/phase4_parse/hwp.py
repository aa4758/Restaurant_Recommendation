"""한글 문서 → 표 격자.

- hwpx: zip 안 `Contents/section*.xml` 의 `hp:tbl` → `hp:tc`(cellAddr·cellSpan). 칸 안의 중첩 표 글자는 그 표 몫.
- hwp(HWP5): OLE `BodyText/Section*` 레코드(압축이면 raw deflate). 표 = CTRL_HEADER('tbl ') → TABLE(행·칸 수)
  → 칸마다 LIST_HEADER(칸 주소·병합) + PARA_TEXT. 배포용·암호 문서는 읽지 않는다(EncryptedHWP).
병합 칸은 html 과 같이 값을 복제한다.
"""
import io
import re
import struct
import zipfile
import zlib

import olefile
from lxml import etree

TAG_PARA_TEXT, TAG_CTRL_HEADER, TAG_LIST_HEADER, TAG_TABLE = 0x43, 0x47, 0x48, 0x4D


class EncryptedHWP(Exception):
    pass


def _fill(cells: list[tuple[int, int, int, int, str]]) -> list[list[str]]:
    """(row, col, rowspan, colspan, text) → 격자."""
    if not cells:
        return []
    nr = max(r + rs for r, _, rs, _, _ in cells)
    nc = max(c + cs for _, c, _, cs, _ in cells)
    grid = [[""] * nc for _ in range(nr)]
    for r, c, rs, cs, t in cells:
        for i in range(r, r + rs):
            for j in range(c, c + cs):
                grid[i][j] = t
    return grid


def hwpx_grids(data: bytes) -> list[list[list[str]]]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)):
            root = etree.fromstring(z.read(name))
            for tbl in root.iter("{*}tbl"):
                cells = []
                for tc in tbl.iter("{*}tc"):
                    if next(tc.iterancestors("{*}tbl")) is not tbl:
                        continue
                    addr, span = tc.find("{*}cellAddr"), tc.find("{*}cellSpan")
                    text = " ".join(t.text or "" for t in tc.iter("{*}t") if next(t.iterancestors("{*}tbl")) is tbl)
                    cells.append((int(addr.get("rowAddr")), int(addr.get("colAddr")),
                                  int(span.get("rowSpan", 1)) if span is not None else 1,
                                  int(span.get("colSpan", 1)) if span is not None else 1, text))
                out.append(_fill(cells))
    return out


def _records(buf: bytes):
    i = 0
    while i + 4 <= len(buf):
        h = struct.unpack_from("<I", buf, i)[0]
        tag, level, size = h & 0x3FF, (h >> 10) & 0x3FF, h >> 20
        i += 4
        if size == 0xFFF:
            size = struct.unpack_from("<I", buf, i)[0]
            i += 4
        yield tag, level, buf[i:i + size]
        i += size


def _para_text(b: bytes) -> str:
    out, i = [], 0
    while i + 2 <= len(b):
        ch = struct.unpack_from("<H", b, i)[0]
        if ch in (10, 13) or 24 <= ch <= 31 or ch == 0:
            out.append(" " if ch in (10, 13) else "")
            i += 2
        elif ch < 32:  # 확장·인라인 컨트롤: 8 WCHAR
            i += 16
        else:
            out.append(chr(ch))
            i += 2
    return "".join(out)


def record_tables(records) -> list[list[list[str]]]:
    """(tag, level, data) 레코드열 → 표 격자들. 중첩 표는 레벨로 구분."""
    out, stack = [], []  # stack: [{"level", "cells"}]
    for tag, level, d in records:
        while stack and level <= stack[-1]["level"]:
            out.append(_fill(stack.pop()["cells"]))
        if tag == TAG_CTRL_HEADER and d[:4] == b" lbt":
            stack.append({"level": level, "cells": []})
        elif stack and tag == TAG_LIST_HEADER and level == stack[-1]["level"] + 1 and len(d) >= 16:
            col, row, cs, rs = struct.unpack_from("<4H", d, 8)
            stack[-1]["cells"].append([row, col, max(rs, 1), max(cs, 1), ""])
        elif stack and tag == TAG_PARA_TEXT and stack[-1]["cells"]:
            cell = stack[-1]["cells"][-1]
            cell[4] = (cell[4] + " " + _para_text(d)).strip()
    while stack:
        out.append(_fill(stack.pop()["cells"]))
    return [g for g in out if g]


def hwp_grids(data: bytes) -> list[list[list[str]]]:
    ole = olefile.OleFileIO(io.BytesIO(data))
    flags = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
    if flags & 0b110:
        raise EncryptedHWP("암호·배포용 HWP — 읽지 않음")
    sections = sorted((s for s in ole.listdir() if s[0] == "BodyText"), key=lambda s: int(re.sub(r"\D", "", s[1]) or 0))

    def records():
        for s in sections:
            buf = ole.openstream(s).read()
            yield from _records(zlib.decompress(buf, -15) if flags & 1 else buf)
    return record_tables(records())
