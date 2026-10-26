# 인수인계 — 클라우드 세션 → 로컬 Claude Code (2026-10-26 기준)

로컬 경로 `C:\Restaurant_Recommendation` · 원격 `aa4758/Restaurant_Recommendation`
작업 브랜치 `claude/blissful-brahmagupta-w7t81a` · 열린 PR **#6** (별점 근거 데이터 입력기, CI 결과 확인 필요)

---

## 1. 로컬에서 이어받기

### 1-1. 코드 받기 (PowerShell)
```powershell
cd C:\Restaurant_Recommendation
git fetch
git checkout claude/blissful-brahmagupta-w7t81a
git pull
```
PR #6 이 병합된 뒤라면 `git checkout master; git pull` 로 충분합니다.

### 1-2. 환경 (최초 1회)
```powershell
cd C:\Restaurant_Recommendation\backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt          # pytest 포함 (pyproj 등은 requirements.txt)
python -m pytest -q                          # 299개 통과가 정상

cd ..\mobile
npm install                                  # expo install 이 403 이면 npm install 로
npx tsc --noEmit
```

### 1-3. Claude Code 실행 + 첫 프롬프트
```powershell
cd C:\Restaurant_Recommendation
claude
```
첫 프롬프트 예시(복사해서 사용):
> CLAUDE.md 와 docs/03_handoff.md 를 읽고 현재 상태를 요약해줘. 그다음 "3. 다음 할 일" 1번부터 진행하자. 기존처럼 기획(찬성/반대)·개발·디자인·품질검증·운영 팀으로 나눠 멀티 에이전트로 진행하고, 에이전트 간 통신 규칙(요약본만 전달, XML 구조화 출력, 최소 도구, 모델 티어링)을 지켜줘.

---

## 2. 현재까지 진행 상황

### 2-1. 단계별
| 단계 | 상태 | 근거 |
|---|---|---|
| 0 브리프 · 1 기획 결정 | ✅ | `docs/00_brief.md`, `docs/01_planning_decision.md` |
| 2 백엔드·점수 엔진 / 디자인 | ✅ | `backend/`, `docs/design/screens.md` |
| 3 모바일(5화면) · 3-B 릴스형 추천 | ✅ (**실기기 미확인**) | `mobile/`, `docs/qa/report_reels.md` |
| 4 QA · 5 운영 준비 | ✅ | `docs/qa/`, `ops/runbook.md`, `.github/workflows/`, `mobile/eas.json` |
| 6 배포 | 👤 미착수 | 계정·호스팅 필요(`docs/02_roadmap.md` 하단) |
| 7 실데이터 | 🔄 | 아래 2-3 |

### 2-2. 병합된 PR
| PR | 내용 |
|---|---|
| #1 | MVP: 백엔드·모바일·QA·운영 준비(0~5단계) |
| #2 | D0·D1: 스키마 v2, 상가정보 어댑터, 점수 배치 계산 |
| #3 | 사전 점수 v2·v2.1(공공 신호 기반 prior) |
| #4 | D2 인허가 적재 + 릴스형 추천 화면 |
| #5 | 인허가 실데이터 적재 수정(헤더 별칭, 지역 키, 전남광주, 휴게음식점 처리, v1 DB 업그레이드) |
| **#6 (열림)** | 별점 근거 입력기: 공공 지정목록·위생등급·행정처분, 인허가번호 우선 매칭 |

### 2-3. 로컬 DB 상태 (`backend\data\jjinmat.db`, git 제외)
- 기존 v1 DB 는 `data\jjinmat_v1_backup.db` 로 백업(가상 샘플 48곳 포함 — 실서비스에 쓰지 말 것).
- **전국 일반음식점 647,729곳** 적재(인허가 기반 `L{관리번호}`), 점수 계산 완료, 평균 별점 ≈ 2.47.
- 지역 256곳(이름 키 `N:<시도> <시군구>` — 상가정보 적재 시 공식 코드로 자동 치환). 지역 없음 0.
- 휴게음식점 파일 적재 완료(신규 생성 없음, 매칭 가게 판별용) — 영업 중 일반 가게를 덮어쓰지 않음 확인.
- 미매칭 약 2.1만 곳(주로 좌표 없음) → `data\out\unmatched_license.csv`.
- **별점 근거는 현재 대부분 '업력'뿐** → 많은 가게가 evidence=low("근거 부족").

