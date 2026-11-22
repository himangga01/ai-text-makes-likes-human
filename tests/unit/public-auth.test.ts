import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, stat, utimes, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, expect, it } from 'vitest';
import {
  derivePasswordKey, PUBLIC_SESSIONS_FILE, PublicAuth, SESSION_COOKIE, writePublicPassword, type DeriveKey, type LoginResult
} from '../../src/network/public-auth.js';

const dirs: string[] = [];
afterEach(async () => { await Promise.all(dirs.splice(0).map(dir => rm(dir, { recursive: true, force: true }))); });
async function authFile() { const dir = await mkdtemp(path.join(os.tmpdir(), 'public-auth-')); dirs.push(dir); return path.join(dir, 'public-auth.json'); }
const cookie = (token: string) => `other=1; ${SESSION_COOKIE}=${token}`;
const tokenOf = (result: LoginResult) => result.ok ? result.token : '';
const sessionsOf = async (file: string) =>
  (JSON.parse(await readFile(path.join(path.dirname(file), PUBLIC_SESSIONS_FILE), 'utf8')) as { sessions: unknown[] }).sessions;

/** The real scrypt, counting how many hashes ran and how many ran at once. */
function countingDerive(base: DeriveKey = derivePasswordKey) {
  const stats = { calls: 0, active: 0, maxActive: 0 };
  const deriveKey: DeriveKey = async (password, salt) => {
    stats.calls++; stats.active++; stats.maxActive = Math.max(stats.maxActive, stats.active);
    try { return await base(password, salt); } finally { stats.active--; }
  };
  return { stats, deriveKey };
}

// A cheap stand-in for scrypt where a test needs many sign-ins; the record is written the way writePublicPassword does.
const quickDerive: DeriveKey = async (password, salt) => createHash('sha256').update(salt).update(password).digest();
async function writeQuickPassword(file: string, password: string) {
  const salt = Buffer.from('fixture-salt');
  await writeFile(file, JSON.stringify({ version: 1, salt: salt.toString('base64'), hash: (await quickDerive(password, salt)).toString('base64'),
    secret: Buffer.from('fixture-secret-0123456789abcdef').toString('base64'), updatedAt: new Date().toISOString() }), { mode: 0o600 });
}

it('refuses everything until a password is set, then signs in and verifies the session', async () => {
  const file = await authFile(), auth = new PublicAuth(file);
  expect(auth.configured).toBe(false);
  expect(await auth.login('0000', 'a')).toEqual({ ok: false, reason: 'unconfigured' });
  await writePublicPassword(file, '0000');
  // Windows keeps no POSIX mode bits.
  if (process.platform !== 'win32') expect((await stat(file)).mode & 0o777).toBe(0o600);
  expect(auth.configured).toBe(true);
  expect(await auth.login('1111', 'a')).toEqual({ ok: false, reason: 'wrong' });
  const result = await auth.login('0000', 'a');
  expect(result.ok).toBe(true);
  const token = tokenOf(result);
  expect(auth.verify(cookie(token))).toBe(true);
  expect(auth.verify(undefined)).toBe(false);
  expect(auth.verify(cookie(`${token}x`))).toBe(false);
  expect(auth.verify(cookie(token.replace(/^\d+/u, '99999999999999')))).toBe(false);
  expect(auth.sessionCookie(token)).toMatch(/HttpOnly; Secure; SameSite=Lax; Max-Age=2592000$/u);
});

it('a session ends after 30 days and when the password changes', async () => {
  const file = await authFile();
  let now = Date.now();
  const auth = new PublicAuth(file, () => now);
  await writePublicPassword(file, '0000');
  const token = tokenOf(await auth.login('0000', 'a'));
  now += 30 * 24 * 60 * 60 * 1000 + 1;
  expect(auth.verify(cookie(token))).toBe(false);
  now = Date.now();
  expect(auth.verify(cookie(token))).toBe(true);
  await writePublicPassword(file, '0000');
  const later = new Date(Date.now() + 5000);
  await utimes(file, later, later); // the cache keys on mtime; make the rewrite visible within one clock tick
  expect(auth.verify(cookie(token))).toBe(false);
  // The new password also drops the old session list.
  await expect(stat(path.join(path.dirname(file), PUBLIC_SESSIONS_FILE))).rejects.toMatchObject({ code: 'ENOENT' });
});

