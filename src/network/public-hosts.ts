import { readFileSync } from "node:fs";
import { isIP } from "node:net";
import { isLoopbackAddress } from "./local-access.js";

/** Public names that a tunnel connector on this machine (Cloudflare Tunnel) forwards to the loopback listener.
 * One name per line in `public-hosts.txt` beside the runtime's jobs directory; `#` starts a comment. A missing file
 * means no public name, and a restart picks up an edited one. */
const HOSTNAME = /^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/u;

export function readPublicHosts(file: string): string[] {
  let text: string;
  try { text = readFileSync(file, "utf8"); } catch { return []; }
  const names = text.split(/\r?\n/u).map(line => line.replace(/#.*/u, "").trim().toLowerCase());
  return [...new Set(names.filter(name => HOSTNAME.test(name) && isIP(name) === 0))];
}

/** The listed public name a request arrived under. Only the local connector can present one: any other name reaching
 * the loopback listener (a rebound DNS name) still meets the local host check. */
export function publicHostOf(host: string | undefined, remoteAddress: string | undefined, publicHosts: readonly string[]): string | undefined {
  if (!host || publicHosts.length === 0 || !isLoopbackAddress(remoteAddress)) return undefined;
  const name = host.toLowerCase();
  return publicHosts.includes(name) ? name : undefined;
}
