/**
 * 디자인 토큰 (순수 TypeScript, 외부 의존성 없음)
 * 출처: docs/00_brief.md, docs/01_planning_decision.md
 * - 별점 체계는 의도적으로 엄격(디플레이션): 평균 ≈ 2.5/5
 * - 5.0 은 상위 ~0.1%, 4.5 이상은 상위 ~0.7% (v2.3, 기획 결정문 참조)
 */

export type ColorScheme = 'light' | 'dark';

export interface ColorPalette {
  background: string;
  surface: string;
  surfaceAlt: string;
  border: string;
  textPrimary: string;
  textSecondary: string;
  textDisabled: string;
  textPlaceholder: string;
  primary: string;
  primaryText: string;
  accent: string;
  success: string;
  warning: string;
  danger: string;
  govBadgeBg: string;
  govBadgeText: string;
  adPenaltyBg: string;
  adPenaltyText: string;
  chipBg: string;
  chipBgSelected: string;
  chipText: string;
  chipTextSelected: string;
  overlay: string;
  overlayText: string;
}

export const colors: Record<ColorScheme, ColorPalette> = {
  light: {
    background: '#FFFFFF',
    surface: '#F7F7F8',
    surfaceAlt: '#EFEFF2',
    border: '#E2E2E6',
    textPrimary: '#17181A',
    textSecondary: '#5B5D63',
    textDisabled: '#A0A2A8',
    textPlaceholder: '#71757D',
    primary: '#C8431C',
    primaryText: '#FFFFFF',
    accent: '#2E6FE4',
    success: '#17794C',
    warning: '#8F5A00',
    danger: '#D0392B',
    govBadgeBg: '#EEF2FF',
    govBadgeText: '#3A4CA8',
    adPenaltyBg: '#FBEAEA',
    adPenaltyText: '#A83A3A',
    chipBg: '#F0F0F2',
    chipBgSelected: '#C8431C',
    chipText: '#3A3B3E',
    chipTextSelected: '#FFFFFF',
    overlay: 'rgba(0,0,0,0.45)',
    overlayText: '#FFFFFF',
  },
  dark: {
    background: '#101113',
    surface: '#1B1C1F',
    surfaceAlt: '#232427',
    border: '#2D2E32',
    textPrimary: '#F2F2F3',
    textSecondary: '#B4B6BC',
    textDisabled: '#6B6D73',
    textPlaceholder: '#8A8D94',
    primary: '#FF7A50',
    primaryText: '#101113',
    accent: '#6C9BFF',
    success: '#4CC98A',
    warning: '#E3A83E',
    danger: '#F0685C',
    govBadgeBg: '#232A4A',
    govBadgeText: '#9BB0FF',
    adPenaltyBg: '#3A2222',
    adPenaltyText: '#F0A2A2',
    chipBg: '#232427',
    chipBgSelected: '#FF7A50',
    chipText: '#D6D7DB',
    chipTextSelected: '#101113',
    overlay: 'rgba(0,0,0,0.6)',
    overlayText: '#FFFFFF',
  },
};

/** 모션 (design_system.md 2-3). 과시용 효과 금지 — 상태 변화 설명용만 */
export const motion = {
  instant: 100,
  fast: 150,
  base: 250,
  slow: 400,
} as const;

export const spacing = {
  none: 0,
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export const radius = {
  none: 0,
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  pill: 999,
} as const;

export interface TypographyScale {
  fontSize: number;
  fontWeight: '400' | '500' | '600' | '700';
  lineHeight: number;
}

export const typography = {
  display: { fontSize: 28, fontWeight: '700', lineHeight: 36 } as TypographyScale,
  title: { fontSize: 22, fontWeight: '700', lineHeight: 30 } as TypographyScale,
  heading: { fontSize: 18, fontWeight: '600', lineHeight: 26 } as TypographyScale,
  body: { fontSize: 15, fontWeight: '400', lineHeight: 22 } as TypographyScale,
  bodyStrong: { fontSize: 15, fontWeight: '600', lineHeight: 22 } as TypographyScale,
  caption: { fontSize: 13, fontWeight: '400', lineHeight: 18 } as TypographyScale,
  captionStrong: { fontSize: 13, fontWeight: '600', lineHeight: 18 } as TypographyScale,
  micro: { fontSize: 11, fontWeight: '500', lineHeight: 14 } as TypographyScale,
} as const;

/**
 * 엄격 별점 스케일 구간별 색상.
 * 기획 결정: 엄격 0~5 스케일, 평균 ≈ 2.5.
 * - 3.5 미만: 평범/주의 (엄격 기준이므로 "나쁨"으로 단정하지 않음)
 * - 3.5 이상: "좋음" (재방문 의향 구간)
 * - 4.5 이상: "최상" (상위 ~0.7%, 일부러 찾아올 곳)
 */
export interface StarBand {
  min: number;
  label: '평범' | '좋음' | '최상';
  colorKey: keyof ColorPalette;
}

export const starScale: StarBand[] = [
  { min: 0, label: '평범', colorKey: 'textSecondary' },
  { min: 3.5, label: '좋음', colorKey: 'success' },
  { min: 4.5, label: '최상', colorKey: 'primary' },
];

export function getStarBand(star: number): StarBand {
  let band = starScale[0];
  for (const b of starScale) {
    if (star >= b.min) band = b;
  }
  return band;
}

export interface ElevationStyle {
  shadowColor: string;
  shadowOffset: { width: number; height: number };
  shadowOpacity: number;
  shadowRadius: number;
  elevation: number; // Android
}

export const elevation: Record<'none' | 'sm' | 'md' | 'lg', ElevationStyle> = {
  none: {
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0,
    shadowRadius: 0,
    elevation: 0,
  },
  sm: {
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 1,
  },
  md: {
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.12,
    shadowRadius: 6,
    elevation: 3,
  },
  lg: {
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.16,
    shadowRadius: 16,
    elevation: 8,
  },
};
