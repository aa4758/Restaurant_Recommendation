"""CMS 별 게시판 어댑터. 각 모듈: ID, INLINE(목록 HTML 자체가 원본인지), matches(board_url),
page_url(board_url, n), last_page(html), list_posts(html, board_url), list_attachments(html, post_url)."""
from src.phase3_collect.boards import bbs_ntt, board_cnts, dom_board, egov_bbs, gwanak_estimate, kedufine, na_ntt, portal_bbs, scms_web, sen_fus

ADAPTERS = [na_ntt, egov_bbs, sen_fus, gwanak_estimate, dom_board, kedufine, bbs_ntt, board_cnts, scms_web, portal_bbs]


def adapter_for(board_url: str):
    return next((a for a in ADAPTERS if a.matches(board_url)), None)
