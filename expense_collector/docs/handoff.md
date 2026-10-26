# 인수인계 — 업무추진비 수집기 (2026-10-26 기준)

작업 브랜치 `claude/upbeat-gauss-m8wec0` (찐맛 `master` 에서 분기, 이 폴더만 다룸)

## 1. 로컬에서 시작하기 (PowerShell, 최초 1회)
```powershell
cd C:\Restaurant_Recommendation
git fetch
git checkout claude/upbeat-gauss-m8wec0
git pull

cd expense_collector
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # 최초 1회: activate 스크립트 실행 허용 (Y 입력)
python -m venv .venv; .venv\Scripts\activate          # 프롬프트 앞에 (.venv) 가 보여야 함
python -m pip install -e ".[dev]"
copy .env.example .env          # 공공데이터포털 서비스 키가 있으면 입력
notepad config.yaml             # http.user_agent 의 연락처(CHANGE_ME) 를 실제 이메일로
claude                          # docs/prompts.md 의 P0 부터 붙여넣기
```
- `claude` 는 반드시 `expense_collector` 폴더에서 실행(이 폴더 CLAUDE.md 가 우선 적용됨).

## 2. 현재 상태
| 항목 | 상태 |
|---|---|
| 명세(`CLAUDE.md`), 설정(`config.yaml`), 의존성(`pyproject.toml`), git 제외 규칙 | ✅ 준비 |
| `src/` 골격 (cli·config·db·http_client) + 테스트 | ✅ P1 |
| Phase 0 기관 마스터 (`data/institutions.csv`, 미커밋) | ✅ 488곳 (교육지원청 홈페이지는 needs_review) |
| Phase 1~5 | ⬜ |

### Phase 0 출처 (2026-10-26)
- 기관 목록: code.go.kr 기관코드 전체자료(공공데이터포털 15092039 링크) → `data/raw/_phase0/` 캐시. 존폐여부=0, 차수·유형분류로 선별.
- 홈페이지: 정부24 `gov.kr/portal/orgSite`(robots 명시 허용, 92쪽). 교육지원청은 목록에 없음.
- 실제 수가 예상과 다른 이유: 전남광주통합특별시(2026-05 출범)로 광역·시도교육청 16, 인천 행정체제 개편(2026-07)으로 기초 227, 중앙 51(대통령직인수위원회 포함 — 검토).

## 3. 사용자 결정·준비 대기
| ID | 항목 | 상태 |
|---|---|---|
| D-1 | 기관 홈페이지 게시판 자동 수집 | ✅ 2026-10-26 승인: 전국 기관 단위 판정, 공공누리 1유형만(2·3·4 보류), 간격 ≥3초 (`../docs/01` 업무추진비 전국 확장) |
| D-2 | 카페를 찐맛 신호에 포함할지 | ✅ 2026-10-26 승인: export 제외, 통합 CSV 엔 보존 |
| — | `config.yaml` User-Agent 연락처 | ✅ 입력됨 |
| — | 공공데이터포털 오픈API 서비스 키(`DATAGOKR_API_KEY`) | 필요 시 신청 |
| — | Tesseract(kor)·LibreOffice 설치 | 스캔 PDF·HWP 확인 후 |

## 4. 다음 할 일
1. ~~P0~~ → ~~P1~~ → **P2 파일럿** (`docs/prompts.md`)
2. Phase 0 검토 대기: 교육지원청 178곳 홈페이지, 미확보 9곳(법제처·공소청·중대범죄수사청·대통령직인수위·용인·영월·검단구·경남교육청·전남광주교육청)
