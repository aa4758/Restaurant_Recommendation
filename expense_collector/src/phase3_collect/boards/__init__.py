"""CMS 별 게시판 어댑터. 각 모듈: ID, matches(board_url), page_url, last_page, list_posts, list_attachments."""
from src.phase3_collect.boards import na_ntt

ADAPTERS = [na_ntt]


def adapter_for(board_url: str):
    return next((a for a in ADAPTERS if a.matches(board_url)), None)
