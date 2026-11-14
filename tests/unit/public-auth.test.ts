import { mkdtemp, rm, stat, utimes } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, expect, it } from 'vitest';
import { PublicAuth, SESSION_COOKIE, writePublicPassword } from '../../src/network/public-auth.js';

const dirs: string[] = [];
afterEach(async () => { await Promise.all(dirs.splice(0).map(dir => rm(dir, { recursive: true, force: true }))); });
async function authFile() { const dir = await mkdtemp(path.join(os.tmpdir(), 'public-auth-')); dirs.push(dir); return path.join(dir, 'public-auth.json'); }
const cookie = (token: string) => `other=1; ${SESSION_COOKIE}=${token}`;

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
  const token = result.ok ? result.token : '';
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
  const first = await auth.login('0000', 'a');
  const token = first.ok ? first.token : '';
  now += 30 * 24 * 60 * 60 * 1000 + 1;
  expect(auth.verify(cookie(token))).toBe(false);
  now = Date.now();
  expect(auth.verify(cookie(token))).toBe(true);
  await writePublicPassword(file, '0000');
  const later = new Date(Date.now() + 5000);
  await utimes(file, later, later); // the cache keys on mtime; make the rewrite visible within one clock tick
  expect(auth.verify(cookie(token))).toBe(false);
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
