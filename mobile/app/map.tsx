/** 리뷰 지도 (ReviewMap) — docs/design/screens.md, docs/01 '리뷰 지도'(I-3). 본인만 보는 화면. */
import React, { useCallback, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, useWindowDimensions, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { api, ApiError, MyReview } from '../src/api/client';
import { clearToken, getToken } from '../src/state/authStore';
import { Button } from '../src/components/Button';
import { LoginButtons } from '../src/components/LoginButtons';
import { RegionMap } from '../src/components/RegionMap';
import { Notice } from '../src/components/ui';
import { REGIONS, sidoProgress, visitedUnits } from '../src/regions';
import { useTheme } from '../src/theme';

export default function ReviewMapScreen() {
  const t = useTheme();
  const router = useRouter();
  const { height } = useWindowDimensions();
  const [reviews, setReviews] = useState<MyReview[] | null>(null);
  const [loggedIn, setLoggedIn] = useState(true);
  const [sido, setSido] = useState<string | null>(null);
  const [unit, setUnit] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = await getToken();
    if (!token) return setLoggedIn(false);
    try {
      setReviews((await api.myReviews(token)).items);
      setLoggedIn(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        setLoggedIn(false);
      } else setReviews([]);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const visited = useMemo(() => visitedUnits(reviews ?? []), [reviews]);
  const keys = useMemo(() => new Set(visited.keys()), [visited]);
  const progress = useMemo(() => sidoProgress(visited), [visited]);
  const doneAll = progress.reduce((a, p) => a + p.done, 0);

  if (!loggedIn) {
    return (
      <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
        <Notice text={'리뷰 지도는 로그인 후 볼 수 있어요.\n리뷰를 쓴 지역이 지도에 칠해져요.'} />
        <LoginButtons onLoggedIn={load} />
      </ScrollView>
    );
  }
  if (reviews == null) return <ActivityIndicator style={{ marginTop: t.spacing.xl }} />;

  const cur = sido ? progress.find((p) => p.name === sido) : null;
  const here = unit ? visited.get(unit) ?? [] : [];
  const h1 = [t.typography.heading, { color: t.colors.textPrimary }];
  const cap = [t.typography.caption, { color: t.colors.textSecondary }];

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      <Text style={h1}>
        {cur ? `${cur.name} ${cur.done}/${cur.total}` : `전국 ${REGIONS.units.length}곳 중 ${doneAll}곳`}
      </Text>
      {sido ? (
        <Button label="← 전국 보기" variant="text" onPress={() => { setSido(null); setUnit(null); }} />
      ) : (
        <Text style={cap}>지역을 누르면 확대돼요.</Text>
      )}
      <RegionMap
        visited={keys}
        sido={sido}
        selected={unit}
        height={Math.min(height * 0.6, 560)}
        onPressUnit={(s, n) => (sido ? setUnit(`${s}|${n}`) : setSido(s))}
      />

      {sido && unit ? (
        <View style={{ gap: t.spacing.xs }}>
          <Text style={[t.typography.bodyStrong, { color: t.colors.textPrimary }]}>{unit.split('|')[1]}</Text>
          {here.length ? (
            here.map((r) => (
              <Pressable key={r.restaurant_id} onPress={() => router.push(`/restaurant/${r.restaurant_id}`)} accessibilityRole="button"
                style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: t.spacing.xs }}>
                <Text style={[t.typography.body, { color: t.colors.textPrimary, flex: 1 }]}>{r.name}</Text>
                <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>★ {r.stars.toFixed(1)}</Text>
              </Pressable>
            ))
          ) : (
            <Text style={cap}>아직 리뷰를 쓴 가게가 없어요.</Text>
          )}
        </View>
      ) : null}

      {!sido
        ? progress.map((p) => (
            <Pressable key={p.name} onPress={() => setSido(p.name)} accessibilityRole="button"
              accessibilityLabel={`${p.name} ${p.total}곳 중 ${p.done}곳`}
              style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: t.spacing.xs, borderBottomWidth: 1, borderBottomColor: t.colors.border }}>
              <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{p.name}</Text>
              <Text style={[t.typography.body, { color: p.done ? t.colors.primary : t.colors.textSecondary }]}>{p.done}/{p.total}</Text>
            </Pressable>
          ))
        : null}
      <Text style={[t.typography.micro, { color: t.colors.textDisabled }]}>경계: 통계청 SGIS · 북한 윤곽: Natural Earth</Text>
    </ScrollView>
  );
}
