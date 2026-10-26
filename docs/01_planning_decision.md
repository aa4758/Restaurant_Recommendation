# 기획팀 결정문 (찬성 vs 반대 토론 중재 결과)

| 쟁점 | 찬성 | 반대 | **결정** |
|---|---|---|---|
| 데이터 수집 | 외부 데이터로 prior | 네이버 크롤링은 약관·법적 리스크 high | **크롤링 금지.** 공식 API(카카오 로컬/네이버 검색 지역 API) + 공공데이터 + 제휴/수기 CSV만. 수집기는 교체 가능한 어댑터 구조 |
| 업무추진비 가중↑ | 재방문 검증 신호 | 낙인·명예훼손·정치적 오해 | **가중치에 반영하되 log 감쇠 + 상한(cap).** UI 문구는 "공공기관 업무추진비 기록 N회(출처·기준연도)" 참고 배지. "공직자 맛집" 표현 금지. 사용자 이름 등 개인정보는 적재 전 제거 |
| 광고리뷰 가중↓ | 찐맛 브랜드 핵심 | 오분류 시 소상공인 불이익 | **감점하되 하한(floor) 적용 + 신뢰도 낮으면 감점 축소.** 판별은 공개 룰(협찬/체험단/제공받아 키워드, 작성 시기 집중도). 업주 이의제기 채널, 분기별 오탐 검수 |
| 엄격 별점 | 분별력 | 이탈·업주 반발 | **엄격 0~5 스케일(평균≈2.5) + "이 지역 상위 N%" 백분위 병기.** 산식은 앱 내 "점수 기준" 화면에 공개 |
| 소수 큐레이션 | 선택 과부하 해소 | 독점 노출·조작 의혹 | **기본 3곳(최대 5).** 각 추천에 이유(reason) 3줄 표시. 동점대(±0.1)는 일 단위 로테이션. 결과 부족 시 완화 순서: 거리→분위기→가격→장르 (음주는 완화 안 함) |
| 조건 필터 | 맥락 맞춤 | 영업정보 오류 | 필터 데이터에 `updated_at` 표시 + 사용자 "정보 틀림" 신고 |
| 베이지안 전환 | 합리적 로드맵 | 축적 지연 | **prior를 가상 리뷰 k=20개로 취급**하는 수축 평균. 자체 리뷰 20개면 50:50. 첫 리뷰 작성 리워드는 2차 |

## MVP 범위
- 지역: 서울 중구(시청 인근, 업무추진비 공개 데이터 밀집) 1곳.
- 필터 5종, 엄격 별점 엔진, prior 엔진, 추천 3곳 + 이유, 자체 리뷰 작성.
- 제외(2차): 로그인 소셜연동, 리워드, 업주 콘솔(이의제기는 이메일 링크로 대체).

## 기술 스택
- 모바일: Expo(React Native) + TypeScript — Windows에서 개발 가능, iOS/Android 동시.
- 백엔드: Python FastAPI + SQLite(MVP) → PostgreSQL/PostGIS(확장 시).
- 점수 엔진: 순수 Python 모듈(`backend/app/scoring/`), 단위 테스트 필수.

## 점수 모델 v2 (2026-10 개정 — 사용자 승인, `docs/04_data_plan.md` 3-2)
개정 사유: 외부 평점(네이버 등)은 공식 API로 제공되지 않고 크롤링은 금지 → prior를 **합법적으로 확보 가능한 공공 신호** 위주로 재구성.
```
prior_raw = 0.30 * 업력      min(log1p(영업연수)/log1p(20), 1)        # 인허가일자 opened_at, 없으면 0
          + 0.25 * 업무추진비  min(log1p(방문수)/log1p(30), 1)          # 기존 w_gov·GOV_CAP 유지
          + 0.15 * 위생등급    매우우수 1 / 우수 0.7 / 좋음 0.4 / 없음 0
          + 0.10 * 지정업소    모범·착한가격·안심식당·백년가게 중 1개 이상이면 1
          + 0.20 * 제휴 평점   0~1 정규화, 없으면 0.5(중립)
          - 행정처분           최근 3년(정확히 3년 전 당일 포함) 건당 0.05, 상한 0.15
          - 광고 감점          0.30 * clamp((ad_ratio-0.15)/0.5, 0, 1) * ad_conf
                               ad_ratio = 자체 리뷰 중 체험단·협찬·제공받아·원고료·소정의 표시 비율
                               ("협찬 아님", "원고료 받지 않았", "광고·협찬 없이" 등 부정 표현은 제외)
                               ad_conf  = min(리뷰수/10, 1)  (제휴 통계가 있으면 신뢰도 높은 쪽 사용)
                               하한: 광고 감점 ≤ 가점 합계의 50%
prior_star = strict_map(prior_raw)    # 시군구 단위 분위수 → 평균 2.5, 4.5 이상 상위 ~3% (변경 없음)
final_star = (k*prior_star + n*user_mean) / (k + n)   # k=20 (변경 없음, 가중 리뷰 v2는 별도 승인)
근거 수준(evidence) = 데이터가 존재하는 신호 수(가점은 값이 있으면, 감점은 0보다 클 때만; 제휴 결측 0.5 제외)
                   0 → "low"(근거 부족 표시, 단 자체 리뷰가 있으면 문구 생략), 1~2 → "mid", 3+ → "high"
```
v1(외부 평점 base 기반)은 폐기. 업무추진비 배지 문구·크롤링 금지 원칙은 그대로.

## API 계약 (백엔드 ↔ 모바일 공통, 변경 시 이 문서 먼저 수정)
- `GET /health` → `{"status":"ok"}`
- `GET /meta/filters` → `{"price":["~1만","1~2만","2~4만","4만+"],"genre":[...],"mood":[...],"alcohol":["any","yes","no"]}`
- `POST /recommend` body `{"lat":float,"lng":float,"radius_m":int=1000,"price":[str]?,"genre":[str]?,"mood":[str]?,"alcohol":"any|yes|no","limit":int=3}`
  → `{"items":[{"id","name","genre","price_band","moods":[str],"alcohol":bool,"lat","lng","distance_m","star":float,"percentile":int,"review_count":int,"gov_visits":int,"gov_source":str?,"reasons":[str],"updated_at":str}],"relaxed":[str]}`
- `GET /restaurants/{id}` → 위 item + `"score_breakdown":{"prior_star","user_mean","n","k","gov_bonus","ad_penalty","components":{"tenure","gov","hygiene","designation","partner","sanction","ad"},"evidence":"low|mid|high"}` (v2: components·evidence 추가, 기존 키 유지)
- `POST /restaurants/{id}/reviews` body `{"stars":0.5~5 (0.5단위),"text":str,"tags":[str]}` → 201 `{"id","final_star"}`
- `POST /restaurants/{id}/report` body `{"field":str,"message":str}` → 202
