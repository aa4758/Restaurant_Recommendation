# 화면 스펙 (찐맛 / JJINMAT MVP)

공통 참조: `mobile/src/theme` (tokens/useTheme). 컴포넌트명은 PascalCase로 확정, 모바일 개발팀이 그대로 파일/컴포넌트명으로 사용.

---

## 1. 조건선택 (Home)

**목적**: 위치 기반으로 가격/장르/분위기/음주/거리 조건을 칩으로 선택 후 "3곳 추천받기" CTA로 추천 결과 진입.

**컴포넌트 트리**
```
HomeScreen
├─ LocationPermissionBanner        (권한 거부 시에만 표시)
├─ HomeHeader                      (앱 로고 + 현재 위치 텍스트)
├─ ConditionTextInput              (2026-10-29: 문장 입력 → POST /filters/parse → 아래 칩에 반영, 칩으로 수정 가능)
│  ├─ ParseButton ("문장으로 조건 고르기")
│  └─ UnknownTermsCaption          ("인식 못함: {낱말} (적용하지 않았어요)", 있을 때만)
├─ FilterChipGroup (x5 + 세부 메뉴)
│  ├─ title: "가격대" | "음식 장르" | "세부 메뉴 · {장르}" | "분위기" | "음주" | "거리"
│  │   세부 메뉴 그룹은 고른 장르와 고른 세부 메뉴의 상위 장르에 대해서만 표시(`/meta/filters` 의 subtype)
│  └─ FilterChip (다중/단일 선택, 옵션별). 문장에서 나온 반경이 기본 옵션에 없으면 "{n}m" 칩 추가
├─ SelectedFilterSummary           (선택 조건 요약 텍스트, 선택 없으면 미표시)
└─ RecommendCTAButton              ("3곳 추천받기")
```

**상태**
- 로딩: 해당 없음 (필터 화면 자체는 정적, `GET /meta/filters` 로드 중엔 `FilterChipGroupSkeleton` 표시)
- 빈 결과: 해당 없음 (결과는 다음 화면에서 처리)
- 에러: `meta/filters` 실패 시 `InlineErrorBanner` ("필터 정보를 불러오지 못했어요. 다시 시도해 주세요.") + `RetryButton`
- 위치 권한 거부: `LocationPermissionBanner` 노출, CTA는 활성 유지하되 거리 필터는 비활성(`FilterChip` disabled) + 안내 "위치 권한을 허용하면 거리순 추천을 받을 수 있어요."

**카피**
- 헤더: "지금 이 근처, 진짜 맛집만"
- CTA: "3곳 추천받기"
- 위치 배너: "위치 권한이 꺼져 있어요. 허용하면 더 정확한 추천을 드릴 수 있어요." + `SettingsLinkButton`("설정에서 허용하기")
- 음주 필터 안내(툴팁): "음주 조건은 결과가 적어도 완화되지 않아요."
- 문장 입력 placeholder: "예) 근처 만원 이하 국밥, 혼밥하기 좋고 술은 안 마셔요" · 해석 실패: "문장을 해석하지 못했어요. 칩으로 골라 주세요."
- 세부 메뉴 안내: "세부 메뉴를 고르면 그 장르는 고른 메뉴만 추천해요." · 완화 배지 라벨: subtype → "세부 메뉴"

---

## 2. 추천결과 (Recommendations) — 릴스형

**목적**: 세로 전체화면 카드 덱으로 소수(기본 3, 최대 5)만 큐레이션. 무한 피드 금지. 사진 없이 타이포 중심. 좋아요·싫어요는 개인화 전용(공개 점수·순위 미반영).

**컴포넌트 트리**
```
RecommendationScreen
├─ RelaxedConditionBanner          (relaxed 있을 때, 덱 상단 오버레이, 닫기 가능)
├─ LocationDisabledNotice          (위치 거부 시, 상단 한 줄)
├─ PageIndicator                   ("1/3", 우상단. 종료 카드에서는 숨김)
├─ RecommendationDeck              (세로 페이징 전체화면, 한 번에 한 장 스냅)
│  ├─ ReelCard (x3~5)
│  └─ EndOfDeckCard                (마지막 1장)
├─ ActionRail                      (우측 세로, 카드 위 고정)
├─ SwipeHint                       (첫 진입 1회)
├─ DislikeReasonSheet              (싫어요 시)
├─ ReviewSheet                     (리뷰 버튼 시)
└─ UndoToast                       (싫어요 후)
```