### 2-4. 원본 데이터 파일 위치 (git 제외)
| 폴더 | 내용 |
|---|---|
| `backend\data\raw\license\` | `식품_일반음식점.csv`(230만 행), `식품_휴게음식점.csv`(65만 행) — 적재 완료 |
| `backend\data\raw\sbiz\` | 상가(상권)정보 — 아직 없음(선택) |
| `backend\data\raw\designations\` | 모범음식점·안심식당·백년가게·착한가격업소 등 — 받을 예정 |
| `backend\data\raw\food_safety\` | 위생등급·행정처분 — 받을 예정 |

---

## 3. 다음 할 일 (우선순위)

1. **PR #6 마무리** — CI 확인 → 병합.
2. **별점 근거 데이터 적재** (파일마다 `--check` → `--dry-run` → 적재, 아래 4-2)
   - 바로 받을 수 있음: 백년가게(data.go.kr 15132695), 원산지표시 우수(국립수산물품질관리원), 모범음식점(시도 현황 + 지자체)
   - 지자체별: 안심식당, 위생등급, 착한가격업소(서울은 열린데이터광장)
   - 직접 정리: 서울미식 100선 / 서울미래유산 / 향토음식점 → 고정 열 CSV(4-3)
   - 인허가 파일 추가 열(`등급구분명`, `전통업소지정번호`) 분포 확인 → 점수 반영 여부를 기획에서 결정
3. **API 키 필요 작업**
   - 행정처분(식품접객업) 오픈API 서비스 키 → API 수집 스크립트 작성(키는 `.env`, git 제외)
   - 식품안전나라 위생등급 API(필요 시)
4. **업무추진비(가중치 0.25, 가장 큼)** — 기관·연도 범위 결정 → 수기 정규화 CSV → `load_designations` 가 아닌 기존 `GovExpenseCSVAdapter` 경로(PII 화이트리스트).
5. **앱 실기기 확인** — 서버 + Expo Go 로 실데이터 추천·릴스 덱·리뷰 시트 동작 확인(4-4).
6. **미매칭 2.1만 곳** — 주소→좌표 지오코딩(예: 브이월드 API, 키 필요).
7. **D5** 지도 링크·메뉴·영업시간 표시 / **D6** 영수증 인증·리뷰 조작 방지(출시 전 필수) + 최종 별점 v2 승인.
8. **배포(6단계)** — Expo 계정, 서버 호스팅, 스토어 계정, `mobile/eas.json` API URL 교체.

---

## 4. 명령어 모음 (PowerShell, `C:\Restaurant_Recommendation\backend` 에서)

### 4-1. 인허가
```powershell
python -m app.ingest.load_license data\raw\license\식품_일반음식점.csv --check
python -m app.ingest.load_license data\raw\license\식품_일반음식점.csv --dry-run
python -m app.ingest.load_license data\raw\license\식품_일반음식점.csv
python -m app.ingest.load_license data\raw\license\식품_휴게음식점.csv
python -m app.ingest.load_license --fix-regions          # 지역 없음 가게 지역 키 재계산
python -m app.ingest.load_license <csv> --calibrate      # 상가정보 적재 후에만 의미 있음
```

### 4-2. 지정목록 / 위생·처분 (PR #6)
```powershell
# --kind: model_restaurant | safe_restaurant | origin_label_excellent | century_store | good_price
#         taste_of_seoul | seoul_future_heritage | local_food   (michelin_* 는 법무 확인 전 보류)
python -m app.ingest.load_designations data\raw\designations\백년가게.csv --kind century_store --source "중소벤처기업부 백년가게" --check
python -m app.ingest.load_designations data\raw\designations\백년가게.csv --kind century_store --source "중소벤처기업부 백년가게" --dry-run
python -m app.ingest.load_designations data\raw\designations\백년가게.csv --kind century_store --source "중소벤처기업부 백년가게"

