/** 탭 3. 좋아요 (LikesByRegion) — docs/design/screens.md 4-3, docs/01 '좋아요 목록' L-1~L-5.
 *  계정에 저장된 좋아요를 시도 → 시군구 → 가게(동으로 묶음)로. 하위 지역이 하나면 그 단계를 건너뜀. 본인만, 점수 무관. */
import React, { useCallback, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, ApiError, MyLike } from '../../src/api/client';
import { clearToken, getToken, syncLikes } from '../../src/state/authStore';
import * as store from '../../src/state/deviceStore';
import { Button } from '../../src/components/Button';
import { LoginButtons } from '../../src/components/LoginButtons';
import { InlineErrorBanner, Notice } from '../../src/components/ui';
import { useTheme } from '../../src/theme';

const ALL = '전체';
const NONE = '지역 정보 없음';
const ETC = '기타';

const sidoOf = (x: MyLike) => x.sido ?? NONE;
const sgOf = (x: MyLike) => x.sigungu ?? NONE;

/** 개수 많은 순(같으면 이름순), last 는 맨 끝 */
function countBy<T>(xs: T[], key: (x: T) => string, last?: string): [string, T[]][] {
  const m = new Map<string, T[]>();
  for (const x of xs) m.set(key(x), [...(m.get(key(x)) ?? []), x]);
  return [...m].sort((a, b) => (a[0] === last ? 1 : 0) - (b[0] === last ? 1 : 0) || b[1].length - a[1].length || a[0].localeCompare(b[0], 'ko'));
}

/** 경로 [] → 시도들, [시도] → 시군구들. 가게 목록 단계면 null */
function childrenOf(items: MyLike[], path: string[]): [string, MyLike[]][] | null {
  if (path[0] === ALL || path.length >= 2) return null;
  if (!path.length) return countBy(items, sidoOf);
  return countBy(items.filter((x) => sidoOf(x) === path[0]), sgOf);
}

export default function LikesScreen() {
  const t = useTheme();
  const router = useRouter();
  const [items, setItems] = useState<MyLike[] | null>(null);
  const [loggedIn, setLoggedIn] = useState(true);
  const [error, setError] = useState(false);
  const [path, setPath] = useState<string[]>([]);

  const load = useCallback(async () => {
    const token = await getToken();
    if (!token) return setLoggedIn(false);
    try {
      setItems(await syncLikes(token));
      setLoggedIn(true);
      setError(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        setLoggedIn(false);
      } else setError(true);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const all = useMemo(() => items ?? [], [items]);
  const go = (p: string[]) => {
    for (let c = childrenOf(all, p); c && c.length === 1; c = childrenOf(all, p)) p = [...p, c[0][0]];
    setPath(p);
  };
  const back = () => {
    let p = path.slice(0, -1);
    while (p.length && childrenOf(all, p)?.length === 1) p = p.slice(0, -1);
    setPath(p);
  };

  const unlike = async (x: MyLike) => {
    const token = await getToken();
    if (!token) return;
    setItems((cur) => cur?.filter((y) => y.restaurant_id !== x.restaurant_id) ?? cur);
    try {
      await api.removeLike(token, x.restaurant_id);
      await store.setLiked(x.restaurant_id, false);
      api.react({ device_id: await store.getDeviceId(), restaurant_id: x.restaurant_id, value: 'none' }).catch(() => undefined);
    } catch {
      setError(true);
      load();
    }
  };

  const h1 = [t.typography.heading, { color: t.colors.textPrimary }];
  const cap = [t.typography.caption, { color: t.colors.textSecondary }];

  if (!loggedIn) {
    return (
      <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
        <Notice text={'로그인하면 좋아요한 가게를 지역별로 볼 수 있어요.\n좋아요는 계정에 저장돼요.'} />
        <LoginButtons onLoggedIn={load} />
      </ScrollView>
    );
  }
  if (items == null && !error) return <ActivityIndicator style={{ marginTop: t.spacing.xl }} />;

  const kids = childrenOf(all, path);
  const shown = path[0] === ALL ? all : all.filter((x) => sidoOf(x) === path[0] && (path.length < 2 || sgOf(x) === path[1]));
  const title = path.length ? `${path[path.length - 1]} ${shown.length}곳` : `좋아요 ${all.length}곳`;

  const row = (label: string, n: number, onPress: () => void) => (
    <Pressable key={label} onPress={onPress} accessibilityRole="button" accessibilityLabel={`${label} ${n}곳`}
      style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: t.spacing.sm, borderBottomWidth: 1, borderBottomColor: t.colors.border }}>
      <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{label}</Text>
      <Text style={[t.typography.body, { color: t.colors.primary }]}>{n}곳</Text>
    </Pressable>
  );

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      {error ? <InlineErrorBanner message="불러오지 못했어요. 다시 시도해 주세요." onRetry={load} /> : null}
      <Text style={h1}>{title}</Text>
      {path.length ? <Button label="← 뒤로" variant="text" onPress={back} /> : null}

      {!all.length && !error ? <Text style={cap}>아직 좋아요한 가게가 없어요. 추천 카드에서 ♥ 를 눌러 보세요.</Text> : null}

      {kids ? (
        <View>
          {!path.length && all.length ? row(ALL, all.length, () => setPath([ALL])) : null}
          {kids.map(([name, xs]) => row(name, xs.length, () => go([...path, name])))}
        </View>
      ) : (
        countBy(shown, (x) => (path[0] === ALL ? `${sidoOf(x)} ${sgOf(x)}` : x.dong ?? ETC), ETC).map(([group, xs]) => (
          <View key={group} style={{ gap: t.spacing.xs }}>
            <Text style={[t.typography.captionStrong, { color: t.colors.textSecondary }]} accessibilityRole="header">{group}</Text>
            {xs.map((x) => (
              <View key={x.restaurant_id} style={{ flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: t.colors.border }}>
                <Pressable onPress={() => router.push(`/restaurant/${x.restaurant_id}`)} accessibilityRole="button"
                  style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: t.spacing.sm, paddingVertical: t.spacing.sm }}>
                  <View style={{ flex: 1 }}>
                    <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{x.name}</Text>
                    {x.food ? <Text style={cap}>{x.food}</Text> : null}
                  </View>
                  {x.star != null ? <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>★ {x.star.toFixed(1)}</Text> : null}
                </Pressable>
                <Pressable onPress={() => unlike(x)} accessibilityRole="button" accessibilityLabel={`${x.name} 좋아요 취소`} hitSlop={8}
                  style={{ padding: t.spacing.sm, minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' }}>
                  <Ionicons name="heart" size={22} color={t.colors.primary} />
                </Pressable>
              </View>
            ))}
          </View>
        ))
      )}
    </ScrollView>
  );
}