### 2-1. ReelCard 레이아웃 (위→아래, 좌측 정렬, 좌우 spacing 20, 우측 72px는 ActionRail 영역 확보)
```
ReelCard  (배경 colors.background, 상하 safe area 준수)
├─ OpenStatusTag          영업 상태 칩: "영업 중" / "곧 마감" / "영업 종료" / "영업 정보 없음"
├─ StarHero               별점 대형(typography 최대 크기, starScale 색상) "4.6"
│  └─ PercentileBadge     "이 지역 상위 8%"
├─ RestaurantName         굵게 2줄 말줄임
├─ MetaLine               "{장르} · {가격대} · {거리}"  (예: "한식 · 1~2만 · 320m")
├─ ReasonList             ReasonLine x3 (각 1~2줄, 불릿 없이 줄 간격 넉넉히)
└─ BadgeRow               EvidenceBadge · GovBudgetBadge · RelaxedBadge (줄바꿈 허용)
```
- `EvidenceBadge`(evidence): low "리뷰 근거 적음" / mid "리뷰 근거 보통" / high "리뷰 근거 충분". 목록 응답에 evidence 없으면 `review_count` 로 대체("리뷰 {n}건"). 색만으로 구분 금지, 텍스트 필수.
- `GovBudgetBadge`(gov_visits>0): "공공기관 업무추진비 기록 {N}회 ({출처}, {기준연도} 기준)". "공직자 맛집" 표현 금지.
- `RelaxedBadge`(해당 항목이 relaxed에 속할 때): "{분위기/가격/세부 메뉴/거리/장르} 조건 완화됨". 음주 조건은 완화 대상 아님.
- 광고 감점 안내는 카드에서 제외(상세 화면 `AdPenaltyRow` 에서만).
- 큰 글자 설정 시 `ReasonList` 는 스크롤 가능한 영역으로 전환, 카드 하단 잘림 금지.

### 2-2. ActionRail (우측 세로, 하단에서 ReelCard 하단 여백 위, 아이콘 28 + 라벨 12, 터치 영역 48x48 이상)
| 순서 | 버튼 | 라벨 | 접근성 라벨 | 동작 |
|---|---|---|---|---|
| 1 | LikeButton | "좋아요" | "{이름} 좋아요, 현재 {선택됨/선택 안 됨}" | 토글. `POST /reactions` like/none. 기기 찜 저장 |
| 2 | DislikeButton | "싫어요" | "{이름} 싫어요, 30일간 숨김" | `DislikeReasonSheet` 열기 |
| 3 | ReviewButton | "리뷰" | "{이름} 리뷰 보기" | `ReviewSheet` 열기 |
| 4 | ShareButton | "공유" | "{이름} 공유하기" | OS 공유 시트 |
- 좋아요 선택 상태는 아이콘 채움+색+라벨 "좋아요 완료"로 이중 표시. 낙관적 업데이트, 실패 시 롤백+토스트 "저장하지 못했어요. 다시 시도해 주세요."
- 리뷰 버튼에 리뷰 수 표시(`review_count`, 0이면 숫자 생략).

### 2-3. DislikeReasonSheet (하단 시트, 높이 콘텐츠 맞춤)
- 제목: "어떤 점이 아쉬웠나요?" / 보조: "이 가게는 30일간 추천에서 숨겨요."
- `ReasonChip` 4개(단일 선택, 선택 즉시 확정): "너무 멀어요"(far) · "가격이 맞지 않아요"(price) · "끌리지 않아요"(not_into) · "이미 가봤어요"(visited)
- `SkipButton` "건너뛰기"(이유 없이 dislike만 전송). 시트 바깥 탭/닫기 = 취소(숨김 안 함).
- 확정 시: 시트 닫힘 → 카드 즉시 사라짐(아래 카드가 올라옴, 150ms) → `UndoToast`.

### 2-4. ReviewSheet (하단 시트, 읽기 전용, 화면 높이 70%, 끌어서 닫기)
```
ReviewSheet
├─ SheetHeader           "{이름} 리뷰 {n}건"
├─ ReviewList            (GET /restaurants/{id}/reviews, 커서 무한 스크롤은 시트 내부만 허용)
│  └─ ReviewItem         별점(★ 4.5) · 본문 · 태그 · 작성일
│     └─ SponsoredLabel  ad_disclosed=true 일 때 "협찬 표시" 라벨 (회색 칩, 목록 하단 정렬은 서버 정렬 그대로)
├─ ReviewEmptyState      "아직 리뷰가 없어요. 첫 리뷰를 남겨보세요."
├─ ReviewErrorState      "리뷰를 불러오지 못했어요." + RetryButton
└─ WriteReviewButton     하단 고정 "리뷰 쓰기" → WriteReview 화면(엄격 기준 가이드 유지)
```
- 로딩: `ReviewItemSkeleton` x3. 별점 없는 한 줄 댓글/답글/신고/좋아요 없음.
- `SponsoredLabel` 접근성 라벨: "협찬 표시된 리뷰".

