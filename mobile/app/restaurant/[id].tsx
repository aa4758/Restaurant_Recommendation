/** 3. 상세 (RestaurantDetail) — docs/design/screens.md */
import React, { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, ScrollView, Text, View } from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { api, RestaurantDetail, ScoreComponents } from '../../src/api/client';
import { Button } from '../../src/components/Button';
import { GovBudgetBadge, InlineErrorBanner, PercentileBadge, ReasonList, StarRatingBadge, ValueTag } from '../../src/components/ui';
import { ReviewSheetEntryButton } from '../../src/components/ReviewSheet';
import { MapLinkButtons } from '../../src/components/MapLinks';
import { useTheme } from '../../src/theme';

function Bar({ label, value, color }: { label: string; value: number; color: string }) {
  const t = useTheme();
  return (
    <View style={{ gap: t.spacing.xxs }}>
      <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>
        {label} {value.toFixed(2)}
      </Text>
      <View style={{ height: 8, backgroundColor: t.colors.surfaceAlt, borderRadius: t.radius.pill }}>
        <View style={{ height: 8, width: `${(value / 5) * 100}%`, backgroundColor: color, borderRadius: t.radius.pill }} />
      </View>
    </View>
  );
}

const COMPONENT_ROWS: { key: keyof ScoreComponents; label: string }[] = [
  { key: 'tenure', label: '업력(영업 연수·백년가게 보정)' },
  { key: 'gov', label: '공공기관 업무추진비 기록' },
  { key: 'hygiene', label: '위생등급' },
  { key: 'designation', label: '지정업소(모범·안심·원산지표시 우수)' },
  { key: 'reputation', label: '외부 평판' },
  { key: 'sanction', label: '행정처분(최근 3년)' },
  { key: 'ad', label: '광고성 리뷰' },
];

function ComponentRow({ label, value }: { label: string; value: number }) {
  const t = useTheme();
  const color = value < 0 ? t.colors.danger : value > 0 ? t.colors.textPrimary : t.colors.textDisabled;
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  // 감점은 색만으로 구분하지 않고 "감점" 라벨 병기
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: t.spacing.sm }}>
      <Text style={[t.typography.caption, { color: t.colors.textSecondary, flexShrink: 1 }]}>
        {value < 0 ? <Text style={[t.typography.captionStrong, { color: t.colors.danger }]}>감점 · </Text> : null}
        {label}
      </Text>
      <Text style={[t.typography.caption, { color }]}>{`${sign}${Math.abs(value).toFixed(2)}`}</Text>
    </View>
  );
}

function LowEvidenceBadge() {
  const t = useTheme();
  return (
    <View
      style={{
        alignSelf: 'flex-start',
        backgroundColor: t.colors.surfaceAlt,
        borderRadius: t.radius.pill,
        paddingHorizontal: t.spacing.sm,
        paddingVertical: t.spacing.xxs,
      }}
    >
      <Text style={[t.typography.caption, { color: t.colors.warning }]}>근거 부족 · 리뷰가 쌓이면 정확해져요</Text>
    </View>
  );
}

export default function RestaurantDetailScreen() {
  const t = useTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [d, setD] = useState<RestaurantDetail | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    api.getRestaurant(id).then(setD, () => setError(true));
  }, [id]);
  useFocusEffect(load); // 리뷰 작성 후 돌아오면 최신 점수 반영

  const report = () =>
    api.reportIssue(id, { field: 'general', message: '앱에서 정보 틀림 신고' }).then(
      () => Alert.alert('신고가 접수됐어요. 확인 후 반영할게요.'),
      () => Alert.alert('신고 접수에 실패했어요. 다시 시도해 주세요.'),
    );

  if (error) return <View style={{ padding: t.spacing.lg }}><InlineErrorBanner message="정보를 불러오지 못했어요." onRetry={load} /></View>;
  if (!d) return <ActivityIndicator style={{ marginTop: t.spacing.xxl }} />;
  const b = d.score_breakdown;
  const text = (s: string) => <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>{s}</Text>;

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      <Text style={[t.typography.title, { color: t.colors.textPrimary }]}>{d.name}</Text>
      {text(`${d.genre} · ${d.price_band} · ${d.alcohol ? '음주 가능' : '비주류'} · ${d.distance_m != null ? `${d.distance_m}m` : '거리 정보 없음'}`)}
      {d.moods.includes('가성비') ? <ValueTag /> : null}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        <StarRatingBadge star={d.star} />
        <PercentileBadge percentile={d.percentile} />
      </View>

      <View style={{ backgroundColor: t.colors.surface, borderRadius: t.radius.lg, padding: t.spacing.lg, gap: t.spacing.sm }}>
        <Text style={[t.typography.heading, { color: t.colors.textPrimary }]}>이 점수는 어떻게 나왔을까요?</Text>
        {b.evidence === 'low' ? <LowEvidenceBadge /> : null}
        <Bar label="사전 점수" value={b.prior_star} color={t.colors.accent} />
        {b.user_mean != null ? <Bar label="방문자 리뷰 평균" value={b.user_mean} color={t.colors.success} /> : null}
        <Bar label="최종 점수" value={d.star} color={t.colors.primary} />
        {text(`사전 점수 ${b.prior_star}점 × ${b.k}건 + 방문자 리뷰 ${b.user_mean ?? '-'}점 × ${b.n}건`)}
        {b.components ? (
          <View style={{ gap: t.spacing.xxs }}>
            {text('사전 점수 구성')}
            {COMPONENT_ROWS.map((row) => (
              <ComponentRow key={row.key} label={row.label} value={b.components![row.key]} />
            ))}
          </View>
        ) : (
          <>
            {b.gov_bonus > 0 ? text(`공공기관 업무추진비 기록 반영: +${b.gov_bonus}`) : null}
            {b.ad_penalty > 0 ? text(`광고성 리뷰 감점: -${b.ad_penalty}`) : null}
          </>
        )}
        <GovBudgetBadge visits={d.gov_visits} source={d.gov_source} />
      </View>

      <ReasonList reasons={d.reasons} />
      {d.review_count === 0 ? text('아직 리뷰가 없어요. 첫 리뷰를 남겨보세요.') : text(`찐맛 리뷰 ${d.review_count}개`)}
      {text(`정보 업데이트: ${d.updated_at || '-'}`)}

      <ReviewSheetEntryButton restaurantId={id} name={d.name} reviewCount={d.review_count} />
      <Button label="리뷰 쓰기" onPress={() => router.push({ pathname: '/review/[id]', params: { id, name: d.name } })} />
      <MapLinkButtons name={d.name} />
      <Button label="정보 틀림 신고하기" variant="text" onPress={report} />
    </ScrollView>
  );
}
