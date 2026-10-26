# 인수인계 — 업무추진비 수집기 (2026-10-26 기준)

작업 브랜치 `claude/upbeat-gauss-m8wec0` (찐맛 `master` 에서 분기, 이 폴더만 다룸)

## 1. 로컬에서 시작하기 (PowerShell, 최초 1회)
```powershell
cd C:\Restaurant_Recommendation
git fetch
git checkout claude/upbeat-gauss-m8wec0
git pull

cd expense_collector
python -m venv .venv; .venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env          # 공공데이터포털 서비스 키가 있으면 입력
notepad config.yaml             # http.user_agent 의 연락처(CHANGE_ME) 를 실제 이메일로
claude                          # docs/prompts.md 의 P0 부터 붙여넣기
```
- `claude` 는 반드시 `expense_collector` 폴더에서 실행(이 폴더 CLAUDE.md 가 우선 적용됨).

## 2. 현재 상태
| 항목 | 상태 |
|---|---|
| 명세(`CLAUDE.md`), 설정(`config.yaml`), 의존성(`pyproject.toml`), git 제외 규칙 | ✅ 준비 |
| `src/` 코드 | ⬜ 미작성 (P1 에서 생성) |
| Phase 0~5 | ⬜ |

## 3. 사용자 결정·준비 대기
| ID | 항목 | 상태 |
|---|---|---|
| D-1 | 기관 홈페이지 게시판 자동 수집 허용 여부(찐맛 크롤링 금지 원칙의 예외) | P0 에서 토론 후 결정 |
| D-2 | 카페를 찐맛 신호에 포함할지 | P0 에서 결정 |
| — | `config.yaml` User-Agent 연락처 | 입력 필요 |
| — | 공공데이터포털 오픈API 서비스 키(`DATAGOKR_API_KEY`) | 필요 시 신청 |
| — | Tesseract(kor)·LibreOffice 설치 | 스캔 PDF·HWP 확인 후 |

## 4. 다음 할 일
1. P0 기획 결정 → 2. P1 골격 + Phase 0 → 3. P2 파일럿 → … (`docs/prompts.md`)
