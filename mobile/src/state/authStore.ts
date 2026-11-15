/** 로그인 토큰 저장·로그인 흐름 — docs/01 '소셜 로그인 세부' L-1·L-2.
 *  토큰은 기기 보안 저장소(웹은 AsyncStorage = localStorage). 서버 중계 + PKCE 방식 검증값. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import { Platform } from 'react-native';
import { api, AuthProvider } from '../api/client';
import { getLikes, replaceLikes } from './deviceStore';

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

/** 좋아요 계정 저장(docs/01 L-1): 로그인 직후엔 기기 좋아요를 계정에 합친 뒤, 기기 사본을 계정 목록으로 덮음.
 *  계정 목록(최신순)을 돌려줌. 합치기 실패는 무시(로그인은 성공). */
export async function syncLikes(token: string, merge = false) {
  if (merge) {
    const local = await getLikes();
    if (local.length) await api.addLikes(token, local.slice(-500)).catch(() => undefined);
  }
  const items = (await api.myLikes(token)).items;
  await replaceLikes(items.map((x) => x.restaurant_id).reverse());
  return items;
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
    const token = (await api.exchangeToken(code, verifier)).token;
    await setToken(token);
    await syncLikes(token, true).catch(() => undefined);
    return 'ok';
  } catch {
    return 'failed';
  }
}
