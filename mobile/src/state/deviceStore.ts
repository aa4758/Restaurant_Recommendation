/** 기기 저장소: device_id, 찜 목록, 숨김 목록(30일 만료). AsyncStorage 실패 시 메모리 fallback. */
import AsyncStorage from '@react-native-async-storage/async-storage';

const K_DEVICE = 'jjinmat.device_id';
const K_LIKES = 'jjinmat.likes';
const K_HIDDEN = 'jjinmat.hidden';
const K_HINT = 'jjinmat.swipe_hint_seen';
export const HIDE_MS = 30 * 24 * 60 * 60 * 1000;
export const MAX_EXCLUDE = 200;

const mem: Record<string, string> = {};

async function get(key: string): Promise<string | null> {
  try {
    const v = await AsyncStorage.getItem(key);
    if (v != null) return v;
  } catch {
    // 메모리 fallback
  }
  return mem[key] ?? null;
}

async function set(key: string, value: string): Promise<void> {
  mem[key] = value;
  try {
    await AsyncStorage.setItem(key, value);
  } catch {
    // 로컬 상태는 메모리로 유지
  }
}

function randomId(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < 32; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

export async function getDeviceId(): Promise<string> {
  const v = await get(K_DEVICE);
  if (v && /^[A-Za-z0-9_-]{8,64}$/.test(v)) return v;
  const id = randomId();
  await set(K_DEVICE, id);
  return id;
}

async function readJson<T>(key: string, fallback: T): Promise<T> {
  try {
    const v = await get(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

export const getLikes = () => readJson<string[]>(K_LIKES, []);

export async function setLiked(id: string, liked: boolean): Promise<string[]> {
  const cur = (await getLikes()).filter((x) => x !== id);
  const next = liked ? [...cur, id] : cur;
  await set(K_LIKES, JSON.stringify(next));
  return next;
}

/** id -> 만료 시각(ms) */
async function getHiddenMap(): Promise<Record<string, number>> {
  const raw = await readJson<Record<string, number>>(K_HIDDEN, {});
  const now = Date.now();
  const out: Record<string, number> = {};
  for (const [id, exp] of Object.entries(raw)) if (exp > now) out[id] = exp;
  return out;
}

export async function hideRestaurant(id: string): Promise<void> {
  const m = await getHiddenMap();
  m[id] = Date.now() + HIDE_MS;
  await set(K_HIDDEN, JSON.stringify(m));
}

export async function unhideRestaurant(id: string): Promise<void> {
  const m = await getHiddenMap();
  delete m[id];
  await set(K_HIDDEN, JSON.stringify(m));
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
