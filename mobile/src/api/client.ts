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
  /** 장르 → 세부 분류 (2026-10-29) */
  subtype: Record<string, string[]>;
  mood: string[];
  alcohol: AlcoholFilter[];
}

/** POST /filters/parse — 자연어 조건 → 필터(규칙 기반) */
export interface Place {
  name: string;
  kind: 'dong' | 'sigungu' | 'landmark';
  /** 고를 때 보여줄 이름 — "서울특별시 중구 신당동" / "강남역 2호선 (서울 강남구)" */
  label: string;
  lat: number;
  lng: number;
}

export interface ParseResponse {
  filters: {
    price?: string[];
    genre?: string[];
    subtype?: string[];
    mood?: string[];
    alcohol: AlcoholFilter;
    radius_m?: number | null;
    /** 문장 속 지명 — 있으면 내 위치 대신 이 좌표로 추천(2026-11-12) */
    place?: Place | null;
  };
  /** 못 알아들은 낱말(적용 안 됨) */
  unknown: string[];
  /** 같은 이름 지역이 여럿 → 먼저 고르게(이때 filters.place 없음) */
  place_options?: Place[];
}

export interface RecommendRequest {
  lat: number;
  lng: number;
  radius_m?: number;
  price?: string[];
  genre?: string[];
  subtype?: string[];
  mood?: string[];
  alcohol?: AlcoholFilter;
  limit?: number;
  /** 이어 받기 시작 위치(표시 별점 내림차순 목록 기준) */
  offset?: number;
  /** 싫어요로 숨긴 가게 id (최대 200) */
  exclude_ids?: string[];
}

/** GET /restaurants/{id}/peers — 같은 시군구·같은 음식, 별점 내림차순 */
export interface PeerItem {
  id: string;
  name: string;
  genre: string;
  subtype?: string | null;
  address?: string | null;
  star: number;
  percentile: number;
}
export interface PeerPage {
  food: string;
  region?: string | null;
  total: number;
  items: PeerItem[];
}

export interface RestaurantItem {
  id: string;
  name: string;
  genre: string;
  /** 세부 분류, 미분류 null */
  subtype?: string | null;
  price_band: string;
  moods: string[];
  /** null = 미확인 */
  alcohol: boolean | null;
  lat: number;
  lng: number;
  distance_m: number | null;
  star: number;
  percentile: number;
  /** 같은 지역 비교 기준 음식(세부 분류, 없으면 장르) */
  food?: string | null;
  /** 이 지역 {food} 중 상위 N% */
  food_percentile?: number | null;
  review_count: number;
  gov_visits: number;
  gov_source?: string | null;
  reasons: string[];
  updated_at: string;
  /** 목록 응답에 없을 수 있음 → review_count 로 대체 표시 */
  evidence?: Evidence | null;
  /** 서버가 내려주면 공유 문구에 사용 */
  address?: string | null;
  /** 항목별 미충족(완화된) 조건. 서버 미구현 시 undefined */
  relaxed?: string[];
}

export interface RecommendResponse {
  items: RestaurantItem[];
  relaxed: string[];
  /** 조건(완화 후)에 맞는 전체 수 — offset + items 수 < total 이면 더 있음 */
  total: number;
}

/** 점수 모델 v2.1 구성요소별 사전 점수 기여분 (감점 항목 sanction·ad 는 음수) */
export interface ScoreComponents {
  tenure: number;
  gov: number;
  hygiene: number;
  designation: number;
  /** 외부 평판 = max(가이드 선정 점수, 제휴 평점), 둘 다 없으면 중립 */
  reputation: number;
  sanction: number;
  ad: number;
}

export type Evidence = 'low' | 'mid' | 'high';

export interface ScoreBreakdown {
  prior_star: number;
  user_mean: number | null;
  n: number;
  k: number;
  gov_bonus: number;
  ad_penalty: number;
  /** v2 추가 — 구버전 서버 호환을 위해 optional */
  components?: ScoreComponents | null; // null = 재계산 전 → 기존 표시 fallback
  evidence?: Evidence | null;
}

export interface RestaurantDetail extends RestaurantItem {
  score_breakdown: ScoreBreakdown;
  designations?: string[]; // 지정목록 표시명(2026-11-05), 구버전 서버는 없음
}

export type PriceBand = '~1만' | '1~2만' | '2~4만' | '4만+';

export interface MenuEntry {
  name: string; // 30자 이하
  price?: number | null; // 원, 1,000~300,000
}

/** 현장 작성 판정용 위치(서버 저장 안 함) — docs/01 R-2 */
export interface ReviewPosition {
  lat: number;
  lng: number;
  accuracy?: number | null;
}

export interface CreateReviewRequest {
  stars: number; // 0.5 ~ 5, 0.5 단위
  text: string;
  tags: string[];
  /** 무시됨(하위 호환). 작성자는 로그인 계정 — Authorization 헤더 */
  device_id?: string;
  spend?: PriceBand | null; // 1인 지출(R-5)
  moods?: string[]; // 분위기(R-6)
  menus?: MenuEntry[]; // 최대 3개(R-4)
  positions?: ReviewPosition[]; // 최대 2개: 화면 열 때·등록할 때
}

