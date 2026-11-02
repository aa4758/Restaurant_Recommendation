/** 4. 리뷰작성 (WriteReview) — docs/design/screens.md. 리뷰 개편: docs/01 R-1~R-6 */
import React, { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Link, useLocalSearchParams, useRouter } from 'expo-router';
import * as Location from 'expo-location';
import { api, ApiError, MenuEntry, PriceBand, ReviewPosition } from '../../src/api/client';
import { clearToken, getToken } from '../../src/state/authStore';
import { Button } from '../../src/components/Button';
import { LoginButtons } from '../../src/components/LoginButtons';
import { FilterChip, InlineErrorBanner, Notice } from '../../src/components/ui';
import { useTheme } from '../../src/theme';

const STEPS = Array.from({ length: 10 }, (_, i) => (i + 1) / 2); // 0.5 ~ 5
const TAGS = ['맛있어요', '가성비', '친절', '양 많아요', '재방문 의사']; // '조용해요' → 분위기 칩(R-6)
const SPENDS: PriceBand[] = ['~1만', '1~2만', '2~4만', '4만+'];
const MOODS = ['조용한', '회식', '데이트', '혼밥', '가성비', '노포']; // /meta/filters mood 와 동일
const MAX_MENUS = 3;
const ANCHORS: [number, string][] = [
  [2.5, '평범'],
  [3.5, '또 올 의향'],
  [4.5, '일부러 찾아올 곳'],
];

function ratingHint(s: number): string {
  const exact = ANCHORS.find(([v]) => v === s);
  if (exact) return `${s} = ${exact[1]}`;
  const lo = [...ANCHORS].reverse().find(([v]) => v < s);
  const hi = ANCHORS.find(([v]) => v > s);
  if (lo && hi) return `${lo[0]}(${lo[1]})와 ${hi[0]}(${hi[1]}) 사이예요`;
  return hi ? `${hi[0]}(${hi[1]})보다 아쉬워요` : `${lo![0]}(${lo![1]}) 이상, 최고예요`;
}

/** 위치 권한이 이미 있을 때만 현재 위치(묻지 않음). 현장 작성 판정에만 쓰고 저장 안 함. */
async function currentPosition(): Promise<ReviewPosition | null> {
  try {
    if ((await Location.getForegroundPermissionsAsync()).status !== 'granted') return null;
    const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
  } catch {
    return null;
  }
}

const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

