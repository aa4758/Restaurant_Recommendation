/** 별 5개 입력 — 별 왼쪽 절반 탭 = .5, 오른쪽 절반 = 정수(0.5~5). 스크린리더는 위/아래로 0.5씩 조절. */
import React from 'react';
import { Pressable, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme';
import { starHeroColor } from '../theme/tokens';

const SIZE = 44; // 터치 영역 44pt 이상

export function StarRatingInput({ value, onChange }: { value: number | null; onChange: (v: number) => void }) {
  const t = useTheme();
  const v = value ?? 0;
  const color = value != null ? starHeroColor(v, t.scheme) : t.colors.textDisabled;
  const step = (d: number) => onChange(Math.min(5, Math.max(0.5, (value ?? 0) + d)));
  return (
    <View
      accessible
      accessibilityRole="adjustable"
      accessibilityLabel="별점"
      accessibilityValue={{ text: value != null ? `${value.toFixed(1)}점` : '선택 안 함' }}
      accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
      onAccessibilityAction={(e) => step(e.nativeEvent.actionName === 'increment' ? 0.5 : -0.5)}
      style={{ flexDirection: 'row', justifyContent: 'center' }}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <Pressable
          key={n}
          importantForAccessibility="no"
          onPress={(e) => onChange(e.nativeEvent.locationX < SIZE / 2 ? n - 0.5 : n)}
          style={{ width: SIZE, height: SIZE, alignItems: 'center', justifyContent: 'center' }}
        >
          <Ionicons name={v >= n ? 'star' : v >= n - 0.5 ? 'star-half' : 'star-outline'} size={36} color={v >= n - 0.5 ? color : t.colors.textDisabled} />
        </Pressable>
      ))}
    </View>
  );
}
