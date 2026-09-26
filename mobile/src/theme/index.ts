import { useColorScheme } from 'react-native';
import {
  colors,
  spacing,
  radius,
  typography,
  starScale,
  getStarBand,
  elevation,
  ColorScheme,
  ColorPalette,
  StarBand,
  TypographyScale,
} from './tokens';

export interface Theme {
  scheme: ColorScheme;
  colors: ColorPalette;
  spacing: typeof spacing;
  radius: typeof radius;
  typography: typeof typography;
  starScale: StarBand[];
  getStarBand: typeof getStarBand;
  elevation: typeof elevation;
}

/**
 * 현재 시스템 색상 모드를 읽어 테마 객체를 반환하는 훅.
 * 시스템 값이 없으면 'light'로 기본 처리.
 */
export function useTheme(): Theme {
  const scheme: ColorScheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  return {
    scheme,
    colors: colors[scheme],
    spacing,
    radius,
    typography,
    starScale,
    getStarBand,
    elevation,
  };
}

export {
  colors,
  spacing,
  radius,
  typography,
  starScale,
  getStarBand,
  elevation,
};
export type { ColorScheme, ColorPalette, StarBand, TypographyScale };
