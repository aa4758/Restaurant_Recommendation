# QA 리포트 — 릴스형 추천 화면

범위: `docs/01_planning_decision.md` "릴스형 추천 화면"·API 계약, `docs/design/screens.md` 2장 ↔ `backend/app/{main,ratelimit,db,schemas,scoring/recommend}.py`, `mobile/app/recommendations.tsx`, `mobile/src/components/ReviewSheet.tsx`, `mobile/src/state/deviceStore.ts`.
결과: **high 0건.** 발견 13건(medium 5 / low 8) 전부 수정. pytest 220/220, `npx tsc --noEmit`·android 번들 통과. **실기기 미확인.**

## 이상 없음
반응이 점수·순위·로테이션 불변, exclude_ids 후 3곳 유지(음주 불완화), limit>5·exclude_ids>200 거부, device_id 검증, reason 은 dislike 만, 리뷰 커서 중복·누락 없음·위조 커서 400, 광고 표시 리뷰 하단 정렬, 기기 ID 비노출, X-Forwarded-For 위조로 우회 불가, 더블탭 좋아요 없음, 공유 문구에 위치·검색조건 없음, 덱 최대 5 + 종료 카드.

## 이슈
| # | 심각도 | 내용 | 조치 |
|---|---|---|---|
| 1 | medium | IP 단일 버킷(30/분) → LB 뒤·통신사 NAT 에서 정상 사용자 차단 | ✅ 기기 30/분 우선 + IP 300/분, 리뷰 작성 device_id(선택), uvicorn `--proxy-headers --forwarded-allow-ips` |
| 2 | medium | 레이트리밋 키 무한 증가 | ✅ 거부 요청 키 미생성, 빈 키 삭제, 10만 키 상한 |
| 3 | medium | 리뷰 페이지마다 전체 로드 + 정규식 | ✅ `ad_disclosed` 컬럼(작성 시 계산·백필) + 인덱스 keyset |
| 4 | medium | 기기 저장 동시 쓰기 유실(숨김 후 되돌리기 꼬임) | ✅ 메모리 마스터 + 키별 직렬화 |
| 5 | medium | 좋아요 실패 무시, 순서 뒤바뀜 | ✅ 실패 시 복원 + 토스트, id별 최신 요청만 |
| 6 | low | 보이지 않는 후보 숨김에도 추천 순서 변경 | ✅ 후보별 sha256(day\|id) 시드 |
| 7 | low | 되돌리기가 이전 좋아요를 지움 | ✅ 이전 반응 복원, 싫어요 완료 후 전송 |
| 8 | low | 언마운트·stale 응답 반영 | ✅ 요청 토큰 가드 |
| 9 | low | 스크린리더 카드 안내 없음 | ✅ announceForAccessibility, adjustable 컨테이너 |
| 10 | low | 완화 배지가 모든 카드에 | ✅ item.relaxed 항목별 |
| 11 | low | 덱 요청이 항상 5곳 | ✅ 기본 3, 최대 5 |
| 12 | low | 영업 정보 태그·0건 빈 상태·카드 애니메이션 누락 | ✅ "영업 정보 없음", EmptyResultView, LayoutAnimation |
| 13 | low | device_id Math.random | ✅ expo-crypto randomUUID |

## 남은 위험
- 레이트리밋은 프로세스 메모리 기반 → 다중 인스턴스 배포 시 공유 저장소(Redis 등) 필요.
- 로그인 없음 → 리뷰 조작 방지는 D6(영수증 인증·기기별 작성 제한)에서.
