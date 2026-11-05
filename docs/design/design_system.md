# 디자인 시스템 · 비주얼 설계 (찐맛 / JJINMAT)

작성: 디자인팀, 2026-11-05. 기준 문서: `docs/design/screens.md`(화면별 기능·카피·상태 — 여기서 반복하지 않음). 이 문서는 **시각 언어·토큰·컴포넌트 치수·와이어프레임·구현 불일치**를 다룬다.
현 토큰 출처: `mobile/src/theme/tokens.ts`. 대비비는 WCAG 2.1 상대 휘도 공식으로 직접 계산한 값(2026-11-05).
**7절 결정(2026-11-05 승인)대로 코드에 반영한다.**

---

## 1. 브랜드 방향

- 한 줄: "후하지 않아서 믿을 수 있는 별점."
- 키워드 3개: **정직(엄격)** · **담백** · **근거 있는**
- 톤: 과장·감탄 금지. 숫자와 근거로 말한다. "대박/인생 맛집" 류 카피 금지. 문장은 해요체, 짧게.
- 시각 언어(엄격함 = 절제):
  1. 사진 없이 **타이포 중심**. 별점 숫자가 주인공(56pt), 나머지는 회색조.
  2. 색은 **의미가 있을 때만**: 별점 구간색(평범 회색 → 좋음 초록 → 최상 주황), 브랜드 primary(CTA·선택 상태). 장식용 색 금지.
  3. 별점은 **숫자 + 구간 라벨 + 상위 %** 3종 세트로 항상 함께 표기. 별 아이콘 5개 나열(후한 앱의 관습)은 쓰지 않는다 — 2.5가 "반쯤 찬 별"로 읽혀 "나쁨"으로 오해되는 것을 막는다.
  4. 여백 넉넉, 모서리 둥글기는 중간(8~16), 그림자는 시트·토스트에만.
  5. 근거(evidence) 표기는 항상 텍스트. 색만으로 의미 전달 금지.

---

## 2. 토큰

### 2-1. 컬러 (역할 · 대비 결과 · 제안)
현 값 유지가 기본. 아래 표의 "판정"은 텍스트 용도 기준(AA: 일반 글자 4.5:1, 큰 글자(≥18.66px 굵게/≥24px) 3:1, UI 경계·아이콘 3:1).

| 토큰 | 역할 | Light 값 | Dark 값 |
|---|---|---|---|
| background / surface / surfaceAlt | 화면 / 카드·안내 상자 / 칩·배지 바탕 | #FFF / #F7F7F8 / #EFEFF2 | #101113 / #1B1C1F / #232427 |
| border | 구분선·입력 테두리 | #E2E2E6 | #2D2E32 |
| textPrimary / textSecondary / textDisabled | 본문 / 보조 / 비활성·placeholder | #17181A / #5B5D63 / #A0A2A8 | #F2F2F3 / #B4B6BC / #6B6D73 |
| primary (+primaryText) | CTA·선택·"최상" 구간 | #E4572E (#FFF) | #FF7A50 (#101113) |
| accent | "현장 작성" 글자, 사전 점수 막대 | #2E6FE4 | #6C9BFF |
| success / warning / danger | "좋음" 구간·방문자 평균 / 근거 부족 / 감점·오류 | #1E8E5A / #C77E12 / #D0392B | #4CC98A / #E3A83E / #F0685C |
| govBadge(Bg/Text) | 업무추진비 배지 | #EEF2FF / #3A4CA8 | #232A4A / #9BB0FF |
| adPenalty(Bg/Text) | 오류 배너·광고 감점 | #FBEAEA / #A83A3A | #3A2222 / #F0A2A2 |
| chip(Bg/Text/Selected) | 필터 칩 | #F0F0F2 / #3A3B3E / primary 바탕 흰 글자 | #232427 / #D6D7DB / primary 바탕 어두운 글자 |

**대비 계산 결과 (Light)**

