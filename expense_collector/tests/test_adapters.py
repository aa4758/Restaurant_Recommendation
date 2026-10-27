"""egov_bbs · sen_fus · gwanak_estimate 어댑터 — 가상 HTML (실데이터·실명 없음)."""
from src.phase3_collect.boards import adapter_for, egov_bbs, gwanak_estimate, sen_fus

EGOV = "https://www.min.example/frt/bbs/type001/commonSelectBoardList.do?bbsId=BBSMSTR_000000000186"
SEN = "http://open.sen.example/fus/MI0001/board/BO0002/ctgynone/list0010v.do"
GW = "https://www.gu.example/site/gu/estimate/estimateList.do"


def test_routing():
    assert adapter_for(EGOV) is egov_bbs
    assert adapter_for(SEN.replace("sen.example", "sen.go.kr")) is sen_fus
    assert adapter_for(GW) is gwanak_estimate


def test_egov():
    html = """<a href="/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=X&nttId=1">메뉴 링크</a>
    <table><tr><td>265</td><td class="l"><a href="/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000186&amp;nttId=130462">실 업무추진비 공개내역(2026년 7월~9월)</a></td>
    <td>기획과</td><td> 2026.10.23.</td></tr></table>
    <a onclick="fn_egov_select_noticeList('27')">끝</a>"""
    assert egov_bbs.list_posts(html, EGOV) == [{
        "title": "실 업무추진비 공개내역(2026년 7월~9월)", "date": "2026-10-23", "ntt_sn": "130462",
        "url": "https://www.min.example/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000186&nttId=130462"}]
    assert egov_bbs.last_page(html) == 27
    assert egov_bbs.page_url(EGOV, 2) == EGOV + "&pageIndex=2"
    att = '<a href="/cmm/fms/FileDown.do?atchFileId=F1&amp;fileSn=0"><img alt="첨부파일"/> 집행내역(7월~9월).xlsx &nbsp;[ 13.2 KB ]</a>'
    assert egov_bbs.list_attachments(att, "https://www.min.example/frt/x") == [
        {"name": "집행내역(7월~9월).xlsx", "url": "https://www.min.example/cmm/fms/FileDown.do?atchFileId=F1&fileSn=0", "ext": "xlsx", "size": 0}]


def test_sen():
    html = """<table><tr><td>237</td><td class="tit"><a href="javascript:fncDetailView('30213');"> 2026년 8월 교육감 업무추진비 사용내역 공개 </a></td>
    <td><img alt="첨부"/></td><td>홍길동</td><td>2026-09-09</td></tr></table><a onclick="fncSearch(24)">끝</a>"""
    posts = sen_fus.list_posts(html, SEN)
    assert posts == [{"title": "2026년 8월 교육감 업무추진비 사용내역 공개", "date": "2026-09-09", "ntt_sn": "30213",
                      "url": "http://open.sen.example/fus/MI0001/board/BO0002/ctgynone/view0010v.do?board_seq=30213"}]
    assert "홍길동" not in str(posts)
    assert sen_fus.last_page(html) == 24
    att = """<a class="file_img" href='/fus/file/down0010f.do?attach_file_id=1&amp;file_seq=1' title="1. 2026년 8월 사용내역.xlsx 파일 다운로드">x</a>"""
    assert sen_fus.list_attachments(att, posts[0]["url"]) == [
        {"name": "1. 2026년 8월 사용내역.xlsx", "url": "http://open.sen.example/fus/file/down0010f.do?attach_file_id=1&file_seq=1", "ext": "xlsx", "size": 0}]


def test_gwanak_inline():
    rec = """<table class="view"><tbody><tr><th>비목</th><td>시책추진</td><th>집행부서</th><td>가과</td>
      <th scope="row">집행일시</th><td>2026-10-26&nbsp;&nbsp;12:08:16</td></tr>
      <tr><th>집행장소</th><td>가게(서울 가구 가로 1)</td><th>집행금액(원)</th><td>52,500</td></tr></tbody></table>"""
    html = rec + rec.replace("2026-10-26", "2024-10-01") + '<a onclick="doBbsFPag(312);return false;">끝</a>'
    assert gwanak_estimate.INLINE
    assert [p["date"] for p in gwanak_estimate.list_posts(html, GW)] == ["2026-10-26", "2024-10-01"]
    assert gwanak_estimate.last_page(html) == 312
    assert gwanak_estimate.page_url(GW, 3) == GW + "?pageIndex=3"
    assert gwanak_estimate.list_attachments(html, GW) == []


