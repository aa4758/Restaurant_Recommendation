/** 탭 4. 내 정보 (Account) — docs/design/screens.md. 계정(로그인·로그아웃·탈퇴, docs/01 L-7)·설정·점수 기준 등 정보. */
import React, { useCallback, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, ScrollView, Text, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { api, ApiError, MeResponse } from '../../src/api/client';
import { clearToken, getToken } from '../../src/state/authStore';
import { Button } from '../../src/components/Button';
import { LoginButtons } from '../../src/components/LoginButtons';
import { InlineErrorBanner, Notice } from '../../src/components/ui';
import { useTheme } from '../../src/theme';

// 문의 이메일(앱에 공개됨): EXPO_PUBLIC_CONTACT_EMAIL, 없으면 메뉴 숨김
const CONTACT = process.env.EXPO_PUBLIC_CONTACT_EMAIL?.trim();

const PROVIDER_LABEL = { kakao: '카카오', google: 'Google' } as const;

/** 설정·정보 한 줄(누르면 이동) */
function Row({ label, onPress }: { label: string; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}
      style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: t.spacing.md, borderBottomWidth: 1, borderBottomColor: t.colors.border }}>
      <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{label}</Text>
      <Text style={[t.typography.body, { color: t.colors.textSecondary }]}>›</Text>
    </Pressable>
  );
}

export default function AccountScreen() {
  const t = useTheme();
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const token = await getToken();
    try {
      setMe(token ? await api.me(token) : null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) await clearToken();
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(); // 다른 화면에서 로그인·로그아웃하고 돌아오면 갱신
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

      <Text style={[t.typography.heading, { color: t.colors.textPrimary, marginTop: t.spacing.lg }]}>설정</Text>
      <Row label="위치 권한 설정" onPress={() => Linking.openSettings()} />
      <Text style={[t.typography.heading, { color: t.colors.textPrimary, marginTop: t.spacing.lg }]}>정보</Text>
      <Row label="찐맛 점수는 어떻게 매기나요?" onPress={() => router.push('/scoring')} />
      {CONTACT ? (
        <Row label="정보 오류 신고·문의" onPress={() => Linking.openURL(`mailto:${CONTACT}?subject=${encodeURIComponent('[찐맛] 문의')}`)} />
      ) : null}
    </ScrollView>
  );
}
