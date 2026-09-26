/**
 * 백엔드 API 계약 타입 + fetch 래퍼.
 * 계약 출처: docs/01_planning_decision.md > "API 계약" (변경 시 그 문서를 먼저 수정할 것)
 *
 * 베이스 URL: EXPO_PUBLIC_API_URL 환경변수.
 * 기본값은 안드로이드 에뮬레이터에서 호스트 PC를 가리키는 10.0.2.2.
 * 실기기(Expo Go)로 테스트할 때는 PC의 LAN IP로 .env 에서 덮어써야 한다. (mobile/README.md 참고)
 */

const DEFAULT_BASE_URL = 'http://10.0.2.2:8000';

export const API_BASE_URL: string =
  process.env.EXPO_PUBLIC_API_URL?.trim() || DEFAULT_BASE_URL;

/** 위치 권한이 거부됐을 때 쓰는 폴백 좌표 (서울시청). */
export const FALLBACK_LOCATION = {
  lat: 37.5663,
  lng: 126.9779,
} as const;

// ---------------------------------------------------------------------------
// 공통 타입
// ---------------------------------------------------------------------------

export type AlcoholFilter = 'any' | 'yes' | 'no';

export interface HealthResponse {
  status: 'ok';
}

export interface FiltersResponse {
  price: string[];
  genre: string[];
  mood: string[];
  alcohol: AlcoholFilter[];
}

export interface RecommendRequest {
  lat: number;
  lng: number;
  radius_m?: number;
  price?: string[];
  genre?: string[];
  mood?: string[];
  alcohol?: AlcoholFilter;
  limit?: number;
}

export interface RestaurantItem {
  id: string;
  name: string;
  genre: string;
  price_band: string;
  moods: string[];
  alcohol: boolean;
  lat: number;
  lng: number;
  distance_m: number | null;
  star: number;
  percentile: number;
  review_count: number;
  gov_visits: number;
  gov_source?: string | null;
  reasons: string[];
  updated_at: string;
}

export interface RecommendResponse {
  items: RestaurantItem[];
  relaxed: string[];
}

export interface ScoreBreakdown {
  prior_star: number;
  user_mean: number | null;
  n: number;
  k: number;
  gov_bonus: number;
  ad_penalty: number;
}

export interface RestaurantDetail extends RestaurantItem {
  score_breakdown: ScoreBreakdown;
}

export interface CreateReviewRequest {
  stars: number; // 0.5 ~ 5, 0.5 단위
  text: string;
  tags: string[];
}

export interface CreateReviewResponse {
  id: number;
  final_star: number;
}

export interface ReportRequest {
  field: string;
  message: string;
}

// ---------------------------------------------------------------------------
// fetch 래퍼
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiError(
      '서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요.',
      0,
    );
  }

  if (!response.ok) {
    let message = `요청이 실패했어요. (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') message = body.detail; // FastAPI 에러 형식
    } catch {
      // 응답 바디가 JSON이 아닐 수 있음 — 기본 메시지 사용
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 202 || response.status === 204) {
    return undefined as unknown as T;
  }

  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  getFilters: () => request<FiltersResponse>('/meta/filters'),

  recommend: (body: RecommendRequest) =>
    request<RecommendResponse>('/recommend', {
      method: 'POST',
      body: JSON.stringify({ radius_m: 1000, limit: 3, alcohol: 'any', ...body }),
    }),

  getRestaurant: (id: string) =>
    request<RestaurantDetail>(`/restaurants/${encodeURIComponent(id)}`),

  createReview: (id: string, body: CreateReviewRequest) =>
    request<CreateReviewResponse>(`/restaurants/${encodeURIComponent(id)}/reviews`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  reportIssue: (id: string, body: ReportRequest) =>
    request<void>(`/restaurants/${encodeURIComponent(id)}/report`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
