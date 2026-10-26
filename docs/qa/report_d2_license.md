# QA 리포트 — D2 인허가 적재

범위: `backend/app/ingest/{license,load_license,matcher}.py` ↔ `docs/04_data_plan.md` D2·2-3.
결과: **high 0건.** 발견 11건(medium 4 / low 7) 전부 수정, 회귀 테스트 포함(`tests/test_ingest_license*.py`).

## 이상 없음
영업상태 매핑(폐업·직권폐업·취소/말소→closed, 휴업→open), 단일 실행 재개업 우선순위(행 순서 무관), EPSG:5174 변환(서울·부산·제주 왕복 <1m), calibrate 선택, 좌표 0/결측/한국 범위 밖 → 미매칭, 멱등 재적재, 미매칭 파일 PII·전화 없음, dry-run DB 불변, 폐업 가게 점수 제거, 적재 선형 시간(2만 행 0.86초).

## 이슈
| # | 심각도 | 내용 | 조치 |
|---|---|---|---|
| M1 | medium | 다른 실행에서 들어온 오래된 폐업 인허가가 영업 중 가게를 폐업 처리 | ✅ 폐업 행의 인허가일이 현재 것 이상일 때만 반영, 아니면 `stale_ignored` |
| M2 | medium | 일반·휴게 동시 영업 시 휴게가 이겨 술 파는 가게가 음주 불가 | ✅ 일반 우선, `alcohol_src='license'`로 출처 기록·복원 |
| M3 | medium | 프랜차이즈 매칭 O(행×후보) (2000×2000 26초) | ✅ 주소 정규화 캐시 + dict 색인 (0.02초) |
| M4 | medium | 전체 메모리 적재(서울 ~0.9GB) | ✅ 스트리밍 + 그룹별 최우선 행만 유지 |
| L1 | low | 제외 업태 기존 가게의 폐업 미반영 | ✅ 제외는 신규 생성에만 |
| L2 | low | 날짜 없으면 closed_at=적재일(비멱등) | ✅ COALESCE, 없으면 NULL |
| L3 | low | opened_at·area_m2 를 NULL 로 덮어씀 | ✅ COALESCE |
| L4 | low | calibrate 표본 하한 없음·CRS별 표본 상이 | ✅ n<30 경고, 공통 쌍만 비교 |
| L5 | low | 시도 없는 '중구' 등 동명 시군구 오매핑 | ✅ 모호하면 None |
| L6 | low | 출장조리·푸드트럭 등 비고정 업태 신규 생성 | ✅ 제외 |
| L7 | low | 미매칭 0건 시 이전 파일 잔존, dry-run이 호출자 트랜잭션까지 롤백 | ✅ 파일 삭제, SAVEPOINT |
