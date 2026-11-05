# 디자인 지식 베이스 (근거 원칙집)

> 디자인 에이전트(`.claude/agents/designer.md`)가 결정을 내릴 때 **반드시 인용하는 원칙 목록**.
> 각 원칙 = ID · 내용 · 근거(출처) · 찐맛 적용. 출처는 표준·플랫폼 가이드·동료심사 논문·대학 강의·고전 교재만.
> 근거 강도: **[규범]** 표준·플랫폼 필수 / **[강]** 반복 검증된 연구 / **[중]** 단일 연구·교재 / **[약]** 효과 논쟁 중 → 단독 근거로 쓰지 않는다.
> 마지막 확인 2026-11-05. 새 원칙은 출처와 강도를 붙여 추가하고, 반박 연구가 나오면 강도를 내린다.

---

## A. 접근성 (어기면 결함)

**A1 글자 대비** [규범] 본문 4.5:1, 큰 글자(18pt, 굵게 14pt≈18.66px) 3:1 이상.
- 근거: W3C WCAG 2.2 SC 1.4.3 Contrast (Minimum), AA.
- 적용: 버튼 글자도 본문. 현재 primary 버튼 3.68:1 → 결함(`design_system.md` §0).

**A2 비텍스트 대비** [규범] 아이콘·입력창 테두리·상태 표시 등 의미 있는 그래픽은 인접 색과 3:1 이상.
- 근거: WCAG 2.2 SC 1.4.11 Non-text Contrast.
- 적용: ActionRail 윤곽 아이콘, 선택 칩 테두리. 장식용 구분선(`line`)은 예외.

**A3 색만으로 전달 금지** [규범] 색 외에 텍스트·모양·위치 중 하나를 함께 쓴다.
- 근거: WCAG 2.2 SC 1.4.1 Use of Color.
- 적용: 별점 구간 라벨(평범/좋음/최상), 좋아요 "좋아요 완료" 이중 표시 — 기존 원칙과 일치.

**A4 터치 영역** [규범] 최소 24×24 CSS px(WCAG 2.2 SC 2.5.8, AA), 권장 44×44(SC 2.5.5, AAA). 플랫폼 권장: iOS 44×44pt(Apple HIG), Android 48×48dp ≈ 9mm(Material Design).
- 적용: 찐맛 기준 **48×48** (두 플랫폼 중 큰 값). 보이는 아이콘이 작으면 `hitSlop` 으로 영역만 키운다.

**A5 움직임 줄이기** [규범] 상호작용으로 생기는 움직임은 끌 수 있어야 한다.
- 근거: WCAG 2.2 SC 2.3.3 Animation from Interactions(AAA); Apple HIG "Reduce Motion"; React Native `AccessibilityInfo.isReduceMotionEnabled`.
- 적용: 덱 넘김·시트 애니메이션은 설정 켜짐 시 투명도 전환만.

**A6 글자 크기 조절** [규범] 시스템 글자 크기(Dynamic Type / 글꼴 크기)를 키워도 잘리거나 겹치지 않아야 한다(200%까지).
- 근거: WCAG 2.2 SC 1.4.4 Resize Text; Apple HIG Typography.
- 적용: 고정 높이 박스에 글자 넣지 않기. `hero` 숫자는 `maxFontSizeMultiplier` 로 상한.

**A7 스크린리더 이름·역할·상태** [규범]
- 근거: WCAG 2.2 SC 4.1.2 Name, Role, Value.
- 적용: 모든 터치 요소에 `accessibilityRole`·`accessibilityLabel`·`accessibilityState`. 별점은 "별점 4.6, 최상"처럼 읽히게.

## B. 인지·지각 (사람의 한계)

**B1 피츠의 법칙** [강] 목표까지 걸리는 시간은 거리에 비례, 크기에 반비례(로그).
- 근거: Fitts (1954) J. Exp. Psychology; MacKenzie (1992) HCI 정식화.
- 적용: 자주 누르는 것(좋아요·다음)은 크게, 엄지 가까이. 위험한 행동(삭제)은 멀리.

**B2 힉-하이먼 법칙** [강] 선택지가 늘수록 결정 시간이 로그로 증가.
- 근거: Hick (1952); Hyman (1953).
- 적용: 화면당 주 행동 1개. 필터 그룹은 접어서 단계 공개(B6).

