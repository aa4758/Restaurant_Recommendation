"""세부 분류(subtype) — docs/01 '세부 분류 필터 + 자연어 조건 입력'.

판정 순서: ① 상호명 키워드 ② 상가정보 업종 소분류(sbiz_category) ③ 메뉴(menus) 키워드 다수결
          ④ 메뉴명 분류 모델(메뉴명에만, 확신도 0.8 이상). 상호명에는 모델을 쓰지 않음(표본 검토 결과 골프장·카페 등
          음식 아닌 상호를 절반 가까이 오분류). 세부 분류의 상위 장르로 genre 보정.
점수·순위에는 쓰지 않는다(필터·표시 전용).

    python -m app.subtype train <AI-Hub '관광 음식메뉴판 데이터' 폴더>   # 모델 학습 → data/models/menu_subtype.json
    python -m app.subtype assign [--db PATH] [--dry-run]                # 가게별 subtype·genre 갱신

모델: 글자 1~3그램 다항 나이브 베이즈(표준 라이브러리). 학습 라벨 = 메뉴명에 ① 규칙 적용, 안 되면 AI-Hub 음식 분류
중 대응이 확실한 것만(아래 AIHUB_MAP), 음료·주류는 '_drink'. AI-Hub 데이터는 학습용으로만 쓰고 원본을 저장·표시하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema

MODEL_PATH = BACKEND_DIR / "data" / "models" / "menu_subtype.json"

# (세부 분류, 상위 장르, 키워드 정규식) — 위에서부터 먼저 맞는 것(구체적인 것을 앞에).
# 2026-11-02 사용자 결정: 장르 16개·세부 분류 약 110개로 세분화(docs/01 '장르·세부 분류 세분화').
RULES = [
    # 뷔페 — 상호에 '뷔페'가 들어가면 다른 키워드(초밥·고기)보다 먼저
    ("해산물/초밥 뷔페", "뷔페", r"씨푸드|해산물뷔페|초밥뷔페|스시뷔페|쿠우쿠우|토다이|무스쿠스"),
    ("한식 뷔페", "뷔페", r"한식뷔페|한식부페|자연별곡|계절밥상|풀잎채"),
    ("고기 뷔페", "뷔페", r"고기뷔페|고기부페|명륜진사"),
    ("뷔페 일반", "뷔페", r"뷔페|부페|애슐리|buffet"),
    # 패밀리레스토랑(체인명)
    ("패밀리레스토랑", "양식", r"아웃백|빕스|티지아이|tgi|베니건스|패밀리레스토랑|매드포갈릭|토니로마스|칠리스"),
    # 중식
    ("마라탕/마라샹궈", "중식", r"마라|탕화쿵푸|라화쿵부"),
    ("훠궈", "중식", r"훠궈|하이디라오"),
    ("양꼬치", "중식", r"양꼬치|양뀀|양꼬지|꿔바로우"),
    ("딤섬", "중식", r"딤섬|샤오롱바오|소룡포|하가우|딘타이펑"),
    ("중화요리", "중식", r"중화요리|중식당|차이니즈|chinese|북경|상해|광동|홍콩반점|대만"),
    ("짜장/짬뽕", "중식", r"짜장|자장|짬뽕|탕수육|반점|중화|차이나|만리장성|중국집|중국성|중국관"),
    # 아시안·세계음식
    ("쌀국수/베트남", "아시안", r"쌀국수|베트남|포[보비]|분짜|반미|하노이|사이공|월남쌈|호치민|다낭|pho"),
    ("태국", "아시안", r"(?<!기|딘)타이(?!어|거|펑)|태국|팟타이|똠양|쏨땀|방콕|푸팟퐁"),
    ("인도네시아/말레이", "아시안", r"인도네시아|나시고렝|미고렝|말레이|싱가포르|락사|발리"),
    ("인도/네팔", "아시안", r"인도(?!어)|네팔|탄두리|(?<!베이)커리|마살라|티베트|비리야니"),
    ("기타 아시안", "아시안", r"필리핀|캄보디아|미얀마|라오스|스리랑카|아시안|동남아"),
    ("멕시칸", "세계음식", r"멕시(?!카나)|타코|브리또|부리또|부리토|퀘사디아|나쵸|화이타"),
    ("중동/터키", "세계음식", r"케밥|터키|튀르키예|할랄|중동|레바논|모로코|아랍|팔라펠|후무스|이집트"),
    ("러시아/중앙아시아", "세계음식", r"러시아|우즈벡|카자흐|샤슬릭|사마르칸트|몽골|키르기스"),
    ("유럽(스페인·독일 등)", "세계음식", r"스페인|빠에야|파에야|타파스|독일|슈니첼|소시지|그리스|포르투갈|헝가리"),
    ("남미", "세계음식", r"브라질|츄라스코|슈하스코|페루|아르헨|남미|쿠바"),
    # 일식
    ("오마카세/일식 코스", "일식", r"오마카세|가이세키|카이세키|갓포"),
    ("초밥/스시", "일식", r"초밥|스시|sushi|사시미"),
    ("라멘", "일식", r"라멘|돈코츠|츠케멘|ramen|멘야"),
    ("우동/소바", "일식", r"우동|소바|모밀|udon"),
    ("텐동/튀김", "일식", r"텐동|텐뿌라|덴뿌라|덴푸라"),
    ("돈까스", "일식", r"돈까스|돈가스|카츠|katsu|돈카츠"),
    ("덮밥/규동", "일식", r"규동|덮밥|돈부리|부타동|사케동|카이센동|오야꼬동"),
    ("일식 카레", "일식", r"카레|curry|코코이찌"),
    ("야키니쿠", "일식", r"야키니쿠|야끼니꾸|야키니꾸"),
    ("일식당", "일식", r"일식|일본식|와쇼쿠|일본가정식"),
    # 주점
    ("이자카야/꼬치", "주점", r"이자카야|이자까야|사케|오뎅바|로바다|선술집|야키토리|야끼도리|꼬치|쿠시"),
    ("와인바/바", "주점", r"와인|wine|bar$|칵테일|위스키|재즈바|라운지바|몰트|하이볼"),
    ("막걸리/전", "주점", r"막걸리|전집|빈대떡|부침개|파전|녹두|동동주|모듬전|지짐이"),
    ("포차", "주점", r"포차|포장마차"),
    ("호프/맥주", "주점", r"호프|맥주|비어|beer|펍|pub|브루|생맥"),
    ("요리주점/술집", "주점", r"주막|술집|요리주점|소주|대포|감성주점|주점|술상|노가리|쏘맥|한잔"),
    # 해산물
    ("장어", "해산물", r"장어"),
    ("복어", "해산물", r"복어|복집|복국|복요리|복지리"),
    ("물회", "해산물", r"물회"),
    ("참치", "해산물", r"참치|마구로"),
    ("대게/킹크랩", "해산물", r"대게|킹크랩|홍게|영덕게"),
    ("게장", "해산물", r"게장|꽃게"),
    ("아구찜/코다리", "해산물", r"아구|아귀|코다리|동태|명태|황태"),
    ("해물탕/해물찜", "해산물", r"해물탕|해물찜|해신탕|해물|해천탕"),
    ("낙지/주꾸미/오징어", "해산물", r"낙지|쭈꾸미|주꾸미|쭈꾸|오징어|문어"),
    ("조개/굴/전복", "해산물", r"조개|가리비|키조개|굴(?:찜|구이|요리|보쌈|전|밥|이랑|대박|하우스|집)|석화|꼬막|전복|멍게|해삼"),
    ("새우/랍스터", "해산물", r"새우|대하|랍스터|로브스터"),
    ("생선구이/조림", "해산물", r"생선구이|고등어|갈치|굴비|삼치|임연수|꽁치|생선|조림"),
    ("매운탕/민물", "해산물", r"매운탕|민물|메기|빠가|잡어|어탕|어죽|붕어|송어|향어"),
    ("회/횟집", "해산물", r"횟집|회센|활어|세꼬시|회수산|수산|회타운|회포차|생선회|회집|광어|우럭|방어"),
    # 국밥·탕·찌개
    ("순대국", "국밥/탕/찌개", r"순대국|순댓국"),
    ("돼지국밥", "국밥/탕/찌개", r"돼지국밥|밀양국밥"),
    ("곰탕/설렁탕", "국밥/탕/찌개", r"곰탕|설렁탕|도가니|사골|설농탕"),
    ("갈비탕", "국밥/탕/찌개", r"갈비탕"),
    ("육개장", "국밥/탕/찌개", r"육개장"),
    ("해장국/감자탕", "국밥/탕/찌개", r"감자탕|해장국|뼈해장|뼈다귀|선지|해장|우거지|내장탕"),
    ("추어탕", "국밥/탕/찌개", r"추어"),
    ("삼계탕/백숙", "국밥/탕/찌개", r"삼계탕|백숙|닭곰탕|능이|한방닭"),
    ("보신/흑염소", "국밥/탕/찌개", r"보신|흑염소|염소|영양탕|사철탕"),
    ("국밥", "국밥/탕/찌개", r"국밥|소머리|수육|콩나물국"),
    ("부대찌개", "국밥/탕/찌개", r"부대찌개|부대"),
    ("김치찌개", "국밥/탕/찌개", r"김치찌개|짜글이|돼지찌개|고추장찌개|김치찜"),
    ("된장/청국장", "국밥/탕/찌개", r"된장|청국장"),
    ("순두부/두부", "국밥/탕/찌개", r"순두부|두부|초당"),
    ("샤브샤브/전골", "국밥/탕/찌개", r"샤브|전골|스키야키|밀푀유|나베"),
    ("찌개/탕 기타", "국밥/탕/찌개", r"찌개|탕$|탕집"),
    # 고기·구이
    ("곱창/막창", "고기/구이", r"곱창|막창|대창|염통|특양"),
    ("양고기", "고기/구이", r"양갈비|램(?:플러스|양|갈비|촙|찹)|양고기|징기스칸|징스램"),
    ("고기 무한리필", "고기/구이", r"무한리필|셀프바"),
    ("돼지갈비", "고기/구이", r"돼지갈비|떡갈비|숯불갈비"),
    ("소고기/한우", "고기/구이", r"한우|소고기|차돌|등심|안심|육회|우대갈비|투뿔|정육식당|갈비살|우설|육사시미|소갈비|왕갈비|생갈비"),
    ("불고기", "고기/구이", r"불고기|석쇠"),
    ("삼겹살/돼지구이", "고기/구이", r"삼겹|오겹|목살|항정|가브리|대패|흑돼지|돼지구이|생고기|뒷고기|갈매기|껍데기|연탄|숯불|돼지"),
    ("닭갈비", "한식", r"닭갈비"),
    # 치킨
    ("닭강정", "치킨", r"닭강정|강정"),
    ("옛날통닭", "치킨", r"통닭|전기구이|장작구이"),
    ("치킨", "치킨", r"치킨|chicken|교촌|bhc|bbq|굽네|네네|페리카나|처갓집|호식이|60계|멕시카나|푸라닭|자담|또래오래|순살|후라이드|지코바"),
    ("고깃집 일반", "고기/구이", r"구이|고깃집|고기|정육|화로|바베큐|갈비|가든"),
    # 면요리
    ("냉면", "면요리", r"냉면|면옥|평양(?:면|냉|막국)|함흥"),
    ("밀면", "면요리", r"밀면"),
    ("막국수", "면요리", r"막국수|메밀"),
    ("칼국수/수제비", "면요리", r"칼국수|수제비|칼제비|손칼|바지락"),
    ("국수", "면요리", r"국수|잔치|국시|소면|면$|면가|면집|면관|누들"),
    # 패스트푸드
    ("버거", "패스트푸드", r"버거|burger|맥도날드|롯데리아|맘스터치|kfc|쉐이크쉑"),
    ("피자", "패스트푸드", r"피자|pizza|피제리아|도미노|파파존스"),
    ("샌드위치/토스트", "패스트푸드", r"샌드위치|써브웨이|subway|토스트|이삭|에그드랍|베이글|핫도그|명랑|크로플"),
    # 양식
    ("파스타/이탈리안", "양식", r"파스타|스파게티|이탈리안|이태리|트라토리아|오스테리아|리조또|뇨끼"),
    ("스테이크", "양식", r"스테이크|steak|스테끼"),
    ("프렌치", "양식", r"프렌치|프랑스|비스트로|브라세리|french"),
    ("경양식/함박", "양식", r"경양식|함박|햄버그|오므라이스|함바그"),
    ("브런치", "양식", r"브런치|brunch|팬케이크|와플"),
    ("샐러드/포케", "양식", r"샐러드|포케|비건|그릭"),
    ("레스토랑 일반", "양식", r"레스토랑|restaurant|다이닝|dining|양식|키친|kitchen"),
    # 분식
    ("떡볶이", "분식", r"떡볶|떡뽁|라볶|엽떡|죠스"),
    ("김밥", "분식", r"김밥"),
    ("라면", "분식", r"라면"),
    ("만두", "분식", r"만두|교자"),
    ("순대/튀김/어묵", "분식", r"순대|튀김|오뎅|어묵"),
    ("분식 일반", "분식", r"분식"),
    # 한식
    ("한정식", "한식", r"한정식|궁중|정찬|한식코스"),
    ("비빔밥", "한식", r"비빔밥|돌솥|산채"),
    ("쌈밥/보리밥", "한식", r"쌈밥|보리밥|우렁"),
    ("솥밥/영양밥", "한식", r"솥밥|영양밥|굴밥|곤드레"),
    ("찜닭/닭볶음탕", "한식", r"찜닭|닭볶음|닭도리"),
    ("닭한마리", "한식", r"닭한마리"),
    ("오리", "한식", r"오리(?!지널)"),
    ("족발/보쌈", "한식", r"족발|보쌈"),
    ("갈비찜/찜요리", "한식", r"갈비찜|등갈비|찜$|찜집"),
    ("죽", "한식", r"죽$|본죽|죽이야기|죽집|의죽|죽전문|전복죽|호박죽"),
    ("도시락/반찬", "한식", r"도시락|한솥|반찬"),
    ("백반/가정식", "한식", r"백반|가정식|집밥|기사식당|밥상|반상|정식|한상|밥집"),
    # 카페·디저트(일반음식점으로 신고된 카페·베이커리 — 다른 규칙에 안 걸린 상호만)
    ("베이커리", "카페/디저트", r"베이커리|bakery|브레드|bread|제과|빵"),
    ("디저트", "카페/디저트", r"디저트|dessert|케이크|케잌|cake|빙수|도넛|도너츠|마카롱|젤라또|아이스크림|크레페|타르트|파이"),
    ("카페", "카페/디저트", r"카페|cafe|café|커피|coffee|다방|에스프레소|로스터|티하우스|찻집"),
]
PATTERNS = [(t, re.compile(p, re.I)) for t, _, p in RULES]
PARENT = {t: g for t, g, _ in RULES}
GENRE_ORDER = ["한식", "국밥/탕/찌개", "고기/구이", "면요리", "해산물", "분식", "치킨", "중식", "일식", "양식", "패스트푸드",
               "아시안", "세계음식", "주점", "카페/디저트", "뷔페", "기타"]
SUBTYPES: dict[str, list[str]] = {g: [t for t, pg, _ in RULES if pg == g] for g in GENRE_ORDER}
SUBTYPES = {g: ts for g, ts in SUBTYPES.items() if ts and ts != [g]}
# 인허가 업태(genre_detail) → 세부 분류(대응이 확실한 것만)
LICENSE_MAP = {"뷔페식": "뷔페 일반", "냉면집": "냉면", "복어취급": "복어", "탕류(보신용)": "보신/흑염소", "김밥(도시락)": "김밥",
               "패밀리레스트랑": "패밀리레스토랑", "횟집": "회/횟집", "통닭(치킨)": "치킨", "감성주점": "요리주점/술집",
               "라이브카페": "와인바/바", "정종/대포집/소주방": "요리주점/술집"}

# 상가정보 업종 소분류 → 세부 분류(대응이 확실한 것만. '국/탕/찌개류'는 넓어서 제외)
SBIZ_MAP = {
    "돼지고기 구이/찜": "삼겹살/돼지구이", "소고기 구이/찜": "소고기/한우", "곱창 전골/구이": "곱창/막창",
    "닭/오리고기 구이/찜": "찜닭/닭볶음탕", "족발/보쌈": "족발/보쌈", "국수/칼국수": "칼국수/수제비", "냉면/밀면": "냉면",
    "백반/한정식": "백반/가정식", "김밥/만두/분식": "분식 일반", "횟집": "회/횟집", "일식 회/초밥": "초밥/스시",
    "해산물 구이/찜": "조개/굴/전복", "복 요리 전문": "복어", "중국집": "짜장/짬뽕", "마라탕/훠궈": "마라탕/마라샹궈",
    "일식 면 요리": "우동/소바", "일식 카레/돈가스/덮밥": "돈까스", "피자": "피자", "버거": "버거",
    "파스타/스테이크": "파스타/이탈리안", "토스트/샌드위치/샐러드": "샌드위치/토스트", "치킨": "치킨",
    "베트남식 전문": "쌀국수/베트남", "기타 동남아식 전문": "기타 아시안", "뷔페": "뷔페 일반",
    "요리 주점": "요리주점/술집", "생맥주 전문": "호프/맥주", "전/부침개": "막걸리/전", "경양식": "경양식/함박",
    "패밀리레스토랑": "패밀리레스토랑", "기타 일식 음식점": "일식당", "기타 서양식 음식점": "레스토랑 일반",
}

# AI-Hub (음식 유형, 세부 유형) → 세부 분류: 메뉴명이 규칙에 안 걸릴 때만, 대응이 확실한 것만
AIHUB_MAP = {
    ("한식", "회"): "회/횟집", ("한식", "죽"): "죽", ("한식", "찌개"): "찌개/탕 기타", ("한식", "전골"): "샤브샤브/전골",
    ("한식", "면"): "국수", ("일식", "면"): "우동/소바", ("일식", "튀김"): "텐동/튀김",
    ("양식", "메인요리"): "레스토랑 일반", ("분식/기타", "분식"): "분식 일반",
    ("중식", "요리"): "중화요리", ("중식", "면"): "짜장/짬뽕", ("중식", "밥"): "짜장/짬뽕",
}
DRINK = "_drink"
MODEL_MIN_P = 0.8  # 메뉴명 예측 채택 기준


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).lower()


def classify(text: str) -> str | None:
    t = norm(text)
    for sub, p in PATTERNS:
        if p.search(t):
            return sub
    return None


# --- 모델 -------------------------------------------------------------------------------
def _grams(text: str) -> list[str]:
    t = f"^{norm(text)}$"
    return [t[i:i + n] for n in (1, 2, 3) for i in range(len(t) - n + 1)]


class Model:
    def __init__(self, data: dict):
        self.classes: list[str] = data["classes"]
        self.logprior = {c: math.log(p) for c, p in data["prior"].items()}
        self.total = data["total"]
        self.v = data["vocab_size"]
        self.counts: dict[str, dict[str, int]] = data["counts"]

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "Model | None":
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def predict(self, text: str) -> tuple[str | None, float]:
        """(세부 분류 또는 '_drink', 사후확률). 아는 그램이 없으면 (None, 0)."""
        grams = [g for g in _grams(text) if g in self.counts]
        if not any(len(g) >= 2 for g in grams):
            return None, 0.0
        score = {}
        for c in self.classes:
            denom = math.log(self.total[c] + self.v)
            score[c] = self.logprior[c] + sum(math.log(self.counts[g].get(c, 0) + 1) - denom for g in grams)
        best = max(score, key=score.get)
        z = sum(math.exp(s - score[best]) for s in score.values())
        return best, 1.0 / z


def _aihub_rows(root: Path):
    for z in sorted(root.rglob("*.zip")):
        zf = zipfile.ZipFile(z, metadata_encoding="cp949")
        split = "valid" if z.name.startswith("VL") else "train"
        for n in zf.namelist():
            if not n.endswith(".json"):
                continue
            for a in json.loads(zf.read(n)).get("annotations", []):
                mi = a.get("menu_information") or {}
                if mi.get("ko"):
                    yield split, mi["ko"], mi.get("food_type") or "", mi.get("food_subtype") or ""


def label(name: str, ftype: str, fsub: str) -> str | None:
    if ftype == "음료/주류":
        return DRINK
    return classify(name) or AIHUB_MAP.get((ftype, fsub))


def train(root: Path, out: Path = MODEL_PATH, min_count: int = 3) -> dict:
    seen, data = set(), {"train": [], "valid": []}
    for split, name, ft, fs in _aihub_rows(root):
        lab = label(name, ft, fs)
        key = (norm(name), lab)
        if lab and key not in seen:  # 같은 메뉴명 중복은 1번만(체인 메뉴 쏠림 방지)
            seen.add(key)
            data[split].append((name, lab))
    counts: dict[str, Counter] = defaultdict(Counter)
    prior = Counter(lab for _, lab in data["train"])
    for name, lab in data["train"]:
        for g in _grams(name):
            counts[g][lab] += 1
    counts = {g: dict(c) for g, c in counts.items() if sum(c.values()) >= min_count}
    total = Counter()
    for c in counts.values():
        total.update(c)
    n = sum(prior.values())
    model = {"classes": sorted(prior), "prior": {c: k / n for c, k in prior.items()}, "total": dict(total),
             "vocab_size": len(counts), "counts": counts,
             "source": "한국지능정보사회진흥원 AI-Hub '관광 음식메뉴판 데이터'(학습용)"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    m = Model(model)
    ok = sum(m.predict(x)[0] == y for x, y in data["valid"])
    return {"train": len(data["train"]), "valid": len(data["valid"]), "valid_acc": ok / max(len(data["valid"]), 1),
            "vocab": len(counts), "path": str(out)}


# --- 가게별 판정 -----------------------------------------------------------------------------
BROAD_SBIZ = {"백반/가정식"}  # 상가 소분류가 넓음 → 기존 장르가 한식·기타일 때만(골뱅이집·고깃집 오분류 방지)


def decide(name: str, sbiz_category: str | None, menus: list[str], model: Model | None,
           genre: str = "기타", genre_detail: str | None = None) -> tuple[str | None, str | None]:
    if t := classify(name):
        return t, "name"
    if t := LICENSE_MAP.get(genre_detail or ""):
        return t, "license"
    if (t := SBIZ_MAP.get(sbiz_category or "")) and (t not in BROAD_SBIZ or genre in ("한식", "기타")):
        return t, "sbiz"
    votes = Counter(t for m in menus if (t := classify(m)))
    if votes:
        return votes.most_common(1)[0][0], "menu"
    if model:
        votes = Counter()
        for m in menus:
            t, p = model.predict(m)
            if t and t != DRINK and p >= MODEL_MIN_P:
                votes[t] += 1
        if votes:
            return votes.most_common(1)[0][0], "model_menu"
    return None, None


def assign(conn: sqlite3.Connection, model: Model | None = None, dry_run: bool = False) -> Counter:
    """모든 가게의 subtype·subtype_src 재계산, 상위 장르가 다르면 genre 보정(점수 무관 → 재계산 없음)."""
    menus: dict[str, list[str]] = defaultdict(list)
    for rid, m in conn.execute("SELECT restaurant_id, name FROM menus"):
        menus[rid].append(m)
    stats, rows = Counter(), []
    for rid, name, genre, cat, detail in conn.execute(
            "SELECT id, name, genre, sbiz_category, genre_detail FROM restaurants"):
        t, src = decide(name, cat, menus.get(rid, []), model, genre, detail)
        stats[src or "none"] += 1
        new_genre = PARENT[t] if t else genre
        stats["genre_changed"] += new_genre != genre
        rows.append((t, src, new_genre, rid))
    conn.execute("SAVEPOINT subtype")
    conn.executemany("UPDATE restaurants SET subtype=?, subtype_src=?, genre=? WHERE id=?", rows)
    conn.execute("ROLLBACK TO subtype" if dry_run else "RELEASE subtype")
    if dry_run:
        conn.execute("RELEASE subtype")
    conn.commit()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="세부 분류: 모델 학습 / 가게별 판정")
    sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("train")
    t.add_argument("aihub_dir", help="AI-Hub '관광 음식메뉴판 데이터' 라벨링 zip 이 있는 폴더(하위 폴더 포함)")
    a = sp.add_parser("assign")
    a.add_argument("--db", default=None)
    a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "train":
        print(train(Path(args.aihub_dir)))
        return
    conn = connect(args.db or db_path())
    init_schema(conn)
    model = Model.load()
    print(f"모델: {'있음' if model else '없음(① ~ ③만)'}")
    st = assign(conn, model, args.dry_run)
    n = sum(st[k] for k in ("name", "license", "sbiz", "menu", "model_menu", "none"))
    for k in ("name", "license", "sbiz", "menu", "model_menu", "none"):
        print(f"  {k}: {st[k]:,} ({st[k] / max(n, 1):.1%})")
    print(f"  genre 보정: {st['genre_changed']:,}{' (dry-run)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
