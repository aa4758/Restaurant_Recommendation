# 배포 가이드 — Railway (백엔드) + EAS (안드로이드 앱)

결정: `docs/01` '로그인·리뷰 신뢰·메뉴 수집·배포'(2026-10-30) — **Railway + 볼륨**, SQLite 그대로. 실제 배포는 **최종 단계**에서 진행.
처음 해 보는 사람 기준. 명령은 PowerShell. Railway 화면 메뉴 이름·요금은 바뀔 수 있으니 진행할 때 화면 기준으로 맞춘다.

---

## 0. 배포 전에 저장소에서 먼저 해결할 것 (개발 작업 — 배포 직전에 같이 처리)
| # | 문제 | 해결안 |
|---|---|---|
| P-1 | **로컬 DB(612MB)를 서버 볼륨에 올릴 방법.** 지금 Dockerfile 은 DB 가 없으면 가상 시드를 적재 → 그대로 배포하면 실데이터가 아닌 시드로 뜸 | 첫 시작 때 DB 가 없으면 **환경변수 `DB_DOWNLOAD_URL` 의 압축 파일을 받아 볼륨에 풀기**(1회). DB 는 압축(약 150~250MB 예상) 후 임시 공유 링크로 올림(내려받은 뒤 링크 삭제). 코드: Dockerfile CMD 수정 |
| P-2 | Dockerfile 의 `VOLUME /data` 줄 | Railway 는 Dockerfile `VOLUME` 대신 자체 볼륨을 쓴다(빌드가 막힐 수 있음) → 줄 삭제, 볼륨은 화면에서 `/data` 에 연결 |
| P-3 | **데이터 갱신 방식이 바뀜.** 지금은 내 PC 에서 적재(인허가·지정목록·업무추진비·세부 분류) → 배포 후에는 리뷰·반응·미인식 낱말이 **서버 DB** 에 쌓임. PC DB 를 다시 올리면 사용자 데이터가 덮어써짐 | 결정 필요(아래 '남은 결정' D-1) |
| P-4 | **주간 사전 보강(`nlp_enrich`)이 PC 작업 스케줄러에서 PC DB 를 대상으로 돎** → 배포 후엔 미인식 낱말이 서버에 쌓이므로 PC 작업은 의미 없음 | Railway **Cron** 서비스로 옮기고(같은 볼륨·`ANTHROPIC_API_KEY`), PC 작업은 삭제(`schtasks /Delete /TN "JJINMAT nlp_enrich" /F`) |
| P-5 | 메뉴명 분류 모델(`data/models/menu_subtype.json`, 7MB)은 git 제외 | 서버에서는 문장 해석의 보조로만 쓰임(없어도 동작). 넣으려면 P-1 압축 파일에 함께 포함 |

---

## 1. 준비 (가입·확인)
1. **GitHub Student Developer Pack** 신청(학생 인증) → 혜택 목록에서 Railway 등 호스팅 크레딧이 있는지 확인. 없으면 그대로 진행.
2. **Railway 가입**: railway.com → GitHub 계정으로 로그인(저장소 연결이 쉬워짐).
3. **요금제 확인**: 볼륨(디스크)을 쓰려면 보통 유료(Hobby) 플랜. 예상 월 약 $5 — 가입 시 실제 요금·포함 사용량 확인. **사용 한도(usage limit)** 를 설정해 과금 상한을 둔다.

## 2. 백엔드 서비스 만들기
1. Railway → **New Project → Deploy from GitHub repo** → `aa4758/Restaurant_Recommendation` 선택.
2. 서비스 **Settings**
   - **Root Directory**: `backend` (Dockerfile 이 있는 폴더)
   - Builder: Dockerfile 자동 인식 확인
   - **Region**: 한국에서 가장 가까운 지역(아시아 — 예: 싱가포르/도쿄 계열, 목록에서 선택)
   - **Healthcheck Path**: `/health`
3. **Volume 추가**: 서비스에 볼륨 생성 → **Mount Path `/data`**, 크기 1GB 이상(DB 612MB + 여유).
4. **Variables(환경변수)**
   | 이름 | 값 | 비고 |
   |---|---|---|
   | `JJINMAT_DB` | `/data/jjinmat.db` | Dockerfile 기본값과 같음(확인용) |
   | `FORWARDED_ALLOW_IPS` | `*` | Railway 프록시 뒤라 실제 사용자 IP 로 레이트리밋 |
   | `DB_DOWNLOAD_URL` | (P-1 압축 파일 링크) | 첫 배포 후 DB 가 생기면 **삭제** |
   | `KAKAO_REST_KEY` 등 | 필요한 키만 | 키는 Railway 변수에만, 저장소에 넣지 않음 |
   | `AUTH_SECRET` | **PC 와 같은 값** | 바꾸면 기존 계정이 끊김(`ops/runbook.md` '소셜 로그인') |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 구글 OAuth | |
   | `PUBLIC_BASE_URL` | `https://<2-5 에서 받은 주소>` | 주소 발급 후 입력 |
   | `AUTH_REDIRECTS` | `jjinmat://` | 개발용 주소(`exp://`, `localhost`) 제외 |
   `PORT` 는 Railway 가 자동으로 넣음(Dockerfile 이 `${PORT:-8000}` 사용).
