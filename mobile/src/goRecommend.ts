/** 조건 → 추천 결과 화면 이동(검색 탭·필터 탭 공통). */
import type { useRouter } from 'expo-router';
import type { AlcoholFilter, Place, RecommendRequest } from './api/client';
import type { LocationState } from './state/useLocation';

export interface Conditions {
  price?: string[];
  genre?: string[];
  subtype?: string[];
  mood?: string[];
  alcohol?: AlcoholFilter;
  radius_m?: number | null;
  place?: Place | null;
}

const some = (v?: string[]) => (v && v.length ? v : undefined);

export function goRecommend(router: ReturnType<typeof useRouter>, loc: LocationState, c: Conditions) {
  const p = c.place; // 지명 검색이면 내 위치 대신 그 지역 중심
  const fallback = !p && loc.isFallback;
  const req: RecommendRequest = {
    lat: p ? p.lat : loc.lat,
    lng: p ? p.lng : loc.lng,
    // 위치 없음 → 거리 조건 없이 (스키마 최대 반경)
    radius_m: fallback ? 20000 : c.radius_m ?? 1000,
    price: some(c.price),
    genre: some(c.genre),
    subtype: some(c.subtype),
    mood: some(c.mood),
    alcohol: c.alcohol ?? 'any',
  };
  router.push({ pathname: '/recommendations', params: { q: JSON.stringify(req), fallback: fallback ? '1' : '', place: p ? (p.kind === 'landmark' ? p.name : p.label) : '' } });
}
