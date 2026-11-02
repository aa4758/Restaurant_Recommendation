/** 리뷰 지도 — docs/design/screens.md 'RegionMap'. 다녀온 시군구(리뷰 있음)만 색칠, 색 진하기는 보류(docs/01 G-2). */
import React from 'react';
import Svg, { G, Path } from 'react-native-svg';
import { REGIONS } from '../regions';
import { useTheme } from '../theme';

const PAD = 0.06;

export function RegionMap({
  visited,
  sido,
  selected,
  onPressUnit,
  height,
}: {
  visited: Set<string>;
  /** null = 전국, 시도명 = 그 시도만 확대 */
  sido: string | null;
  selected?: string | null;
  onPressUnit?: (sido: string, name: string) => void;
  height: number;
}) {
  const t = useTheme();
  const box = sido ? REGIONS.sido.find((s) => s.name === sido)?.bbox ?? REGIONS.viewBox : REGIONS.viewBox;
  const [x, y, w, h] = box;
  const pad = Math.max(w, h) * PAD;
  const viewBox = `${x - pad} ${y - pad} ${w + pad * 2} ${h + pad * 2}`;
  const stroke = Math.max(w, h) / 600; // 화면 크기와 무관하게 가는 선
  const units = sido ? REGIONS.units.filter((u) => u.sido === sido) : REGIONS.units;

  return (
    <Svg width="100%" height={height} viewBox={viewBox} accessibilityLabel={`${sido ?? '전국'} 리뷰 지도`}>
      {!sido && REGIONS.north ? <Path d={REGIONS.north} fill={t.colors.surfaceAlt} stroke={t.colors.border} strokeWidth={stroke} /> : null}
      <G>
        {units.map((u) => {
          const key = `${u.sido}|${u.name}`;
          const on = visited.has(key);
          return (
            <Path
              key={key}
              d={u.d}
              fill={on ? t.colors.primary : t.colors.surfaceAlt}
              fillOpacity={on ? 0.85 : 1}
              stroke={key === selected ? t.colors.textPrimary : t.colors.background}
              strokeWidth={key === selected ? stroke * 3 : stroke}
              // 웹 개발 모드에선 react-native-svg 가 'Unknown event handler property' 경고를 내지만 동작함(앱·배포 빌드엔 없음)
              onPress={onPressUnit ? () => onPressUnit(u.sido, u.name) : undefined}
            />
          );
        })}
      </G>
    </Svg>
  );
}