it('locks one visitor after 5 misses and everyone after 10, then lets them in again later', async () => {
  const file = await authFile();
  let now = Date.now();
  const auth = new PublicAuth(file, () => now);
  await writePublicPassword(file, '0000');
  for (let i = 0; i < 5; i++) expect((await auth.login('9999', 'a')).ok).toBe(false);
  expect(await auth.login('0000', 'a')).toEqual({ ok: false, reason: 'locked' });
  expect((await auth.login('0000', 'b')).ok).toBe(true);
  for (let i = 0; i < 5; i++) await auth.login('9999', `c${i}`);
  expect(await auth.login('0000', 'd')).toEqual({ ok: false, reason: 'locked' });
  now += 60 * 60 * 1000 + 1;
  expect((await auth.login('0000', 'a')).ok).toBe(true);
});

it('counts a burst of concurrent guesses before hashing any, so the right password is refused once locked', async () => {
  const file = await authFile();
  await writePublicPassword(file, 'right-pass');
  const { stats, deriveKey } = countingDerive();
  const auth = new PublicAuth(file, Date.now, deriveKey);
  const attempts = Array.from({ length: 200 }, (_, i) => auth.login(`wrong-${i}`, `visitor-${i}`));
  attempts.push(auth.login('right-pass', 'visitor-right'));
  const results = await Promise.all(attempts);
  expect(results.at(-1)).toEqual({ ok: false, reason: 'locked' });
  expect(results.filter(result => !result.ok && result.reason === 'wrong').length).toBe(stats.calls);
  expect(stats.calls).toBeLessThanOrEqual(10);
  expect(stats.maxActive).toBe(1);
});

it('never hashes more guesses than the hourly limit, however the bursts arrive', async () => {
  const file = await authFile();
  await writePublicPassword(file, 'right-pass');
  const now = Date.now();
  const { stats, deriveKey } = countingDerive();
  const auth = new PublicAuth(file, () => now, deriveKey);
  for (let wave = 0; wave < 10; wave++) {
    await Promise.all(Array.from({ length: 20 }, (_, i) => auth.login(`wrong-${wave}-${i}`, `visitor-${wave}-${i}`)));
  }
  expect(stats.calls).toBe(10);
  expect(await auth.login('right-pass', 'someone-else')).toEqual({ ok: false, reason: 'locked' });
  expect(stats.calls).toBe(10);
  expect(stats.maxActive).toBe(1);
});

it('holds one visitor to 5 guesses even in parallel, while others can still sign in', async () => {
  const file = await authFile();
  await writePublicPassword(file, 'right-pass');
  const now = Date.now();
  const { stats, deriveKey } = countingDerive();
  const auth = new PublicAuth(file, () => now, deriveKey);
  for (let wave = 0; wave < 5; wave++) await Promise.all(Array.from({ length: 20 }, (_, i) => auth.login(`wrong-${wave}-${i}`, 'one-visitor')));
  expect(stats.calls).toBe(5);
  expect(await auth.login('right-pass', 'one-visitor')).toEqual({ ok: false, reason: 'locked' });
  expect((await auth.login('right-pass', 'another-visitor')).ok).toBe(true);
});