def test_dom_board():
    from src.phase3_collect.boards import dom_board
    board = "https://www.edu.example/finance/board/list.jbe?menuCd=DOM_000000001&boardId=BBS_0000359&categoryCode1=A06"
    assert adapter_for(board) is dom_board and not dom_board.matches("https://x.example/board/list.do?boardId=7")
    html = """<ul><li><a href="/board/view.do?boardId=BBS_1&menuCd=DOM_2&dataSid=9">메뉴</a></li></ul>
    <table><tr><td>130</td><td><a href="/board/view.jbe?boardId=BBS_0000359&amp;startPage=1&amp;dataSid=1187" title="2026-09-30 업무추진비">2026-09-30 업무..</a></td>
    <td>홍길동</td><td>26.10.08</td></tr>
    <tr><td><a href="/board/view.jbe?boardId=BBS_0000359&amp;dataSid=1100">9월 사용내역</a></td><td>26.10.08</td></tr></table>
    <a href="/board/list.jbe?boardId=BBS_0000359&amp;startPage=328" class="next2">마지막 페이지</a>"""
    posts = dom_board.list_posts(html, board)
    assert [(p["title"], p["date"], p["ntt_sn"]) for p in posts] == [
        ("2026-09-30 업무추진비", "2026-09-30", "1187"), ("9월 사용내역", "2026-10-08", "1100")]
    assert "홍길동" not in str(posts)
    assert dom_board.last_page(html) == 328 and dom_board.page_url(board, 2).endswith("startPage=2")
    det = """<a href="/finance/board/download.jbe?dataSid=1187&amp;fileSid=7" title="2026.9. 사용내역 .xlsx" class="ico_file">2026.9. 사용내역 .xlsx (15 kb)</a>
    <a href="/finance/board/download.jbe?dataSid=1187&amp;fileSid=7" class="ico_viewer" title="전용뷰어">바로보기</a>
    <a href="/board/download.do?dataSid=1&amp;fileSid=8">내역.pdf(10 kb)</a><a href="/board/download.do?fileSid=9" title="표.hwpx 다운받기">x</a>"""
    assert [(f["name"], f["ext"]) for f in dom_board.list_attachments(det, "https://www.edu.example/board/view.jbe")] == [
        ("2026.9. 사용내역.xlsx", "xlsx"), ("내역.pdf", "pdf"), ("표.hwpx", "hwpx")]


def test_kedufine():
    from src.phase3_collect.boards import kedufine
    board = "https://www.edu.example/kedufine/ir/selectJobPrtnCtList.do?mi=17708&orgCode=R1"
    assert adapter_for(board) is kedufine
    html = """<table><tbody><tr><td>33</td><td>2026</td><td>가교육지원청 행정과</td>
    <td><a href="#none" onclick="selectDetailView('669019','603816');">간담회비 지급</a></td><td>1,760,000</td><td>2026-09-14</td></tr></tbody></table>
    <a onclick="goPaging(8)">8</a>"""
    post = kedufine.list_posts(html, board)[0]
    assert post == {"title": "간담회비 지급", "date": "2026-09-14", "ntt_sn": "669019",
                    "url": "https://www.edu.example/kedufine/ir/selectJobPrtnCtView.do?mi=17708&jobPrtnCtSn=669019&ifEsbSeqNo=603816"}
    assert kedufine.last_page(html) == 8
    assert "inpBdt=2000%2F01%2F01" in kedufine.page_url(board, 2) and kedufine.page_url(board, 2).endswith("currPage=2")
    assert kedufine.list_attachments("", post["url"]) == [{"name": "669019.html", "url": post["url"], "ext": "html", "size": 0}]


