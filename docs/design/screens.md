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
├─ FilterChipGroup (x5)
│  ├─ title: "가격대" | "음식 장르" | "분위기" | "음주" | "거리"
│  └─ FilterChip (다중/단일 선택, 옵션별)
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

---

## 2. 추천결과 (Recommendations)

**목적**: 조건에 맞는 3곳(최대 5곳)을 카드로 제시. 각 카드는 별점+상위 N% 배지, 이유 3줄, 업무추진비 배지(규칙 준수), 조건 완화 시 안내 배너.

**컴포넌트 트리**
```
RecommendationScreen
├─ RelaxedConditionBanner          (relaxed 배열 있을 때만)
├─ RecommendationList
│  └─ RestaurantCard (x3~5)
│     ├─ RestaurantThumbnail
│     ├─ RestaurantName
│     ├─ StarRatingBadge           (별점 + 색상은 starScale 기준)
│     ├─ PercentileBadge           ("상위 N%")
│     ├─ ReasonList                (ReasonLine x3)
│     ├─ GovBudgetBadge            (gov_visits > 0 일 때만)
│     ├─ AdPenaltyNotice           (ad_conf 높고 감점 적용 시, 선택적 표시)
│     └─ DistanceTag
├─ RefreshRecommendationButton     ("다른 곳 보기" — 동점대 로테이션 트리거)
└─ ReportInfoLink                  ("정보가 틀렸나요?")
```

**상태**
- 로딩: `RecommendationList` 자리에 `RestaurantCardSkeleton` x3
- 빈 결과: `EmptyResultView` — 일러스트 + "조건에 맞는 곳을 찾지 못했어요. 조건을 조금 넓혀볼까요?" + `AdjustFilterButton`("조건 다시 선택하기")
- 에러: `FullScreenErrorView` ("추천을 불러오는 중 문제가 생겼어요.") + `RetryButton`
- 위치 권한 거부: 거리 조건 없이 결과 표시, 카드 상단에 `LocationDisabledNotice` ("위치 정보 없이 추천 중이에요.")

**카피 (배지 문구 규칙 — "공직자 맛집" 등 표현 금지)**
- `GovBudgetBadge`: "공공기관 업무추진비 기록 {N}회 ({출처}, {기준연도} 기준)"
- `PercentileBadge`: "이 지역 상위 {N}%"
- `RelaxedConditionBanner`: "조건에 맞는 곳이 적어 {거리/분위기/가격/장르} 조건을 완화했어요."
- `AdPenaltyNotice`(선택): "광고성 리뷰 비중이 높아 점수에 반영했어요."
- `RefreshRecommendationButton`: "다른 곳 보기"

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
├─ ReportInfoButton                 ("정보 틀림 신고하기")
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
├─ SubmitReviewButton               ("리뷰 등록하기")
└─ SubmitErrorNotice                (제출 실패 시)
```

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
├─ RelaxOrderExplainCard             (완화 순서: 거리→분위기→가격→장르, 음주 제외)
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
- `RelaxOrderExplainCard`: "조건에 맞는 곳이 부족하면 거리 → 분위기 → 가격 → 장르 순으로 완화해요. 음주 조건은 바꾸지 않아요."
- `ExternalDataDisclosureCard`: "네이버 등 크롤링 데이터는 사용하지 않아요. 공식 API와 공공데이터만 사용합니다."
