/** 기기 저장소: device_id, 찜 목록, 숨김 목록(30일 만료). AsyncStorage 실패 시 메모리 fallback. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getRandomBytes } from 'expo-crypto';

const K_DEVICE = 'jjinmat.device_id';
const K_LIKES = 'jjinmat.likes';
const K_HIDDEN = 'jjinmat.hidden';
const K_HINT = 'jjinmat.swipe_hint_seen';
export const HIDE_MS = 30 * 24 * 60 * 60 * 1000;
export const MAX_EXCLUDE = 200;

const mem: Record<string, string> = {};

/** mem 이 마스터 사본: 한 번 읽거나 쓴 키는 항상 mem 이 우선한다. */
async function get(key: string): Promise<string | null> {
  if (key in mem) return mem[key];
  try {
    const v = await AsyncStorage.getItem(key);
    if (v != null) {
      mem[key] = v;
      return v;
    }
  } catch {
    // 메모리 fallback
  }
  return null;
}

async function set(key: string, value: string): Promise<void> {
  mem[key] = value;
  try {
    await AsyncStorage.setItem(key, value);
  } catch {
    // 로컬 상태는 메모리로 유지
  }
}

export async function getDeviceId(): Promise<string> {
  const v = await get(K_DEVICE);
  if (v && /^[A-Za-z0-9_-]{8,64}$/.test(v)) return v;
  // randomUUID 는 웹에서 https·localhost 에서만 동작 → 어디서나 되는 getRandomBytes 로 만듦(32자 hex)
  const id = Array.from(getRandomBytes(16), (b) => b.toString(16).padStart(2, '0')).join('');
  await set(K_DEVICE, id);
  return id;
}

/** 키별 직렬화: 같은 키의 read-modify-write 를 promise chain 으로 순차 실행. */
const chains: Record<string, Promise<unknown>> = {};
function mutate<T, R>(key: string, fallback: T, fn: (cur: T) => { next: T; result: R }): Promise<R> {
  const run = (chains[key] ?? Promise.resolve()).then(async () => {
    const { next, result } = fn(await readJson<T>(key, fallback));
    await set(key, JSON.stringify(next));
    return result;
  });
  chains[key] = run.catch(() => undefined);
  return run;
}

async function readJson<T>(key: string, fallback: T): Promise<T> {
  try {
    const v = await get(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

export const getLikes = async () => {
  await (chains[K_LIKES] ?? Promise.resolve());
  return readJson<string[]>(K_LIKES, []);
};

export function setLiked(id: string, liked: boolean): Promise<string[]> {
  return mutate<string[], string[]>(K_LIKES, [], (cur) => {
    const rest = cur.filter((x) => x !== id);
    const next = liked ? [...rest, id] : rest;
    return { next, result: next };
  });
}

/** id -> 만료 시각(ms) */
function pruneHidden(raw: Record<string, number>): Record<string, number> {
  const now = Date.now();
  const out: Record<string, number> = {};
  for (const [id, exp] of Object.entries(raw)) if (exp > now) out[id] = exp;
  return out;
}

async function getHiddenMap(): Promise<Record<string, number>> {
  await (chains[K_HIDDEN] ?? Promise.resolve());
  return pruneHidden(await readJson<Record<string, number>>(K_HIDDEN, {}));
}

export function hideRestaurant(id: string): Promise<void> {
  return mutate<Record<string, number>, void>(K_HIDDEN, {}, (cur) => {
    const m = pruneHidden(cur);
    m[id] = Date.now() + HIDE_MS;
    return { next: m, result: undefined };
  });
}

export function unhideRestaurant(id: string): Promise<void> {
  return mutate<Record<string, number>, void>(K_HIDDEN, {}, (cur) => {
    const m = pruneHidden(cur);
    delete m[id];
    return { next: m, result: undefined };
  });
}

/** 미만료 숨김 id, 최신 숨김 우선 최대 200개 */
export async function getExcludeIds(): Promise<string[]> {
  const m = await getHiddenMap();
  return Object.entries(m)
    .sort((a, b) => b[1] - a[1])
    .slice(0, MAX_EXCLUDE)
    .map(([id]) => id);
}

export async function consumeSwipeHint(): Promise<boolean> {
  if (await get(K_HINT)) return false;
  await set(K_HINT, '1');
  return true;
}
