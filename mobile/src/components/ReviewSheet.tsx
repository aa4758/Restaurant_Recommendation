/** ReviewSheet (하단 시트, 읽기 전용) + ReviewSheetEntryButton — docs/design/screens.md 2-4 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { api, ReviewListItem } from '../api/client';
import { Button } from './Button';
import { RetryButton } from './RetryButton';
import { useTheme } from '../theme';

function SponsoredLabel() {
  const t = useTheme();
  return (
    <View
      accessible
      accessibilityLabel="협찬 표시된 리뷰"
      style={{ alignSelf: 'flex-start', backgroundColor: t.colors.surfaceAlt, borderRadius: t.radius.pill, paddingHorizontal: t.spacing.sm, paddingVertical: 2 }}
    >
      <Text style={[t.typography.micro, { color: t.colors.textSecondary }]}>협찬 표시</Text>
    </View>
  );
}

function OnsiteLabel() {
  const t = useTheme();
  return (
    <View style={{ alignSelf: 'flex-start', backgroundColor: t.colors.surfaceAlt, borderRadius: t.radius.pill, paddingHorizontal: t.spacing.sm, paddingVertical: 2 }}>
      <Text style={[t.typography.micro, { color: t.colors.accent }]}>현장 작성</Text>
    </View>
  );
}

function ReviewItem({ r }: { r: ReviewListItem }) {
  const t = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`별점 ${r.stars}점, ${r.text}${r.onsite ? ', 현장 작성' : ''}${r.ad_disclosed ? ', 협찬 표시된 리뷰' : ''}${r.edited ? ', 수정됨' : ''}`}
      style={{ gap: t.spacing.xs, paddingVertical: t.spacing.md, borderBottomWidth: 1, borderBottomColor: t.colors.border }}
    >
      <Text style={[t.typography.bodyStrong, { color: t.colors.textPrimary }]}>★ {r.stars.toFixed(1)}</Text>
      {r.onsite ? <OnsiteLabel /> : null}
      {r.ad_disclosed ? <SponsoredLabel /> : null}
      <Text style={[t.typography.body, { color: t.colors.textPrimary }]}>{r.text}</Text>
      {r.tags.length ? <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>{r.tags.map((x) => `#${x}`).join(' ')}</Text> : null}
      <Text style={[t.typography.caption, { color: t.colors.textDisabled }]}>{(r.created_at || '').slice(0, 10)}{r.edited ? ' · 수정됨' : ''}</Text>
    </View>
  );
}

function Skeleton() {
  const t = useTheme();
  return (
    <View accessibilityLabel="리뷰를 불러오는 중" style={{ gap: t.spacing.md, paddingVertical: t.spacing.md }}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={{ gap: t.spacing.xs }}>
          <View style={{ height: 14, width: 60, borderRadius: 4, backgroundColor: t.colors.surfaceAlt }} />
          <View style={{ height: 14, borderRadius: 4, backgroundColor: t.colors.surfaceAlt }} />
          <View style={{ height: 14, width: '70%', borderRadius: 4, backgroundColor: t.colors.surfaceAlt }} />
        </View>
      ))}
    </View>
  );
}

export function ReviewSheet({
  visible,
  restaurantId,
  name,
  reviewCount,
  onClose,
}: {
  visible: boolean;
  restaurantId: string;
  name: string;
  reviewCount: number;
  onClose: () => void;
}) {
  const t = useTheme();
  const router = useRouter();
  const [items, setItems] = useState<ReviewListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const busy = useRef(false);
  const token = useRef(0); // 요청 토큰: 재오픈/언마운트/가게 변경 시 증가 → 이전 응답 무시

  const load = useCallback(
    async (next: string | null, reset: boolean) => {
      if (reset) {
        token.current += 1;
        busy.current = false;
      } else if (busy.current) return;
      const tok = token.current;
      busy.current = true;
      setLoading(true);
      setError(false);
      try {
        const res = await api.listReviews(restaurantId, next);
        if (tok !== token.current) return;
        setItems((prev) => (reset ? res.items : [...prev, ...res.items]));
        setCursor(res.next_cursor ?? null);
        setLoaded(true);
      } catch {
        if (tok === token.current) setError(true);
      } finally {
        if (tok === token.current) {
          busy.current = false;
          setLoading(false);
        }
      }
    },
    [restaurantId],
  );

  useEffect(() => {
    if (!visible) return;
    setItems([]);
    setCursor(null);
    setLoaded(false);
    load(null, true);
    return () => {
      token.current += 1; // 닫힘/가게 변경/언마운트 시 진행 중 응답 무효화
      busy.current = false;
    };
  }, [visible, load]);

  const total = loaded && !cursor ? items.length : Math.max(reviewCount, items.length);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="리뷰 닫기" accessibilityRole="button" onPress={onClose} style={{ flex: 1, backgroundColor: t.colors.overlay }} />
      <View style={{ height: '70%', backgroundColor: t.colors.background, borderTopLeftRadius: t.radius.lg, borderTopRightRadius: t.radius.lg, padding: t.spacing.lg }}>
        <Text accessibilityRole="header" style={[t.typography.heading, { color: t.colors.textPrimary }]}>
          {name} 리뷰 {total}건
        </Text>
        <View style={{ flex: 1 }}>
          {error && !items.length ? (
            <View style={{ flex: 1, justifyContent: 'center', gap: t.spacing.md }}>
              <Text style={[t.typography.body, { color: t.colors.textPrimary, textAlign: 'center' }]}>리뷰를 불러오지 못했어요.</Text>
              <RetryButton onPress={() => load(null, true)} />
            </View>
          ) : !loaded && loading ? (
            <Skeleton />
          ) : loaded && !items.length ? (
            <View style={{ flex: 1, justifyContent: 'center' }}>
              <Text style={[t.typography.body, { color: t.colors.textSecondary, textAlign: 'center' }]}>아직 리뷰가 없어요. 첫 리뷰를 남겨보세요.</Text>
            </View>
          ) : (
            <FlatList
              data={items}
              keyExtractor={(r) => String(r.id)}
              renderItem={({ item }) => <ReviewItem r={item} />}
              onEndReachedThreshold={0.5}
              onEndReached={() => cursor && load(cursor, false)}
              ListFooterComponent={
                loading ? <ActivityIndicator style={{ margin: t.spacing.md }} /> : error ? <RetryButton onPress={() => load(cursor, false)} /> : null
              }
            />
          )}
        </View>
        <Button
          label="리뷰 쓰기"
          onPress={() => {
            onClose();
            router.push({ pathname: '/review/[id]', params: { id: restaurantId, name } });
          }}
        />
      </View>
    </Modal>
  );
}

/** 상세 화면 진입 버튼 — 누르면 ReviewSheet 를 연다. */
export function ReviewSheetEntryButton({ restaurantId, name, reviewCount }: { restaurantId: string; name: string; reviewCount: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        label={reviewCount > 0 ? `리뷰 보기 (${reviewCount})` : '리뷰 보기'}
        variant="secondary"
        onPress={() => setOpen(true)}
      />
      <ReviewSheet visible={open} restaurantId={restaurantId} name={name} reviewCount={reviewCount} onClose={() => setOpen(false)} />
    </>
  );
}
