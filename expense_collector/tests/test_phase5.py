"""Phase 5 정규화·중복 제거·PII 마스킹·찐맛 export — 가상 값만(실명·실번호 없음)."""
import re

import pandas as pd

from src.phase5_merge import merge
from src.phase5_merge import normalize as nz


def test_map_columns():
    cols = ["연번", "사용일자(일시)", "사용장소 (가맹점명)", "사용목적(내역) * 사용대상 포함", "대상 인원수", "참석자/대상",
            "사용금액(원)", "결제 방법", "사용자", "비고(잔액)", "알수없음"]
    m = nz.map_columns(cols)
    assert m["사용일자(일시)"] == "exec_date" and m["사용장소 (가맹점명)"] == "vendor_raw"
    assert m["사용목적(내역) * 사용대상 포함"] == "purpose" and m["대상 인원수"] == "headcount"
    assert m["참석자/대상"] == "attendees" and m["사용금액(원)"] == "amount" and m["결제 방법"] == "payment_method"
    assert m["사용자"] == "executor_position" and m["연번"] == m["비고(잔액)"] == "ignore" and "알수없음" not in m
    assert nz.map_columns(["계약일자", "예정가격 (A)", "계약금액 (B)"]) is None
    assert nz.map_columns(["일자", "일시", "금액"])["일시"] == "ignore"  # 같은 표준 칸 두 번째


def test_parse_date():
    ref = "2026-01-10"
    cases = {"2025-03-04 12:30:00": ("2025-03-04", "12:30", False), "2025.3.4.": ("2025-03-04", "", False),
             "25-03-04 09:05": ("2025-03-04", "09:05", False), "2025. 3. 4. 12:30": ("2025-03-04", "12:30", False),
             "20250304": ("2025-03-04", "", False), "2025년 3월 4일": ("2025-03-04", "", False),
             "1.5.(월) 12:00": ("2026-01-05", "12:00", True), "12.25.": ("2025-12-25", "", True),  # 게시일 다음 해 → 전년
             "10.05. 12:30": ("2025-10-05", "12:30", True), "45720": ("2025-03-04", "", False),
             "합계": ("", "", False), "2025-02-30": ("", "", False)}
    for s, want in cases.items():
        assert nz.parse_date(s, ref) == want, s
    assert nz.parse_date("3.4.", None)[0] == ""
    assert nz.parse_time("0.5") == "12:00"


def test_amount_headcount():
    assert nz.parse_amount("120,000원") == 120000 and nz.parse_amount("1 20,000") == 120000
    assert nz.parse_amount("99.000") == 99000 and nz.parse_amount("150", thousand=True) == 150000
    assert nz.parse_amount("서구 둔산로 12") is None and nz.parse_amount("-") is None and nz.parse_amount("0") is None
    assert nz.parse_amount("12345678901234567890") is None
    assert nz.parse_headcount("8") == 8 and nz.parse_headcount("직원 등 12명", need_unit=True) == 12
    assert nz.parse_headcount("2팀 관계자", need_unit=True) is None


def test_mask_pii():
    assert nz.mask_pii("자원관리과장 가나다") == "자원관리과장 ○○○"
    assert nz.mask_pii("부시장 가나다 등 5명 오찬") == "부시장 ○○○ 등 5명 오찬"
    assert nz.mask_pii("가나다 외 3명 간담회") == "○○○ 외 3명 간담회"
    assert nz.mask_pii("라마바 과장") == "○○○ 과장"
    assert nz.mask_pii("학교신축과 신축2팀장 가나국") == "학교신축과 신축2팀장 ○○○"
    assert nz.mask_pii("자문위원 부위원장 가나다 등 신임위원 위촉에 따른 식사") == "자문위원 부위원장 ○○○ 등 신임위원 위촉에 따른 식사"
    assert nz.mask_pii("가나다님 외") == "○○○님 외" and nz.mask_pii("가나다외 2명") == "○○○외 2명"
    assert nz.mask_pii("문의 010-1234-5678") == "문의 ○○○" and nz.mask_pii("02-123-4567") == "○○○"
    assert nz.mask_pii("카드 1234-****-****-5678") == "카드 ○○○"
    kept = "총무과 직원 등 10명 격려 오찬"  # 조직·일반 명사는 그대로
    assert nz.mask_pii(kept) == kept and nz.mask_pii("직원 외 3명") == "직원 외 3명"
    assert nz.position_only("자원관리과장 가나다") == "자원관리과장" and nz.position_only("가나다") == ""
    assert nz.position_only("구청장") == "구청장"