export default function WriteReviewScreen() {
  const t = useTheme();
  const router = useRouter();
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const [stars, setStars] = useState<number | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [spend, setSpend] = useState<PriceBand | null>(null);
  const [moods, setMoods] = useState<string[]>([]);
  const [menus, setMenus] = useState<{ name: string; price: string }[]>([]);
  const [known, setKnown] = useState<MenuEntry[]>([]);
  const [more, setMore] = useState(false);
  const [existing, setExisting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null); // null = 확인 중
  const openPos = useRef<Promise<ReviewPosition | null>>(Promise.resolve(null));

  // 상세에서 왔으면 돌아가고, 바로 열었으면(딥링크·새로고침) 상세로
  const done = () => (router.canGoBack() ? router.back() : router.replace(`/restaurant/${encodeURIComponent(id)}`));

  const loadMine = async (token: string) => {
    try {
      const mine = (await api.myReviews(token)).items.find((r) => r.restaurant_id === id);
      if (!mine) return;
      setExisting(true);
      setStars(mine.stars);
      setText(mine.text);
      setTags(mine.tags);
      setSpend(mine.spend);
      setMoods(mine.moods);
      setMenus(mine.menus.map((m) => ({ name: m.name, price: m.price ? String(m.price) : '' })));
      if (mine.spend || mine.moods.length || mine.menus.length) setMore(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        setLoggedIn(false);
      }
    }
  };

  useEffect(() => {
    openPos.current = currentPosition(); // 화면 열 때 위치(R-2)
    api.getMenus(id).then((r) => setKnown(r.items)).catch(() => undefined);
    getToken().then((tok) => {
      setLoggedIn(!!tok);
      if (tok) loadMine(tok);
    });
  }, [id]);

  const onLoggedIn = async () => {
    setLoggedIn(true);
    const tok = await getToken();
    if (tok) loadMine(tok);
  };

  const fail = async (e: unknown) => {
    if (e instanceof ApiError && e.status === 401) {
      await clearToken(); // 만료·탈퇴 → 다시 로그인(작성 중인 내용은 유지)
      setLoggedIn(false);
    } else setError(e instanceof ApiError && e.status === 429 ? e.message : '요청에 실패했어요. 다시 시도해 주세요.');
  };

  const submit = async () => {
    if (stars == null) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) return setLoggedIn(false);
      const positions = (await Promise.all([openPos.current, currentPosition()])).filter((p): p is ReviewPosition => !!p);
      const menuBody = menus
        .filter((m) => m.name.trim())
        .map((m) => ({ name: m.name.trim(), price: Number(m.price) >= 1000 ? Number(m.price) : null }));
      await api.createReview(id, { stars, text, tags, spend, moods, menus: menuBody, positions }, token);
      done();
    } catch (e) {
      await fail(e);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) return setLoggedIn(false);
      await api.deleteMyReview(id, token);
      done();
    } catch (e) {
      await fail(e);
    } finally {
      setBusy(false);
    }
  };

  const setMenu = (i: number, patch: Partial<{ name: string; price: string }>) =>
    setMenus(menus.map((m, k) => (k === i ? { ...m, ...patch } : m)));
  const inputStyle = [t.typography.body, { color: t.colors.textPrimary, borderColor: t.colors.border, borderWidth: 1, borderRadius: t.radius.md, padding: t.spacing.sm }];
  const caption = [t.typography.caption, { color: t.colors.textSecondary }];
  const label = [t.typography.bodyStrong, { color: t.colors.textPrimary }];

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      {name ? <Text style={[t.typography.heading, { color: t.colors.textPrimary }]}>{name}</Text> : null}
      {existing ? <Text style={caption}>이미 쓴 리뷰가 있어요. 등록하면 수정돼요.</Text> : null}
      <Notice text={'이 앱의 별점은 엄격합니다\n2.5 = 평범한 곳이에요\n3.5 = 또 올 의향이 있어요\n4.5 = 일부러 찾아올 곳이에요'} />

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        {STEPS.map((s) => (
          <FilterChip key={s} label={s.toFixed(1)} selected={stars === s} onPress={() => setStars(s)} />
        ))}
      </View>
      {stars != null ? <Text style={caption}>{ratingHint(stars)}</Text> : null}

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        {TAGS.map((tag) => (
          <FilterChip key={tag} label={tag} selected={tags.includes(tag)} onPress={() => setTags(toggle(tags, tag))} />
        ))}
      </View>
      <TextInput
        value={text}
        onChangeText={setText}
        placeholder="어땠는지 짧게 남겨주세요"
        placeholderTextColor={t.colors.textDisabled}
        multiline
        maxLength={1000}
        style={[...inputStyle, { minHeight: 100, padding: t.spacing.md, textAlignVertical: 'top' }]}
      />

      <Button label={more ? '더 알려주기 접기' : '더 알려주기 (선택)'} variant="text" onPress={() => setMore(!more)} />
      {more ? (
        <View style={{ gap: t.spacing.md }}>
          <Text style={caption}>다른 사람의 가격대·분위기 필터에 쓰여요.</Text>
          <Text style={label}>1인 지출</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
            {SPENDS.map((s) => (
              <FilterChip key={s} label={s} selected={spend === s} onPress={() => setSpend(spend === s ? null : s)} />
            ))}
          </View>
          <Text style={label}>분위기</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
            {MOODS.map((m) => (
              <FilterChip key={m} label={m} selected={moods.includes(m)} onPress={() => setMoods(toggle(moods, m))} />
            ))}
          </View>
          <Text style={label}>먹은 메뉴 (최대 {MAX_MENUS}개)</Text>
          {known.length ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
              {known
                .filter((k) => !menus.some((m) => m.name.replace(/\s/g, '') === k.name.replace(/\s/g, '')))
                .slice(0, 8)
                .map((k) => (
                  <FilterChip
                    key={k.name}
                    label={`+ ${k.name}`}
                    selected={false}
                    onPress={() => menus.length < MAX_MENUS && setMenus([...menus, { name: k.name, price: k.price ? String(k.price) : '' }])}
                  />
                ))}
            </View>
          ) : null}
          {menus.map((m, i) => (
            <View key={i} style={{ flexDirection: 'row', gap: t.spacing.xs, alignItems: 'center' }}>
              <TextInput value={m.name} onChangeText={(v) => setMenu(i, { name: v })} placeholder="메뉴명" maxLength={30}
                placeholderTextColor={t.colors.textDisabled} style={[...inputStyle, { flex: 2, minWidth: 0 }]} accessibilityLabel={`메뉴 ${i + 1} 이름`} />
              <TextInput value={m.price} onChangeText={(v) => setMenu(i, { price: v.replace(/\D/g, '').slice(0, 6) })} placeholder="가격(원)"
                keyboardType="number-pad" placeholderTextColor={t.colors.textDisabled} style={[...inputStyle, { flex: 1, minWidth: 0 }]} accessibilityLabel={`메뉴 ${i + 1} 가격`} />
              <Pressable onPress={() => setMenus(menus.filter((_, k) => k !== i))} accessibilityRole="button" accessibilityLabel={`메뉴 ${i + 1} 삭제`}
                hitSlop={8} style={{ width: 32, height: 44, alignItems: 'center', justifyContent: 'center' }}>
                <Text style={[t.typography.body, { color: t.colors.textSecondary }]}>✕</Text>
              </Pressable>
            </View>
          ))}
          {menus.length < MAX_MENUS ? (
            <Button label="+ 메뉴 직접 입력" variant="text" onPress={() => setMenus([...menus, { name: '', price: '' }])} />
          ) : null}
        </View>
      ) : null}

      <Text style={caption}>가게 근처(200m)에서 쓰면 '현장 작성' 표시가 붙어요. 위치는 저장하지 않아요.</Text>
      {error ? <InlineErrorBanner message={error} /> : null}
      {loggedIn === false ? (
        <>
          <Notice text={'리뷰는 로그인 후 등록할 수 있어요.\n한 사람이 여러 번 쓰는 걸 막기 위해서예요.'} />
          <LoginButtons onLoggedIn={onLoggedIn} />
        </>
      ) : (
        <>
          <Button label={existing ? '리뷰 수정하기' : '리뷰 등록하기'} onPress={submit} disabled={stars == null || loggedIn == null} loading={busy} />
          {existing ? <Button label="리뷰 삭제" variant="text" onPress={remove} disabled={busy} /> : null}
        </>
      )}
      <Link href="/account" style={[t.typography.caption, { color: t.colors.accent, textAlign: 'center' }]}>
        계정 관리
      </Link>
    </ScrollView>
  );
}
