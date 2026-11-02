/** 지도 링크 — docs/design/screens.md 'MapLinkButtons', docs/04 '지도 앱 링크'. 저장 없이 앱에서 생성. */
import React from 'react';
import { Linking, Platform, View } from 'react-native';
import { Button } from './Button';
import { useTheme } from '../theme';

const APP_NAME = 'com.jjinmat.app'; // 네이버지도 앱 스킴 필수 파라미터(앱 패키지명)

/** 검색어 = 가게명만(2026-11-02 사용자 결정: 주소를 붙이면 지도 앱에서 검색이 안 됨).
 *  지도 앱은 보통 현재 위치 주변부터 보여 줌. 사용자 위치·좌표는 넣지 않음. */
export function mapLinks(name: string) {
  const q = encodeURIComponent(name.trim());
  return {
    naver: { app: `nmap://search?query=${q}&appname=${APP_NAME}`, web: `https://map.naver.com/p/search/${q}` },
    kakao: { app: `kakaomap://search?q=${q}`, web: `https://map.kakao.com/?q=${q}` },
  };
}

/** 지도 앱이 있으면 앱, 없거나 실패하면 웹. */
export function openMap(link: { app: string; web: string }) {
  const web = () => Linking.openURL(link.web).catch(() => undefined);
  if (Platform.OS === 'web') return web();
  return Linking.openURL(link.app).catch(web);
}

export function MapLinkButtons({ name, compact }: { name: string; compact?: boolean }) {
  const t = useTheme();
  const links = mapLinks(name);
  return (
    <View style={{ flexDirection: 'row', gap: t.spacing.sm, flexWrap: 'wrap' }}>
      <Button
        label={compact ? '네이버지도' : '네이버지도에서 보기'}
        variant="text"
        onPress={() => openMap(links.naver)}
        accessibilityLabel={`${name} 네이버지도에서 열기`}
      />
      <Button
        label={compact ? '카카오맵' : '카카오맵에서 보기'}
        variant="text"
        onPress={() => openMap(links.kakao)}
        accessibilityLabel={`${name} 카카오맵에서 열기`}
      />
    </View>
  );
}