**B3 작업기억 한계** [강] 동시에 붙잡을 수 있는 덩어리는 약 4개(±1). "7±2"는 낡은 수치.
- 근거: Miller (1956) Psych. Review; Cowan (2001) Behavioral and Brain Sciences.
- 적용: 카드 한 장의 정보 덩어리 4개 이하(별점·이름·태그·이유). 태그 최대 3개.

**B4 인지 부하** [강] 과제와 무관한 정보(외재적 부하)는 이해를 방해한다.
- 근거: Sweller (1988) Cognitive Science.
- 적용: 미니멀의 이론적 근거. 장식·중복 문구 제거, 점수 산식은 별도 화면(ScoringExplainer)으로.

**B5 게슈탈트 — 근접·유사·공통 영역** [강] 가까운 것, 닮은 것, 같은 면 안의 것은 한 묶음으로 보인다.
- 근거: Wertheimer (1923); Palmer (1992) Cognitive Psychology "Common region".
- 적용: 선 대신 **여백**으로 묶는다(간격 8 = 묶음 안, 24 = 묶음 사이). 면 색(surface)은 묶음 경계가 꼭 필요할 때만.

**B6 단계적 공개** [중] 고급·드문 기능은 처음에 숨기고 필요할 때 보인다.
- 근거: Nielsen Norman Group "Progressive Disclosure" (2006); Tidwell 외 *Designing Interfaces* 3판 (O'Reilly, 2020).
- 적용: 점수 근거(breakdown)는 상세 화면에서만. 카드에는 결론(별점)과 이유 한 줄만.

**B7 고립 효과(폰 레스토프)** [강] 무리 중 혼자 다른 것이 기억·주목된다.
- 근거: von Restorff (1933) Psychologische Forschung.
- 적용: **강조색을 하나만, 드물게** 쓰는 근거. 강조색이 여기저기 쓰이면 효과가 사라진다 → '최상' 별점·주 버튼에만.

**B8 응답 시간 한계** [강] 0.1초 = 즉각, 1초 = 흐름 유지, 10초 = 주의 유지 한계.
- 근거: Miller (1968) AFIPS "Response time in man-computer conversational transactions"; Card, Robertson, Mackinlay (1991) CHI; Nielsen *Usability Engineering* (1993) 5장.
- 적용: 누름 반응 100ms 이내(즉시 눌림 표시), 1초 넘는 로딩은 스켈레톤, 10초 넘으면 진행·취소 제공.

## C. 사용성 휴리스틱·상호작용

**C1 닐슨 10대 휴리스틱** [강] 상태 가시성, 실세계 일치, 사용자 통제·자유(되돌리기), 일관성·표준, 오류 예방, 기억보다 인식, 유연성·효율, 미니멀한 미학, 오류 복구 도움, 도움말.
- 근거: Nielsen (1994) "Enhancing the explanatory power of usability heuristics", CHI '94; NN/g 10 Usability Heuristics.
- 적용: 디자인 리뷰 체크리스트의 뼈대. 8번 "Aesthetic and minimalist design" = 관련 없는 정보는 관련 있는 정보와 경쟁한다.

**C2 시그니파이어·피드백·매핑** [강] 무엇을 할 수 있는지 보여 주고(시그니파이어), 한 일의 결과를 즉시 알리고(피드백), 조작과 결과의 대응을 자연스럽게(매핑).
- 근거: Norman, *The Design of Everyday Things* 개정판 (2013).
- 적용: 미니멀의 함정 — 버튼처럼 안 보이는 버튼. 누를 수 있는 글자는 굵기·밑줄·위치 중 하나로 표시. 스와이프는 첫 실행 힌트(screens 2-6).

**C3 플랫폼 관례 따르기** [규범] 뒤로 가기, 하단 시트 끌어 닫기, 탭 바 등은 각 OS 관례대로.
- 근거: Apple HIG; Material Design 3; 휴리스틱 C1-4(일관성·표준).
- 적용: 자체 제스처 발명 금지. 덱 세로 스와이프는 숏폼 앱 관례로 인정.

**C4 되돌리기 > 확인 창** [중] 되돌릴 수 있는 행동은 확인 창 대신 실행 후 "실행 취소"를 준다.
- 근거: Nielsen 휴리스틱 3(사용자 통제); Raskin, *The Humane Interface* (2000).
- 적용: 싫어요·숨기기 → 토스트에 "되돌리기". 리뷰 삭제만 확인 창.

**C5 엄지 영역** [중] 한 손 조작이 흔하므로 주 행동은 화면 아래쪽·가운데에.
- 근거: Hoober (2013) UXmatters "How Do Users Really Hold Mobile Devices?" — 화면을 만지던 780명 중 한 손 49%, 받쳐 잡기 36%, 두 손 15%. **주의:** 2013년 관찰, 화면이 커진 지금과 다를 수 있고 저자 스스로 일부 도식을 수정함 → 비율보다 "아래가 닿기 쉽다"는 방향만 쓴다.
- 적용: CTA·ActionRail 은 하단 절반. 화면 상단 모서리에 주 행동 두지 않기.

**C6 움직임은 의미를 전달할 때만** [중] 애니메이션은 공간 관계(어디서 와서 어디로 가는지)와 상태 변화를 알릴 때 쓴다. 들어올 때 감속, 나갈 때 가속.
- 근거: Material Design 3 Motion (easing: emphasized decelerate `cubic-bezier(0.05,0.7,0.1,1)` 진입 / emphasized accelerate `(0.3,0,0.8,0.15)` 퇴장, 지속 50~600ms 단계); Apple HIG Motion.
- 적용: 작은 요소 100~200ms, 시트·카드 250~400ms. 장식용 반복 애니메이션 금지.

## D. 미학·첫인상

**D1 미적-사용성 효과** [강] 보기 좋은 화면을 더 쓰기 쉽다고 느끼고 작은 문제에 관대해진다.
- 근거: Kurosu & Kashimura (1995) CHI; Tractinsky, Katz, Ikar (2000) Interacting with Computers "What is beautiful is usable".
- 적용: 다듬기에 시간을 쓸 가치가 있다는 근거. 단, 실제 사용성 문제를 가리므로 QA는 과제 기반으로.

**D2 첫인상은 순간에, 복잡도가 좌우** [강] 화면의 시각적 호감은 50ms 안에 형성되고 오래 본 뒤 판단과 일치한다. 첫인상에는 색채보다 **시각 복잡도**의 영향이 크다.
- 근거: Lindgaard 외 (2006) Behaviour & Information Technology "Attention web designers: You have 50 milliseconds..."; Reinecke 외 (2013) CHI "Predicting users' first impressions of website aesthetics..." (웹사이트 450개·참가자 548명).
- 적용: 미니멀 방향의 직접 근거. 카드 첫 화면 요소 수를 줄이는 것이 색을 바꾸는 것보다 효과가 크다. 같은 연구에서 선호 복잡도는 연령·문화에 따라 다름 → 너무 비우면 오히려 낮게 평가될 수 있음(중간 복잡도가 최고점).

**D3 글자 짜임** [중] 한 줄 45~75자(라틴 기준), 줄간격 본문 크기의 약 1.4~1.6배, 크기 단계는 일정 비율.
- 근거: Bringhurst, *The Elements of Typographic Style* (4판, 2012); Material 3 Type scale.
- 적용: 한글은 글자 폭이 넓어 한 줄 글자 수가 더 적다 → 카드 이유 문구 2줄 이내. 본문 15/22(1.47배).

**D4 숫자 표기** [중] 바뀌는 숫자는 고정폭 숫자로 정렬·흔들림 방지.
- 근거: Bringhurst (2012) 숫자 장; Apple HIG Typography(SF 의 tabular figures).
- 적용: 별점 `fontVariant: ['tabular-nums']`.

## E. 추천·평가 화면 (도메인)

**E1 추천 이유 설명** [강] 설명의 목적 7가지: 투명성, 이의 제기(scrutability), 신뢰, 효과성, 설득, 효율, 만족. 목적끼리 충돌하므로 무엇을 노리는지 정해야 한다.
- 근거: Tintarev & Masthoff (2007) ICDE Workshop "A survey of explanations in recommender systems"; (2012) UMUAI "Evaluating the effectiveness of explanations for recommender systems".
- 적용: 찐맛은 **투명성·신뢰** 우선(설득 아님). 이유 문구는 사실 기반("공공기관 업무추진비 기록 3회"), 과장 금지. 싫어요 이유 시트 = 이의 제기 통로. 투명성이 곧 신뢰는 아님 — 이해 못 할 설명은 역효과.

**E2 평점 분포의 왜곡** [강] 일반 리뷰 평점은 J자형(극단치 과다)으로 평균이 실제 품질을 잘 대표하지 못한다.
- 근거: Hu, Pavlou, Zhang (2009) Communications of the ACM "Overcoming the J-shaped distribution of product reviews".
- 적용: 엄격 별점(평균 ≈ 2.5)의 근거. 화면은 사용자가 익숙한 "4점 = 보통"을 깨야 하므로 **3.0 이 나쁘지 않다**는 것을 구간 라벨·점수 기준 화면으로 알린다.

**E3 근거 양 표시** [중] 적은 표본의 평균은 불확실함을 함께 보여 줘야 오해를 줄인다.
- 근거: Kay, Kola, Hullman, Munson (2016) CHI "When (ish) is my bus?" 불확실성 시각화; Hullman 외 (2019) IEEE TVCG 불확실성 표현 평가.
- 적용: EvidenceBadge(근거 적음/보통/충분) 유지 — 숫자 옆에 같은 무게로.

**E4 선택 과부하** [약] 선택지가 많으면 선택을 포기한다는 효과는 유명하지만 메타분석상 평균 효과는 거의 0, 조건에 따라 나타난다.
- 근거: Iyengar & Lepper (2000) JPSP; Scheibehenne, Greifeneder, Todd (2010) J. Consumer Research 메타분석.
- 적용: 단독 근거로 쓰지 않는다. 한 장씩 보여 주는 덱 구조의 근거는 B3·B4 로 댄다.

**E5 끝맺음 경험(피크-엔드)** [중] 경험의 기억은 절정과 끝 순간이 좌우한다.
- 근거: Kahneman, Fredrickson, Schreiber, Redelmeier (1993) Psychological Science; Fredrickson & Kahneman (1993) JPSP.
- 적용: EndOfDeckCard 를 빈 화면이 아닌 다음 행동(조건 넓히기)을 주는 끝맺음으로.

## F. 윤리 (어기면 결함)

**F1 다크 패턴 금지** [강] 성가심(nagging), 방해(obstruction), 몰래(sneaking), 인터페이스 간섭, 강요의 5유형.
- 근거: Gray, Kou, Battles, Hoggatt, Toombs (2018) CHI "The dark (patterns) side of UX design"; Mathur 외 (2019) CSCW 쇼핑몰 1.1만 곳 조사.
- 적용: 로그인 강요 금지(리뷰 작성만 로그인 — 기존 결정), 협찬 표시 숨기기 금지, 무한 덱에 끝 표시(EndOfDeckCard) 유지, 좋아요/싫어요가 순위에 영향 없음을 오해시키는 문구 금지.

---

## 학습 경로 (출처 목록)

| 분류 | 출처 |
|---|---|
| 표준 | W3C WCAG 2.2 (2023, 2024 개정) 및 Understanding 문서 — https://www.w3.org/WAI/WCAG22/Understanding/ |
| 플랫폼 | Apple Human Interface Guidelines — https://developer.apple.com/design/human-interface-guidelines/ · Material Design 3 — https://m3.material.io/ |
| 강의 | Stanford CS147 Introduction to HCI Design · MIT 6.813/6.831 User Interface Design & Implementation · UC San Diego(Klemmer) Interaction Design Specialization (Coursera) |
| 교재 | Norman *The Design of Everyday Things* (2013) · Johnson *Designing with the Mind in Mind* 3판 (2020) · Tidwell 외 *Designing Interfaces* 3판 (2020) · Bringhurst *The Elements of Typographic Style* (2012) · Nielsen *Usability Engineering* (1993) |
| 논문 | 각 원칙에 표기 (CHI, CSCW, TOCHI, UMUAI, CACM, JPSP 등) |
| 연구기관 | Nielsen Norman Group 아티클(연구 기반 실무 지침, [중]으로 취급) |

**포함하지 않는 것:** 개인 블로그·Medium·Dribbble 유행, 출처 없는 "UX 법칙" 모음(예: 출처 불명 수치). 필요하면 원 논문을 찾아 위 형식으로 추가한다.
