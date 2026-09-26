/** 2. 추천결과 (Recommendations) — docs/design/screens.md */
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { api, RecommendRequest, RecommendResponse, RestaurantItem } from '../src/api/client';
import { Button } from '../src/components/Button';
import { RetryButton } from '../src/components/RetryButton';
import { GovBudgetBadge, Notice, PercentileBadge, ReasonList, StarRatingBadge } from '../src/components/ui';
import { useTheme } from '../src/theme';

const RELAX_LABEL: Record<string, string> = { distance: '거리', mood: '분위기', price: '가격', genre: '장르' };

function RestaurantCard({ item, onPress }: { item: RestaurantItem; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={{ backgroundColor: t.colors.surface, borderRadius: t.radius.lg, padding: t.spacing.lg, gap: t.spacing.sm, ...t.elevation.sm }}
    >
      <Text style={[t.typography.heading, { color: t.colors.textPrimary }]}>{item.name}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        <StarRatingBadge star={item.star} />
        <PercentileBadge percentile={item.percentile} />
      </View>
      <ReasonList reasons={item.reasons} />
      <GovBudgetBadge visits={item.gov_visits} source={item.gov_source} />
    </Pressable>
  );
}

export default function RecommendationScreen() {
  const t = useTheme();
  const router = useRouter();
  const { q, fallback } = useLocalSearchParams<{ q: string; fallback?: string }>();
  const [limit, setLimit] = useState(3);
  const [data, setData] = useState<RecommendResponse | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    setData(null);
    const req: RecommendRequest = { ...JSON.parse(q), limit };
    api.recommend(req).then(setData, () => setError(true));
  }, [q, limit]);
  useEffect(load, [load]);

  if (error) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', padding: t.spacing.xl, gap: t.spacing.md }}>
        <Text style={[t.typography.body, { color: t.colors.textPrimary, textAlign: 'center' }]}>
          추천을 불러오는 중 문제가 생겼어요.
        </Text>
        <RetryButton onPress={load} />
      </View>
    );
  }
  if (!data) return <ActivityIndicator style={{ marginTop: t.spacing.xxl }} />;

  if (!data.items.length) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', padding: t.spacing.xl, gap: t.spacing.md }}>
        <Text style={[t.typography.body, { color: t.colors.textPrimary, textAlign: 'center' }]}>
          조건에 맞는 곳을 찾지 못했어요. 조건을 조금 넓혀볼까요?
        </Text>
        <Button label="조건 다시 선택하기" variant="secondary" onPress={() => router.back()} />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      {fallback ? <Notice text="위치 정보 없이 추천 중이에요." /> : null}
      {data.relaxed.length ? (
        <Notice text={`조건에 맞는 곳이 적어 ${data.relaxed.map((r) => RELAX_LABEL[r] ?? r).join('/')} 조건을 완화했어요.`} />
      ) : null}
      {data.items.map((it) => (
        <RestaurantCard key={it.id} item={it} onPress={() => router.push(`/restaurant/${it.id}`)} />
      ))}
      {/* ponytail: 동점대 로테이션은 서버에서 일 단위라 재요청해도 같음 → "다른 곳 보기"는 최대 5곳으로 확장 */}
      {limit < 5 ? <Button label="다른 곳 보기" variant="secondary" onPress={() => setLimit(5)} /> : null}
    </ScrollView>
  );
}
