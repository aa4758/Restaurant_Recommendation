/** 탭 1. 검색 (Search) — docs/design/screens.md 1. 구글형(2026-11-12): 가운데 앱 이름 + 검색 박스 + 매번 바뀌는 추천 검색어. */
import React, { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api } from '../../src/api/client';
import { goRecommend } from '../../src/goRecommend';
import { useLocation } from '../../src/state/useLocation';
import { Button } from '../../src/components/Button';
import { FilterChip, InlineErrorBanner, Notice } from '../../src/components/ui';
import { useTheme } from '../../src/theme';

// 규칙 해석기(nlparse)가 알아듣는 표현만. "술 안 마셔"류는 음주 불가 숨김(2026-11-12)이라 넣지 않음.
const SUGGESTIONS = [
  '근처 만원 이하 국밥', '도보 10분 회식하기 좋은 고깃집', '혼밥하기 좋은 라멘', '조용한 한정식',
  '데이트하기 좋은 파스타', '2만원대 초밥', '가성비 좋은 김치찌개', '노포 냉면', '얼큰한 짬뽕',
  '소주 한잔하기 좋은 곱창', '만원 이하 칼국수', '혼밥 돈가스', '회식 삼겹살', '맥주랑 치킨',
  '조용한 카페', '근처 쌀국수', '노포 순대국', '데이트 스테이크', '도보 5분 분식', '가성비 뷔페',
  '해장하기 좋은 곳', '혼밥 덮밥', '회식하기 좋은 횟집', '막걸리랑 전', '근처 떡볶이',
];
const SHOW = 2;

const pick = <T,>(list: T[], n: number) => [...list].sort(() => Math.random() - 0.5).slice(0, n);

export default function SearchScreen() {
  const t = useTheme();
  const router = useRouter();
  const loc = useLocation();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [seed, setSeed] = useState(0);
  // 화면에 돌아올 때마다 다른 추천 검색어
  useFocusEffect(React.useCallback(() => setSeed((s) => s + 1), []));
  const suggestions = useMemo(() => pick(SUGGESTIONS, SHOW), [seed]);

  // 문장 → 조건(규칙 기반 해석) → 추천. 못 알아들은 낱말은 적용 안 함.
  const search = async (q: string = text) => {
    const s = q.trim();
    if (!s) return goRecommend(router, loc, {});
    setBusy(true);
    setError(false);
    try {
      const { filters: f } = await api.parseFilters(s);
      goRecommend(router, loc, f);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: t.spacing.lg, gap: t.spacing.lg }} keyboardShouldPersistTaps="handled">
        <Text accessibilityRole="header" style={{ fontSize: 56, lineHeight: 64, fontWeight: '700', textAlign: 'center', color: t.colors.primary }}>찐맛</Text>
        <Text style={[t.typography.body, { textAlign: 'center', color: t.colors.textSecondary, marginTop: -t.spacing.md }]}>지금 이 근처, 진짜 맛집만</Text>

        <View style={{ flexDirection: 'row', alignItems: 'center', borderColor: t.colors.border, borderWidth: 1, borderRadius: t.radius.pill,
          backgroundColor: t.colors.surface, paddingLeft: t.spacing.lg, paddingRight: t.spacing.xs, ...t.elevation.sm }}>
          <Ionicons name="search" size={20} color={t.colors.textSecondary} />
          <TextInput
            value={text}
            onChangeText={setText}
            onSubmitEditing={() => search()}
            placeholder="어떤 맛집을 찾으세요?"
            placeholderTextColor={t.colors.textPlaceholder}
            maxLength={200}
            returnKeyType="search"
            accessibilityLabel="원하는 조건을 문장으로 입력"
            style={[t.typography.body, { flex: 1, minHeight: 52, paddingHorizontal: t.spacing.sm, color: t.colors.textPrimary }]}
          />
          {text ? (
            <Pressable onPress={() => setText('')} accessibilityRole="button" accessibilityLabel="입력 지우기" hitSlop={8}
              style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="close-circle" size={20} color={t.colors.textSecondary} />
            </Pressable>
          ) : null}
        </View>

        <View style={{ flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: t.spacing.xs }}>
          {suggestions.map((e) => (
            <FilterChip key={e} label={e} selected={false} onPress={() => { setText(e); search(e); }} />
          ))}
        </View>

        {error ? <InlineErrorBanner message="문장을 해석하지 못했어요. 필터 탭에서 골라 주세요." /> : null}
        <Button label={text.trim() ? '추천받기' : '조건 없이 추천받기'} onPress={() => search()} loading={busy || loc.isLoading} />

        {loc.isFallback ? (
          <View style={{ gap: t.spacing.sm }}>
            <Notice text="위치 권한이 꺼져 있어요. 허용하면 더 정확한 추천을 드릴 수 있어요." />
            <Button label="설정에서 허용하기" variant="text" onPress={() => Linking.openSettings()} />
          </View>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
