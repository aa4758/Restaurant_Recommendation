/** 탭 1. 검색 (Search) — docs/design/screens.md 1. 구글형(2026-11-12): 가운데 앱 이름 + 검색 박스 + 매번 바뀌는 추천 검색어. */
import React, { useMemo, useState } from 'react';
import { KeyboardAvoidingView, Linking, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useFocusEffect, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { api, ParseResponse, Place } from '../../src/api/client';
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
  const [choose, setChoose] = useState<{ f: ParseResponse['filters']; options: Place[] } | null>(null); // 같은 이름 지역 고르기
  const insets = useSafeAreaInsets();
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
      const { filters: f, place_options } = await api.parseFilters(s);
      if (place_options && place_options.length > 1) setChoose({ f, options: place_options });
      else goRecommend(router, loc, f);
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

      {/* 같은 이름 지역이 여럿 → 어느 곳인지 먼저 고르기(2026-11-12) */}
      <Modal visible={!!choose} transparent animationType="slide" onRequestClose={() => setChoose(null)}>
        <Pressable accessibilityRole="button" accessibilityLabel="닫기" onPress={() => setChoose(null)} style={{ flex: 1, backgroundColor: t.colors.overlay }} />
        <View style={{ backgroundColor: t.colors.background, borderTopLeftRadius: t.radius.lg, borderTopRightRadius: t.radius.lg,
          padding: t.spacing.lg, paddingBottom: t.spacing.lg + insets.bottom, gap: t.spacing.sm }}>
          <View style={{ alignSelf: 'center', width: 36, height: 4, borderRadius: t.radius.pill, backgroundColor: t.colors.border }} />
          <Text accessibilityRole="header" style={[t.typography.heading, { color: t.colors.textPrimary }]}>
            어느 {choose?.options[0].kind === 'landmark' ? '곳' : '지역'}인가요?
          </Text>
          <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>같은 이름이 여러 곳에 있어요.</Text>
          {choose?.options.map((o) => (
            <Pressable
              key={o.label}
              accessibilityRole="button"
              accessibilityLabel={`${o.label} 주변 추천받기`}
              onPress={() => { const p = choose!; setChoose(null); goRecommend(router, loc, { ...p.f, place: o }); }}
              style={{ minHeight: 48, justifyContent: 'center', paddingHorizontal: t.spacing.md, backgroundColor: t.colors.surface, borderRadius: t.radius.lg }}
            >
              <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{o.label}</Text>
            </Pressable>
          ))}
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}