| 조합 | 대비 | 판정 |
|---|---|---|
| textPrimary / background | 17.8 | 통과 |
| textSecondary / background · surfaceAlt | 6.6 · 5.7 | 통과 |
| textDisabled / background | 2.6 | 미달 — **placeholder에 쓰이므로 문제**(비활성 컨트롤은 AA 면제) |
| primaryText(흰색) / primary | **3.7** | **미달**(15px 버튼·13px 선택 칩 글자) / 56pt 숫자로는 통과 |
| primary / background (글자·아이콘) | 3.7 | 큰 글자·아이콘만 통과. 작은 글자 금지 |
| success / background | **4.1** | 작은 글자 미달, 56pt 숫자 통과 |
| success / surfaceAlt (StarRatingBadge 13px) | **3.6** | **미달** |
| warning / background · surfaceAlt | **3.3 · 2.9** | **미달**(LowEvidenceBadge 13px) |
| danger / background | 4.9 | 통과 |
| accent / background · surfaceAlt | 4.7 · 4.1 | 배경 통과 / 칩 위 미달 |
| govBadgeText / govBadgeBg | 6.8 | 통과 |
| adPenaltyText / adPenaltyBg | 5.4 | 통과 |
| chipText / chipBg | 9.8 | 통과 |

**Dark**: 위 조합이 모두 6.0 이상으로 통과. 예외는 textDisabled/background 3.65(placeholder 미달, light와 같은 사유).

**제안 값 (Light만 조정, Dark 유지)** — 브랜드 색감은 유지하며 어둡게:

| 토큰 | 현재 → 제안 | 새 대비 |
|---|---|---|
| primary(light) | #E4572E → **#C8431C** | 흰 글자 4.9 / surfaceAlt 위 4.3(큰 글자 전용) |
| success(light) | #1E8E5A → **#17794C** | background 5.4 / surfaceAlt 4.7 |
| warning(light) | #C77E12 → **#8F5A00** | background 5.8 / surfaceAlt 5.0 |
| accent(light) | #2E6FE4 → #245FCC (선택) | surfaceAlt 5.1 |
| textDisabled(light) | #A0A2A8 → placeholder 전용 `textPlaceholder` #71757D 신설 (4.6, 초안 #767A82 는 4.3 미달로 교체), dark #8A8D94 (5.7) | — |

단, chipBgSelected 는 primary 와 같은 값이므로 같이 바뀐다. 주황이 어두워져 "최상" 구간의 화사함이 줄 수 있어 **사용자 시각 확인 필요**(열린 질문 1).

### 2-2. 타이포 스케일
현 `typography` 유지(한글 가독성 기준 적절). 역할 매핑과 추가분:

| 토큰 | px/행간/굵기 | 용도 |
|---|---|---|
| **starHero (신설)** | 56/64/700 | ReelCard 별점 숫자. 현재 인라인 하드코딩 |
| display | 28/36/700 | 카드 가게명 |
| title | 22/30/700 | 화면 제목, 상세 가게명 |
| heading | 18/26/600 | 섹션·시트 제목 |
| body / bodyStrong | 15/22 | 본문 / 버튼 |
| caption / captionStrong | 13/18 | 보조·칩·배지 |
| micro | 11/14/500 | ActionRail 라벨. 최소 크기 — 이보다 작게 금지 |

- 폰트: 시스템 폰트(iOS Apple SD Gothic Neo, Android Noto Sans KR). 별도 폰트 번들 없음(앱 용량·로딩). 숫자는 `fontVariant: ['tabular-nums']` 권장(별점·거리 자리 흔들림 방지).
- 큰 글자(OS 글자 크기): 기본 허용. starHero·PageIndicator·탭 라벨만 `maxFontSizeMultiplier` 1.3 상한. 본문은 상한 없이 스크롤로 흡수(screens.md 2-1).

