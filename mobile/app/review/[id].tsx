/** 4. 리뷰작성 (WriteReview) — docs/design/screens.md */
import React, { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { api } from '../../src/api/client';
import { Button } from '../../src/components/Button';
import { FilterChip, InlineErrorBanner, Notice } from '../../src/components/ui';
import { useTheme } from '../../src/theme';

const STEPS = Array.from({ length: 10 }, (_, i) => (i + 1) / 2); // 0.5 ~ 5
const TAGS = ['맛있어요', '가성비', '친절', '조용해요', '양 많아요', '재방문 의사'];
const ANCHORS: [number, string][] = [
  [2.5, '평범'],
  [3.5, '또 올 의향'],
  [4.5, '일부러 찾아올 곳'],
];

function ratingHint(s: number): string {
  const exact = ANCHORS.find(([v]) => v === s);
  if (exact) return `${s} = ${exact[1]}`;
  const lo = [...ANCHORS].reverse().find(([v]) => v < s);
  const hi = ANCHORS.find(([v]) => v > s);
  if (lo && hi) return `${lo[0]}(${lo[1]})와 ${hi[0]}(${hi[1]}) 사이예요`;
  return hi ? `${hi[0]}(${hi[1]})보다 아쉬워요` : `${lo![0]}(${lo![1]}) 이상, 최고예요`;
}

export default function WriteReviewScreen() {
  const t = useTheme();
  const router = useRouter();
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const [stars, setStars] = useState<number | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const submit = async () => {
    if (stars == null) return;
    setBusy(true);
    setError(false);
    try {
      await api.createReview(id, { stars, text, tags });
      router.back();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      {name ? <Text style={[t.typography.heading, { color: t.colors.textPrimary }]}>{name}</Text> : null}
      <Notice text={'이 앱의 별점은 엄격합니다\n2.5 = 평범한 곳이에요\n3.5 = 또 올 의향이 있어요\n4.5 = 일부러 찾아올 곳이에요'} />

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        {STEPS.map((s) => (
          <FilterChip key={s} label={s.toFixed(1)} selected={stars === s} onPress={() => setStars(s)} />
        ))}
      </View>
      {stars != null ? <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>{ratingHint(stars)}</Text> : null}

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs }}>
        {TAGS.map((tag) => (
          <FilterChip
            key={tag}
            label={tag}
            selected={tags.includes(tag)}
            onPress={() => setTags(tags.includes(tag) ? tags.filter((x) => x !== tag) : [...tags, tag])}
          />
        ))}
      </View>
      <TextInput
        value={text}
        onChangeText={setText}
        placeholder="어땠는지 짧게 남겨주세요"
        placeholderTextColor={t.colors.textDisabled}
        multiline
        maxLength={1000}
        style={[t.typography.body, { minHeight: 100, color: t.colors.textPrimary, borderColor: t.colors.border, borderWidth: 1, borderRadius: t.radius.md, padding: t.spacing.md, textAlignVertical: 'top' }]}
      />
      {error ? <InlineErrorBanner message="리뷰 등록에 실패했어요. 다시 시도해 주세요." /> : null}
      <Button label="리뷰 등록하기" onPress={submit} disabled={stars == null} loading={busy} />
    </ScrollView>
  );
}