python -m app.ingest.load_food_safety data\raw\food_safety\위생등급.csv --type hygiene --check
python -m app.ingest.load_food_safety data\raw\food_safety\행정처분.csv --type sanction --check
```
- `--check` 출력의 `헤더:`·`매핑:` 줄을 먼저 확인(실제 원본 헤더로는 아직 미검증). 못 찾는 열은 별칭 추가.
- xlsx 는 CSV 로 저장 후 사용. 미매칭은 `data\out\unmatched_*.csv`(PII 없음).

### 4-3. 직접 정리하는 목록 CSV 양식
```csv
name,address,lat,lng,kind,base_date,source
가게이름,서울특별시 중구 세종대로 110,,,taste_of_seoul,2025-01-01,서울미식 100선 2025
```

### 4-4. 서버·앱 실행
```powershell
# 서버
cd C:\Restaurant_Recommendation\backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 앱 (다른 창) — EXPO_PUBLIC_API_URL 에 PC 의 LAN IP
cd C:\Restaurant_Recommendation\mobile
$env:EXPO_PUBLIC_API_URL = "http://<PC_LAN_IP>:8000"
npx expo start          # 휴대폰 Expo Go 로 QR 스캔
```

### 4-5. DB 상태 확인 (한글 출력 깨짐 방지 포함)
```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
@'
from app.db import connect
c = connect(); q = lambda s: c.execute(s).fetchone()[0]
print("가게", q("SELECT COUNT(*) FROM restaurants"), "점수", q("SELECT COUNT(*) FROM scores"))
print("지역", q("SELECT COUNT(DISTINCT sigungu_code) FROM restaurants"), "지역없음", q("SELECT COUNT(*) FROM restaurants WHERE sigungu_code IS NULL"))
print("평균별점", q("SELECT ROUND(AVG(star),2) FROM scores"))
for k, n in c.execute("SELECT IFNULL(evidence,'-'), COUNT(*) FROM scores GROUP BY 1"): print("근거", k, n)
for k, n in c.execute("SELECT kind, COUNT(*) FROM restaurant_signals GROUP BY 1"): print("신호", k, n)
'@ | python -
```
- PowerShell 에서 `python -c "..."` 안에 `\"` 를 쓰면 깨짐 → 위처럼 here-string(`@' ... '@ | python -`) 사용.

### 4-6. 테스트·검사
```powershell
cd C:\Restaurant_Recommendation\backend; python -m pytest -q
cd C:\Restaurant_Recommendation\mobile;  npx tsc --noEmit
```

---

## 5. 작업하면서 배운 주의점
- **헤더는 배포처·시점마다 다름** → 새 파일은 항상 `--check` 먼저. 별칭은 `app/ingest/license.py`(ALIASES)·`signal_common.py`.
- **2026 행정구역 변경**: 전남광주통합특별시(광주+전남). 옛 이름도 같은 약칭 `전남광주` 로 처리(`matcher._SIDO_MERGED`). 새 시도명이 나오면 `_SIDO_LONG` 에 추가.
- **일반 → 휴게 순서 적재**: 영업 중 인허가가 붙은 가게는 자기 관리번호 행으로만 닫힘(PR #5 수정).
- **엄격 별점은 시군구 단위 분위수** → 지역 키가 비면 전국 한 묶음이 됨. 적재 후 '지역없음' 확인.
- **expo install 이 프록시 403** 이면 `node_modules/expo/bundledNativeModules.json` 의 버전으로 `npm install`.
- 클라우드 세션에선 PC 의 `data\raw\` 파일을 볼 수 없음 → 로컬에서는 Claude Code 가 직접 파일을 읽고 `--check` 를 돌릴 수 있음.

---

## 6. 사용자 결정·준비 대기 목록
| 항목 | 상태 |
|---|---|
| 업무추진비 범위(기관·연도) | 결정 필요 |
| 행정처분 API 서비스 키 | 신청 필요 |
| 인허가 추가 열(등급구분명·전통업소) 점수 반영 | 분포 확인 후 결정 |
| 최종 별점 v2(영수증 인증 가중·시간 감쇠·후한 작성자 보정) | 승인 필요(D6 과 함께) |
| 미슐랭·업무추진비 배지·공공누리 출처표시 | 법무 검토 |
| 배포 계정(Expo·스토어)·서버 호스팅 | 준비 필요 |
