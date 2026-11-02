import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useTheme } from '../src/theme';

export default function RootLayout() {
  const t = useTheme();
  return (
    <>
      <StatusBar style={t.scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: t.colors.background },
          headerTintColor: t.colors.textPrimary,
          contentStyle: { backgroundColor: t.colors.background },
        }}
      >
        <Stack.Screen name="index" options={{ title: '찐맛' }} />
        <Stack.Screen name="recommendations" options={{ title: '추천 결과' }} />
        <Stack.Screen name="restaurant/[id]" options={{ title: '상세' }} />
        <Stack.Screen name="review/[id]" options={{ title: '리뷰 쓰기' }} />
        <Stack.Screen name="scoring" options={{ title: '점수 기준' }} />
        <Stack.Screen name="account" options={{ title: '계정' }} />
        <Stack.Screen name="auth" options={{ title: '로그인' }} />
      </Stack>
    </>
  );
}
