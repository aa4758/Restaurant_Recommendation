/** 탭 1. 검색 (Search) — docs/design/screens.md 1. 문장 하나로 조건을 말하면 바로 추천. */
import React, { useState } from 'react';
import { Linking, ScrollView, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';
import { api } from '../../src/api/client';
import { goRecommend } from '../../src/goRecommend';
import { useLocation } from '../../src/state/useLocation';
import { Button } from '../../src/components/Button';
import { FilterChip, InlineErrorBanner, Notice } from '../../src/components/ui';
import { useTheme } from '../../src/theme';

const EXAMPLES = ['근처 만원 이하 국밥', '도보 10분 회식하기 좋은 고깃집', '혼밥하기 좋은 라멘', '술 없이 조용한 한정식'];

export default function SearchScreen() {
  const t = useTheme();
  const router = useRouter();
  const loc = useLocation();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

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
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }} keyboardShouldPersistTaps="handled">
      {loc.isFallback ? (
        <View style={{ gap: t.spacing.sm }}>
          <Notice text="위치 권한이 꺼져 있어요. 허용하면 더 정확한 추천을 드릴 수 있어요." />
          <Button label="설정에서 허용하기" variant="text" onPress={() => Linking.openSettings()} />
        </View>
      ) : null}
      <Text style={[t.typography.title, { color: t.colors.textPrimary }]}>지금 이 근처, 진짜 맛집만</Text>
      <TextInput
        value={text}
        onChangeText={setText}
        onSubmitEditing={() => search()}
        placeholder="예) 근처 만원 이하 국밥, 혼밥하기 좋고 술은 안 마셔요"
        placeholderTextColor={t.colors.textDisabled}
        maxLength={200}
        returnKeyType="search"
        accessibilityLabel="원하는 조건을 문장으로 입력"
        style={[t.typography.body, { color: t.colors.textPrimary, borderColor: t.colors.border, borderWidth: 1, borderRadius: t.radius.md, padding: t.spacing.md }]}
      />
      {error ? <InlineErrorBanner message="문장을 해석하지 못했어요. 필터 탭에서 골라 주세요." /> : null}
      <Button label={text.trim() ? '추천받기' : '조건 없이 추천받기'} onPress={() => search()} loading={busy || loc.isLoading} />
      <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>이렇게 물어보세요</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        {EXAMPLES.map((e) => (
          <FilterChip key={e} label={e} selected={false} onPress={() => { setText(e); search(e); }} />
        ))}
      </View>
    </ScrollView>
  );
}
