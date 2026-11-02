/** 계정 (Account) — docs/design/screens.md. 로그인 상태, 로그아웃, 회원 탈퇴(docs/01 L-7). */
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, Text } from 'react-native';
import { api, ApiError, MeResponse } from '../src/api/client';
import { clearToken, getToken } from '../src/state/authStore';
import { Button } from '../src/components/Button';
import { LoginButtons } from '../src/components/LoginButtons';
import { InlineErrorBanner, Notice } from '../src/components/ui';
import { useTheme } from '../src/theme';

const PROVIDER_LABEL = { kakao: '카카오', google: 'Google' } as const;

export default function AccountScreen() {
  const t = useTheme();
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

  useEffect(() => {
    load();
  }, [load]);

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
    </ScrollView>
  );
}
