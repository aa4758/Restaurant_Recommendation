/** 2. 추천결과 (릴스형 RecommendationDeck) — docs/design/screens.md */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Modal, Pressable, ScrollView, Share, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { api, DislikeReason, Evidence, RecommendRequest, RestaurantItem } from '../src/api/client';
import { Button } from '../src/components/Button';
import { RetryButton } from '../src/components/RetryButton';
import { ReviewSheet } from '../src/components/ReviewSheet';
import { GovBudgetBadge, Notice, PercentileBadge, ReasonList, StarRatingBadge } from '../src/components/ui';
import * as store from '../src/state/deviceStore';
import { useTheme } from '../src/theme';

const RELAX_LABEL: Record<string, string> = { distance: '거리', mood: '분위기', price: '가격', genre: '장르' };
const EVIDENCE_LABEL: Record<Evidence, string> = { low: '리뷰 근거 적음', mid: '리뷰 근거 보통', high: '리뷰 근거 충분' };
const DISLIKE_REASONS: { value: DislikeReason; label: string }[] = [
  { value: 'far', label: '너무 멀어요' },
  { value: 'price', label: '가격이 맞지 않아요' },
  { value: 'not_into', label: '끌리지 않아요' },
  { value: 'visited', label: '이미 가봤어요' },
];
const RAIL_W = 72;
const END = 'END_OF_DECK';

/** 서버 기록은 best-effort: 실패해도 로컬 상태 유지, 429 는 무시. */
function sendReaction(deviceId: string, id: string, value: 'like' | 'dislike' | 'none', reason?: DislikeReason) {
  api.react({ device_id: deviceId, restaurant_id: id, value, ...(reason ? { reason } : {}) }).catch(() => undefined);
}

function EvidenceBadge({ item }: { item: RestaurantItem }) {
  const t = useTheme();
  const text = item.evidence ? EVIDENCE_LABEL[item.evidence] : `리뷰 ${item.review_count}건`;
  return (
    <View style={{ backgroundColor: t.colors.surfaceAlt, borderRadius: t.radius.pill, paddingVertical: 2, paddingHorizontal: t.spacing.sm }}>
      <Text style={[t.typography.captionStrong, { color: t.colors.textSecondary }]}>{text}</Text>
    </View>
  );
}