### 2-3. Spacing · Radius · Elevation · 아이콘 · 모션
- **spacing** (현행 유지): 2/4/8/12/16/24/32/48. 화면 좌우 패딩 16(스크롤 화면), 릴스 카드 좌 20·우 80(레일 영역 72+8). 요소 간 기본 gap 12(md), 칩/배지 gap 4~8.
- **radius**: 칩·배지 pill, 버튼·입력 8(md), 안내 상자 8, 카드형 박스·시트 상단 12(lg), 16(xl)은 예약.
- **elevation**: none 기본. `sm`=카드형 박스(선택), `md`=토스트, `lg`=하단 시트. 릴스 카드 자체는 평면(그림자 없음). 다크 모드는 그림자 대신 surface 단계로 구분.
- **터치 영역**: 최소 44x44(iOS HIG) / 권장 48x48. 시각 크기가 작으면 `hitSlop` 으로 보강.
- **아이콘 크기**: 탭 바 24(기본) · ActionRail 28 · 칩 내부 16 · 배지 내부 12 · 상태 화면 일러스트 대용 48. 라이브러리는 Ionicons 하나로 통일(윤곽=기본, 채움=선택).
- **모션 (신설 토큰, 현재 없음)**

| 토큰 | 값 | 용도 |
|---|---|---|
| duration.instant | 100ms | 눌림 피드백 |
| duration.fast | 150ms | 카드 제거 후 올라옴, 칩 선택 |
| duration.base | 250ms | 시트 열고 닫기, 토스트 등장 |
| duration.slow | 400ms | 별점 숫자 첫 등장(선택) |
| easing.standard | cubic-bezier(0.2, 0, 0, 1) | 대부분 |
| easing.exit | cubic-bezier(0.4, 0, 1, 1) | 사라짐 |

  원칙: 모션은 상태 변화 설명용. 별점 숫자 카운트업 같은 과시 효과 금지(엄격함 톤). "동작 줄이기" 설정 시 모든 이동 모션을 페이드 100ms 로 대체, SwipeHint 화살표 정지(screens.md 2-6).

---

## 3. 별점 시각화 · 배지 체계

### 3-1. 별점 표기 규칙
- 표시: **소수 1자리 숫자**(`toFixed(1)`) + 구간 라벨 + "이 지역 상위 N%". 별(★)은 **글리프 1개만**(배지 안 "★ 4.6") — 5개 나열·부분 채움 별 사용 안 함. 소수점 별(부분 채움)은 쓰지 않는 것으로 결정 제안: 점수 모델이 시군구 분위수 기반이라 "별 몇 개 찬 정도"보다 "상위 몇 %"가 정직한 표현.
- 구간(현 `starScale` 유지, 4구간 확장 제안은 열린 질문 2):

| 구간 | 범위 | 라벨 | 색(제안 light / dark) | 의미 문구(상세·가이드용) |
|---|---|---|---|---|
| 평범 | 0 ~ 3.49 | 평범 | textSecondary 회색 | "평균(2.5) 근처 — 나쁜 곳이 아니라 보통이에요" |
| 좋음 | 3.5 ~ 4.49 | 좋음 | success | "또 올 의향이 있어요" |
| 최상 | 4.5 ~ 5.0 | 최상 | primary | "일부러 찾아올 곳 (상위 약 0.7%)" |

- **2.5가 '평범'으로 읽히게 하는 장치**: (1) 회색조 = 경고색(빨강/주황)을 쓰지 않음, (2) 라벨 "평범" 명시, (3) 3.0 미만도 danger 색 금지, (4) 리뷰 작성 화면 상단의 "2.5 = 평범한 곳이에요" 안내를 그대로 유지(screens.md/구현 일치), (5) 덱이 별점 내림차순이므로 낮은 점수는 덱 뒤쪽에서만 만나며 그때도 같은 중립 톤.
- 색 + 라벨 + 숫자 중복 표기로 색약 대응. 별점 색은 글자·숫자에만 적용, 배경 채움 금지.
- 평균 이하 세분(예: "아쉬움")은 신설하지 않음 — 서비스 철학(엄격하되 낙인 없음).

### 3-2. 배지·태그 우선순위
카드(ReelCard) 한 줄 영역에 노출하는 배지는 **최대 3개**, 넘치면 줄바꿈하되 아래 순서로 자르고 나머지는 상세에서만 보인다.

