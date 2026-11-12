/** 2. 추천결과 (릴스형 RecommendationDeck) — docs/design/screens.md */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, ActivityIndicator, FlatList, LayoutAnimation, Modal, Pressable, ScrollView, Share, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { api, DislikeReason, Evidence, RecommendRequest, RestaurantItem } from '../src/api/client';
import { Button } from '../src/components/Button';
import { RetryButton } from '../src/components/RetryButton';
import { ReviewSheet } from '../src/components/ReviewSheet';
import { GovBudgetBadge, Notice, PercentileBadge, ReasonList, StarRatingBadge, ValueTag } from '../src/components/ui';
import * as store from '../src/state/deviceStore';
import { useTheme } from '../src/theme';
import { genreColor, starHeroColor } from '../src/theme/tokens';
import { MapLinkButtons, mapLinks } from '../src/components/MapLinks';

const RELAX_LABEL: Record<string, string> = { subtype: '세부 메뉴', distance: '거리', mood: '분위기', price: '가격', genre: '장르' };
const EVIDENCE_LABEL: Record<Evidence, string> = { low: '리뷰 근거 적음', mid: '리뷰 근거 보통', high: '리뷰 근거 충분' };
const DISLIKE_REASONS: { value: DislikeReason; label: string }[] = [
  { value: 'far', label: '너무 멀어요' },
  { value: 'price', label: '가격이 맞지 않아요' },
  { value: 'not_into', label: '끌리지 않아요' },
  { value: 'visited', label: '이미 가봤어요' },
];
const RAIL_W = 72;
const END = 'END_OF_DECK';

const SAVE_FAIL = '저장하지 못했어요. 다시 시도해 주세요.';

/** 반응 요청은 id별로 순차 전송(싫어요 → 되돌리기 순서 보장). 실패(429 포함)는 reject. */
const reactChains = new Map<string, Promise<unknown>>();
function sendReaction(deviceId: string, id: string, value: 'like' | 'dislike' | 'none', reason?: DislikeReason): Promise<void> {
  const run = (reactChains.get(id) ?? Promise.resolve()).then(() =>
    api.react({ device_id: deviceId, restaurant_id: id, value, ...(reason ? { reason } : {}) }),
  );
  reactChains.set(id, run.catch(() => undefined));
  return run;
}

// 영업 상태 태그는 영업시간 데이터(D5)가 생기면 추가 — 그전엔 "영업 정보 없음" 반복 노출 대신 숨김

function RelaxedBadge({ relaxed }: { relaxed?: string[] }) {
  const t = useTheme();
  if (!relaxed || !relaxed.length) return null;
  return (
    <View style={{ borderWidth: 1, borderColor: t.colors.border, borderRadius: t.radius.pill, paddingVertical: 1, paddingHorizontal: t.spacing.sm }}>
      <Text style={[t.typography.captionStrong, { color: t.colors.textSecondary }]}>
        {relaxed.map((r) => RELAX_LABEL[r] ?? r).join('/')} 조건 완화됨
      </Text>
    </View>
  );
}

/** 첫 로딩 자리표시 — 카드 배치(별점·배지·이름·메타·이유)를 회색 블록으로 */
function ReelCardSkeleton() {
  const t = useTheme();
  const block = (w: number | `${number}%`, h: number) => <View style={{ width: w, height: h, borderRadius: t.radius.md, backgroundColor: t.colors.surfaceAlt }} />;
  return (
    <View accessible accessibilityLabel="추천을 불러오는 중" style={{ flex: 1, paddingLeft: 20, paddingRight: RAIL_W + 8, paddingTop: 56, gap: t.spacing.md }}>
      {block(96, 64)}
      {block(140, 22)}
      {block('80%', 36)}
      {block('50%', 22)}
      {block('90%', 18)}
      {block('70%', 18)}
    </View>
  );
}

