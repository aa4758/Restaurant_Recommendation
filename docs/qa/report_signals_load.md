# QA: 공공 신호 실적재 검수 (restaurant_signals)

검수일 2026-10-26 · DB `data/jjinmat.db`(읽기 전용) vs 백업 `data/jjinmat_before_signals.db` · 테스트 `tests/test_ingest_signals_qa.py`

## 적재 현황 (DB 실측)
| kind | 신호 행 | 가게 수 | 인허가번호 일치 | 상호+주소 일치 |
|---|---|---|---|---|
| model_restaurant | 2,860 | 2,767 | 2,823 | 37 |
| century_store | 489 | 489 | - | 489 |
| good_price | 6,939 | 6,939 | - | 6,939 |
| origin_label_excellent | 193 | 193 | - | 193 |

- model_restaurant 는 신호 행이 가게 수보다 많다. 지정일자가 여러 번인 가게가 있어서이며, UNIQUE 키에 base_date 가 들어가므로 설계대로다.
- 적재 출력의 매칭 수(인허가 2,841 / 주소 40)와 DB 실측(2,823 / 37)이 다르다. 출력은 INSERT OR IGNORE 로 중복을 걸러내기 전에 센 값이다.

## 1) 오매칭 표본 (상호+주소 매칭, kind 별 무작위 20건)
| kind | 표본 | 오매칭 | 비고 |
|---|---|---|---|
| model_restaurant | 20 (모집단 37) | 0 | 경계 1건: '임고집(2호점)' 2층 → 본점. 본점은 이미 인허가번호로 지정돼 있어 점수 영향 없음 |
| century_store | 20 | 0 | |
| good_price | 20 | 0 | |
| origin_label_excellent | 20 | 0 | |

## 2) 점수 규칙
| 규칙 | 결과 | 근거 |
|---|---|---|
| (a) good_price 는 prior 무변화 | 통과 | good_price 만 있는 가게 6,860곳의 components 가 백업과 같다. prior_star 가 바뀐 1,169곳은 시군구 분위수 이동 때문이다(신호 없는 대조군도 637k 중 80k 변동, 최대폭 0.16 으로 같음) |
| (b) century_store 는 업력 보정만 | 통과 | 437곳 designation 0, 업력 상승 50·동일 387·하락 0, 다른 구성요소 변화 0 |
| (c) model_restaurant → designation=1 | 통과 | 2,767곳 모두 0.10. 지정 신호 없는 가게 중 designation>0 은 0곳 |
| (c) 시군구 평균 ≈2.5 | 통과 | 서울 25개 구 2.466~2.495 (적재 전 2.457~2.489), 전국 256개 시군구 2.438~2.500 |

## 3) `_ROAD_TOK` 변경 회귀 (address 647,634건)
| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| 도로명 키 생성 | 564,602 (87.2%) | 642,818 (99.3%) |
| 새로 생긴 / 사라진 / 바뀐 키 | | +78,216 / 0 / 0 |
| 'X로N가 숫자' 50건 중 키 생성 | 2 | 2 (둘 다 앞에 진짜 도로명 있음) |
| address==jibun 인데 키 생성 | | 0 |

새로 생긴 키 표본 20개는 모두 진짜 도로명이다. 을지로1가 같은 지번은 여전히 None 이다. 회귀 테스트 `test_road_tok_change_no_jibun_regression` 으로 고정했다.

## 결함
| # | 내용 | 영향 | 상태 |
|---|---|---|---|
| 1 | `matcher._strip` 이 괄호 안 지점명을 지워서 '(강남점)' 과 '(역삼점)' 을 같은 가게로 판정 | 낮음. 이번 적재에서 점수 영향 0, 상호만으로 매칭하는 경로에서 위험 | **수정됨**: `_PAREN_BRANCH_RE` 로 괄호 안 '…점'을 지점 토큰으로 살린다. `test_paren_branch_not_dropped` 통과 |

## 추가: 경기 목록 (사용자 승인 후 적재)
| kind | 원본 행 | 신호 행 | 매칭 경로 | 비고 |
|---|---|---|---|---|
| model_restaurant (경기) | | 1,081 | 상호+시군 유일 | 미매칭 514, 그중 345 는 전국 동명 8곳 이상(프랜차이즈)이라 일부러 건너뜀 |
| gyeonggi_best | 125 | 78 | 상호+주소 / 50m | 원본에 도로명주소·WGS84 좌표 있음. guide 0.7 |

- 상호+시군 매칭 표본 검수 결과 오매칭 없음. 매칭 조건은 같은 시군에 영업 중 후보가 정확히 1곳이고 전국 후보가 8곳 미만일 때뿐이다.
- 회귀 테스트: `test_city_match_for_list_without_address`, `test_city_match_skips_franchise_names`, `test_gyeonggi_best_is_guide_kind`, `test_wgs84_coordinate_headers`.

## 테스트
`python -m pytest -q` → 312 passed
