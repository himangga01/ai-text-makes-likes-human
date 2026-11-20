import type { IncomingHttpHeaders } from "node:http";
import { isIP } from "node:net";

/** The portal serves this PC only. The listener binds loopback, and every request must also come from a loopback
 * socket whatever HOST says; other devices use the public address (see public-hosts.ts), which asks the password. */
export function isLoopbackAddress(value: string | undefined): boolean {
  if (!value) return false;
  const lower = value.toLowerCase();
  const address = lower.startsWith("::ffff:") ? lower.slice(7) : lower;
  return address === "::1" || (isIP(address) === 4 && address.startsWith("127."));
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** The names this PC's own browser uses, with an optional port. Any other name could be a DNS name that an external
 * site rebinds to 127.0.0.1, so it is refused. */
export function isLocalHostHeader(value: string | undefined): boolean {
  if (!value) return false;
  try {
    const parsed = new URL(`http://${value}`);
    if (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) return false;
    return LOCAL_HOSTS.has(parsed.hostname.toLowerCase());
  } catch {
    return false;
  }
}

const EDGE_HEADERS = ["cf-connecting-ip", "cf-connecting-ipv6", "cf-ray", "cf-visitor", "cf-warp-tag-id"];

/** Whether a Cloudflare edge forwarded the request. Such a request is a public visitor even when its Host names this
 * PC (a tunnel that rewrote Host), so it never takes the local no-password path. */
export function cameThroughTunnel(headers: IncomingHttpHeaders): boolean {
  if (EDGE_HEADERS.some(name => headers[name] !== undefined)) return true;
  const loop = headers["cdn-loop"];
  return /cloudflare/iu.test(Array.isArray(loop) ? loop.join(",") : loop ?? "");
}