function EmptyResultView({ onBack }: { onBack: () => void }) {
  const t = useTheme();
  return (
    <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', padding: t.spacing.xl, gap: t.spacing.md }}>
      <Text style={[t.typography.heading, { color: t.colors.textPrimary, textAlign: 'center' }]}>조건에 맞는 곳을 찾지 못했어요</Text>
      <Text style={[t.typography.body, { color: t.colors.textSecondary, textAlign: 'center' }]}>조건을 바꿔 다시 찾아볼 수 있어요.</Text>
      <Button label="조건 다시 선택하기" variant="secondary" onPress={onBack} />
    </View>
  );
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

function ReelCard({ item, height, bottomInset, onPress }: { item: RestaurantItem; height: number; bottomInset: number; onPress: () => void }) {
  const t = useTheme();
  const food = item.subtype ?? item.genre;
  const meta = [item.genre, item.price_band, item.distance_m != null ? `${item.distance_m}m` : null].filter(Boolean).join(' · ');
  // 지도 버튼은 카드(버튼) 밖에 둔다 — 버튼 안 버튼은 접근성·웹에서 오류
  // 장 전체(빈 공간 포함) 탭 → 상세(2026-11-12). 바깥은 accessible=false 라 버튼으로 노출되지 않음 — 스크린리더는 안쪽 버튼 사용
  // 상단 노치는 Stack 헤더가 흡수, 56 은 안내(Notice)·페이지 표시 자리. 하단은 홈 인디케이터만큼 더 띄움
  return (
    <Pressable
      onPress={onPress}
      accessible={false}
      style={{ height, paddingLeft: 20, paddingRight: RAIL_W + 8, paddingTop: 56, paddingBottom: 24 + bottomInset }}
    >
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${item.name}, 별점 ${item.star.toFixed(1)}, 이 지역 상위 ${item.percentile}퍼센트. 상세 보기`}
      style={{ flex: 1 }}
    >
      {/* 사진 대신 큰 글씨 히어로(2026-11-12): 위 = 별점(구간 색)·음식(장르 색), 아래 = 이름·이유·배지 */}
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'space-between', gap: t.spacing.xl }}>
        <View style={{ gap: t.spacing.sm }}>
          <Text style={{ fontSize: 96, lineHeight: 104, fontWeight: '700', color: starHeroColor(item.star, t.scheme) }}>{item.star.toFixed(1)}</Text>
          <Text numberOfLines={1} adjustsFontSizeToFit style={{ fontSize: 40, lineHeight: 48, fontWeight: '700', color: genreColor(item.genre, t.scheme) }}>{food}</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
            <StarRatingBadge star={item.star} compact />
            <PercentileBadge percentile={item.percentile} />
          </View>
        </View>
        <View style={{ gap: t.spacing.md }}>
        <Text numberOfLines={2} style={[t.typography.display, { color: t.colors.textPrimary }]}>{item.name}</Text>
        <Text style={[t.typography.body, { color: t.colors.textSecondary }]}>{meta}</Text>
        <ReasonList reasons={item.reasons.slice(0, 3)} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
          {/* 카드 배지 최대 3개: 근거 > 업무추진비 > 완화 > 가성비 (design_system.md 3-2) */}
          {[
            <EvidenceBadge key="ev" item={item} />,
            item.gov_visits > 0 ? <GovBudgetBadge key="gov" visits={item.gov_visits} source={item.gov_source} /> : null,
            item.relaxed?.length ? <RelaxedBadge key="rx" relaxed={item.relaxed} /> : null,
            item.moods.includes('가성비') ? <ValueTag key="val" /> : null,
          ].filter(Boolean).slice(0, 3)}
        </View>
        </View>
      </ScrollView>
    </Pressable>
    <MapLinkButtons name={item.name} compact />
    </Pressable>
  );
}

type IconName = React.ComponentProps<typeof Ionicons>['name'];

function RailButton({ icon, label, a11y, active, onPress }: { icon: IconName; label: string; a11y: string; active?: boolean; onPress: () => void }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11y}
      accessibilityState={active === undefined ? undefined : { selected: active }}
      style={{ minWidth: 48, minHeight: 48, alignItems: 'center', justifyContent: 'center' }}
    >
      <Ionicons name={icon} size={28} color={active ? t.colors.primary : t.colors.textPrimary} />
      <Text style={[t.typography.micro, { color: active ? t.colors.primary : t.colors.textSecondary }]}>{label}</Text>
    </Pressable>
  );
}

function ActionRail({
  item,
  liked,
  bottomInset,
  onLike,
  onDislike,
  onReview,
  onShare,
}: {
  item: RestaurantItem;
  liked: boolean;
  bottomInset: number;
  onLike: () => void;
  onDislike: () => void;
  onReview: () => void;
  onShare: () => void;
}) {
  return (
    <View style={{ position: 'absolute', right: 8, bottom: 32 + bottomInset, width: RAIL_W - 16, alignItems: 'center', gap: 12 }}>
      <RailButton icon={liked ? 'heart' : 'heart-outline'} label={liked ? '좋아요 완료' : '좋아요'} active={liked} onPress={onLike}
        a11y={`${item.name} 좋아요, 현재 ${liked ? '선택됨' : '선택 안 됨'}`} />
      <RailButton icon="close" label="싫어요" onPress={onDislike} a11y={`${item.name} 싫어요, 30일간 숨김`} />
      <RailButton icon="chatbubble-outline" label={item.review_count > 0 ? `리뷰 ${item.review_count}` : '리뷰'} onPress={onReview} a11y={`${item.name} 리뷰 보기`} />
      <RailButton icon="share-outline" label="공유" onPress={onShare} a11y={`${item.name} 공유하기`} />
    </View>
  );
}

function DislikeReasonSheet({ item, onPick, onClose }: { item: RestaurantItem | null; onPick: (reason?: DislikeReason) => void; onClose: () => void }) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={!!item} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityRole="button" accessibilityLabel="닫기" onPress={onClose} style={{ flex: 1, backgroundColor: t.colors.overlay }} />
      <View style={{ backgroundColor: t.colors.background, borderTopLeftRadius: t.radius.lg, borderTopRightRadius: t.radius.lg, padding: t.spacing.lg, paddingBottom: t.spacing.lg + insets.bottom, gap: t.spacing.md }}>
        <View style={{ alignSelf: 'center', width: 36, height: 4, borderRadius: t.radius.pill, backgroundColor: t.colors.border }} />
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

function MessageToast({ text }: { text: string }) {
  const t = useTheme();
  return (
    <View
      accessibilityLiveRegion="polite"
      style={{ position: 'absolute', left: 16, right: 16, bottom: 80, backgroundColor: t.colors.textPrimary, borderRadius: t.radius.md, padding: t.spacing.md }}
    >
      <Text style={[t.typography.body, { color: t.colors.background }]}>{text}</Text>
    </View>
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

const PAGE = 10; // 한 번에 받는 개수
const PREFETCH = 3; // 끝에서 몇 장 앞에서 다음 묶음을 받을지

export default function RecommendationDeck() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { q, fallback } = useLocalSearchParams<{ q: string; fallback?: string }>();
  const [items, setItems] = useState<RestaurantItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const fetched = useRef(0); // 서버에서 받은 개수(싫어요로 화면에서 뺀 것 포함) = 다음 offset
  const loadingMore = useRef(false);
  const baseReq = useRef<RecommendRequest | null>(null);
  const [relaxed, setRelaxed] = useState<string[]>([]);
  const [showRelaxed, setShowRelaxed] = useState(true);
  const [error, setError] = useState(false);
  const [deckH, setDeckH] = useState(0);
  const [page, setPage] = useState(0);
  const [likes, setLikes] = useState<string[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const [dislikeTarget, setDislikeTarget] = useState<RestaurantItem | null>(null);
  const [reviewTarget, setReviewTarget] = useState<RestaurantItem | null>(null);
  const [undo, setUndo] = useState<{ item: RestaurantItem; index: number; prev: 'like' | 'none' } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [hint, setHint] = useState(false);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listRef = useRef<FlatList>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadToken = useRef(0);
  const mounted = useRef(true);
  const likeSeq = useRef(new Map<string, number>());
  const likesRef = useRef<string[]>([]);
  likesRef.current = likes;

  const showToast = (msg: string) => {
    if (!mounted.current) return;
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    const tok = ++loadToken.current;
    const stale = () => tok !== loadToken.current || !mounted.current;
    setError(false);
    setItems(null);
    try {
      const [id, exclude, liked] = await Promise.all([store.getDeviceId(), store.getExcludeIds(), store.getLikes()]);
      if (stale()) return;
      setDeviceId(id);
      setLikes(liked);
      const query = JSON.parse(q) as RecommendRequest;
      // 표시 별점 내림차순으로 끝까지 이어 보기(2026-11-02): PAGE 개씩 받음
      const req: RecommendRequest = { ...query, limit: PAGE, offset: 0, ...(exclude.length ? { exclude_ids: exclude } : {}) };
      baseReq.current = req;
      const res = await api.recommend(req);
      if (stale()) return;
      fetched.current = res.items.length;
      setTotal(res.total ?? res.items.length);
      setItems(res.items);
      setPage(0);
      setRelaxed(res.relaxed);
      store.consumeSwipeHint().then((first) => first && !stale() && res.items.length > 1 && setHint(true));
    } catch {
      if (!stale()) setError(true);
    }
  }, [q]);
  useEffect(() => {
    load();
  }, [load]);

  const loadMore = useCallback(async () => {
    const req = baseReq.current;
    if (!req || loadingMore.current || fetched.current >= total) return;
    loadingMore.current = true;
    const tok = loadToken.current;
    try {
      const res = await api.recommend({ ...req, offset: fetched.current });
      if (tok !== loadToken.current || !mounted.current) return;
      fetched.current += res.items.length;
      if (!res.items.length) fetched.current = total; // 서버 쪽 개수가 줄었으면 끝
      setItems((cur) => {
        const have = new Set((cur ?? []).map((x) => x.id));
        return [...(cur ?? []), ...res.items.filter((x) => !have.has(x.id))];
      });
    } catch {
      showToast('다음 가게를 불러오지 못했어요.');
    } finally {
      loadingMore.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total]);

  // 끝에서 PREFETCH 장 앞에 오면 다음 묶음
  useEffect(() => {
    if (items && page >= items.length - PREFETCH) loadMore();
  }, [page, items, loadMore]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (undoTimer.current) clearTimeout(undoTimer.current);
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  const announceId = items && items[page] ? items[page].id : null;
  useEffect(() => {
    if (!items || !announceId) return;
    const idx = items.findIndex((x) => x.id === announceId);
    if (idx < 0) return;
    AccessibilityInfo.announceForAccessibility(`${idx + 1}번째, 총 ${items.length + Math.max(0, total - fetched.current)}곳, ${items[idx].name}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [announceId]);

  const reactionHint = () =>
    store.consumeReactionHint().then((first) => first && showToast('좋아요·싫어요는 내 추천에만 쓰여요. 별점에는 반영되지 않아요.'), () => undefined);

  const toggleLike = async (item: RestaurantItem) => {
    reactionHint();
    const prev = likesRef.current.includes(item.id);
    const next = !prev;
    const seq = (likeSeq.current.get(item.id) ?? 0) + 1;
    likeSeq.current.set(item.id, seq);
    const apply = (v: boolean) => setLikes((l) => (v ? (l.includes(item.id) ? l : [...l, item.id]) : l.filter((x) => x !== item.id)));
    apply(next);
    try {
      await store.setLiked(item.id, next);
      await sendReaction(deviceId, item.id, next ? 'like' : 'none');
    } catch {
      // 해당 id 의 최신 요청만 반영
      if (likeSeq.current.get(item.id) !== seq) return;
      if (mounted.current) apply(prev);
      store.setLiked(item.id, prev).catch(() => undefined);
      showToast(SAVE_FAIL);
    }
  };

  const confirmDislike = (reason?: DislikeReason) => {
    const target = dislikeTarget;
    setDislikeTarget(null);
    if (!target || !items) return;
    reactionHint(); // 시트가 닫힌 뒤에 보이도록 여기서
    const index = items.findIndex((x) => x.id === target.id);
    const prev: 'like' | 'none' = likesRef.current.includes(target.id) ? 'like' : 'none';
    LayoutAnimation.configureNext(LayoutAnimation.create(t.motion.fast, LayoutAnimation.Types.easeInEaseOut, LayoutAnimation.Properties.opacity));
    setItems(items.filter((x) => x.id !== target.id));
    setPage((p) => Math.min(p, Math.max(items.length - 1, 0)));
    store.hideRestaurant(target.id).catch(() => undefined);
    sendReaction(deviceId, target.id, 'dislike', reason).catch(() => undefined);
    setUndo({ item: target, index, prev });
    if (undoTimer.current) clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setUndo(null), 5000);
  };

  const undoDislike = () => {
    if (!undo) return;
    const { item, index, prev } = undo;
    setUndo(null);
    if (undoTimer.current) clearTimeout(undoTimer.current);
    setItems((cur) => {
      const arr = [...(cur ?? [])];
      arr.splice(Math.min(index, arr.length), 0, item);
      return arr;
    });
    store.unhideRestaurant(item.id).catch(() => undefined);
    // 같은 id 의 싫어요 요청 뒤에 순차 전송, 이전 반응(like/none)으로 복원
    sendReaction(deviceId, item.id, prev).catch(() => undefined);
  };

  const share = (item: RestaurantItem) => {
    const addr = item.address?.trim();
    const link = mapLinks(item.name).kakao.web;
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
  if (!items) return <ReelCardSkeleton />;

  const data: (RestaurantItem | typeof END)[] = [...items, END];
  const hasMore = fetched.current < total;
  const count = items.length + Math.max(0, total - fetched.current); // 화면에서 뺀(싫어요) 곳 제외한 전체
  const onEnd = page >= items.length;
  const current = items[page];
  const a11yLabel = current && !onEnd ? `${page + 1}번째, 총 ${count}곳, ${current.name}` : '마지막 카드';
  const moveBy = (delta: number) => {
    const n = Math.max(0, Math.min(data.length - 1, page + delta));
    listRef.current?.scrollToIndex({ index: n, animated: true });
    setPage(n);
  };

  return (
    <View style={{ flex: 1 }} onLayout={(e) => setDeckH(e.nativeEvent.layout.height)}>
      {deckH > 0 && !items.length ? <EmptyResultView onBack={() => router.back()} /> : null}
      {deckH > 0 && items.length ? (
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
          // 웹은 momentum 이벤트가 없어 스크롤 위치로도 현재 장을 맞춤(같은 값이면 다시 그리지 않음)
          onScroll={(e) => setPage(Math.round(e.nativeEvent.contentOffset.y / deckH))}
          scrollEventThrottle={100}
          onEndReached={loadMore}
          onEndReachedThreshold={PREFETCH}
          renderItem={({ item: d }) =>
            d === END && hasMore ? (
              <View style={[center, { height: deckH, alignItems: 'center' }]}>
                <ActivityIndicator accessibilityLabel="다음 가게를 불러오는 중" />
              </View>
            ) : d === END ? (
              <View style={[center, { height: deckH, alignItems: 'center' }]}>
                <Text style={[t.typography.heading, { color: t.colors.textPrimary, textAlign: 'center' }]}>조건에 맞는 곳을 모두 봤어요</Text>
                <Text style={[t.typography.body, { color: t.colors.textSecondary, textAlign: 'center' }]}>조건을 바꿔 다시 찾아볼 수 있어요.</Text>
                <Button label="조건 다시 선택하기" variant="secondary" onPress={() => router.back()} />
              </View>
            ) : (
              <View>
                <ReelCard item={d} height={deckH} bottomInset={insets.bottom} onPress={() => router.push(`/restaurant/${d.id}`)} />
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

      {items.length ? (
        <View
          accessible
          accessibilityRole="adjustable"
          accessibilityLabel={a11yLabel}
          accessibilityActions={[{ name: 'increment', label: '다음 카드' }, { name: 'decrement', label: '이전 카드' }]}
          onAccessibilityAction={(e) => moveBy(e.nativeEvent.actionName === 'increment' ? 1 : -1)}
          style={{ position: 'absolute', top: 4, right: 8, minWidth: 48, minHeight: 44, alignItems: 'center', justifyContent: 'center' }}
        >
          {!onEnd ? (
            <Text style={[t.typography.captionStrong, { color: t.colors.textSecondary }]}>
              {page + 1}/{count}
            </Text>
          ) : null}
        </View>
      ) : null}

      {current && !onEnd ? (
        <ActionRail
          item={current}
          liked={likes.includes(current.id)}
          bottomInset={insets.bottom}
          onLike={() => toggleLike(current)}
          onDislike={() => setDislikeTarget(current)}
          onReview={() => setReviewTarget(current)}
          onShare={() => share(current)}
        />
      ) : null}

      {hint && !onEnd ? (
        <Pressable onPress={() => setHint(false)} accessibilityRole="button" accessibilityLabel="스와이프 안내 닫기"
          style={{ position: 'absolute', bottom: 8 + insets.bottom, alignSelf: 'center', backgroundColor: t.colors.overlay, borderRadius: t.radius.pill, paddingVertical: t.spacing.xs, paddingHorizontal: t.spacing.md }}>
          <Text style={[t.typography.caption, { color: t.colors.overlayText }]}>↑ 위로 밀어 다음 곳 보기</Text>
        </Pressable>
      ) : null}

      {toast ? <MessageToast text={toast} /> : null}
      {undo ? <UndoToast onUndo={undoDislike} /> : null}
      <DislikeReasonSheet item={dislikeTarget} onPick={confirmDislike} onClose={() => setDislikeTarget(null)} />
      {reviewTarget ? (
        <ReviewSheet visible restaurantId={reviewTarget.id} name={reviewTarget.name} reviewCount={reviewTarget.review_count} onClose={() => setReviewTarget(null)} />
      ) : null}
    </View>
  );
}
