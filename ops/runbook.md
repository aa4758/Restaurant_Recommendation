# 운영 런북

## 서버 실행 (Docker)
```sh
cd backend
docker build -t jjinmat-api .
docker run -d -p 8000:8000 -v jjinmat-data:/data --env-file ../.env jjinmat-api
curl http://localhost:8000/health   # {"status":"ok"}
```
- 첫 기동 시 `/data/jjinmat.db` 가 없으면 가상 시드를 자동 적재. 이후 재시작은 기존 DB 유지.
- 호스팅(Fly.io/Render 등)은 **영구 볼륨을 `/data` 에 마운트** 해야 리뷰가 보존됨. `PORT` 환경변수 자동 반영.
- LB/리버스 프록시 뒤라면 `-e FORWARDED_ALLOW_IPS=<LB 대역, 예: 10.0.0.0/8>` 설정(미설정 시 127.0.0.1 만 신뢰 → 모든 요청이 LB IP 하나로 묶여 레이트리밋 오차단).

## 소셜 로그인 (app/auth.py, docs/01 L-1~L-8)
환경변수(사용자 환경변수는 `setx`, 배포 시 Railway 변수):
| 이름 | 값 |
|---|---|
| `AUTH_SECRET` | **필수.** 고유번호 HMAC 키(16자 이상). 생성: `setx AUTH_SECRET (python -c "import secrets; print(secrets.token_urlsafe(32))")`. **바꾸면 기존 계정과 연결이 끊김**(같은 사람이 새 계정이 됨) → 한 번 정하면 유지, 백업 |
| `KAKAO_REST_KEY` / `KAKAO_CLIENT_SECRET` | 카카오 REST 키 / Client Secret(콘솔에서 켰을 때만) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 구글 OAuth 웹 클라이언트 |
| `PUBLIC_BASE_URL` | 서버 외부 주소(기본 `http://localhost:8000`). 공급자 콘솔 Redirect URI = `<PUBLIC_BASE_URL>/auth/kakao/callback`, `/auth/google/callback` |
| `AUTH_REDIRECTS` | 로그인 후 돌아갈 앱 주소 접두어(기본 `jjinmat://,exp://,http://localhost:8081/` — 개발용). 배포 시 `jjinmat://` 만 |
- 미설정이면 `/auth/*` 는 503, 리뷰 작성 불가(읽기·추천은 정상).
- 로컬 확인: 백엔드 `uvicorn app.main:app --port 8000` + 앱 `npx expo start --web`(`EXPO_PUBLIC_API_URL=http://localhost:8000`) → 계정 화면에서 로그인.
- 구글은 OAuth 동의 화면이 '테스트' 상태인 동안 등록한 테스트 사용자만 로그인 가능 → 배포 단계에서 앱 게시.

## 리뷰 지도 경계 (I-3, app/ingest/build_regions.py)
- 결과물 `mobile/assets/regions.json`(git 포함, 약 160KB). 행정구역이 바뀌거나(구 신설·통합) 가게 DB 를 새로 적재했을 때 다시 만듦.
- 키: SGIS 개발지원센터 인증키 → 사용자 환경변수 `SGIS_CONSUMER_KEY`, `SGIS_CONSUMER_SECRET`.
```powershell
cd backend
python -m app.ingest.build_regions            # 최신 연도 자동(2026-11 기준 2025년)
```
- 경계 연도와 가게 행정구역이 달라도 **가게 좌표로 연결**. 출력의 '분할 배정'(예: 인천 중구 → 영종구·제물포구)·'이름 불일치' 줄을 확인하고, 단위 수가 가게 DB 지도 단위 수와 같은지 본다(2026-11: 230).

## 데이터 갱신 (업무추진비·리뷰 통계·카카오)
> ⚠️ `python -m app.ingest.load_seed` 는 **DB 파일을 삭제 후 재생성** 한다 → `user_reviews`, `reports` 소실.
1. 백업: `docker cp <컨테이너>:/data/jjinmat.db ./backup-$(date +%F).db`
2. 새 CSV를 `backend/data/seed/` 형식에 맞춰 교체 (업무추진비 CSV는 **개인정보 컬럼 제거 후**).
3. 새 DB를 별도 경로에 적재: `python -m app.ingest.load_seed --db new.db`
4. 백업 DB의 사용자 데이터 이관:
   ```sh
   sqlite3 new.db "ATTACH 'backup.db' AS old;
     INSERT INTO user_reviews(id,restaurant_id,stars,text,tags,user_id,verified,created_at)
       SELECT id,restaurant_id,stars,text,tags,user_id,verified,created_at FROM old.user_reviews
       WHERE restaurant_id IN (SELECT id FROM restaurants);
     INSERT INTO reports SELECT * FROM old.reports WHERE restaurant_id IN (SELECT id FROM restaurants);"
   ```
   이관 후 점수 재계산: `JJINMAT_DB=new.db python -m app.service` (`ad_disclosed` 는 비워 두면 기동 시 자동 백필)