### 2-5. 공유 문구 템플릿 (OS 공유 시트, 텍스트+링크)
```
[찐맛] {이름}
★ {star} · 이 지역 상위 {percentile}%
{주소}
{reasons[0]}
지도에서 보기: {지도 검색 링크(이름+주소 검색어)}
```
- 금지: 사용자 위치·좌표·거리·검색 조건·기기 ID. 링크는 가게 이름+주소 기반 검색어만. 거리/영업 상태 미포함.

### 2-6. 제스처 / 인디케이터 / 힌트
- 세로 스와이프 = 다음/이전 카드(스냅). 카드 본문 탭 = 상세(`RestaurantDetail`). ActionRail·배지 영역 탭은 각자 동작. **더블탭 좋아요 없음(오조작 방지).**
- 접근성: 스와이프 대체로 스크린리더용 "다음 카드"/"이전 카드" 액션(accessibilityActions) 제공. 카드 전환 시 "{현재}번째, 총 {전체}곳, {이름}" 안내.
- `PageIndicator`: "1/3" (텍스트, 우상단). 종료 카드 포함하지 않음. 싫어요로 줄면 분모 갱신.
- `SwipeHint`: 최초 진입 1회만(AsyncStorage `reel_hint_seen`). 첫 카드 하단에 위 화살표 애니메이션 + "위로 밀어 다음 곳 보기". 첫 스와이프/탭/3초 후 사라짐. 모션 줄이기 설정 시 정지 화살표.

### 2-7. EndOfDeckCard
- 문구: "오늘의 추천은 여기까지예요" / 보조 "조건을 바꾸면 다른 곳을 보여드릴게요."
- `AdjustFilterButton`(주) "조건 바꾸기" → Home. `RefreshRecommendationButton`(보조) "다른 곳 보기" → 동점대 로테이션 재요청(`exclude_ids` 유지). `ReportInfoLink` "정보가 틀렸나요?".
- 좋아요한 곳 요약은 1단계 제외.

### 2-8. 상태
- 로딩: `ReelCardSkeleton` 1장(별점·이름·이유 3줄 자리 블록) + `PageIndicator` 숨김.
- 빈결과: `EmptyResultView` "조건에 맞는 곳을 찾지 못했어요. 조건을 조금 넓혀볼까요?" + `AdjustFilterButton` "조건 다시 선택하기". (싫어요로 전부 숨겨져 0장이면 바로 `EndOfDeckCard`)
- 에러: `FullScreenErrorView` "추천을 불러오는 중 문제가 생겼어요." + `RetryButton` "다시 시도". 반응 전송 실패는 토스트로만 처리.
- 위치 거부: 거리 없이 추천. `LocationDisabledNotice` "위치 정보 없이 추천 중이에요." + `MetaLine` 에서 거리 생략. 설정 이동 링크 "설정에서 허용하기".
- 싫어요 후: 카드 즉시 사라짐 → 서버 재선정으로 덱 유지(`exclude_ids` 갱신, 새 카드는 덱 끝에 추가, 최대 5장) → `UndoToast` "30일간 숨겼어요 · 되돌리기" (5초). 되돌리기 = `POST /reactions` none + 카드를 원래 위치로 복원. 토스트는 ActionRail 아래에 위치, 스크린리더 live region.
- 조건 완화: `RelaxedConditionBanner` "조건에 맞는 곳이 적어 {분위기/가격/세부 메뉴/거리/장르} 조건을 완화했어요."

### 2-9. 토큰 / 접근성
- 신규 토큰 불필요(기존 `colors`, `typography`, `starScale`, `radius`, `elevation`, `spacing` 사용). 시트 배경 dim = `colors.overlay`.
- 본문 대비 4.5:1 이상, 터치 48dp 이상, 다크 모드 동일 구조, 별점·상태는 색+텍스트 병기.

---

## 3. 상세 (RestaurantDetail)

**목적**: 선택한 음식점의 상세 정보와 `score_breakdown` 시각화(사전 점수 vs 사용자 평균 vs 최종 점수 구성).

