/** 로그인 후 돌아오는 주소(jjinmat://auth, 웹 /auth). 웹 팝업은 여기서 결과를 넘기고 닫힘. */
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';

WebBrowser.maybeCompleteAuthSession();

export default function AuthRedirect() {
  const router = useRouter();
  useEffect(() => {
    // 앱에서 이 화면이 열리면(딥링크) 이전 화면으로 — 결과는 openAuthSessionAsync 가 처리
    if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [router]);
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
      <ActivityIndicator />
    </View>
  );
}