it('refuses checks beyond the small queue at once, without hashing them', async () => {
  const file = await authFile();
  await writeQuickPassword(file, 'right-pass');
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let calls = 0;
  const auth = new PublicAuth(file, Date.now, async (password, salt) => { calls++; await gate; return quickDerive(password, salt); });
  const first = Array.from({ length: 4 }, (_, i) => auth.login('wrong', `visitor-${i}`));
  // One check runs and three wait; the queue is full, so even the right password is turned away untouched.
  expect(await auth.login('right-pass', 'visitor-late')).toEqual({ ok: false, reason: 'locked' });
  release();
  expect((await Promise.all(first)).map(result => result.ok ? 'ok' : result.reason)).toEqual(['wrong', 'wrong', 'wrong', 'wrong']);
  expect(calls).toBe(4);
  expect((await auth.login('right-pass', 'visitor-late')).ok).toBe(true);
});

it('gives back the count of a correct password, also when it races wrong ones', async () => {
  const file = await authFile();
  await writeQuickPassword(file, 'right-pass');
  const now = Date.now();
  const auth = new PublicAuth(file, () => now, quickDerive);
  const mixed = await Promise.all([auth.login('w1', 'a'), auth.login('right-pass', 'b'), auth.login('w2', 'c'), auth.login('w3', 'd')]);
  expect(mixed.map(result => result.ok)).toEqual([false, true, false, false]);
  for (let i = 0; i < 6; i++) expect(await auth.login('wrong', `e${i}`)).toEqual({ ok: false, reason: 'wrong' });
  // Nine failures so far: the right password still gets in and leaves the count at nine.
  expect((await auth.login('right-pass', 'f')).ok).toBe(true);
  expect(await auth.login('wrong', 'g')).toEqual({ ok: false, reason: 'wrong' });
  expect(await auth.login('right-pass', 'h')).toEqual({ ok: false, reason: 'locked' });
});

it('signing out revokes the session on the server, so a copied cookie stops working too', async () => {
  const file = await authFile();
  await writeQuickPassword(file, 'right-pass');
  const auth = new PublicAuth(file, Date.now, quickDerive);
  const kept = tokenOf(await auth.login('right-pass', 'a'));
  const copied = tokenOf(await auth.login('right-pass', 'b'));
  const sessions = path.join(path.dirname(file), PUBLIC_SESSIONS_FILE);
  if (process.platform !== 'win32') expect((await stat(sessions)).mode & 0o777).toBe(0o600);
  // The file lists digests, never the tokens themselves.
  const text = await readFile(sessions, 'utf8');
  for (const token of [kept, copied]) expect(text).not.toContain(token.split('.')[1]);
  // The list survives a restart.
  expect(new PublicAuth(file, Date.now, quickDerive).verify(cookie(copied))).toBe(true);
  await auth.logout(cookie(copied));
  expect(auth.verify(cookie(copied))).toBe(false);
  expect(new PublicAuth(file, Date.now, quickDerive).verify(cookie(copied))).toBe(false);
  expect(auth.verify(cookie(kept))).toBe(true);
  expect(await sessionsOf(file)).toHaveLength(1);
  // A token that is signed but was never listed is refused as well.
  await rm(sessions);
  expect(auth.verify(cookie(kept))).toBe(false);
  await auth.logout(cookie(kept)); // nothing to revoke: no error
});

it('keeps a bounded list: expired sessions are pruned and the oldest give way', async () => {
  const file = await authFile();
  await writeQuickPassword(file, 'right-pass');
  let now = Date.now();
  const auth = new PublicAuth(file, () => now, quickDerive);
  const stale = tokenOf(await auth.login('right-pass', 'a'));
  now += 31 * 24 * 60 * 60 * 1000;
  const tokens: string[] = [];
  for (let i = 0; i < 55; i++) { now += 1; tokens.push(tokenOf(await auth.login('right-pass', 'a'))); }
  expect(auth.verify(cookie(stale))).toBe(false);
  expect(await sessionsOf(file)).toHaveLength(50);
  expect(tokens.map(token => auth.verify(cookie(token)))).toEqual([...Array(5).fill(false), ...Array(50).fill(true)]);
});
