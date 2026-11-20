import { createHash, createHmac, randomBytes, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { mkdir, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";

/** Password gate for requests that arrive under a public name (see public-hosts.ts); this PC's own localhost needs none.
 * `public-auth.json` beside the jobs directory holds a scrypt hash and the session-signing secret; setting a new
 * password replaces both, which signs every browser out. Without the file the public name serves nothing.
 * `public-sessions.json` beside it lists the sessions still signed in, so signing out ends a session for good. */
export const PUBLIC_AUTH_FILE = "public-auth.json";
export const PUBLIC_SESSIONS_FILE = "public-sessions.json";
export const SESSION_COOKIE = "sejong_session";
const SESSION_MS = 30 * 24 * 60 * 60 * 1000;
const MAX_SESSIONS = 50;
const SCRYPT = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
// A short password survives only because guesses are scarce: per client, and for everyone together.
const CLIENT_LIMIT = { failures: 5, windowMs: 15 * 60 * 1000 };
const GLOBAL_LIMIT = { failures: 10, windowMs: 60 * 60 * 1000 };
// One password check runs at a time and a few more may wait; anything beyond is refused without hashing.
const MAX_PENDING_CHECKS = 4;

interface AuthRecord { version: 1; salt: string; hash: string; secret: string; updatedAt: string }
interface SessionsRecord { version: 1; sessions: Array<{ id: string; expires: number }> }
interface FailureWindow { failures: number; resetAt: number }
export type LoginResult = { ok: true; token: string } | { ok: false; reason: "unconfigured" | "locked" | "wrong" };
export type DeriveKey = (password: string, salt: Buffer) => Promise<Buffer>;

export const derivePasswordKey: DeriveKey = (password, salt) => new Promise<Buffer>((resolve, reject) =>
  scryptCallback(password.normalize("NFC"), salt, 32, SCRYPT, (error, key) => error ? reject(error) : resolve(key)));
const sign = (secret: Buffer, payload: string) => createHmac("sha256", secret).update(payload).digest("base64url");
// The list keeps a digest of each session's nonce, never the nonce itself.
const sessionId = (nonce: string) => createHash("sha256").update(nonce).digest("base64url");

export function publicAuthPath(runtimeRoot: string): string {
  return path.join(path.dirname(runtimeRoot), PUBLIC_AUTH_FILE);
}

/** Owner-only file replaced in one step, so a reader sees the old content or the new, never half of it. */
async function writePrivateFile(file: string, text: string): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.tmp`;
  await rm(temporary, { force: true }); // a leftover would keep its old mode
  await writeFile(temporary, text, { mode: 0o600 });
  await rename(temporary, file);
}

export async function writePublicPassword(file: string, password: string): Promise<void> {
  const salt = randomBytes(16);
  const record: AuthRecord = { version: 1, salt: salt.toString("base64"), hash: (await derivePasswordKey(password, salt)).toString("base64"),
    secret: randomBytes(32).toString("base64"), updatedAt: new Date().toISOString() };
  // The new secret already invalidates every session; dropping the list keeps no dead entries behind.
  await rm(path.join(path.dirname(file), PUBLIC_SESSIONS_FILE), { force: true });
  await writePrivateFile(file, `${JSON.stringify(record)}\n`);
}

export class PublicAuth {
  private cache: { mtimeMs: number; record?: AuthRecord } | undefined;
  private readonly clients = new Map<string, FailureWindow>();
  private overall: FailureWindow = { failures: 0, resetAt: 0 };
  private checks: Promise<unknown> = Promise.resolve();
  private pendingChecks = 0;
  private readonly sessionsFile: string;
  private sessionCache: { mtimeMs?: number; entries: Map<string, number> } | undefined;
  private sessionWrites: Promise<unknown> = Promise.resolve();
  private pendingSessionWrites = 0;

  constructor(private readonly file: string, private readonly now: () => number = Date.now,
    private readonly deriveKey: DeriveKey = derivePasswordKey) {
    this.sessionsFile = path.join(path.dirname(file), PUBLIC_SESSIONS_FILE);
  }

  /** Re-read when the file changes, so a password set while the portal runs applies at once. */
  private record(): AuthRecord | undefined {
    let mtimeMs: number;
    try { mtimeMs = statSync(this.file).mtimeMs; } catch { this.cache = undefined; return undefined; }
    if (this.cache?.mtimeMs === mtimeMs) return this.cache.record;
    let record: AuthRecord | undefined;
    try {
      const value = JSON.parse(readFileSync(this.file, "utf8")) as Partial<AuthRecord>;
      if (value.version === 1 && [value.salt, value.hash, value.secret].every(item => typeof item === "string" && item)) record = value as AuthRecord;
    } catch { /* unreadable: treated as unset */ }
    this.cache = { mtimeMs, record };
    return record;
  }

  get configured(): boolean { return Boolean(this.record()); }

  private locked(client: string): boolean {
    const now = this.now(), entry = this.clients.get(client);
    return (this.overall.resetAt > now && this.overall.failures >= GLOBAL_LIMIT.failures) ||
      (entry !== undefined && entry.resetAt > now && entry.failures >= CLIENT_LIMIT.failures);
  }

  /** Counts the attempt as a failure before its password is hashed, so attempts arriving together cannot all pass the
   * lock check while the first hash runs. A correct password gives its count back. */
  private reserve(client: string): FailureWindow {
    const now = this.now();
    if (this.overall.resetAt <= now) this.overall = { failures: 0, resetAt: now + GLOBAL_LIMIT.windowMs };
    this.overall.failures++;
    const entry = this.clients.get(client);
    if (!entry || entry.resetAt <= now) this.clients.set(client, { failures: 1, resetAt: now + CLIENT_LIMIT.windowMs });
    else entry.failures++;
    if (this.clients.size > 1000) for (const [key, value] of this.clients) if (value.resetAt <= now) this.clients.delete(key);
    return this.overall;
  }

  /** Runs password checks one after another: a burst of guesses gets no parallel hashing. */
  private serialized<T>(task: () => Promise<T>): Promise<T> {
    const run = this.checks.then(task);
    this.checks = run.catch(() => undefined);
    return run;
  }

  private async matches(record: AuthRecord, password: string): Promise<boolean> {
    const expected = Buffer.from(record.hash, "base64");
    const actual = await this.deriveKey(password.slice(0, 256), Buffer.from(record.salt, "base64"));
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  }

  async login(password: string, client: string): Promise<LoginResult> {
    const record = this.record();
    if (!record) return { ok: false, reason: "unconfigured" };
    // Everything up to reserve() runs synchronously: no other attempt can slip in between the check and the count.
    if (this.locked(client) || this.pendingChecks >= MAX_PENDING_CHECKS) return { ok: false, reason: "locked" };
    const window = this.reserve(client);
    this.pendingChecks++;
    let matched: boolean;
    try { matched = await this.serialized(() => this.matches(record, password)); } finally { this.pendingChecks--; }
    if (!matched) return { ok: false, reason: "wrong" };
    if (this.overall === window && window.failures > 0) window.failures--;
    this.clients.delete(client);
    const expires = this.now() + SESSION_MS, nonce = randomBytes(16).toString("base64url");
    await this.addSession(nonce, expires);
    const payload = `${expires}.${nonce}`;
    return { ok: true, token: `${payload}.${sign(Buffer.from(record.secret, "base64"), payload)}` };
  }

  /** The signed-in sessions by nonce digest, re-read when another process changes the file (a new password removes
   * it). While this process is still writing, its own copy is the newer one. */
  private sessions(): Map<string, number> {
    if (this.sessionCache && this.pendingSessionWrites > 0) return this.sessionCache.entries;
    let mtimeMs: number | undefined;
    try { mtimeMs = statSync(this.sessionsFile).mtimeMs; } catch { mtimeMs = undefined; }
    if (this.sessionCache && this.sessionCache.mtimeMs === mtimeMs) return this.sessionCache.entries;
    const entries = new Map<string, number>();
    if (mtimeMs !== undefined) {
      try {
        const value = JSON.parse(readFileSync(this.sessionsFile, "utf8")) as Partial<SessionsRecord>;
        if (value.version === 1 && Array.isArray(value.sessions)) {
          for (const item of value.sessions) {
            if (typeof item?.id === "string" && Number.isFinite(item.expires)) entries.set(item.id, item.expires);
          }
        }
      } catch { /* unreadable: nobody stays signed in */ }
    }
    this.sessionCache = { mtimeMs, entries };
    return entries;
  }

  private saveSessions(): Promise<void> {
    this.pendingSessionWrites++;
    const write = this.sessionWrites.then(async () => {
      const entries = this.sessionCache?.entries ?? new Map<string, number>();
      const record: SessionsRecord = { version: 1, sessions: [...entries].map(([id, expires]) => ({ id, expires })) };
      await writePrivateFile(this.sessionsFile, `${JSON.stringify(record)}\n`);
      const { mtimeMs } = await stat(this.sessionsFile);
      if (this.sessionCache && this.sessionCache.entries === entries) this.sessionCache.mtimeMs = mtimeMs;
    });
    this.sessionWrites = write.catch(() => undefined).finally(() => { this.pendingSessionWrites--; });
    return write;
  }

  private async addSession(nonce: string, expires: number): Promise<void> {
    const sessions = this.sessions(), now = this.now();
    for (const [id, until] of sessions) if (until <= now) sessions.delete(id);
    sessions.set(sessionId(nonce), expires);
    while (sessions.size > MAX_SESSIONS) {
      let oldest: [string, number] | undefined;
      for (const entry of sessions) if (!oldest || entry[1] < oldest[1]) oldest = entry;
      sessions.delete(oldest![0]);
    }
    await this.saveSessions();
  }

  /** The nonce of a validly signed, unexpired session that is still listed. */
  private signedInNonce(cookieHeader: string | undefined): string | undefined {
    const record = this.record();
    const token = cookieHeader?.split(";").map(part => part.trim()).find(part => part.startsWith(`${SESSION_COOKIE}=`))?.slice(SESSION_COOKIE.length + 1);
    if (!record || !token) return undefined;
    const [expires, nonce, signature, extra] = token.split(".");
    if (!expires || !nonce || !signature || extra !== undefined || !(Number(expires) > this.now())) return undefined;
    const expected = Buffer.from(sign(Buffer.from(record.secret, "base64"), `${expires}.${nonce}`));
    const actual = Buffer.from(signature);
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return undefined;
    const listed = this.sessions().get(sessionId(nonce));
    return listed !== undefined && listed > this.now() ? nonce : undefined;
  }

  verify(cookieHeader: string | undefined): boolean {
    return this.signedInNonce(cookieHeader) !== undefined;
  }

  /** Ends the session on the server too, so a copied cookie stops working with the browser's. */
  async logout(cookieHeader: string | undefined): Promise<void> {
    const nonce = this.signedInNonce(cookieHeader);
    if (nonce === undefined) return;
    this.sessions().delete(sessionId(nonce));
    await this.saveSessions();
  }

  sessionCookie(token: string): string {
    return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_MS / 1000}`;
  }

  clearedCookie(): string {
    return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
  }
}
