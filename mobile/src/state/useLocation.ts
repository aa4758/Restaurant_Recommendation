import { useCallback, useEffect, useState } from 'react';
import * as Location from 'expo-location';
import { FALLBACK_LOCATION } from '../api/client';

export interface LocationState {
  lat: number;
  lng: number;
  /** 위치 권한이 거부되어 서울시청 좌표로 대체된 경우 true */
  isFallback: boolean;
  /** 권한 확인이 아직 끝나지 않음 */
  isLoading: boolean;
}

/**
 * 위치 권한을 요청하고 좌표를 반환하는 훅.
 * 권한이 거부되면 서울시청 좌표(37.5663, 126.9779)로 폴백하고 isFallback=true 를 반환한다.
 * (screens.md: LocationPermissionBanner / LocationDisabledNotice 표시 조건으로 사용)
 */
export function useLocation() {
  const [state, setState] = useState<LocationState>({
    ...FALLBACK_LOCATION,
    isFallback: false,
    isLoading: true,
  });

  const resolveLocation = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true }));
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setState({ ...FALLBACK_LOCATION, isFallback: true, isLoading: false });
        return;
      }
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setState({
        lat: position.coords.latitude,
        lng: position.coords.longitude,
        isFallback: false,
        isLoading: false,
      });
    } catch {
      setState({ ...FALLBACK_LOCATION, isFallback: true, isLoading: false });
    }
  }, []);

  useEffect(() => {
    resolveLocation();
  }, [resolveLocation]);

  return { ...state, retryPermission: resolveLocation };
}
