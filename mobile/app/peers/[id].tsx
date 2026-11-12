/** 같은 지역·같은 음식 가게 별점순 목록 — 릴스 "주변 다른 {음식} 음식점 보러가기"(2026-11-12) */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, Text, View } from 'react-native';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { api, PeerItem } from '../../src/api/client';
import { InlineErrorBanner } from '../../src/components/ui';
import { useTheme } from '../../src/theme';
import { genreColor, starHeroColor } from '../../src/theme/tokens';

export default function PeersScreen() {
  const t = useTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [items, setItems] = useState<PeerItem[]>([]);
  const [head, setHead] = useState<{ food: string; region?: string | null; total: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const load = async (offset: number) => {
    if (busy) return;
    setBusy(true);
    setError(false);
    try {
      const p = await api.getPeers(id, offset);
      setHead({ food: p.food, region: p.region, total: p.total });
      setItems((prev) => (offset ? [...prev, ...p.items] : p.items));
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load(0);
  }, [id]);

  const title = head ? `${head.region ?? '이 지역'} ${head.food} 별점순` : '별점순 목록';
  return (
    <View style={{ flex: 1 }}>
      <Stack.Screen options={{ title }} />
      <FlatList
        data={items}
        keyExtractor={(r) => r.id}
        contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.sm }}
        ListHeaderComponent={
          head ? <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>총 {head.total}곳 · 별점 높은 순</Text> : undefined
        }
        onEndReached={() => head && items.length < head.total && load(items.length)}
        onEndReachedThreshold={0.5}
        ListFooterComponent={
          error ? <InlineErrorBanner message="목록을 불러오지 못했어요." onRetry={() => load(items.length)} />
          : busy ? <ActivityIndicator accessibilityLabel="불러오는 중" /> : undefined
        }
        renderItem={({ item: r, index }) => (
          <Pressable
            onPress={() => router.push(`/restaurant/${r.id}`)}
            accessibilityRole="button"
            accessibilityLabel={`${index + 1}위 ${r.name}, 별점 ${r.star.toFixed(1)}, 상위 ${r.percentile}퍼센트. 상세 보기`}
            style={{
              flexDirection: 'row', alignItems: 'center', gap: t.spacing.md, padding: t.spacing.md,
              backgroundColor: r.id === id ? t.colors.surfaceAlt : t.colors.surface, borderRadius: t.radius.lg,
            }}
          >
            <Text style={[t.typography.captionStrong, { width: 28, color: t.colors.textSecondary }]}>{index + 1}</Text>
            <Text style={[t.typography.title, { width: 48, color: starHeroColor(r.star, t.scheme) }]}>{r.star.toFixed(1)}</Text>
            <View style={{ flex: 1, gap: t.spacing.xxs }}>
              <Text numberOfLines={1} style={[t.typography.bodyStrong, { color: t.colors.textPrimary }]}>{r.name}</Text>
              <Text numberOfLines={1} style={[t.typography.caption, { color: t.colors.textSecondary }]}>
                <Text style={{ color: genreColor(r.genre, t.scheme) }}>{r.subtype ?? r.genre}</Text> · 상위 {r.percentile}%{r.address ? ` · ${r.address}` : ''}
              </Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}