5. **Networking → Generate Domain** → `https://<이름>.up.railway.app` 같은 주소 발급.
6. 배포 로그에서 `Uvicorn running` 확인 → 브라우저로 `https://<주소>/health` → `{"status":"ok"}`, `/meta/filters` 응답 확인.

## 3. DB 올리기 (P-1 방식, 최초 1회)
```powershell
cd C:\Restaurant_Recommendation\backend\data
tar -czf jjinmat_db.tgz jjinmat.db ..\data\models\menu_subtype.json   # 모델은 선택
```
1. `jjinmat_db.tgz` 를 비공개 링크로 공유할 수 있는 곳에 업로드(예: 개인 클라우드 드라이브의 '링크가 있는 사람' 공유 → 직접 다운로드 링크).
2. Railway 변수 `DB_DOWNLOAD_URL` 에 링크 → 재배포 → 로그에서 다운로드·압축 해제 확인.
3. `/restaurants/<가게 id>` 로 실데이터 확인 → **`DB_DOWNLOAD_URL` 삭제 + 공유 링크 삭제.**
- DB 에는 개인정보가 없지만(공공데이터·점수), 링크는 확인 직후 지운다.

## 4. 주간 사전 보강 옮기기 (P-4)
1. 같은 프로젝트에 **Cron 서비스** 추가(같은 저장소·`backend`), Start Command `python -m app.nlp_enrich run`, Schedule `0 19 * * 0` (UTC 일 19:00 = KST 월 04:00).
2. 같은 볼륨 `/data` 연결 가능 여부 확인(안 되면 백엔드 서비스 안에서 주 1회 실행하는 방식으로 대체 — 배포 직전에 결정).
3. 변수 `ANTHROPIC_API_KEY`, `JJINMAT_DB=/data/jjinmat.db`.
4. 승인(`list`/`approve`)은 Railway 서비스의 셸/명령 실행 기능으로.

## 4-1. 소셜 로그인 운영 전환
1. 카카오 콘솔 Redirect URI, 구글 '승인된 리디렉션 URI' 에 `https://<주소>/auth/kakao/callback`, `/auth/google/callback` 추가.
2. 구글 OAuth 동의 화면 **앱 게시**(테스트 → 프로덕션). 개인정보처리방침 URL 필요.
3. **웹 탈퇴 경로**(Google Play 정책): 탈퇴 방법 안내 웹페이지(앱 → 계정 → 회원 탈퇴, 또는 문의 이메일) URL 을 Play Console 에 등록.

## 5. 앱(EAS) 연결
1. `mobile/eas.json` 의 `EXPO_PUBLIC_API_URL`(`https://CHANGE-ME.example.com`) → 2-5 에서 받은 주소로 수정·커밋.
2. Expo 계정(무료) 로그인 → `npx eas build -p android --profile preview` → 내부 테스트용 APK 설치.
3. 실기기 확인: 추천·상세·리뷰·**지도 버튼(네이버지도/카카오맵 앱으로 열리는지)**·문장 조건 입력.
4. Google Play 개발자 계정($25, 1회) → `production` 빌드 → 내부 테스트 트랙 → 심사.

## 6. 운영
- **백업**: 볼륨의 DB 를 주기적으로 받아 둔다(방법은 배포 시 Railway 기능 확인 — 볼륨 백업/스냅샷 기능 또는 셸에서 `sqlite3 .backup` 후 다운로드).
- **비용 확인**: Railway 사용량 화면을 월 1회 확인, 사용 한도 유지.
- **배포 갱신**: `master` 에 머지하면 Railway 가 자동 재배포(설정에서 자동 배포 확인). 볼륨의 DB 는 유지됨.

## 남은 결정 (배포 직전에)
| ID | 안건 | 선택지 |
|---|---|---|
| D-1 | 공공데이터 갱신(인허가·지정목록·업무추진비·세부 분류)을 어디서 돌릴지 (P-3) | ① 서버 셸에서 적재 명령 실행(원본 파일을 서버에 올려야 함) ② PC 에서 적재한 **공공데이터 테이블만** 서버 DB 에 반영하는 동기화 명령 작성(사용자 데이터는 건드리지 않음) ③ DB 를 공공데이터 DB / 사용자 DB 로 분리 |
| D-2 | 주간 보강 실행 위치 | Railway Cron(볼륨 공유 가능 시) vs 백엔드 서비스 내부 주 1회 |