| 우선 | 배지 | 조건 | 스타일 | 카드 | 상세 |
|---|---|---|---|---|---|
| 1 | EvidenceBadge | 항상 | surfaceAlt 바탕 + textSecondary. low 이면 warning 아이콘(⚠ 대신 Ionicons `alert-circle-outline` 12) 추가 | O | O (low 는 LowEvidenceBadge 로 설명 포함) |
| 2 | GovBudgetBadge | gov_visits>0 | govBadge 색. 문구 고정: "공공기관 업무추진비 기록 N회 (출처 기준)" | O | O |
| 3 | RelaxedBadge | 해당 조건 완화 시 | 현재 배지 아닌 회색 글자 → **pill 윤곽(border)** 로 통일 제안 | O | X |
| 4 | 가성비 태그 | 착한가격업소 | 윤곽 pill + 텍스트 "가성비". **점수 무관 → 별점 근처에 두지 않고 MetaLine 옆/하단**. 색은 중립(success 금지: 점수 좋음과 혼동) | O(자리 있을 때) | O |
| 5 | 지정목록 태그 | 모범·안심·원산지 우수 | 윤곽 pill, 상세 "점수 구성" 안에서만(카드 제외) | X | O |
| 6 | 광고 페널티 | 광고성 리뷰 감점 있음 | 카드 제외(screens.md 2-1). 상세 점수 구성 행에서만 danger 글자 | X | O |

- 협찬 라벨(리뷰 항목)은 위 체계 밖: 리뷰 행 우측 회색 pill, "협찬 표시".
- 금지 표현 "공직자". 업무추진비 배지는 govBadge 색(파랑 계열)을 이 배지에만 쓴다(다른 배지가 파랑 쓰면 혼동).
- 반드시 텍스트 포함, 아이콘 단독 금지.

---

## 4. 핵심 컴포넌트 명세

공통: 모든 눌림 요소 `accessibilityRole="button"`, 상태는 `accessibilityState`, 눌림 피드백은 opacity 0.75(100ms), 비활성은 opacity 0.4~0.5 + `disabled`.

### 4-1. ReelCard (screens.md 2-1)
- 크기: 덱 높이 1장 = 화면 전체. 패딩 좌 20 / 우 80 / 상 = 안전영역 + 16(+ 헤더) / 하 = 안전영역 + 24.
- 구성 간격: 12(md). 별점 숫자 56/64, 이름 28 최대 2줄, MetaLine 15 textSecondary.
- 상태: default / pressed(전체 opacity 0.85, 카드 자체는 눌림 하이라이트 없음) / skeleton / 큰 글자(ReasonList 스크롤).
- 접근성: 라벨 `"{이름}, 별점 {n.n}, 이 지역 상위 {p}퍼센트. 상세 보기"`(구현 일치). 지도 버튼은 카드 밖 형제 요소(버튼 중첩 금지, 구현 일치).

### 4-2. ActionRail (screens.md 2-2)
- 위치: 우측 8, 하단 32(안전영역 포함), 폭 56, 항목 간 12, 항목 최소 48x48.
- 아이콘 28 + 라벨 micro 11. 아이콘은 **Ionicons**(heart / heart-outline, close-circle-outline, create-outline 또는 chatbubble-outline, share-outline) 제안.
- 상태: default(textPrimary) / pressed(opacity .75) / selected(좋아요: 채운 하트 + primary + 라벨 "좋아요 완료") / disabled(요청 중 중복 방지 0.5).
- 레일 아이콘은 밝은/어두운 배경 어디서나 보이도록 textPrimary 사용(현재 일치). 접근성 라벨은 screens.md 표 그대로.
- 개인화 오해 방지: 좋아요/싫어요 라벨 아래 보조 문구를 붙이지 않되, **첫 사용 시 1회 툴팁** "좋아요·싫어요는 내 추천에만 반영돼요. 별점·순위는 바뀌지 않아요."(열린 질문 3).

