import { Stack, router } from 'expo-router';
import { Pressable, Text } from 'react-native';
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
        <Stack.Screen name="(tabs)" options={{ headerShown: false, title: '찐맛' }} />
        <Stack.Screen
          name="recommendations"
          options={{
            title: '추천 결과',
            // 처음(검색 탭)으로 바로 돌아가기 — 상세·리뷰를 거쳐도 한 번에
            headerRight: () => (
              <Pressable onPress={() => router.dismissTo('/')} accessibilityRole="button" accessibilityLabel="처음 화면으로" hitSlop={12} style={{ paddingHorizontal: t.spacing.md }}>
                <Text style={[t.typography.bodyStrong, { color: t.colors.primary }]}>처음으로</Text>
              </Pressable>
            ),
          }}
        />
        <Stack.Screen name="restaurant/[id]" options={{ title: '상세' }} />
        <Stack.Screen name="review/[id]" options={{ title: '리뷰 쓰기' }} />
        <Stack.Screen name="peers/[id]" options={{ title: '별점순 목록' }} />
        <Stack.Screen name="scoring" options={{ title: '점수 기준' }} />
        <Stack.Screen name="auth" options={{ title: '로그인' }} />
      </Stack>
    </>
  );
}
