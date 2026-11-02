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

/** 시도별 (다녀온 단위 수, 전체 단위 수) */
export function sidoProgress(visited: Map<string, MyReview[]>) {
  return REGIONS.sido.map((s) => {
    const units = REGIONS.units.filter((u) => u.sido === s.name);
    return { name: s.name, done: units.filter((u) => visited.has(`${u.sido}|${u.name}`)).length, total: units.length };
  });
}
