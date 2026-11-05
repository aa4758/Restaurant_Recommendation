import React from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  ViewStyle,
} from 'react-native';
import { useTheme } from '../theme';

type Variant = 'primary' | 'secondary' | 'text';

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
  /** 스크린리더 이름(없으면 label) */
  accessibilityLabel?: string;
}

/**
 * 내부 공용 버튼 프리미티브. screens.md 의 각 버튼(RecommendCTAButton,
 * RetryButton, SubmitReviewButton 등)은 이 컴포넌트를 감싸거나 그대로 사용한다.
 */
export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  loading = false,
  style,
  accessibilityLabel,
}: ButtonProps) {
  const theme = useTheme();
  const isDisabled = disabled || loading;

  const backgroundColor =
    variant === 'primary'
      ? theme.colors.primary
      : variant === 'secondary'
        ? theme.colors.surfaceAlt
        : 'transparent';
  const textColor =
    variant === 'primary' ? theme.colors.primaryText : theme.colors.primary;

  return (
    <TouchableOpacity
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: isDisabled }}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.75}
      style={[
        styles.base,
        {
          backgroundColor,
          borderRadius: theme.radius.md,
          minHeight: 48,
          paddingVertical: theme.spacing.md,
          paddingHorizontal: theme.spacing.lg,
          opacity: isDisabled ? 0.5 : 1,
        },
        style,
      ]}
    >
      {/* loading 중에도 라벨 자리를 유지해 버튼 폭이 흔들리지 않게 */}
      <Text
        style={[
          theme.typography.bodyStrong,
          { color: textColor, opacity: loading ? 0 : 1 },
        ]}
      >
        {label}
      </Text>
      {loading ? <ActivityIndicator color={textColor} style={StyleSheet.absoluteFill} /> : null}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
