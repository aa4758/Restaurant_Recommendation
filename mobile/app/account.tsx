/** 계정 (Account) — docs/design/screens.md. 로그인 상태, 로그아웃, 회원 탈퇴(docs/01 L-7). */
import React, { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { api, ApiError, MeResponse, MyReview } from '../src/api/client';
import { clearToken, getToken } from '../src/state/authStore';
import { Button } from '../src/components/Button';
import { LoginButtons } from '../src/components/LoginButtons';
import { InlineErrorBanner, Notice } from '../src/components/ui';
import { useTheme } from '../src/theme';

const PROVIDER_LABEL = { kakao: '카카오', google: 'Google' } as const;

export default function AccountScreen() {
  const t = useTheme();
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [visited, setVisited] = useState<MyReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const token = await getToken();
    try {
      setMe(token ? await api.me(token) : null);
      setVisited(token ? (await api.myReviews(token)).items : []);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) await clearToken();
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(); // 리뷰 쓰고 돌아오면 목록 갱신
    }, [load]),
  );

  const signOut = async (remove: boolean) => {
    setBusy(true);
    setError(false);
    const token = await getToken();
    try {
      if (token) await (remove ? api.deleteAccount(token) : api.logout(token));
      await clearToken();
      setMe(null);
      setConfirm(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await clearToken();
        setMe(null);
      } else setError(true);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <ActivityIndicator style={{ marginTop: t.spacing.xl }} />;

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      {me ? (
        <>
          <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{PROVIDER_LABEL[me.provider]} 계정으로 로그인했어요.</Text>
          <Text style={[t.typography.heading, { color: t.colors.textPrimary }]}>내가 다녀온 가게 {visited.length}곳</Text>
          {visited.length ? (
            visited.map((v) => (
              <Pressable
                key={v.restaurant_id}
                onPress={() => router.push(`/restaurant/${v.restaurant_id}`)}
                accessibilityRole="button"
                accessibilityLabel={`${v.name}, 내 별점 ${v.stars}점${v.onsite ? ', 현장 작성' : ''}`}
                style={{ paddingVertical: t.spacing.sm, borderBottomWidth: 1, borderBottomColor: t.colors.border, gap: 2 }}
              >
                <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                  <Text style={[t.typography.bodyStrong, { color: t.colors.textPrimary, flex: 1 }]}>{v.name}</Text>
                  <Text style={[t.typography.bodyStrong, { color: t.colors.textPrimary }]}>★ {v.stars.toFixed(1)}</Text>
                </View>
                <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>
                  {(v.updated_at ?? v.created_at).slice(0, 10)}{v.onsite ? ' · 현장 작성' : ''}
                </Text>
              </Pressable>
            ))
          ) : (
            <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>리뷰를 쓰면 여기에 가게가 저장돼요.</Text>
          )}
          <Button label="로그아웃" variant="secondary" onPress={() => signOut(false)} disabled={busy} />
          {confirm ? (
            <>
              <Notice text={'탈퇴하면 계정과 내가 쓴 리뷰가 모두 삭제되고 되돌릴 수 없어요.'} />
              <Button label="탈퇴하기" onPress={() => signOut(true)} loading={busy} />
              <Button label="취소" variant="text" onPress={() => setConfirm(false)} disabled={busy} />
            </>
          ) : (
            <Button label="회원 탈퇴" variant="text" onPress={() => setConfirm(true)} disabled={busy} />
          )}
          {error ? <InlineErrorBanner message="요청에 실패했어요. 다시 시도해 주세요." /> : null}
        </>
      ) : (
        <>
          <Notice text={'로그인은 리뷰를 쓸 때만 필요해요.\n이메일·닉네임은 받지 않아요.'} />
          <LoginButtons onLoggedIn={load} />
        </>
      )}
    </ScrollView>
  );
}