**컴포넌트 트리**
```
RestaurantDetailScreen
├─ RestaurantHeroImage
├─ RestaurantTitleBlock             (이름/장르/가격대/음주 가능 여부)
├─ StarRatingBadge + PercentileBadge
├─ ScoreBreakdownSection
│  ├─ ScoreBreakdownChart           (prior_star vs user_mean 막대/도넛)
│  ├─ ScoreWeightRow ("사전 점수(prior)", "자체 리뷰 평균", 각 가중치 n/k 표시)
│  ├─ GovBonusRow                   (gov_bonus 표시, GovBudgetBadge 재사용)
│  └─ AdPenaltyRow                  (ad_penalty > 0 일 때만)
├─ ReasonList (ReasonLine x3)
├─ MoodTagList
├─ UpdatedAtNotice                  ("정보 업데이트: {updated_at}")
├─ MapLinkButtons                   (2026-10-30: "네이버지도" · "카카오맵" 나란히, 아래 '지도 링크')
├─ ReportInfoButton                 ("정보 틀림 신고하기")
├─ ReviewSheetEntryButton           ("리뷰 {n}건 보기" → 2-4 ReviewSheet 재사용)
├─ WriteReviewButton                ("리뷰 쓰기" → 리뷰작성 화면 이동)
└─ ReviewSummaryList                (자체 리뷰 최근 목록, 없으면 EmptyReviewNotice)
```

**상태**
- 로딩: `RestaurantDetailSkeleton`
- 빈 결과: 해당 없음 (리뷰가 없을 때는 `EmptyReviewNotice` "아직 리뷰가 없어요. 첫 리뷰를 남겨보세요.")
- 에러: `InlineErrorBanner` + `RetryButton`
- 위치 권한 거부: 거리 표시 대신 `DistanceUnavailableTag` ("거리 정보 없음")

**카피**
- 섹션 제목: "이 점수는 어떻게 나왔을까요?"
- `ScoreWeightRow` 예시: "사전 점수 {prior_star}점 × {k}건 + 방문자 리뷰 {user_mean}점 × {n}건"
- `GovBonusRow`: "공공기관 업무추진비 기록 반영: +{gov_bonus}"
- `AdPenaltyRow`: "광고성 리뷰 감점: -{ad_penalty}"
- `MapLinkButtons`(지도 링크, 2026-10-30): 버튼 "네이버지도에서 보기" · "카카오맵에서 보기". 접근성 라벨 "{이름} 네이버지도에서 열기"/"{이름} 카카오맵에서 열기".
  동작: 해당 지도 앱이 있으면 앱(`nmap://search?query={이름 주소}&appname={패키지명}` / `kakaomap://search?q={이름 주소}`), 없거나 실패하면 웹(`https://map.naver.com/p/search/{이름 주소}` / `https://map.kakao.com/?q={이름 주소}`).
  검색어 = 가게명 + 도로명주소(없으면 지번, 둘 다 없으면 가게명). 주소 뒤 괄호(동·건물·층·호)는 검색을 흐려서 뺌. 사용자 위치·좌표는 넘기지 않음. 추천 카드에서는 카드 본문 아래 `MapLinkButtons`(작은 텍스트 버튼, 카드 탭 영역 밖 — 버튼 안 버튼 금지)로 같은 동작.

---

## 4. 리뷰작성 (WriteReview)

**목적**: 0.5 단위 별점(0.5~5)과 텍스트/태그로 리뷰 작성. 엄격한 별점 기준 가이드 제공.

**컴포넌트 트리**
```
WriteReviewScreen
├─ RestaurantSummaryCard            (대상 음식점 요약)
├─ StrictRatingGuideCard            (엄격 별점 안내, 접기/펼치기)
├─ HalfStarRatingInput              (0.5 단위, 0~5)
├─ RatingHintText                   (선택한 점수에 따라 동적 문구)
├─ ReviewTagPicker                  (선택 태그 다중선택)
├─ ReviewTextInput
├─ SubmitReviewButton               ("리뷰 등록하기") — 로그인 상태일 때만
├─ LoginButtons                     (로그인 안 됨·토큰 만료 시 버튼 자리에 표시, 작성 중 내용 유지)
├─ SubmitErrorNotice                (제출 실패 시)
└─ AccountLink                      ("계정 관리" → Account)
```
- 로그인 안내(2026-11-02, docs/01 L-5): "리뷰는 로그인 후 등록할 수 있어요. / 한 사람이 여러 번 쓰는 걸 막기 위해서예요."

**상태**
- 로딩: `SubmitReviewButton` 내 `LoadingSpinner` (제출 중, 버튼 비활성)
- 빈 결과: 해당 없음
- 에러: `SubmitErrorNotice` ("리뷰 등록에 실패했어요. 다시 시도해 주세요.") + `RetryButton`
- 위치 권한 거부: 영향 없음 (리뷰 작성은 위치 비의존)

