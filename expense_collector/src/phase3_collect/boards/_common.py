"""어댑터 공통 도우미."""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

DATE = re.compile(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})")


def iso_date(text: str) -> str | None:
    m = DATE.search(text or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def with_param(url: str, key: str, value, drop_if=None) -> str:
    """url 의 쿼리에서 key 를 value 로 바꾼다(value == drop_if 면 제거)."""
    p = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(p.query).items() if k != key}
    if value != drop_if:
        q[key] = str(value)
    return p._replace(query=urlencode(q)).geturl()


def max_call_arg(html: str, func: str) -> int:
    """onclick="func(3)" / func('3') 중 가장 큰 숫자 = 마지막 페이지(보이는 범위 내)."""
    return max((int(n) for n in re.findall(rf"{func}\(\s*'?(\d+)'?", html)), default=1)


def file_entry(name: str, url: str, base: str, size: int = 0) -> dict:
    name = re.sub(r"\s*[\[(]\s*(\w+,)?[\d.,\s]*[kmg]?b\s*[\])]$", "", re.sub(r"\s+", " ", name).strip(), flags=re.I)  # '(15 kb)'·'(xlsx, 28.1KB)'
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"name": name, "url": urljoin(base, url), "ext": ext, "size": size}
