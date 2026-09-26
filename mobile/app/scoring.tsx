/** 5. 점수기준 설명 (ScoringExplainer) — 정적 콘텐츠, docs/design/screens.md 카피 그대로 */
import React from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useTheme } from '../src/theme';

const SECTIONS: [string, string][] = [
  ['왜 엄격한 별점인가요?', '찐맛의 별점은 일부러 짜게 매겨요. 평균은 2.5점, 진짜 좋은 곳만 4.5점 이상이에요.'],
  ['공공기관 업무추진비', '공공기관 업무추진비 공개 내역에 자주 등장하면 신뢰 신호로 일부 반영해요. 방문 횟수가 많아질수록 반영폭은 점점 줄어들어요(상한 있음).'],
  ['광고·체험단 리뷰', '협찬·체험단 리뷰 비율이 높으면 감점하되, 판별 신뢰도가 낮으면 감점을 줄여요.'],
  ['리뷰가 쌓이면', '리뷰가 없을 땐 사전 점수로 시작하고, 방문자 리뷰가 20개 쌓이면 사전 점수와 실제 리뷰를 절반씩 반영해요.'],
  ['이 지역 상위 N%', '같은 지역 음식점들의 최종 별점을 비교해, 나보다 점수가 높은 곳의 비율로 계산해요.'],
  ['조건 완화', '조건에 맞는 곳이 부족하면 거리 → 분위기 → 가격 → 장르 순으로 완화해요. 음주 조건은 바꾸지 않아요.'],
  ['데이터 출처', '네이버 등 크롤링 데이터는 사용하지 않아요. 공식 API와 공공데이터만 사용합니다.'],
];

export default function ScoringExplainerScreen() {
  const t = useTheme();
  return (
    <ScrollView contentContainerStyle={{ padding: t.spacing.lg, gap: t.spacing.md }}>
      <View style={{ flexDirection: 'row', gap: t.spacing.md }}>
        {t.starScale.map((b) => (
          <Text key={b.label} style={[t.typography.captionStrong, { color: t.colors[b.colorKey] }]}>
            ★ {b.min.toFixed(1)}+ {b.label}
          </Text>
        ))}
      </View>
      {SECTIONS.map(([title, body]) => (
        <View key={title} style={{ backgroundColor: t.colors.surface, borderRadius: t.radius.lg, padding: t.spacing.lg, gap: t.spacing.xs }}>
          <Text style={[t.typography.bodyStrong, { color: t.colors.textPrimary }]}>{title}</Text>
          <Text style={[t.typography.body, { color: t.colors.textSecondary }]}>{body}</Text>
        </View>
      ))}
    </ScrollView>
  );
}
