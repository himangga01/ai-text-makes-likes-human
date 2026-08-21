import { describe, expect, it } from "vitest";
import { isAllowedClientAddress } from "../../src/network/private-address.js";

describe("isAllowedClientAddress", () => {
  it.each([
    "127.0.0.1",
    "::1",
    "10.0.0.8",
    "172.16.4.2",
    "172.31.255.254",
    "192.168.0.25",
    "::ffff:192.168.1.7",
    "fe80::1",
    "fe80::1%12",
    "fc00::1234",
    "fd12:3456::1"
  ])("allows private client %s", value => {
    expect(isAllowedClientAddress(value)).toBe(true);
  });

  it.each([
    undefined,
    "8.8.8.8",
    "172.15.255.255",
    "172.32.0.1",
    "203.0.113.5",
    "2001:4860:4860::8888",
    "169.254.1.2",
    "not-an-ip"
  ])("rejects non-private client %s", value => {
    expect(isAllowedClientAddress(value)).toBe(false);
  });
});
