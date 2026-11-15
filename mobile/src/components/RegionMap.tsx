/** 리뷰 지도 — docs/design/screens.md 'RegionMap'. 다녀온 곳(리뷰 있음)만 색칠, 색 진하기는 보류(docs/01 G-2).
 *  2026-11-12: 전국 = 시도 경계만, 시도 = 화면 가운데 크게, +/− 버튼 확대(확대 중 끌어 이동),
 *  선택 구역은 살짝 커지며 강조(애니메이션). 떨어진 섬 구역(울릉군)은 빈 모서리에 축소 표시(regions.json inset). */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, PanResponder, Pressable, Text, View } from 'react-native';
import Svg, { G, Path, Rect } from 'react-native-svg';
import { Ionicons } from '@expo/vector-icons';
import { REGIONS, RegionUnit } from '../regions';
import { useTheme } from '../theme';

const PAD = 0.06;
const MAX_ZOOM = 4;
const POP = 0.12; // 선택 강조 확대량

type Box = [number, number, number, number];

/** 섬 inset 이동: 점 p → p·k + d */
const insetTf = (u: RegionUnit) => (u.inset ? `translate(${u.inset[0]} ${u.inset[1]}) scale(${u.inset[2]})` : undefined);
const insetPt = (u: RegionUnit, [x, y]: [number, number]): [number, number] =>
  u.inset ? [x * u.inset[2] + u.inset[0], y * u.inset[2] + u.inset[1]] : [x, y];

