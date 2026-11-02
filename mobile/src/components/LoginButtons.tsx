/** 소셜 로그인 버튼(카카오·구글) — docs/design/screens.md 'LoginButtons'. 브랜드 스타일은 디자인 단계에서. */
import React, { useState } from 'react';
import { View } from 'react-native';
import { AuthProvider } from '../api/client';
import { login } from '../state/authStore';
import { Button } from './Button';
import { InlineErrorBanner } from './ui';
import { useTheme } from '../theme';

export function LoginButtons({ onLoggedIn }: { onLoggedIn: () => void }) {
  const t = useTheme();
  const [busy, setBusy] = useState<AuthProvider | null>(null);
  const [error, setError] = useState(false);

  const run = async (p: AuthProvider) => {
    setBusy(p);
    setError(false);
    const r = await login(p).catch(() => 'failed' as const);
    setBusy(null);
    if (r === 'ok') onLoggedIn();
    else if (r === 'failed') setError(true);
  };

  return (
    <View style={{ gap: t.spacing.sm }}>
      <Button label="카카오로 로그인" onPress={() => run('kakao')} loading={busy === 'kakao'} disabled={busy != null} />
      <Button label="Google로 로그인" variant="secondary" onPress={() => run('google')} loading={busy === 'google'} disabled={busy != null} />
      {error ? <InlineErrorBanner message="로그인에 실패했어요. 다시 시도해 주세요." /> : null}
    </View>
  );
}
