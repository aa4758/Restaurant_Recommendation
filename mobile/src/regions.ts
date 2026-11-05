/** 리뷰 지도(I-3) 경계 자산 + 지도 단위 계산 — docs/01 '리뷰 지도'.
 *  자산은 backend/app/ingest/build_regions.py 가 만든 assets/regions.json (SGIS 경계, 북한 윤곽 Natural Earth). */
import raw from '../assets/regions.json';
import type { MyReview } from './api/client';

export interface RegionUnit {
  sido: string;
  name: string;
  d: string; // SVG 경로
  bbox: [number, number, number, number]; // x, y, w, h
}

export interface RegionData {
  scale_m: number;
  viewBox: [number, number, number, number];
  north: string;
  sido: { name: string; bbox: [number, number, number, number] }[];
  units: RegionUnit[];
}

export const REGIONS = raw as unknown as RegionData;

/** 일반구는 시로 합침(백엔드 unit_name 과 같은 규칙): '천안시 동남구' → '천안시' */
export function unitName(sigungu: string): string {
  const m = sigungu.trim().match(/^(\S+?시)\s?\S+구$/);
  return m ? m[1] : sigungu.trim();
}

export const unitKey = (sido: string, sigungu: string) => `${sido}|${unitName(sigungu)}`;

/** 지도 단위 키 → 그 단위에서 내가 리뷰한 가게들 */
export function visitedUnits(reviews: MyReview[]): Map<string, MyReview[]> {
  const out = new Map<string, MyReview[]>();
  for (const r of reviews) {
    if (!r.sido) continue;
    const k = unitKey(r.sido, r.sigungu ?? r.sido); // 세종(시군구 없음) = 시도 자체
    out.set(k, [...(out.get(k) ?? []), r]);
  }
  return out;
}

/** 시도 표시 순서 = 주민등록 인구 많은 순(대략값, 전남광주는 전남+광주 합산). 목록에 없는 이름은 맨 뒤 */
const SIDO_ORDER = [
  '경기도', '서울특별시', '부산광역시', '경상남도', '전남광주통합특별시', '인천광역시', '경상북도', '대구광역시',
  '충청남도', '전북특별자치도', '충청북도', '강원특별자치도', '대전광역시', '울산광역시', '제주특별자치도', '세종특별자치시',
];
const rank = (name: string) => (SIDO_ORDER.indexOf(name) + 1 || SIDO_ORDER.length + 1);

/** 시도별 (다녀온 단위 수, 전체 단위 수), 인구 많은 순 */
export function sidoProgress(visited: Map<string, MyReview[]>) {
  return [...REGIONS.sido].sort((a, b) => rank(a.name) - rank(b.name)).map((s) => {
    const units = REGIONS.units.filter((u) => u.sido === s.name);
    return { name: s.name, done: units.filter((u) => visited.has(`${u.sido}|${u.name}`)).length, total: units.length };
  });
}
