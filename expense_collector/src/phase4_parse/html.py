"""HTML 본문·목록 표 → 격자. colspan·rowspan 은 값을 복제해 칸을 맞춘다."""
from bs4 import BeautifulSoup


def table_grid(table) -> list[list[str]]:
    grid, pending = [], {}  # pending[(row, col)] = rowspan 으로 내려온 값
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        row, c, r = [], 0, len(grid)
        for cell in tr.find_all(["td", "th"], recursive=False):
            while (r, c) in pending:
                row.append(pending.pop((r, c)))
                c += 1
            text = cell.get_text(" ", strip=True)
            cs, rs = int(cell.get("colspan", 1) or 1), int(cell.get("rowspan", 1) or 1)
            for k in range(cs):
                row.append(text)
                for d in range(1, rs):
                    pending[(r + d, c + k)] = text
            c += cs
        while (r, c) in pending:
            row.append(pending.pop((r, c)))
            c += 1
        grid.append(row)
    return grid


def grids(data: bytes) -> list[list[list[str]]]:
    soup = BeautifulSoup(data, "lxml")
    return [table_grid(t) for t in soup.find_all("table") if not t.find("table")]  # 바깥 배치용 표는 건너뜀