export interface MyReview {
  restaurant_id: string;
  name: string;
  sido: string | null; // 리뷰 지도(I-3)
  sigungu: string | null;
  stars: number;
  text: string;
  tags: string[];
  spend: PriceBand | null;
  moods: string[];
  menus: MenuEntry[];
  onsite: boolean;
  created_at: string;
  updated_at: string | null;
}

export type AuthProvider = 'kakao' | 'google';

export interface TokenResponse {
  token: string;
  expires_at: string;
  provider: AuthProvider;
}

export interface MeResponse {
  provider: AuthProvider;
  created_at: string;
}

export interface CreateReviewResponse {
  id: number;
  final_star: number;
  updated: boolean; // 기존 리뷰를 덮어씀
  onsite: boolean;
}

export interface ReviewListItem {
  id: number;
  stars: number;
  text: string;
  tags: string[];
  created_at: string;
  ad_disclosed: boolean;
  onsite: boolean; // 현장 작성
  edited: boolean; // 수정됨
}

export interface ReviewListResponse {
  items: ReviewListItem[];
  next_cursor?: string | null;
}

export type ReactionValue = 'like' | 'dislike' | 'none';
export type DislikeReason = 'far' | 'price' | 'not_into' | 'visited';

export interface ReactionRequest {
  device_id: string; // 8~64자 [A-Za-z0-9-_]
  restaurant_id: string;
  value: ReactionValue;
  reason?: DislikeReason;
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

const bearer = (token: string) => ({ Authorization: `Bearer ${token}` });

export const api = {
  health: () => request<HealthResponse>('/health'),

  getFilters: () => request<FiltersResponse>('/meta/filters'),

  parseFilters: (text: string) =>
    request<ParseResponse>('/filters/parse', { method: 'POST', body: JSON.stringify({ text }) }),

  recommend: (body: RecommendRequest) =>
    request<RecommendResponse>('/recommend', {
      method: 'POST',
      body: JSON.stringify({ radius_m: 1000, limit: 3, alcohol: 'any', ...body }),
    }),

  getRestaurant: (id: string) =>
    request<RestaurantDetail>(`/restaurants/${encodeURIComponent(id)}`),

  /** 로그인 필수(docs/01 L-5). 토큰 없음·만료 → ApiError status 401 */
  createReview: (id: string, body: CreateReviewRequest, token: string) =>
    request<CreateReviewResponse>(`/restaurants/${encodeURIComponent(id)}/reviews`, {
      method: 'POST',
      body: JSON.stringify(body),
      headers: bearer(token),
    }),

  deleteMyReview: (id: string, token: string) =>
    request<void>(`/restaurants/${encodeURIComponent(id)}/reviews/me`, { method: 'DELETE', headers: bearer(token) }),

  /** 리뷰 메뉴 자동완성(R-4) */
  getPeers: (id: string, offset = 0, limit = 20) =>
    request<PeerPage>(`/restaurants/${encodeURIComponent(id)}/peers?limit=${limit}&offset=${offset}`),
  getMenus: (id: string) => request<{ items: MenuEntry[] }>(`/restaurants/${encodeURIComponent(id)}/menus`),

  /** 내가 다녀온 가게 = 내 리뷰 목록(R-7) */
  myReviews: (token: string) => request<{ items: MyReview[] }>('/me/reviews', { headers: bearer(token) }),

  /** 로그인 시작 주소(브라우저로 엶). 서버가 공급자 로그인 후 redirect?code= 로 돌려보냄 */
  authStartUrl: (provider: AuthProvider, redirect: string, challenge: string) =>
    `${API_BASE_URL}/auth/${provider}/start?redirect=${encodeURIComponent(redirect)}&challenge=${challenge}`,

  exchangeToken: (code: string, verifier: string) =>
    request<TokenResponse>('/auth/token', { method: 'POST', body: JSON.stringify({ code, verifier }) }),

  me: (token: string) => request<MeResponse>('/auth/me', { headers: bearer(token) }),

  logout: (token: string) => request<void>('/auth/logout', { method: 'POST', headers: bearer(token) }),

  /** 회원 탈퇴: 계정과 그 계정의 리뷰 삭제 */
  deleteAccount: (token: string) => request<void>('/auth/me', { method: 'DELETE', headers: bearer(token) }),

  listReviews: (id: string, cursor?: string | null, limit = 20) =>
    request<ReviewListResponse>(
      `/restaurants/${encodeURIComponent(id)}/reviews?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
    ),

  react: (body: ReactionRequest) =>
    request<void>('/reactions', { method: 'POST', body: JSON.stringify(body) }),

  reportIssue: (id: string, body: ReportRequest) =>
    request<void>(`/restaurants/${encodeURIComponent(id)}/report`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
