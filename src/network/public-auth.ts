import { createHmac, randomBytes, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";

/** Password gate for requests that arrive under a public name (see public-hosts.ts). LAN access stays open.
 * `public-auth.json` beside the jobs directory holds a scrypt hash and the session-signing secret; setting a new
 * password replaces both, which signs every browser out. Without the file the public name serves nothing. */
export const PUBLIC_AUTH_FILE = "public-auth.json";
export const SESSION_COOKIE = "sejong_session";
const SESSION_MS = 30 * 24 * 60 * 60 * 1000;
const SCRYPT = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
// A short password survives only because guesses are scarce: per client, and for everyone together.
const CLIENT_LIMIT = { failures: 5, windowMs: 15 * 60 * 1000 };
const GLOBAL_LIMIT = { failures: 10, windowMs: 60 * 60 * 1000 };

interface AuthRecord { version: 1; salt: string; hash: string; secret: string; updatedAt: string }
export type LoginResult = { ok: true; token: string } | { ok: false; reason: "unconfigured" | "locked" | "wrong" };

const derive = (password: string, salt: Buffer) => new Promise<Buffer>((resolve, reject) =>
  scryptCallback(password.normalize("NFC"), salt, 32, SCRYPT, (error, key) => error ? reject(error) : resolve(key)));
const sign = (secret: Buffer, payload: string) => createHmac("sha256", secret).update(payload).digest("base64url");

export function publicAuthPath(runtimeRoot: string): string {
  return path.join(path.dirname(runtimeRoot), PUBLIC_AUTH_FILE);
}

export async function writePublicPassword(file: string, password: string): Promise<void> {
  const salt = randomBytes(16);
  const record: AuthRecord = { version: 1, salt: salt.toString("base64"), hash: (await derive(password, salt)).toString("base64"),
    secret: randomBytes(32).toString("base64"), updatedAt: new Date().toISOString() };
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(record)}\n`, { mode: 0o600 });
  await rename(temporary, file);
}

export class PublicAuth {
  private cache: { mtimeMs: number; record?: AuthRecord } | undefined;
  private readonly clients = new Map<string, { failures: number; resetAt: number }>();
  private overall = { failures: 0, resetAt: 0 };

  constructor(private readonly file: string, private readonly now: () => number = Date.now) {}

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

  private fail(client: string): void {
    const now = this.now();
    if (this.overall.resetAt <= now) this.overall = { failures: 0, resetAt: now + GLOBAL_LIMIT.windowMs };
    this.overall.failures++;
    const entry = this.clients.get(client);
    if (!entry || entry.resetAt <= now) this.clients.set(client, { failures: 1, resetAt: now + CLIENT_LIMIT.windowMs });
    else entry.failures++;
    if (this.clients.size > 1000) for (const [key, value] of this.clients) if (value.resetAt <= now) this.clients.delete(key);
  }

  async login(password: string, client: string): Promise<LoginResult> {
    const record = this.record();
    if (!record) return { ok: false, reason: "unconfigured" };
    if (this.locked(client)) return { ok: false, reason: "locked" };
    const expected = Buffer.from(record.hash, "base64");
    const actual = await derive(password.slice(0, 256), Buffer.from(record.salt, "base64"));
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) { this.fail(client); return { ok: false, reason: "wrong" }; }
    this.clients.delete(client);
    const payload = `${this.now() + SESSION_MS}.${randomBytes(16).toString("base64url")}`;
    return { ok: true, token: `${payload}.${sign(Buffer.from(record.secret, "base64"), payload)}` };
  }

  verify(cookieHeader: string | undefined): boolean {
    const record = this.record();
    const token = cookieHeader?.split(";").map(part => part.trim()).find(part => part.startsWith(`${SESSION_COOKIE}=`))?.slice(SESSION_COOKIE.length + 1);
    if (!record || !token) return false;
    const [expires, nonce, signature, extra] = token.split(".");
    if (!expires || !nonce || !signature || extra !== undefined || !(Number(expires) > this.now())) return false;
    const expected = Buffer.from(sign(Buffer.from(record.secret, "base64"), `${expires}.${nonce}`));
    const actual = Buffer.from(signature);
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  }

  sessionCookie(token: string): string {
    return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_MS / 1000}`;
  }

  clearedCookie(): string {
    return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
  }
}
