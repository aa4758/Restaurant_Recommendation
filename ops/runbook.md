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
   ```
   결과: 모범 3,941(서울 2,860 + 경기 1,081) / 원산지 193 / 백년 489 / 착한가격 6,939 (+메뉴 13,878) / 경기 으뜸맛집 78. 재적재는 멱등(UNIQUE + INSERT OR IGNORE).
5. 미매칭 가게는 `data\out\unmatched_<출처>.csv` (PII 없음) — 분기마다 수기 검토.
6. 목록 갱신 주기: 모범음식점·착한가격 반기, 백년가게는 새 목록 공개 시 교체.

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