### 4-3. Chip (FilterChip / ReasonChip / 태그 칩)
- 높이 **최소 36 시각 / 44 터치**(hitSlop 또는 minHeight 44), 가로 패딩 12, pill, 글자 caption 13.
- 상태: default(chipBg/chipText) / selected(chipBgSelected/chipTextSelected, **체크 아이콘 12 추가 제안** — 색만으로 구분 금지) / pressed(opacity .75) / disabled(opacity .4, `accessibilityState.disabled`).
- 접근성: role button + `selected` 상태, 라벨은 화면 텍스트 그대로. 그룹 제목은 `accessibilityRole="header"`.

### 4-4. Badge (Pill)
- 높이 22(세로 패딩 2~4 + caption 18), 가로 8, pill, captionStrong 13. 터치 불가(정보 전용) → `accessible` 한 덩어리 텍스트로 읽힘.
- 변형: neutral(surfaceAlt) / gov(govBadge) / outline(border + 투명) / warning(**warning 글자는 제안 색 적용 후에만 사용**).
- 접근성: 화면 문구 그대로. 아이콘이 있으면 아이콘은 `accessibilityElementsHidden`.

### 4-5. BottomSheet (DislikeReasonSheet · ReviewSheet)
- 상단 모서리 12, 바탕 background, 그림자 lg, 상단 핸들 바 36x4 (surfaceAlt→border 색) 추가 제안. 바깥 영역 overlay(0.45/0.6), 탭=닫기.
- 높이: DislikeReasonSheet 콘텐츠 맞춤(최대 60%), ReviewSheet 70%. 하단 안전영역 패딩.
- 모션: 열림 250ms standard / 닫힘 150ms exit. 닫기 접근성: 오버레이 라벨 "닫기"(구현 일치), `accessibilityViewIsModal`, 제목 role header, 포커스는 제목으로 이동.