def test_bbs_ntt():
    from src.phase3_collect.boards import bbs_ntt
    board = "https://www.gu.example/www/selectBbsNttList.do?bbsNo=14&key=331"
    assert adapter_for(board) is bbs_ntt
    html = """<table><tbody><tr><td>315</td><td class="p-subject"><a href="./selectBbsNttView.do?key=331&amp;bbsNo=14&amp;nttNo=149439&amp;pageIndex=1">
    2026년 9월 업무추진비 </a></td><td><span class="p-icon">xlsx 파일 첨부</span></td><td> 2026.10.21 </td></tr></tbody></table>
    <a href="?pageIndex=32">끝</a>"""
    assert bbs_ntt.list_posts(html, board) == [{"title": "2026년 9월 업무추진비", "date": "2026-10-21", "ntt_sn": "149439",
        "url": "https://www.gu.example/www/selectBbsNttView.do?key=331&bbsNo=14&nttNo=149439&pageIndex=1"}]
    assert bbs_ntt.last_page(html) == 32
    det = """<a href="./downloadBbsFile.do?atchmnflNo=55050" class="p-attach__link"><span class="p-icon p-icon__xlsx">xlsx 문서</span>
    1. 사용내역(3분기).xlsx &nbsp;</a><a href="./downloadBbsFileAll.do?atchmnflNo=1">전체 압축 파일 받기</a>"""
    assert bbs_ntt.list_attachments(det, "https://www.gu.example/www/selectBbsNttView.do") == [
        {"name": "1. 사용내역(3분기).xlsx", "url": "https://www.gu.example/www/downloadBbsFile.do?atchmnflNo=55050", "ext": "xlsx", "size": 0}]
    det = """<div><span><img alt="xlsx"/>1동 업무추진비(9월).xlsx</span><a href="/www/downloadBbsFile.do?atchmnflNo=2">다운로드</a></div>
    <a href="downloadBbsFileStr.do?bbsNo=31&amp;atchmnflStr=X"><span class="p-icon">pdf 파일</span><span>9월 내역.pdf (pdf, 40.5 KB)</span><svg><title>파일다운로드</title></svg></a>
    <a href="/staff/downloadBbsFile.do?atchmnflNo=9">안내서</a>"""
    assert [(f["name"], f["ext"]) for f in bbs_ntt.list_attachments(det, "https://www.gu.example/www/v")] == [
        ("1동 업무추진비(9월).xlsx", "xlsx"), ("9월 내역.pdf", "pdf")]


def test_board_cnts():
    from src.phase3_collect.boards import board_cnts
    board = "https://www.edu.example/boardCnts/listRenew.do?boardID=10150&m=041209&s=moe"
    assert adapter_for(board) is board_cnts
    html = """<table><tbody><tr><td>205</td><td><a href="#" onclick="javascript:goView('10150', '107066', '0', null, 'W', '1', 'N', '');">
    2026년 6월 업무추진비 사용내역 </a></td><td>정**</td><td>2026-08-28</td></tr></tbody></table><a href="?page=21&amp;m=1">끝</a>"""
    assert board_cnts.list_posts(html, board) == [{"title": "2026년 6월 업무추진비 사용내역", "date": "2026-08-28", "ntt_sn": "107066",
        "url": "https://www.edu.example/boardCnts/viewRenew.do?boardID=10150&boardSeq=107066&lev=0&statusYN=W&m=041209&s=moe"}]
    assert board_cnts.last_page(html) == 21
    det = """<a href='/boardCnts/fileDown.do?m=1&s=x&fileSeq=a1'>(가)2026년 9월 사용내역.hwp</a>
    <li> 6월 사용 내역.xlsx [ 13.6 KB ] <a href="/boardCnts/fileDown.do?m=1&amp;s=x&amp;fileSeq=b2" title="다운로드"><span>다운로드</span></a></li>"""
    assert [(f["name"], f["ext"]) for f in board_cnts.list_attachments(det, board)] == [
        ("(가)2026년 9월 사용내역.hwp", "hwp"), ("6월 사용 내역.xlsx", "xlsx")]


def test_egov_variants():
    board = "https://www.gun.example/cop/bbs/BBSMSTR_000000000096/selectBoardList.do"
    assert adapter_for(board) is egov_bbs
    html = """<table><tr><td>2636</td><td><a href="/cop/bbs/BBSMSTR_000000000096/selectBoardArticle.do?nttId=212545&amp;pageIndex=1">관광과 업무추진비(7월~9월)</a></td>
    <td>관광과</td><td class="date">2026-10-23</td></tr></table><a onclick="linkPage(264)">끝</a>"""
    assert [(p["ntt_sn"], p["date"]) for p in egov_bbs.list_posts(html, board)] == [("212545", "2026-10-23")]
    assert egov_bbs.last_page(html) == 264
    det = """<script>function fn_egov_downFile(a, s){ window.open("/np/cmm/fms/FileDown.do;jsessionid=AB.c1?atchFileId="+a+"&fileSn="+s); }</script>
    <a href="#" onclick="fn_egov_downFile('FILE_1','0'); return false;" title="첨부파일 다운로드, 파일명 : 9월 집행현황.pdf"> 9월 집행현황.pdf(0.06MB)</a>
    <a href="javascript:fn_egov_downFile('FILE_2','1')">3분기 내역.hwp &nbsp;[0.086&nbsp;mbyte]</a>
    <a href="/kfsweb/cmm/fms/FileDown.do;jsessionid=Z.e5?atchFileId=AF_3&amp;fileSn=0" aria-label="차장 내역.xlsx 다운로드">다운로드</a>
    <a alt="위원장 내역.xlsx" href="#LINK" onclick="javascript:fn_egov_downFile('FILE_4','1','xlsx')" title="첨부파일 다운로드">다운로드</a>"""
    assert [(f["name"], f["url"]) for f in egov_bbs.list_attachments(det, "https://www.gun.example/np/x")] == [
        ("9월 집행현황.pdf", "https://www.gun.example/np/cmm/fms/FileDown.do?atchFileId=FILE_1&fileSn=0"),
        ("3분기 내역.hwp", "https://www.gun.example/np/cmm/fms/FileDown.do?atchFileId=FILE_2&fileSn=1"),
        ("차장 내역.xlsx", "https://www.gun.example/kfsweb/cmm/fms/FileDown.do?atchFileId=AF_3&fileSn=0"),
        ("위원장 내역.xlsx", "https://www.gun.example/np/cmm/fms/FileDown.do?atchFileId=FILE_4&fileSn=1")]