5. 서버 중지 → `new.db` 를 `/data/jjinmat.db` 로 교체 → 재기동 → `/health`, `/recommend` 확인.

## 별점 근거 지정목록 적재 (모범음식점·원산지·백년가게·착한가격)
1. 백업: `Copy-Item data\jjinmat.db data\jjinmat_before_signals.db` (실패 시 이 파일로 되돌림).
2. xls 원본은 CSV 로 변환 후 사용:
   ```powershell
   @'
   import pandas as p; p.read_excel(r"<xls>").to_csv(r"<csv>", index=False, encoding="utf-8-sig")
   '@ | python -
   ```
3. 파일마다 `--check` → `--dry-run` → 적재 순. 경로에 공백이 있으므로 반드시 따옴표.
4. 2026-10-26 적재 명령(backend 에서, PowerShell):
   ```powershell
   python -m app.ingest.load_designations (Get-ChildItem "data\raw\designations\서울시*.csv").FullName --kind model_restaurant --source "서울시 자치구 모범음식점"
   python -m app.ingest.load_designations "data\raw\designations\원산지표시 우수 음식점_20261026.csv" --kind origin_label_excellent --source "국립수산물품질관리원 원산지표시 우수" --base-date 2026-10-26
   python -m app.ingest.load_designations "data\raw\designations\소상공인시장진흥공단_전국 백년가게 현황_20220713.csv" --kind century_store --source "중소벤처기업부 백년가게" --base-date 2022-07-13
   python -m app.ingest.load_designations "data\raw\designations\행정안전부_착한가격업소 현황_20260930.csv" --kind good_price --source "행정안전부 착한가격업소" --base-date 2026-09-30
   # 경기: 주소 없음 → 상호+시군 유일 매칭(프랜차이즈·동명 복수는 미매칭)
   python -m app.ingest.load_designations data\raw\designations\경기_모범음식점현황.csv --kind model_restaurant --source "경기도 모범음식점" --sido 경기 --base-date 2026-06-30
   python -m app.ingest.load_designations data\raw\designations\경기도으뜸맛집현황.csv --kind gyeonggi_best --source "경기도 으뜸맛집"
   python -m app.ingest.link_sbiz   # 상가정보(data\raw\sbiz\*.csv, 분기 갱신) → 기존 가게에 sbiz_id·업종 소분류 연결
   # 세부 분류(docs/01 '세부 분류 필터'): 위 적재·인허가 재적재 뒤에 항상 다시 실행(genre 보정 포함, 점수 무관)
   python -m app.subtype assign
   ```
   세부 분류 모델(최초 1회·AI-Hub 데이터 갱신 시, 학습용으로만 — 원본·모델은 git 제외):
   ```powershell
   python -m app.subtype train "$env:USERPROFILE\Downloads\222.관광 음식메뉴판 데이터\01-1.정식개방데이터"   # → data\models\menu_subtype.json
   ```
   결과: 모범 3,941(서울 2,860 + 경기 1,081) / 원산지 193 / 백년 489 / 착한가격 6,939 (+메뉴 13,878) / 경기 으뜸맛집 78. 재적재는 멱등(UNIQUE + INSERT OR IGNORE).
5. 미매칭 가게는 `data\out\unmatched_<출처>.csv` (PII 없음) — 분기마다 수기 검토.
6. 목록 갱신 주기: 모범음식점·착한가격 반기, 백년가게는 새 목록 공개 시 교체.

## 업무추진비 적재 (서울시 본청 Open API)
1. 인증키: 열린데이터광장(data.seoul.go.kr) 로그인 → 인증키 신청 → `$env:SEOUL_API_KEY = "<키>"`.
2. backend 에서:
   ```powershell
   python -m app.ingest.load_gov_expense --fetch-seoul                       # → data\raw\gov_expense\seoul_odExpense_<날짜>.csv (PII 없음)
   python -m app.ingest.load_gov_expense data\raw\gov_expense\seoul_odExpense_<날짜>.csv --check
   python -m app.ingest.load_gov_expense data\raw\gov_expense\seoul_odExpense_<날짜>.csv --dry-run
   python -m app.ingest.load_gov_expense data\raw\gov_expense\seoul_odExpense_<날짜>.csv
   ```