### 4-6. Button (`components/Button.tsx`)
| 변형 | 바탕 / 글자 | 용도 |
|---|---|---|
| primary | primary / primaryText | 화면당 1개 주 행동 ("추천받기", "리뷰 쓰기") |
| secondary | surfaceAlt / primary | 보조 ("조건 다시 선택하기") |
| text | 투명 / primary | 약한 행동 ("신고하기", "설정에서 허용하기") |
- 높이 **최소 48**(현재 15pt 줄높이 22 + 12x2 = 46 → 제안: minHeight 48), 가로 패딩 16, radius 8, 라벨 bodyStrong.
- 상태: default / pressed(opacity .75) / disabled(.5, 이유가 있으면 인접 캡션) / loading(스피너, 폭 유지). primary 흰 글자 대비 문제는 2-1 제안(#C8431C) 적용 시 해결.
- 파괴적 행동(탈퇴)은 danger 글자 text 변형 + 확인 대화상자.

### 4-7. 빈 · 로딩 · 에러 상태
| 상태 | 시각 | 문구/동작 |
|---|---|---|
| 로딩(카드) | ReelCardSkeleton: 별점 자리 56x120 블록 + 이름 2줄 + 이유 3줄, surfaceAlt, 펄스 600ms(동작 줄이기 시 정지) | 현재 스피너만 → 제안 |
| 로딩(목록·시트) | Skeleton 3행 | 라벨 "불러오는 중" |
| 다음 묶음 | 마지막 칸 스피너 | "다음 가게를 불러오는 중" |
| 빈 결과 | 중앙: heading + body + secondary 버튼. 일러스트 없음(톤 유지) | screens.md 2-8 |
| 에러 | 전체화면: heading + body + primary "다시 시도". 인라인: InlineErrorBanner(danger 계열) | 문구는 사과 없이 안내형 |
| 토스트 | 하단, 높이 44, 바탕 textPrimary 반전 + 글자 background, 3초, 실패는 5초 | 되돌리기 버튼은 터치 44 이상 |
- 모든 로딩은 `accessibilityLabel`, 에러/토스트는 `accessibilityLiveRegion="polite"`(Android) / `AccessibilityInfo.announceForAccessibility`(iOS).

---

## 5. 화면 와이어프레임 (ASCII)

폭 360dp 기준 개략. `[ ]` 버튼, `( )` 칩, `{ }` 배지.

### 5-1. 검색 탭
```
┌──────────────────────────────┐
│ 찐맛                          │ 헤더
├──────────────────────────────┤
│ 지금 이 근처, 진짜 맛집만     │ title
│ (위치 배너: 꺼졌을 때만)      │
│ ┌──────────────────────────┐ │
│ │ 예) 근처 만원 이하 국밥... │ │ 입력(2~3줄)
│ └──────────────────────────┘ │
│ [      추천받기      ]       │ primary
│ 이렇게 물어보세요            │
│ (국밥 근처) (혼밥 가능) ...  │ 예시 칩
├──────────────────────────────┤
│ 🔍검색  ⚙필터  🗺내 지도  👤내 정보 │ 탭 바 (선택=primary)
└──────────────────────────────┘
```
### 5-2. 필터 탭
```
│ 조건 골라 찾기                │
│ 가격대   (1만↓)(1~2만)(2만↑) │
│ 음식 장르 (한식)(일식)(…)     │
│ 세부 메뉴 · 한식 (국밥)(…)    │ 장르 선택 시만
│ 분위기   (혼밥)(데이트)…     │
│ 음주     (가능)(불가)        │
│   음주 조건은 완화되지 않아요 │ caption
│ 거리     (300m)(500m)(1km)   │
│ 선택: 한식 · 1~2만            │ 요약
│ [추천받기]   선택 초기화      │
```
### 5-3. 내 지도 탭
```
│ 내 리뷰 지도                  │
│ ┌──────────────────────────┐ │
│ │      (전국 SVG 지도)      │ │ 시·도 탭 → 시군구
│ └──────────────────────────┘ │
│ 서울 12/340 · 경기 3/… (행)  │ 진행도 = 색 농도 + 숫자
│ 내가 다녀온 가게 N곳         │
│  가게명  ★3.5 {현장 작성}     │
```
### 5-4. 내 정보 탭
```
│ 내 정보                       │
│ [카카오로 시작하기]           │ 로그아웃 상태
│ [Google로 시작하기]           │
│  (리뷰 작성만 로그인이 필요해요)│
│ 설정 · 위치 권한 설정  >      │
│ 정보 · 찐맛 점수는 어떻게…  > │
│ 로그아웃 / 탈퇴(danger text)  │
```
### 5-5. 추천 덱 (릴스)
```
┌──────────────────────────────┐
│ 처음으로            3/24     │ 헤더 + PageIndicator
│ (조건 완화 안내 – 닫기 가능)  │
│                              │
│ {영업 정보 없음}             │
│ 4.6                          │ starHero 56, 구간색
│ {★ 4.6 · 좋음} {상위 8%}     │
│ 가게 이름이 이렇게            │ display 28
│ 두 줄까지                    │            ♥ 좋아요
│ 한식 · 1~2만 · 320m          │            ✕ 싫어요
│  · 이유 한 줄                │            ✎ 리뷰 3
│  · 이유 한 줄                │            ↗ 공유
│  · 이유 한 줄                │
│ {리뷰 근거 보통}{업무추진비…}│
│ [네이버지도][카카오맵]       │
│   ↑ 위로 밀어 다음 곳 보기   │ 첫 진입 1회
└──────────────────────────────┘
```
### 5-6. 상세
```
│ ← 가게 이름 (title)           │
│ 한식 · 1~2만 · 비주류 · 320m │
│ {★ 4.6 · 좋음} {상위 8%}     │
│ ┌ 이 점수는 어떻게 나왔을까요? ┐│
│ │ {근거 부족…}(low 일 때)    ││
│ │ 사전 점수  ▓▓▓▓░ 3.1       ││
│ │ 방문자 평균 ▓▓▓▓▓░ 4.0     ││
│ │ 최종 점수  ▓▓▓▓▓░ 4.6      ││
│ │ 사전 점수 구성 (행 7개 ±)  ││ 광고 감점 = danger 행
│ │ {업무추진비 기록 N회}      ││
│ └────────────────────────────┘│
│ · 이유                        │
│ 찐맛 리뷰 3개 [리뷰 보기]    │
│ [리뷰 쓰기] (primary)         │
│ [지도 열기] [정보 틀림 신고]  │
```
### 5-7. 리뷰 작성
```
│ 가게 이름                     │
│ ┌ 이 앱의 별점은 엄격합니다 ┐ │
│ │ 2.5=평범 3.5=또 올 의향    │ │
│ │ 4.5=일부러 찾아올 곳       │ │
│ └────────────────────────────┘│
│ (0.5)(1.0)(1.5)…(5.0)         │ 선택 칩
│ 선택한 점수 힌트 (caption)    │
│ (태그 칩들)                   │
│ ┌ 어땠는지 짧게 남겨주세요 ┐  │
│ [더 알려주기 (선택) ▾]       │
│ [리뷰 등록]                   │
```

---

## 6. 현 구현 ↔ 스펙 불일치 · 개선 제안

번호는 우선순위 순. **반영 현황**: P0 #1~3 ✅(PR #25), P1 #4~13 ✅(2026-11-05, 상단 여백은 Stack 헤더가 노치를 흡수해 하단 홈 인디케이터만 반영). P2 #14~20 미착수.

| # | 우선 | 위치 | 내용 | 제안 |
|---|---|---|---|---|
| 1 | **P0** | `tokens.ts:41`(primary light) `Button.tsx:44-46` `ui.tsx:25-37` | 흰 글자/primary 대비 3.7 — 주 버튼(15pt)·선택 칩(13pt) AA 미달 | primary(light) #C8431C |
| 2 | **P0** | `tokens.ts` success/warning light, `ui.tsx` StarRatingBadge(~L82) `restaurant/[id].tsx:~53` | 배지 글자 success 3.6 / warning 2.9 (13pt) AA 미달. 구간색이 색약 사용자에게만 정보가 되는 건 아님(라벨 병기)이나 읽기 자체가 어려움 | 2-1 제안값 또는 배지 글자는 textPrimary + 색은 점/테두리로 |
| 3 | **P0** | `recommendations.tsx:92` 와 `ui.tsx` StarRatingBadge | 카드에 별점 숫자(56pt)와 "★ 4.6 · 좋음" 배지가 숫자 중복. 정보 위계는 맞지만 스크린리더가 별점을 두 번 읽을 수 있음(카드는 Pressable 라벨로 한 번에 읽혀 영향 작음 → 시각 중복만 해당) | 카드에서는 배지를 "좋음" 라벨만(★ 숫자 제거). P0→ 사실상 P2 로 하향 가능 |
| 4 | **P1** | `ui.tsx:25-37` FilterChip | 세로 패딩 8 + 줄높이 18 = 34 < 44 터치 기준 | minHeight 44 또는 hitSlop 5, 선택 시 체크 아이콘(색만 구분 금지) |
| 5 | **P1** | `recommendations.tsx:120-124` RailButton | 아이콘이 유니코드 글리프(♥ ✕ ✎ ↗) — 기기/폰트별 모양·두께 불일치, 탭 바는 Ionicons 사용 | Ionicons 로 통일(4-2) |
| 6 | **P1** | `recommendations.tsx:36-43` OpenStatusTag | 항상 "영업 정보 없음" 고정 표시 — 스펙의 영업 중/곧 마감/영업 종료 미구현, 모든 카드 맨 위에 의미 없는 회색 칩 반복 | 데이터 없으면 숨김(노이즈 제거), 데이터 생기면 4상태 |
| 7 | **P1** | `recommendations.tsx:83` | 상단 패딩 56 하드코딩, safe area 미반영(노치/동적 섬/하단 제스처 바 기종에서 겹침 가능). `PageIndicator` 위치도 top:4 하드코딩(:461) | `useSafeAreaInsets` 기반 + 헤더 높이 |
| 8 | **P1** | `recommendations.tsx:485` | `#FFFFFF` 하드코딩(overlay 위 글자) — 토큰 우회, 밝은 모드 overlay 0.45 위 흰 글자 대비는 배경 의존 | `overlayText` 토큰 신설 |
| 9 | **P1** | `tokens.ts` 전반 | 모션 토큰 없음, 화면별 임의(애니메이션 `Modal animationType="slide"` 기본값) | 2-3 모션 토큰 도입 |
| 10 | **P1** | `ui.tsx` RelaxedBadge(`recommendations.tsx:46-55`) | 완화 표시가 배지가 아닌 맨 글자(스타일 불일치), 기타 배지는 pill | 윤곽 pill 로 통일 |
| 11 | **P1** | `Button.tsx:~47-60` | 높이 46 < 48, `TouchableOpacity`(Pressable 아님, 스펙 불일치는 아님). loading 시 폭 변동 | minHeight 48, loading 중 라벨 투명 유지 |
| 12 | **P1** | `index.tsx:~46`, `review/[id].tsx` | placeholder 가 textDisabled(대비 2.6)라 읽기 어려움 | `textPlaceholder` 신설 |
| 13 | **P1** | `recommendations.tsx:~391` | 첫 로딩이 스피너만 — 스펙의 ReelCardSkeleton 미구현 | 4-7 스켈레톤 |
| 14 | **P2** | `restaurant/[id].tsx:~125` | 광고 감점 전용 `AdPenaltyRow` 없음(점수 구성 안 `ad` 행으로만 표시), 일반 행과 스타일 차이 없음(음수만 danger 글자) | 음수 행 좌측 점 + 라벨 "감점" 병기(색만 구분 금지) |
| 15 | **P2** | `restaurant/[id].tsx` | "가성비" 태그·지정목록 태그 미구현(데이터가 API에 있으면 3-2 순서대로) | API 필드 확인 후 반영 |
| 16 | **P2** | `restaurant/[id].tsx:~127` | 상세에 리뷰 보기 버튼과 리뷰 쓰기 버튼이 모두 전체 폭 동일 위계 — primary 가 "리뷰 쓰기"인 것은 합당하나 "리뷰 보기"가 secondary 스타일로 구분되는지 확인 필요 | 보기=secondary, 쓰기=primary 고정 |
| 17 | **P2** | `recommendations.tsx:157-` DislikeReasonSheet | 시트 핸들·하단 안전영역 패딩 없음, 닫기 접근성 라벨은 있음 | 4-5 |
| 18 | **P2** | 전역 | 좋아요/싫어요가 개인화 전용임을 알리는 안내 없음 | 첫 사용 1회 툴팁(열린 질문 3) |
| 19 | **P2** | `review/[id].tsx:~157` | 별점 선택이 칩 11개(0.5 단위?)로 별 모양 없음 — 의도(엄격 숫자 중심)에는 맞음. 선택 시 구간 라벨 힌트(`ratingHint`)는 구현됨 | 힌트 문구에 구간 색 적용(선택) |
| 20 | **P2** | `tokens.ts:starScale` | 구간 3개 — 3.5 미만 전체가 "평범" | 열린 질문 2 |

비고: 위 라인 번호 중 `~` 표시는 근사치(해당 파일의 해당 컴포넌트 근처). 정확한 라인은 개발 착수 시 확인.

---

## 7. 결정 (2026-11-05 사용자 승인 — 열린 질문 1~5 전부 제안대로)
1. primary(light) #E4572E → **#C8431C** (chipBgSelected 동반). success #17794C · warning #8F5A00 · `textPlaceholder` #71757D(dark #8A8D94) 도 2-1 값대로.
2. 별점 구간은 현행 3구간(평범/좋음/최상) 유지. 평균 이하 세분 없음.
3. 좋아요/싫어요 개인화 전용 안내 툴팁(첫 사용 1회) 추가.
4. 부분 채움 별 없이 숫자 + 구간 라벨 + 상위 % 로만 표기.
5. 카드 배지 최대 3개, 우선순위 근거 > 업무추진비 > 완화 > 가성비. 가성비 태그는 카드에 자리 있을 때 노출(3-2 표대로).
