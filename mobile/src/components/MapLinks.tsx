/** 지도 링크 — docs/design/screens.md 'MapLinkButtons', docs/04 '지도 앱 링크'. 저장 없이 앱에서 생성. */
import React from 'react';
import { Linking, Platform, View } from 'react-native';
import { Button } from './Button';
import { useTheme } from '../theme';

const APP_NAME = 'com.jjinmat.app'; // 네이버지도 앱 스킴 필수 파라미터(앱 패키지명)

/** 검색어 = 가게명 + 주소(도로명 우선, 없으면 가게명만). 주소 뒤 괄호(동·건물·층)는 검색을 흐려서 뺌.
 *  사용자 위치·좌표는 넣지 않음. */
export function mapLinks(name: string, address?: string | null) {
  const addr = (address ?? '').replace(/\s*\(.*$/, '').trim();
  const q = encodeURIComponent(addr ? `${name} ${addr}` : name);
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

export function MapLinkButtons({ name, address, compact }: { name: string; address?: string | null; compact?: boolean }) {
  const t = useTheme();
  const links = mapLinks(name, address);
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
