"""na_ntt 어댑터 — 가상 HTML (실데이터·실명 없음)."""
from src.phase3_collect.boards import adapter_for, na_ntt

BOARD = "https://www.edu.example/site/na/ntt/selectNttList.do?mi=100&bbsId=7"
LIST = """<table><tbody>
<tr><td>2</td><td class="ta_l"><a href="javascript:" data-id="501" class="nttInfoBtn"> 2026년 9월 교육장 업무추진비 집행내역 </a></td>
    <td>작성자 홍길동</td><td><em class="mTit">등록일</em> 2026.10.02</td></tr>
<tr><td>1</td><td class="ta_l"><a href="javascript:" data-id="500" class="nttInfoBtn">2024년 10월 집행내역</a></td>
    <td>작성자 홍길동</td><td>2024.10.05</td></tr>
</tbody></table>
<a onclick="goPaging(2)">2</a><a onclick="goPaging(9)">끝</a>"""
DETAIL = """<script>
DEXT5UPLOAD.AddUploadedFile("abc", "2026년 9월 업무추진비.xlsx", "/upload/site/na/bbs_7/2026/10/x.xlsx", "11889", "abc", G_UploadID);
DEXT5UPLOAD.AddUploadedFile("def", "증빙.pdf", "/upload/site/na/bbs_7/2026/10/y.pdf", "", "def", G_UploadID);
</script>"""


def test_matches():
    assert adapter_for(BOARD) is na_ntt
    assert adapter_for("https://x.go.kr/bbs/list.do") is None


def test_list_posts_no_author():
    posts = na_ntt.list_posts(LIST, BOARD)
    assert posts == [
        {"title": "2026년 9월 교육장 업무추진비 집행내역", "date": "2026-10-02", "ntt_sn": "501",
         "url": "https://www.edu.example/site/na/ntt/selectNttInfo.do?mi=100&bbsId=7&nttSn=501"},
        {"title": "2024년 10월 집행내역", "date": "2024-10-05", "ntt_sn": "500",
         "url": "https://www.edu.example/site/na/ntt/selectNttInfo.do?mi=100&bbsId=7&nttSn=500"},
    ]
    assert "홍길동" not in str(posts)  # 작성자(PII)는 읽지 않음


def test_paging():
    assert na_ntt.last_page(LIST) == 9
    assert na_ntt.page_url(BOARD, 3) == BOARD + "&currPage=3"
    assert na_ntt.page_url(BOARD + "&currPage=3", 1) == BOARD


def test_attachments_file_list_variant():
    html = """<ul class="bbsV_file"><li>
      <a class="fileName" href="javaScript:goFileDown('k1');">[붙임] 2026년 3분기 집행내역.pdf</a>
      <a href="javascript:void(0);" onclick="previewAjax('https://www.edu.example/resource/na/bbs_7/z.pdf','[붙임] 2026년 3분기 집행내역.pdf')">미리보기</a>
    </li></ul>"""
    assert na_ntt.list_attachments(html, "https://www.edu.example/a/selectNttInfo.do") == [
        {"name": "[붙임] 2026년 3분기 집행내역.pdf", "url": "https://www.edu.example/resource/na/bbs_7/z.pdf", "ext": "pdf", "size": 0}]


def test_attachments():
    files = na_ntt.list_attachments(DETAIL, "https://www.edu.example/site/na/ntt/selectNttInfo.do?nttSn=501")
    assert files == [
        {"name": "2026년 9월 업무추진비.xlsx", "url": "https://www.edu.example/upload/site/na/bbs_7/2026/10/x.xlsx", "ext": "xlsx", "size": 11889},
        {"name": "증빙.pdf", "url": "https://www.edu.example/upload/site/na/bbs_7/2026/10/y.pdf", "ext": "pdf", "size": 0},
    ]