def test_scms_web():
    from src.phase3_collect.boards import scms_web
    board = "https://www.gun.example/00099/00146/00171.web"
    assert adapter_for(board) is scms_web
    html = """<ul><li><a href="https://www.gun.example/06996.web?amode=view">나의 맞춤정보</a></li>
    <li class="li1"><div><a class="a1" href="?gcode=2&amp;idx=172&amp;amode=view&amp;"><span><strong class="t1"> 2026년 9월 업무추진비 <img alt="xlsx"/></strong>
    <i><span class="t3"><b>게시물번호 : 201</b></span><span class="t3">2026-10-08</span><span class="t3"> 행정과 </span></i></span></a></div></li></ul>
    <a href="?gcode=2&amp;cpage=21" title="맨끝 페이지">»</a>"""
    assert scms_web.list_posts(html, board) == [{"title": "2026년 9월 업무추진비", "date": "2026-10-08", "ntt_sn": "172",
        "url": "https://www.gun.example/00099/00146/00171.web?gcode=2&idx=172&amode=view&"}]
    assert scms_web.last_page(html) == 21 and scms_web.page_url(board, 3) == board + "?cpage=3"
    det = """<a class="filename" href="/board/download.do?idx=172&amp;fnum=1&amp;gcode=2">업무추진비 2026. 9.(군수).xlsx(15.3 KB)</a>"""
    assert scms_web.list_attachments(det, board) == [{"name": "업무추진비 2026. 9.(군수).xlsx", "ext": "xlsx", "size": 0,
        "url": "https://www.gun.example/board/download.do?idx=172&fnum=1&gcode=2"}]
    table = """<table><tr><td>17454</td><td><a class="cv3" href="?gcode=1036&amp;idx=886399&amp;amode=view&amp;">(국) 7월~9월 업무추진비 <i class="ic1 new"><span class="t1">새 글</span></i></a></td>
    <td> 추진단 </td><td>2026-10-26</td></tr></table>"""
    assert [(p["title"], p["date"], p["ntt_sn"]) for p in scms_web.list_posts(table, board)] == [("(국) 7월~9월 업무추진비", "2026-10-26", "886399")]


def test_portal_bbs():
    from src.phase3_collect.boards import portal_bbs
    board = "https://www.gun.example/portal/bbs/list.do?ptIdx=226&mId=0305010000"
    assert adapter_for(board) is portal_bbs
    html = """<table><tr><td>685</td><td><a href="#" onclick="goTo.view('list','204431','226','0305010000'); return false;"> 3/4분기 업무추진비 </a></td>
    <td>총무과</td><td>2026-10-22</td></tr></table><a onclick="goPage(69)">끝</a>"""
    assert portal_bbs.list_posts(html, board) == [{"title": "3/4분기 업무추진비", "date": "2026-10-22", "ntt_sn": "204431",
        "url": "https://www.gun.example/portal/bbs/view.do?mId=0305010000&bIdx=204431&ptIdx=226"}]
    assert portal_bbs.last_page(html) == 69 and portal_bbs.page_url(board, 3).endswith("page=3")
    det = """<a href="#" onclick="fn_egov_downFile('6bcd','f9a1'); return false;"><span>총무과 사용내역.pdf</span>&nbsp;[48.8 KByte]</a>"""
    assert portal_bbs.list_attachments(det, board) == [{"name": "총무과 사용내역.pdf", "ext": "pdf", "size": 0,
        "url": "https://www.gun.example/cmm/fms/FileDown.do?atchFileId=6bcd&fileSn=f9a1"}]
    yh = """<a href="#" onclick=" yhLib.file.download('7cb3','f9a1'); return false;" class="download"><span> 사용내역(2026.9.).pdf </span></a>"""
    assert [(f["name"], f["url"]) for f in portal_bbs.list_attachments(yh, board)] == [
        ("사용내역(2026.9.).pdf", "https://www.gun.example/common/file/download.do?atchFileId=7cb3&fileSn=f9a1")]
