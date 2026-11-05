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
  const units = sido ? REGIONS.units.filter((u) => u.sido === sido) : REGIONS.units;
  const sel = selected ? units.find((u) => `${u.sido}|${u.name}` === selected) : undefined;

  // 선 두께는 화면 픽셀 기준으로 고정(non-scaling-stroke) — 확대 배율·구역 크기와 무관하게 같은 두께
  const unitPath = (u: (typeof units)[number], highlight: boolean) => {
    const key = `${u.sido}|${u.name}`;
    const on = visited.has(key);
    return (
      <Path
        key={key}
        d={u.d}
        fill={on ? t.colors.primary : t.colors.surfaceAlt}
        fillOpacity={on ? 0.85 : 1}
        stroke={highlight ? t.colors.textPrimary : t.colors.background}
        strokeWidth={highlight ? 2.5 : 1}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        // 웹 개발 모드에선 react-native-svg 가 'Unknown event handler property' 경고를 내지만 동작함(앱·배포 빌드엔 없음)
        onPress={onPressUnit ? () => onPressUnit(u.sido, u.name) : undefined}
      />
    );
  };

  return (
    <Svg width="100%" height={height} viewBox={viewBox} accessibilityLabel={`${sido ?? '전국'} 리뷰 지도`}>
      {!sido && REGIONS.north ? (
        <Path d={REGIONS.north} fill={t.colors.surfaceAlt} stroke={t.colors.border} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      ) : null}
      <G>{units.filter((u) => u !== sel).map((u) => unitPath(u, false))}</G>
      {/* 선택 구역은 맨 위에 다시 그리고 중심 기준으로 살짝 키워 강조(이웃 구역 선에 가려지지 않게) */}
      {sel ? (() => {
        const [bx, by, bw, bh] = sel.bbox;
        const cx = bx + bw / 2;
        const cy = by + bh / 2;
        return <G transform={`translate(${cx} ${cy}) scale(1.08) translate(${-cx} ${-cy})`}>{unitPath(sel, true)}</G>;
      })() : null}
    </Svg>
  );
}