def test_vendor_and_category():
    assert nz.normalize_vendor("(주)가나식당 시청점") == "가나식당"
    assert nz.normalize_vendor("가나식당(시흥대로 15)") == "가나식당" and nz.normalize_vendor("가나식당 외 1곳") == "가나식당"
    assert nz.normalize_vendor(nz.mask_pii("과장 가나다 외 1")) == "" and nz.normalize_vendor("합 계") == ""
    assert nz.normalize_vendor("과장, 주무팀장") == ""
    assert nz.categorize("가나칼국수", "") == "restaurant" and nz.categorize("다라커피", "") == "cafe"
    assert nz.categorize("마바마트", "오찬") == "other" and nz.categorize("사아", "직원 격려 오찬") == "restaurant"
    assert nz.categorize("사아", "회의") == "unknown"


def test_records_drop_and_mask():
    cols = {"일자": "exec_date", "사용처": "vendor_raw", "목적": "purpose", "참석자": "attendees", "금액": "amount"}
    rows = [{"일자": "10.05.", "사용처": "가나식당", "목적": "부시장 가나다 등 오찬", "참석자": "가나다, 라마바 등 6명", "금액": "60,000"},
            {"일자": "", "사용처": "합계", "목적": "", "참석자": "", "금액": "60,000"},
            {"일자": "", "사용처": "다라식당", "목적": "", "참석자": "", "금액": "1,000"},  # 병합 칸 → 윗 날짜
            {"일자": "", "사용처": "(시청점)", "목적": "", "참석자": "", "금액": ""},  # 줄바꿈 이어진 행
            {"일자": "3월 중", "사용처": "마바식당", "목적": "", "참석자": "", "금액": "2,000"}]
    out, drop = nz.records(rows, cols, dict(file_id=1, table_index=0, post_date="2025-11-03", parse_confidence=1.0))
    assert drop == {"total": 1, "no_date": 2, "empty": 0} and len(out) == 2
    assert out[1]["exec_date"] == "2025-10-05" and out[1]["amount"] == 1000
    r = out[0]
    assert r["exec_date"] == "2025-10-05" and r["parse_confidence"] == 0.9 and r["headcount"] == 6
    assert r["purpose"] == "부시장 ○○○ 등 오찬" and "attendees" not in r and "가나다" not in str(r)


def _df(rows):
    base = {c: "" for c in merge.COLUMNS}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_dedupe_prefers_datagokr():
    a = dict(institution_id="1", exec_date="2025-10-05", amount=60000, vendor_normalized="가나식당", parse_confidence=1.0)
    df = _df([{**a, "record_id": "b", "source": "BOARD"}, {**a, "record_id": "d", "source": "DATAGOKR", "parse_confidence": 0.7},
              {**a, "record_id": "x", "source": "BOARD", "amount": 50000},
              {**a, "record_id": "p1", "source": "BOARD", "vendor_normalized": "", "purpose": "오찬"},
              {**a, "record_id": "p2", "source": "BOARD", "vendor_normalized": "", "purpose": "만찬"},
              {**a, "record_id": "v", "source": "BOARD", "executor_position": "부시장"}])  # 다른 직위 = 다른 집행
    assert sorted(merge.dedupe(df)["record_id"]) == ["d", "p1", "p2", "v", "x"]


def test_jjinmat_export_contract():
    common = dict(institution_name="가상시", exec_date="2025-10-05", amount=60000, source="BOARD", license="공공누리 1유형",
                  executor_position="부시장", headcount=6, department="총무과")
    df = _df([{**common, "vendor_normalized": "가나식당", "vendor_category": "restaurant", "parse_confidence": 0.9,
               "purpose": "부시장 가나다 등 오찬 010-1234-5678"},
              {**common, "vendor_normalized": "다라커피", "vendor_category": "cafe", "parse_confidence": 0.9},
              {**common, "vendor_normalized": "마바식당", "vendor_category": "restaurant", "parse_confidence": 0.5}])
    ex = merge.to_jjinmat(df, ["restaurant"], 0.7)
    assert list(ex.columns) == ["restaurant_name", "address", "exec_date", "agency", "amount", "purpose", "source", "base_year"]
    assert ex["restaurant_name"].tolist() == ["가나식당"] and ex["base_year"].tolist() == ["2025"]
    assert ex["source"].iloc[0] == "가상시 업무추진비 공개(BOARD, 공공누리 1유형)"
    text = ex.to_csv(index=False)
    assert "가나다" not in text and not re.search(r"01\d-?\d{3,4}-?\d{4}|\d{4}-\d{4}-\d{4}-\d{4}", text)
    assert "공직자" not in text
