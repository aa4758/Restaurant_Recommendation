/** 1. 조건선택 (Home) — docs/design/screens.md */
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Linking, ScrollView, Text, View } from 'react-native';
import { Link, useRouter } from 'expo-router';
import { api, AlcoholFilter, FiltersResponse, RecommendRequest } from '../src/api/client';
import { useLocation } from '../src/state/useLocation';
import { Button } from '../src/components/Button';
import { FilterChipGroup, InlineErrorBanner, Notice } from '../src/components/ui';
import { useTheme } from '../src/theme';

const RADIUS_OPTIONS = [
  { value: '500', label: '500m' },
  { value: '1000', label: '1km' },
  { value: '2000', label: '2km' },
];
const ALCOHOL_LABEL: Record<AlcoholFilter, string> = { any: '상관없음', yes: '술 마실래요', no: '술 없이' };

const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
const opts = (vals: string[]) => vals.map((v) => ({ value: v, label: v }));

export default function HomeScreen() {
  const t = useTheme();
  const router = useRouter();
  const loc = useLocation();
  const [filters, setFilters] = useState<FiltersResponse | null>(null);
  const [error, setError] = useState(false);
  const [price, setPrice] = useState<string[]>([]);
  const [genre, setGenre] = useState<string[]>([]);
  const [mood, setMood] = useState<string[]>([]);
  const [alcohol, setAlcohol] = useState<AlcoholFilter>('any');
  const [radius, setRadius] = useState('1000');

  const loadFilters = useCallback(() => {
    setError(false);
    api.getFilters().then(setFilters, () => setError(true));
  }, []);
  useEffect(loadFilters, [loadFilters]);

  const summary = [...price, ...genre, ...mood, alcohol !== 'any' ? ALCOHOL_LABEL[alcohol] : ''].filter(Boolean);

  const submit = () => {
    const req: RecommendRequest = {
      lat: loc.lat,
      lng: loc.lng,
      // 위치 없음 → 거리 조건 없이 (스키마 최대 반경)
      radius_m: loc.isFallback ? 20000 : Number(radius),
      price: price.length ? price : undefined,
      genre: genre.length ? genre : undefined,
      mood: mood.length ? mood : undefined,
      alcohol,
    };
    router.push({ pathname: '/recommendations', params: { q: JSON.stringify(req), fallback: loc.isFallback ? '1' : '' } });
  };

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      {loc.isFallback ? (
        <View style={{ gap: t.spacing.sm }}>
          <Notice text="위치 권한이 꺼져 있어요. 허용하면 더 정확한 추천을 드릴 수 있어요." />
          <Button label="설정에서 허용하기" variant="text" onPress={() => Linking.openSettings()} />
        </View>
      ) : null}

      <Text style={[t.typography.title, { color: t.colors.textPrimary }]}>지금 이 근처, 진짜 맛집만</Text>

      {error ? (
        <InlineErrorBanner message="필터 정보를 불러오지 못했어요. 다시 시도해 주세요." onRetry={loadFilters} />
      ) : !filters ? (
        <ActivityIndicator />
      ) : (
        <View>
          <FilterChipGroup title="가격대" options={opts(filters.price)} selected={price} onToggle={(v) => setPrice(toggle(price, v))} />
          <FilterChipGroup title="음식 장르" options={opts(filters.genre)} selected={genre} onToggle={(v) => setGenre(toggle(genre, v))} />
          <FilterChipGroup title="분위기" options={opts(filters.mood)} selected={mood} onToggle={(v) => setMood(toggle(mood, v))} />
          <FilterChipGroup
            title="음주"
            options={filters.alcohol.map((a) => ({ value: a, label: ALCOHOL_LABEL[a] }))}
            selected={[alcohol]}
            onToggle={(v) => setAlcohol(v as AlcoholFilter)}
            hint="음주 조건은 결과가 적어도 완화되지 않아요."
          />
          <FilterChipGroup
            title="거리"
            options={RADIUS_OPTIONS}
            selected={[radius]}
            onToggle={setRadius}
            disabled={loc.isFallback}
            hint={loc.isFallback ? '위치 권한을 허용하면 거리순 추천을 받을 수 있어요.' : undefined}
          />
        </View>
      )}

      {summary.length ? (
        <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>선택: {summary.join(' · ')}</Text>
      ) : null}
      <Button label="3곳 추천받기" onPress={submit} loading={loc.isLoading} />
      <Link href="/scoring" style={[t.typography.caption, { color: t.colors.accent, textAlign: 'center' }]}>
        찐맛 점수는 어떻게 매기나요?
      </Link>
    </ScrollView>
  );
}
