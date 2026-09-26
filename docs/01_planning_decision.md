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

## 점수 모델 (확정)
```
prior_raw  = base(외부 평점 정규화, 0~1)
           + w_gov * min(log1p(gov_visits)/log1p(GOV_CAP), 1)   # w_gov=0.25, GOV_CAP=30
           - w_ad  * clamp((ad_ratio - 0.15)/0.5, 0, 1) * ad_conf # w_ad=0.30, ad_conf=판별 신뢰도 0~1
prior_star = strict_map(prior_raw)            # 지역 내 분위수 → 엄격 스케일(평균 2.5, 4.5 이상은 상위 ~3%)
final_star = (k*prior_star + n*user_mean) / (k + n)   # k=20, user_mean은 자체 리뷰 평균(0.5 단위, 원래 엄격 기준)
rank_score = final_star + 조건적합도 보너스 - 거리 패널티
```

## API 계약 (백엔드 ↔ 모바일 공통, 변경 시 이 문서 먼저 수정)
- `GET /health` → `{"status":"ok"}`
- `GET /meta/filters` → `{"price":["~1만","1~2만","2~4만","4만+"],"genre":[...],"mood":[...],"alcohol":["any","yes","no"]}`
- `POST /recommend` body `{"lat":float,"lng":float,"radius_m":int=1000,"price":[str]?,"genre":[str]?,"mood":[str]?,"alcohol":"any|yes|no","limit":int=3}`
  → `{"items":[{"id","name","genre","price_band","moods":[str],"alcohol":bool,"lat","lng","distance_m","star":float,"percentile":int,"review_count":int,"gov_visits":int,"gov_source":str?,"reasons":[str],"updated_at":str}],"relaxed":[str]}`
- `GET /restaurants/{id}` → 위 item + `"score_breakdown":{"prior_star","user_mean","n","k","gov_bonus","ad_penalty"}`
- `POST /restaurants/{id}/reviews` body `{"stars":0.5~5 (0.5단위),"text":str,"tags":[str]}` → 201 `{"id","final_star"}`
- `POST /restaurants/{id}/report` body `{"field":str,"message":str}` → 202