function ReelCard({ item, height, relaxed, onPress }: { item: RestaurantItem; height: number; relaxed: string[]; onPress: () => void }) {
  const t = useTheme();
  const band = t.getStarBand(item.star);
  const meta = [item.genre, item.price_band, item.distance_m != null ? `${item.distance_m}m` : null].filter(Boolean).join(' · ');
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${item.name}, 별점 ${item.star.toFixed(1)}, 이 지역 상위 ${item.percentile}퍼센트. 상세 보기`}
      style={{ height, paddingLeft: 20, paddingRight: RAIL_W + 8, paddingTop: 56, paddingBottom: 24 }}
    >
      {/* TODO: OpenStatusTag — 영업 상태 데이터가 API 에 생기면 렌더 */}
      <ScrollView contentContainerStyle={{ gap: t.spacing.md }}>
        <Text style={{ fontSize: 56, lineHeight: 64, fontWeight: '700', color: t.colors[band.colorKey] }}>{item.star.toFixed(1)}</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
          <StarRatingBadge star={item.star} />
          <PercentileBadge percentile={item.percentile} />
        </View>
        <Text numberOfLines={2} style={[t.typography.display, { color: t.colors.textPrimary }]}>{item.name}</Text>
        <Text style={[t.typography.body, { color: t.colors.textSecondary }]}>{meta}</Text>
        <ReasonList reasons={item.reasons.slice(0, 3)} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
          <EvidenceBadge item={item} />
          <GovBudgetBadge visits={item.gov_visits} source={item.gov_source} />
          {relaxed.length ? (
            <Text style={[t.typography.captionStrong, { color: t.colors.textSecondary }]}>
              {relaxed.map((r) => RELAX_LABEL[r] ?? r).join('/')} 조건 완화됨
            </Text>
          ) : null}
        </View>
      </ScrollView>
    </Pressable>
  );
}

function RailButton({ icon, label, a11y, active, onPress }: { icon: string; label: string; a11y: string; active?: boolean; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11y}
      accessibilityState={active === undefined ? undefined : { selected: active }}
      style={{ minWidth: 48, minHeight: 48, alignItems: 'center', justifyContent: 'center' }}
    >
      <Text style={{ fontSize: 28, color: active ? t.colors.primary : t.colors.textPrimary }}>{icon}</Text>
      <Text style={[t.typography.micro, { color: active ? t.colors.primary : t.colors.textSecondary }]}>{label}</Text>
    </Pressable>
  );
}

function ActionRail({
  item,
  liked,
  onLike,
  onDislike,
  onReview,
  onShare,
}: {
  item: RestaurantItem;
  liked: boolean;
  onLike: () => void;
  onDislike: () => void;
  onReview: () => void;
  onShare: () => void;
}) {
  return (
    <View style={{ position: 'absolute', right: 8, bottom: 32, width: RAIL_W - 16, alignItems: 'center', gap: 12 }}>
      <RailButton icon={liked ? '♥' : '♡'} label={liked ? '좋아요 완료' : '좋아요'} active={liked} onPress={onLike}
        a11y={`${item.name} 좋아요, 현재 ${liked ? '선택됨' : '선택 안 됨'}`} />
      <RailButton icon="✕" label="싫어요" onPress={onDislike} a11y={`${item.name} 싫어요, 30일간 숨김`} />
      <RailButton icon="✎" label={item.review_count > 0 ? `리뷰 ${item.review_count}` : '리뷰'} onPress={onReview} a11y={`${item.name} 리뷰 보기`} />
      <RailButton icon="↗" label="공유" onPress={onShare} a11y={`${item.name} 공유하기`} />
    </View>
  );
}

function DislikeReasonSheet({ item, onPick, onClose }: { item: RestaurantItem | null; onPick: (reason?: DislikeReason) => void; onClose: () => void }) {
  const t = useTheme();
  return (
    <Modal visible={!!item} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityRole="button" accessibilityLabel="닫기" onPress={onClose} style={{ flex: 1, backgroundColor: t.colors.overlay }} />
      <View style={{ backgroundColor: t.colors.background, borderTopLeftRadius: t.radius.lg, borderTopRightRadius: t.radius.lg, padding: t.spacing.lg, gap: t.spacing.md }}>
        <Text accessibilityRole="header" style={[t.typography.heading, { color: t.colors.textPrimary }]}>어떤 점이 아쉬웠나요?</Text>
        <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>이 가게는 30일간 추천에서 숨겨요.</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.sm }}>
          {DISLIKE_REASONS.map((r) => (
            <Pressable
              key={r.value}
              accessibilityRole="button"
              accessibilityLabel={r.label}
              onPress={() => onPick(r.value)}
              style={{ backgroundColor: t.colors.chipBg, borderRadius: t.radius.pill, paddingVertical: t.spacing.sm, paddingHorizontal: t.spacing.md, minHeight: 44, justifyContent: 'center' }}
            >
              <Text style={[t.typography.body, { color: t.colors.chipText }]}>{r.label}</Text>
            </Pressable>
          ))}
        </View>
        <Button label="건너뛰기" variant="text" onPress={() => onPick(undefined)} />
      </View>
    </Modal>
  );
}

function UndoToast({ onUndo }: { onUndo: () => void }) {
  const t = useTheme();
  return (
    <View
      accessibilityLiveRegion="polite"
      style={{ position: 'absolute', left: 16, right: 16, bottom: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: t.colors.textPrimary, borderRadius: t.radius.md, padding: t.spacing.md }}
    >
      <Text style={[t.typography.body, { color: t.colors.background }]}>30일간 숨겼어요</Text>
      <Pressable onPress={onUndo} accessibilityRole="button" accessibilityLabel="숨김 되돌리기" style={{ minHeight: 44, justifyContent: 'center', paddingHorizontal: t.spacing.sm }}>
        <Text style={[t.typography.bodyStrong, { color: t.colors.primary }]}>되돌리기</Text>
      </Pressable>
    </View>
  );
}

export default function RecommendationDeck() {
  const t = useTheme();
  const router = useRouter();
  const { q, fallback } = useLocalSearchParams<{ q: string; fallback?: string }>();
  const [items, setItems] = useState<RestaurantItem[] | null>(null);
  const [relaxed, setRelaxed] = useState<string[]>([]);
  const [showRelaxed, setShowRelaxed] = useState(true);
  const [error, setError] = useState(false);
  const [deckH, setDeckH] = useState(0);
  const [page, setPage] = useState(0);
  const [likes, setLikes] = useState<string[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const [dislikeTarget, setDislikeTarget] = useState<RestaurantItem | null>(null);
  const [reviewTarget, setReviewTarget] = useState<RestaurantItem | null>(null);
  const [undo, setUndo] = useState<{ item: RestaurantItem; index: number } | null>(null);
  const [hint, setHint] = useState(false);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listRef = useRef<FlatList>(null);

  const load = useCallback(async () => {
    setError(false);
    setItems(null);
    try {
      const [id, exclude, liked] = await Promise.all([store.getDeviceId(), store.getExcludeIds(), store.getLikes()]);
      setDeviceId(id);
      setLikes(liked);
      const req: RecommendRequest = { ...JSON.parse(q), limit: 5, ...(exclude.length ? { exclude_ids: exclude } : {}) };
      const res = await api.recommend(req);
      setItems(res.items.slice(0, 5));
      setRelaxed(res.relaxed);
      store.consumeSwipeHint().then((first) => first && res.items.length > 1 && setHint(true));
    } catch {
      setError(true);
    }
  }, [q]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => () => { if (undoTimer.current) clearTimeout(undoTimer.current); }, []);

  const toggleLike = (item: RestaurantItem) => {
    const next = !likes.includes(item.id);
    setLikes((l) => (next ? [...l, item.id] : l.filter((x) => x !== item.id)));
    store.setLiked(item.id, next);
    sendReaction(deviceId, item.id, next ? 'like' : 'none');
  };

  const confirmDislike = (reason?: DislikeReason) => {
    const target = dislikeTarget;
    setDislikeTarget(null);
    if (!target || !items) return;
    const index = items.findIndex((x) => x.id === target.id);
    setItems(items.filter((x) => x.id !== target.id));
    setPage((p) => Math.min(p, Math.max(items.length - 1, 0)));
    store.hideRestaurant(target.id);
    sendReaction(deviceId, target.id, 'dislike', reason);
    setUndo({ item: target, index });
    if (undoTimer.current) clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setUndo(null), 5000);
  };

  const undoDislike = () => {
    if (!undo) return;
    const { item, index } = undo;
    setUndo(null);
    if (undoTimer.current) clearTimeout(undoTimer.current);
    setItems((cur) => {
      const arr = [...(cur ?? [])];
      arr.splice(Math.min(index, arr.length), 0, item);
      return arr;
    });
    store.unhideRestaurant(item.id);
    sendReaction(deviceId, item.id, 'none');
  };

  const share = (item: RestaurantItem) => {
    const addr = item.address?.trim();
    const link = `https://map.kakao.com/?q=${encodeURIComponent(addr ? `${item.name} ${addr}` : item.name)}`;
    const lines = [`[찐맛] ${item.name}`, `★ ${item.star.toFixed(1)} · 이 지역 상위 ${item.percentile}%`];
    if (addr) lines.push(addr);
    if (item.reasons[0]) lines.push(item.reasons[0]);
    lines.push(`지도에서 보기: ${link}`);
    Share.share({ message: lines.join('\n') }).catch(() => undefined);
  };

  const center = { flex: 1, justifyContent: 'center' as const, padding: t.spacing.xl, gap: t.spacing.md };
  if (error) {
    return (
      <View style={center}>
        <Text style={[t.typography.body, { color: t.colors.textPrimary, textAlign: 'center' }]}>추천을 불러오는 중 문제가 생겼어요.</Text>
        <RetryButton onPress={load} />
      </View>
    );
  }
  if (!items) return <ActivityIndicator accessibilityLabel="추천을 불러오는 중" style={{ marginTop: t.spacing.xxl }} />;

  const data: (RestaurantItem | typeof END)[] = [...items, END];
  const onEnd = page >= items.length;
  const current = items[page];

  return (
    <View style={{ flex: 1 }} onLayout={(e) => setDeckH(e.nativeEvent.layout.height)}>
      {deckH > 0 ? (
        <FlatList
          ref={listRef}
          data={data}
          keyExtractor={(d) => (d === END ? END : d.id)}
          pagingEnabled
          showsVerticalScrollIndicator={false}
          getItemLayout={(_, i) => ({ length: deckH, offset: deckH * i, index: i })}
          onMomentumScrollEnd={(e) => {
            setPage(Math.round(e.nativeEvent.contentOffset.y / deckH));
            setHint(false);
          }}
          accessibilityActions={[{ name: 'increment', label: '다음 카드' }, { name: 'decrement', label: '이전 카드' }]}
          onAccessibilityAction={(e) => {
            const n = Math.max(0, Math.min(data.length - 1, page + (e.nativeEvent.actionName === 'increment' ? 1 : -1)));
            listRef.current?.scrollToIndex({ index: n, animated: true });
            setPage(n);
          }}
          renderItem={({ item: d, index }) =>
            d === END ? (
              <View style={[center, { height: deckH, alignItems: 'center' }]}>
                <Text style={[t.typography.heading, { color: t.colors.textPrimary, textAlign: 'center' }]}>오늘의 추천은 여기까지예요</Text>
                <Text style={[t.typography.body, { color: t.colors.textSecondary, textAlign: 'center' }]}>조건을 바꿔 다시 찾아볼 수 있어요.</Text>
                <Button label="조건 다시 선택하기" variant="secondary" onPress={() => router.back()} />
              </View>
            ) : (
              <View accessible={false} accessibilityLabel={`${index + 1}번째, 총 ${items.length}곳, ${d.name}`}>
                <ReelCard item={d} height={deckH} relaxed={relaxed} onPress={() => router.push(`/restaurant/${d.id}`)} />
              </View>
            )
          }
        />
      ) : null}

      <View pointerEvents="box-none" style={{ position: 'absolute', top: 8, left: 16, right: 16, gap: t.spacing.xs }}>
        {fallback ? <Notice text="위치 정보 없이 추천 중이에요." /> : null}
        {relaxed.length && showRelaxed ? (
          <Pressable accessibilityRole="button" accessibilityLabel="조건 완화 안내 닫기" onPress={() => setShowRelaxed(false)}>
            <Notice text={`조건에 맞는 곳이 적어 ${relaxed.map((r) => RELAX_LABEL[r] ?? r).join('/')} 조건을 완화했어요. (탭하여 닫기)`} />
          </Pressable>
        ) : null}
      </View>

      {!onEnd && items.length ? (
        <Text accessibilityLabel={`${page + 1}번째, 총 ${items.length}곳`} style={[t.typography.captionStrong, { position: 'absolute', top: 12, right: 16, color: t.colors.textSecondary }]}>
          {page + 1}/{items.length}
        </Text>
      ) : null}

      {current && !onEnd ? (
        <ActionRail
          item={current}
          liked={likes.includes(current.id)}
          onLike={() => toggleLike(current)}
          onDislike={() => setDislikeTarget(current)}
          onReview={() => setReviewTarget(current)}
          onShare={() => share(current)}
        />
      ) : null}

      {hint && !onEnd ? (
        <Pressable onPress={() => setHint(false)} accessibilityRole="button" accessibilityLabel="스와이프 안내 닫기"
          style={{ position: 'absolute', bottom: 8, alignSelf: 'center', backgroundColor: t.colors.overlay, borderRadius: t.radius.pill, paddingVertical: t.spacing.xs, paddingHorizontal: t.spacing.md }}>
          <Text style={[t.typography.caption, { color: '#FFFFFF' }]}>↑ 위로 밀어 다음 곳 보기</Text>
        </Pressable>
      ) : null}

      {undo ? <UndoToast onUndo={undoDislike} /> : null}
      <DislikeReasonSheet item={dislikeTarget} onPick={confirmDislike} onClose={() => setDislikeTarget(null)} />
      {reviewTarget ? (
        <ReviewSheet visible restaurantId={reviewTarget.id} name={reviewTarget.name} reviewCount={reviewTarget.review_count} onClose={() => setReviewTarget(null)} />
      ) : null}
    </View>
  );
}