3. 재적재는 같은 source 전체 교체(멱등). 매달 다음 달 중순 공개분 반영.
4. 자치구 파일은 같은 열(exec_dt,agency,dept,place,amount,category,source)로 정규화한 CSV 를 같은 명령으로 적재.
5. 구청 게시판(관악·구로, 01 크롤링 예외 조건): 사이트당 3초 간격이라 관악 약 30분, 구로 1시간 이상 걸림. 첨부(PDF)는 `data\raw\gov_expense\cache\<구>\` 에 캐시돼 재실행 때 새 글 첨부만 받음(목록은 매번 새로 받음).
   ```powershell
   pip install pdfplumber   # 구로 PDF 파싱(수집 전용)
   python -m app.ingest.collect_gov_boards gwanak   # → data\raw\gov_expense\gwanak_<날짜>.csv
   python -m app.ingest.collect_gov_boards guro
   python -m app.ingest.load_gov_expense data\raw\gov_expense\gwanak_<날짜>.csv data\raw\gov_expense\guro_<날짜>.csv --dry-run
   ```
   `robots.txt 금지` 오류가 나면 사이트 정책이 바뀐 것 → 수집 중단하고 01 문서 시범 조사 행을 고칠 것(우회 금지).

## 이의제기·정보 오류 신고
- 사용자 신고는 `reports` 테이블에 쌓임: `sqlite3 /data/jjinmat.db "SELECT * FROM reports ORDER BY created_at DESC LIMIT 50"`
- 업주 이의제기는 이메일로 접수(MVP). 처리: 사실 확인 → CSV 수정 → 위 "데이터 갱신" 절차.
- 영업정보 수정 시 해당 행 `updated_at` 갱신 (앱에 표시됨).

## 광고 리뷰 오탐 분기 검수
1. `review_stats` 에서 `ad_ratio >= 0.15` 인 가게 표본 추출.
2. 표본별 판별 근거(협찬/체험단/제공받아 키워드, 작성 시기 집중도) 수기 확인.
3. 오탐이면 `ad_conf` 를 낮춰 CSV 수정 → 데이터 갱신. 결과를 분기 기록으로 남김.

## 모바일 빌드 (EAS)
```sh
cd mobile
npx eas-cli login
# eas.json 의 EXPO_PUBLIC_API_URL 을 실제 서버 URL(https)로 교체
npx eas-cli build -p android --profile preview      # 내부 테스트 APK
npx eas-cli build -p android --profile production   # 스토어용 AAB
npx eas-cli submit -p android
```

## 공개 전 체크리스트
- [x] 리뷰 레이트리밋(기기 분당 30 + IP 분당 300) — `docs/qa/report.md` 이슈 #2. 프록시 뒤면 `FORWARDED_ALLOW_IPS` 확인
- [ ] CORS `allow_origins=["*"]` 제한 (웹 클라이언트 없으면 무관)
- [ ] 법무 검토: 업무추진비 배지 문구, 광고 감점

## 자연어 조건 사전 보강 (매주, docs/01 '자연어 조건 입력')
- 매주 월요일 04:00 작업 스케줄러가 `python -m app.nlp_enrich run` 실행: 지난주 배치 결과 수거 → 90일 지난 미인식 낱말 삭제 → 새 Batch 제출(Claude Haiku 5.5).
  키는 사용자 환경변수 `ANTHROPIC_API_KEY`(없으면 보강만 건너뜀). 로그 `backend\data\out\nlp_enrich.log`.
- 등록(최초 1회, PowerShell. 2026-10-29 이 PC 에 등록됨):
  ```powershell
  schtasks /Create /TN "JJINMAT nlp_enrich" /SC WEEKLY /D MON /ST 04:00 /F /TR "cmd /c cd /d C:\Restaurant_Recommendation\backend && python -m app.nlp_enrich run >> data\out\nlp_enrich.log 2>&1"
  schtasks /Query /TN "JJINMAT nlp_enrich"     # 확인 · 삭제: schtasks /Delete /TN "JJINMAT nlp_enrich" /F
  ```
- 승인(사람): `python -m app.nlp_enrich list` → `python -m app.nlp_enrich approve 얼큰한 땡초` (또는 `--all`) / `reject <낱말>`. 승인한 것만 다음 요청부터 해석에 쓰임.
