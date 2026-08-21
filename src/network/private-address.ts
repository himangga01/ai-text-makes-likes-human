import { isIP } from "node:net";

function isPrivateIpv4(value: string): boolean {
  const parts = value.split(".").map(Number);
  if (
    parts.length !== 4 ||
    parts.some(part => !Number.isInteger(part) || part < 0 || part > 255)
  ) {
    return false;
  }

  const [first = -1, second = -1] = parts;
  if (first === 127 || first === 10) return true;
  if (first === 172 && second >= 16 && second <= 31) return true;
  return first === 192 && second === 168;
}

export function isAllowedClientAddress(
  value: string | undefined
): boolean {
  if (!value) return false;

  const withoutZone = value.split("%", 1)[0] ?? value;
  const ipv4MappedPrefix = "::ffff:";
  if (withoutZone.toLowerCase().startsWith(ipv4MappedPrefix)) {
    return isPrivateIpv4(withoutZone.slice(ipv4MappedPrefix.length));
  }

  const family = isIP(withoutZone);
  if (family === 4) return isPrivateIpv4(withoutZone);
  if (family !== 6) return false;

  const normalized = withoutZone.toLowerCase();
  return (
    normalized === "::1" ||
    normalized.startsWith("fc") ||
    normalized.startsWith("fd") ||
    /^fe[89ab]/u.test(normalized)
  );
}
