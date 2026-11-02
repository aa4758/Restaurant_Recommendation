/** 로그인 토큰 저장·로그인 흐름 — docs/01 '소셜 로그인 세부' L-1·L-2.
 *  토큰은 기기 보안 저장소(웹은 AsyncStorage = localStorage). 서버 중계 + PKCE 방식 검증값. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import { Platform } from 'react-native';
import { api, AuthProvider } from '../api/client';

const K_TOKEN = 'jjinmat.auth_token';

export async function getToken(): Promise<string | null> {
  try {
    return Platform.OS === 'web' ? await AsyncStorage.getItem(K_TOKEN) : await SecureStore.getItemAsync(K_TOKEN);
  } catch {
    return null;
  }
}

async function setToken(token: string): Promise<void> {
  if (Platform.OS === 'web') await AsyncStorage.setItem(K_TOKEN, token);
  else await SecureStore.setItemAsync(K_TOKEN, token);
}

export async function clearToken(): Promise<void> {
  try {
    if (Platform.OS === 'web') await AsyncStorage.removeItem(K_TOKEN);
    else await SecureStore.deleteItemAsync(K_TOKEN);
  } catch {
    // 이미 없음
  }
}

/** 로그인 결과: ok | cancelled(사용자 취소) | failed */
export async function login(provider: AuthProvider): Promise<'ok' | 'cancelled' | 'failed'> {
  const verifier = (Crypto.randomUUID() + Crypto.randomUUID()).replace(/-/g, ''); // 64자, 앱만 앎
  const b64 = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {
    encoding: Crypto.CryptoEncoding.BASE64,
  });
  const challenge = b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const redirect = Linking.createURL('auth'); // 웹 http://localhost:8081/auth, 앱 jjinmat://auth
  const res = await WebBrowser.openAuthSessionAsync(api.authStartUrl(provider, redirect, challenge), redirect);
  if (res.type !== 'success') return 'cancelled';
  const { queryParams } = Linking.parse(res.url);
  const code = queryParams?.code;
  if (typeof code !== 'string') return queryParams?.error === 'cancelled' ? 'cancelled' : 'failed';
  try {
    await setToken((await api.exchangeToken(code, verifier)).token);
    return 'ok';
  } catch {
    return 'failed';
  }
}