export function RegionMap({
  visited,
  sido,
  selected,
  onPressSido,
  onPressUnit,
  height,
}: {
  visited: Set<string>;
  /** null = 전국(시도 경계만), 시도명 = 그 시도 시군구 */
  sido: string | null;
  selected?: string | null;
  onPressSido?: (sido: string) => void;
  onPressUnit?: (sido: string, name: string) => void;
  height: number;
}) {
  const t = useTheme();
  const s = sido ? REGIONS.sido.find((x) => x.name === sido) : undefined;
  const padBox = ([x, y, w, h]: Box): Box => {
    const pad = Math.max(w, h) * PAD;
    return [x - pad, y - pad, w + pad * 2, h + pad * 2];
  };
  // base = 처음 화면(본토), outer = 축소하면 보이는 전체(옹진군처럼 흩어진 섬 포함)
  const base: Box = useMemo(() => padBox(s?.view ?? s?.bbox ?? REGIONS.viewBox), [s]);
  const outer: Box = useMemo(() => {
    const o = padBox(s?.bbox ?? REGIONS.viewBox);
    const x0 = Math.min(o[0], base[0]), y0 = Math.min(o[1], base[1]);
    return [x0, y0, Math.max(o[0] + o[2], base[0] + base[2]) - x0, Math.max(o[1] + o[3], base[1] + base[3]) - y0];
  }, [s, base]);
  const minZoom = Math.min(1, base[2] / outer[2], base[3] / outer[3]);
  const units = sido ? REGIONS.units.filter((u) => u.sido === sido) : [];
  const sel = selected ? units.find((u) => `${u.sido}|${u.name}` === selected) : undefined;
  const visitedSido = useMemo(() => new Set([...visited].map((k) => k.split('|')[0])), [visited]);

  // --- 확대·이동: 확대 배율 + 보이는 중심(지도 좌표). 시도가 바뀌면 처음으로
  const [zoom, setZoom] = useState(1);
  const [center, setCenter] = useState<[number, number]>([base[0] + base[2] / 2, base[1] + base[3] / 2]);
  const [layoutW, setLayoutW] = useState(1);
  useEffect(() => {
    setZoom(1);
    setCenter([base[0] + base[2] / 2, base[1] + base[3] / 2]);
  }, [base]);
  const vw = base[2] / zoom;
  const vh = base[3] / zoom;
  const clampC = (c: [number, number], z: number): [number, number] => {
    const axis = (v: number, lo: number, len: number, half: number) =>
      half * 2 >= len ? lo + len / 2 : Math.min(Math.max(v, lo + half), lo + len - half);
    return [axis(c[0], outer[0], outer[2], base[2] / z / 2), axis(c[1], outer[1], outer[3], base[3] / z / 2)];
  };
  const viewBox = `${center[0] - vw / 2} ${center[1] - vh / 2} ${vw} ${vh}`;
  // 화면 1pt = 지도 몇 단위(가로·세로 중 맞춰지는 쪽, preserveAspectRatio meet)
  const unitsPerPt = Math.max(vw / layoutW, vh / height);

  const live = useRef({ zoom, center, unitsPerPt, minZoom });
  live.current = { zoom, center, unitsPerPt, minZoom };
  const start = useRef<[number, number] | null>(null);
  const pan = useMemo(
    () =>
      PanResponder.create({
        // 확대(+ 버튼) 중 끌 때만 가로채 이동. 탭은 지도(구역 누르기)로 넘김. 두 손가락 확대는 없음(2026-11-12 취소)
        onMoveShouldSetPanResponder: (_, g) => live.current.zoom !== 1 && Math.hypot(g.dx, g.dy) > 6,
        onPanResponderGrant: () => void (start.current = live.current.center),
        onPanResponderMove: (_, g) => {
          const st = start.current;
          if (!st) return;
          const k = live.current.unitsPerPt;
          setCenter(clampC([st[0] - g.dx * k, st[1] - g.dy * k], live.current.zoom));
        },
        onPanResponderRelease: () => void (start.current = null),
        onPanResponderTerminate: () => void (start.current = null),
      }),
    [base, outer],
  );
  const zoomBy = (f: number) => {
    if (f === 0) return void (setZoom(1), setCenter([base[0] + base[2] / 2, base[1] + base[3] / 2])); // 처음 크기
    const z = Math.min(MAX_ZOOM, Math.max(minZoom, zoom * f));
    setZoom(z);
    setCenter(clampC(center, z));
  };

  // --- 선택 강조: 0 → 1 로 살짝 커짐
  const pop = useRef(new Animated.Value(0)).current;
  const [popV, setPopV] = useState(0);
  useEffect(() => {
    const id = pop.addListener(({ value }) => setPopV(value));
    return () => pop.removeListener(id);
  }, [pop]);
  useEffect(() => {
    pop.setValue(0);
    if (sel) Animated.timing(pop, { toValue: 1, duration: 220, easing: Easing.out(Easing.back(2)), useNativeDriver: false }).start();
  }, [selected]);

  const stroke = (on: boolean) => (on ? t.colors.textPrimary : t.colors.background);

  const unitPath = (u: RegionUnit, highlight: boolean) => {
    const on = visited.has(`${u.sido}|${u.name}`);
    return (
      <Path
        key={`${u.sido}|${u.name}`}
        d={u.d}
        transform={insetTf(u)}
        fill={on ? t.colors.primary : t.colors.surfaceAlt}
        fillOpacity={on ? 0.85 : 1}
        stroke={stroke(highlight)}
        strokeWidth={highlight ? 2.5 : 1}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        // 웹 개발 모드에선 react-native-svg 가 'Unknown event handler property' 경고를 내지만 동작함(앱·배포 빌드엔 없음)
        onPress={onPressUnit ? () => onPressUnit(u.sido, u.name) : undefined}
      />
    );
  };

  return (
    <View style={{ height }} onLayout={(e) => setLayoutW(e.nativeEvent.layout.width || 1)} {...pan.panHandlers}>
      <Svg width="100%" height={height} viewBox={viewBox} accessibilityLabel={`${sido ?? '전국'} 리뷰 지도`}>
        {!sido ? (
          <>
            {REGIONS.north ? <Path d={REGIONS.north} fill={t.colors.surfaceAlt} stroke={t.colors.border} strokeWidth={1} vectorEffect="non-scaling-stroke" /> : null}
            {REGIONS.sido.map((x) => (
              <Path key={x.name} d={x.d} fill={visitedSido.has(x.name) ? t.colors.primary : t.colors.surfaceAlt}
                fillOpacity={visitedSido.has(x.name) ? 0.85 : 1} stroke={t.colors.background} strokeWidth={1.5} strokeLinejoin="round"
                vectorEffect="non-scaling-stroke" onPress={onPressSido ? () => onPressSido(x.name) : undefined} />
            ))}
          </>
        ) : (
          <>
            <G>{units.filter((u) => u !== sel).map((u) => unitPath(u, false))}</G>
            {units.filter((u) => u.inset).map((u) => {
              const [bx, by, bw, bh] = u.bbox;
              const k = u.inset![2];
              const pad = 20;
              return <Rect key={`f-${u.name}`} x={bx * k + u.inset![0] - pad} y={by * k + u.inset![1] - pad} width={bw * k + pad * 2}
                height={bh * k + pad * 2} fill="none" stroke={t.colors.border} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" pointerEvents="none" />;
            })}
            {/* 선택 구역은 맨 위에 다시 그리고 중심 기준으로 살짝 키워 강조(이웃 구역 선에 가려지지 않게) */}
            {sel ? (() => {
              const [cx, cy] = insetPt(sel, [sel.bbox[0] + sel.bbox[2] / 2, sel.bbox[1] + sel.bbox[3] / 2]);
              const k = 1 + POP * popV;
              return <G transform={`translate(${cx} ${cy}) scale(${k}) translate(${-cx} ${-cy})`}>{unitPath(sel, true)}</G>;
            })() : null}
          </>
        )}
      </Svg>
      {/* 확대 버튼 */}
      <View style={{ position: 'absolute', right: 4, bottom: 4, gap: 4 }}>
        {([['add', '확대', 1.5], ['remove', '축소', 1 / 1.5]] as const).map(([icon, a11y, f]) => (
          <Pressable key={icon} onPress={() => zoomBy(f)} accessibilityRole="button" accessibilityLabel={`지도 ${a11y}`}
            style={{ width: 40, height: 40, borderRadius: t.radius.pill, alignItems: 'center', justifyContent: 'center', backgroundColor: t.colors.surface, ...t.elevation.sm }}>
            <Ionicons name={icon} size={22} color={t.colors.textPrimary} />
          </Pressable>
        ))}
      </View>
      {zoom !== 1 ? (
        <Pressable onPress={() => zoomBy(0)} accessibilityRole="button" accessibilityLabel="지도 처음 크기로"
          style={{ position: 'absolute', left: 4, bottom: 4, paddingHorizontal: t.spacing.sm, minHeight: 32, justifyContent: 'center', borderRadius: t.radius.pill, backgroundColor: t.colors.surface }}>
          <Text style={[t.typography.caption, { color: t.colors.textPrimary }]}>처음 크기</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
