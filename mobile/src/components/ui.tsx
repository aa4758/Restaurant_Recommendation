/** screens.md 공통 컴포넌트 (이름은 스펙 그대로). */
import React from 'react';
import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme';
import { RetryButton } from './RetryButton';

export function FilterChip({
  label,
  selected,
  disabled,
  onPress,
}: {
  label: string;
  selected: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={{
        backgroundColor: selected ? t.colors.chipBgSelected : t.colors.chipBg,
        borderRadius: t.radius.pill,
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: t.spacing.xs,
        paddingHorizontal: t.spacing.md,
        opacity: disabled ? 0.4 : 1,
      }}
    >
      {/* 선택을 색만으로 구분하지 않음 */}
      {selected ? <Ionicons name="checkmark" size={16} color={t.colors.chipTextSelected} /> : null}
      <Text style={[t.typography.caption, { color: selected ? t.colors.chipTextSelected : t.colors.chipText }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function FilterChipGroup({
  title,
  options,
  selected,
  onToggle,
  disabled,
  hint,
}: {
  title: string;
  options: { value: string; label: string }[];
  selected: string[];
  onToggle: (value: string) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const t = useTheme();
  return (
    <View style={{ marginBottom: t.spacing.lg }}>
      <Text style={[t.typography.bodyStrong, { color: t.colors.textPrimary, marginBottom: t.spacing.sm }]}>
        {title}
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.sm }}>
        {options.map((o) => (
          <FilterChip
            key={o.value}
            label={o.label}
            selected={selected.includes(o.value)}
            disabled={disabled}
            onPress={() => onToggle(o.value)}
          />
        ))}
      </View>
      {hint ? (
        <Text style={[t.typography.caption, { color: t.colors.textSecondary, marginTop: t.spacing.xs }]}>{hint}</Text>
      ) : null}
    </View>
  );
}

function Pill({ text, bg, fg }: { text: string; bg: string; fg: string }) {
  const t = useTheme();
  return (
    <View style={{ backgroundColor: bg, borderRadius: t.radius.pill, paddingVertical: 2, paddingHorizontal: t.spacing.sm }}>
      <Text style={[t.typography.captionStrong, { color: fg }]}>{text}</Text>
    </View>
  );
}

/** compact: 큰 별점 숫자 바로 아래(릴스 카드)에서는 구간 라벨만 — 숫자 중복 방지 */
export function StarRatingBadge({ star, compact }: { star: number; compact?: boolean }) {
  const t = useTheme();
  const band = t.getStarBand(star);
  return <Pill text={compact ? band.label : `★ ${star.toFixed(1)} · ${band.label}`} bg={t.colors.surfaceAlt} fg={t.colors[band.colorKey]} />;
}

/** 윤곽 태그(중립색) — 기본은 착한가격업소 '가성비'(점수 무관이라 별점 옆이 아닌 메타 줄 아래). 지정목록 태그도 같은 모양 */
export function ValueTag({ label = '가성비' }: { label?: string }) {
  const t = useTheme();
  return (
    <View style={{ alignSelf: 'flex-start', borderWidth: 1, borderColor: t.colors.border, borderRadius: t.radius.pill, paddingVertical: 1, paddingHorizontal: t.spacing.sm }}>
      <Text style={[t.typography.captionStrong, { color: t.colors.textSecondary }]}>{label}</Text>
    </View>
  );
}

export function PercentileBadge({ percentile }: { percentile: number }) {
  const t = useTheme();
  return <Pill text={`이 지역 상위 ${percentile}%`} bg={t.colors.surfaceAlt} fg={t.colors.textSecondary} />;
}

/** 문구 규칙: "공직자 맛집" 등 표현 금지. gov_source 는 백엔드에서 "출처·기준연도" 형태로 옴. */
/** compact = 릴스 카드 줄임말(2026-11-12). 전체 문구·출처는 상세에서. "인증" 표현 금지(기관 보증 아님) */
export function GovBudgetBadge({ visits, source, compact }: { visits: number; source?: string | null; compact?: boolean }) {
  const t = useTheme();
  if (visits <= 0) return null;
  const full = `공공기관 업무추진비 기록 ${visits}회${source ? ` (${source} 기준)` : ''}`;
  return (
    <View accessible accessibilityLabel={full}>
      <Pill text={compact ? `업무추진비 ${visits}회` : full} bg={t.colors.govBadgeBg} fg={t.colors.govBadgeText} />
    </View>
  );
}

export function ReasonList({ reasons }: { reasons: string[] }) {
  const t = useTheme();
  return (
    <View style={{ gap: t.spacing.xxs }}>
      {reasons.map((r) => (
        <Text key={r} style={[t.typography.caption, { color: t.colors.textSecondary }]}>
          · {r}
        </Text>
      ))}
    </View>
  );
}

export function InlineErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const t = useTheme();
  return (
    <View style={{ backgroundColor: t.colors.adPenaltyBg, borderRadius: t.radius.md, padding: t.spacing.md, gap: t.spacing.sm }}>
      <Text style={[t.typography.body, { color: t.colors.adPenaltyText }]}>{message}</Text>
      {onRetry ? <RetryButton onPress={onRetry} /> : null}
    </View>
  );
}

export function Notice({ text }: { text: string }) {
  const t = useTheme();
  return (
    <View style={{ backgroundColor: t.colors.surface, borderRadius: t.radius.md, padding: t.spacing.md }}>
      <Text style={[t.typography.caption, { color: t.colors.textSecondary }]}>{text}</Text>
    </View>
  );
}
