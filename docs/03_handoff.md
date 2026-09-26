# 인수인계 (클라우드 세션 → 로컬 Claude Code)

로컬 경로: `C:\Restaurant_Recommendation` · 브랜치: `claude/blissful-brahmagupta-w7t81a`

## 이어받기
```cmd
cd C:\
git clone https://github.com/aa4758/Restaurant_Recommendation.git
cd Restaurant_Recommendation
git checkout claude/blissful-brahmagupta-w7t81a
claude
```
(이미 클론돼 있다면 `git fetch && git checkout claude/blissful-brahmagupta-w7t81a && git pull`)

첫 프롬프트 예시:
> docs/00_brief.md, 01_planning_decision.md, 02_roadmap.md, 03_handoff.md 를 읽고 로드맵 2-A단계부터 멀티 에이전트로 이어서 진행해줘. 에이전트 간 통신 규칙(요약본만 전달, XML 구조화 출력, 최소 도구, 모델 티어링)은 그대로 적용.

## 단계별 현재 상태
| 단계 | 상태 | 남은 일 |
|---|---|---|
| 0 브리프 / 1 기획 결정 / 2-B 디자인 | ✅ 완료 | — |
| 2-A 백엔드·엔진 | ✅ 완료(pytest 15개 통과) | — |
| 3 모바일 | ⚠️ 중단(초기 골격만) | 아래 참고 |
| 4 QA / 5 운영 / 6 배포 / 7 실데이터 | ⏳ 미착수 | `docs/02_roadmap.md` 참고 |

### 2-A 백엔드 — 작성됨(미검증)
`backend/app/`: main.py, schemas.py, db.py, service.py, constants.py, scoring/{prior,strict,bayes,recommend}.py, ingest/{base,csv_adapters,kakao,load_seed}.py, `backend/data/seed/*.csv`
**남은 일:** `backend/requirements.txt`, `backend/README.md`, `backend/tests/`(pytest: 단조성, 평균≈2.5, cap/floor, n=20→50:50, 완화 로직, API), 전체 테스트 실행·수정. 코드가 결정문 점수 모델·API 계약과 일치하는지 검토 필요.

### 3 모바일 — 골격만
있음: package.json, app.json, tsconfig.json, babel.config.js, src/api/client.ts, src/state/useLocation.ts, src/components/{Button,RetryButton}.tsx, src/theme/(디자인팀 완료)
**남은 일:** 5개 화면(docs/design/screens.md), 핵심 컴포넌트, 라우팅, `npm install` + `npx tsc --noEmit`, mobile/README.md(Windows 실행법).

## 결정 사항 요약(변경 시 01 문서 먼저 수정)
- 네이버 크롤링 금지 → 공식 API·공공데이터·CSV 어댑터만
- 업무추진비: log 감쇠+상한 가중, 배지 문구 "공공기관 업무추진비 기록 N회"
- 광고리뷰: 감점+하한, 판별 신뢰도 반영
- 엄격 별점 평균≈2.5 + 상위 N% 병기, 베이지안 k=20
- 추천 3곳 + 이유, 완화 순서 거리→분위기→가격→장르(음주 불완화)
- 스택: Expo(RN, TS) + FastAPI + SQLite