**카피 (엄격 별점 가이드 — `StrictRatingGuideCard`)**
- 타이틀: "이 앱의 별점은 엄격합니다"
- 본문:
  - "2.5 = 평범한 곳이에요"
  - "3.5 = 또 올 의향이 있어요"
  - "4.5 = 일부러 찾아올 곳이에요"
- `RatingHintText` 동적 예시: 사용자가 4.0 선택 시 "3.5(또 올 의향)와 4.5(일부러 찾아올 곳) 사이예요"
- `SubmitReviewButton`: "리뷰 등록하기"

---

### 4-1. LoginButtons (2026-11-02, docs/01 '소셜 로그인 세부')
- "카카오로 로그인"(primary) / "Google로 로그인"(secondary). 진행 중 해당 버튼 스피너, 둘 다 비활성.
- 사용자 취소는 조용히 무시, 실패만 "로그인에 실패했어요. 다시 시도해 주세요."
- 브랜드 가이드(카카오 노란 버튼·구글 로고)는 디자인 단계에서 적용(스토어 출시 전 필수).

### 4-2. Account (계정, 홈 하단 "계정" 링크·리뷰작성 "계정 관리")
- 로그인 안 됨: 안내 "로그인은 리뷰를 쓸 때만 필요해요. / 이메일·닉네임은 받지 않아요." + LoginButtons
- 로그인 됨: "{카카오|Google} 계정으로 로그인했어요." + "로그아웃"(secondary) + "회원 탈퇴"(text)
- 회원 탈퇴 → 확인 단계: "탈퇴하면 계정과 내가 쓴 리뷰가 모두 삭제되고 되돌릴 수 없어요." + "탈퇴하기" / "취소"

---

## 5. 점수기준 설명 (ScoringExplainer)

**목적**: 엄격 별점, 사전 점수(prior), 업무추진비/광고리뷰 가중 로직, 베이지안 수축을 사용자에게 투명하게 공개.

**컴포넌트 트리**
```
ScoringExplainerScreen
├─ ScoringIntroSection               ("왜 엄격한 별점인가요?")
├─ StarBandLegend                    (평범/좋음/최상 구간 색상 범례 — starScale 기반)
├─ PriorScoreSection
│  ├─ GovWeightExplainCard           (log 감쇠 + 상한 설명)
│  └─ AdPenaltyExplainCard           (하한/신뢰도 설명)
├─ BayesianShrinkExplainCard         (k=20 가상 리뷰, n건 누적 시 전환 예시)
├─ PercentileExplainCard             ("이 지역 상위 N%" 산정 방식)
├─ RelaxOrderExplainCard             (완화 순서: 분위기→가격→세부 메뉴→거리→장르, 음주 제외)
└─ ExternalDataDisclosureCard        (공공데이터/공식 API만 사용, 크롤링 금지 고지)
```

**상태**
- 로딩: 정적 콘텐츠이므로 스켈레톤 불필요 (서버 설정값 fetch 시에만 `SectionSkeleton`)
- 빈 결과: 해당 없음
- 에러: 서버 설정값 로드 실패 시 정적 기본 설명만 표시 (silent fallback), `InlineErrorBanner` 없이 진행
- 위치 권한 거부: 영향 없음

**카피**
- 인트로: "찐맛의 별점은 일부러 짜게 매겨요. 평균은 2.5점, 진짜 좋은 곳만 4.5점 이상이에요."
- `GovWeightExplainCard`: "공공기관 업무추진비 공개 내역에 자주 등장하면 신뢰 신호로 일부 반영해요. 방문 횟수가 많아질수록 반영폭은 점점 줄어들어요(상한 있음)."
- `AdPenaltyExplainCard`: "협찬·체험단 리뷰 비율이 높으면 감점하되, 판별 신뢰도가 낮으면 감점을 줄여요."
- `BayesianShrinkExplainCard`: "리뷰가 없을 땐 사전 점수로 시작하고, 방문자 리뷰가 20개 쌓이면 사전 점수와 실제 리뷰를 절반씩 반영해요."
- `RelaxOrderExplainCard`: "조건에 맞는 곳이 부족하면 분위기 → 가격 → 세부 메뉴 → 거리 → 장르 순으로 완화해요. 세부 메뉴는 같은 장르 전체로 넓혀요. 음주 조건은 바꾸지 않아요."
- `ExternalDataDisclosureCard`: "네이버 등 크롤링 데이터는 사용하지 않아요. 공식 API와 공공데이터만 사용합니다."
