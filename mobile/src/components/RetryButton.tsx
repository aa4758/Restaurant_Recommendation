import React from 'react';
import { Button } from './Button';

interface RetryButtonProps {
  onPress: () => void;
  loading?: boolean;
}

export function RetryButton({ onPress, loading }: RetryButtonProps) {
  return <Button label="다시 시도" onPress={onPress} variant="secondary" loading={loading} />;
}
