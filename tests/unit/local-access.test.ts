import { describe, expect, it } from "vitest";
import { cameThroughTunnel, isLocalHostHeader, isLoopbackAddress } from "../../src/network/local-access.js";

describe("isLoopbackAddress", () => {
  it.each(["127.0.0.1", "127.0.0.53", "::1", "::ffff:127.0.0.1", "::FFFF:127.0.0.1"])("accepts loopback %s", value => {
    expect(isLoopbackAddress(value)).toBe(true);
  });

  it.each([
    undefined, "", "192.168.0.22", "10.0.0.8", "172.16.4.2", "::ffff:192.168.1.7", "fe80::1", "fe80::1%12",
    "fd12:3456::1", "8.8.8.8", "0.0.0.0", "::", "127.0.0.1.example.com", "not-an-ip"
  ])("refuses %s, including private network addresses", value => {
    expect(isLoopbackAddress(value)).toBe(false);
  });
});

describe("isLocalHostHeader", () => {
  it.each(["localhost", "localhost:7882", "LOCALHOST:7882", "127.0.0.1", "127.0.0.1:7882", "[::1]", "[::1]:7882"])(
    "accepts this PC's own name %s", value => {
      expect(isLocalHostHeader(value)).toBe(true);
    });

  it.each([
    undefined, "", "192.168.0.10:7882", "10.0.0.8", "[fe80::1]", "[fd00::1]:7882", "0.0.0.0:7882", "127.0.0.2",
    "mac.local:7882", "attacker.example", "localhost.attacker.example", "localhost.", "user@localhost",
    "localhost:7882/path", "localhost:99999"
  ])("refuses %s, so a rebound DNS name or a LAN address cannot reach the portal", value => {
    expect(isLocalHostHeader(value)).toBe(false);
  });
});

describe("cameThroughTunnel", () => {
  it.each([
    { "cf-connecting-ip": "203.0.113.7" },
    { "cf-ray": "0123456789abcdef-ICN" },
    { "cf-visitor": '{"scheme":"https"}' },
    { "cf-warp-tag-id": "x" },
    { "cdn-loop": "cloudflare" },
    { "cdn-loop": "cloudflare; loops=1" },
    { "cdn-loop": ["other", "Cloudflare"] }
  ])("treats %j as a request from outside", headers => {
    expect(cameThroughTunnel(headers)).toBe(true);
  });

  it("leaves ordinary local requests alone", () => {
    expect(cameThroughTunnel({ host: "localhost:7882", origin: "http://localhost:7882" })).toBe(false);
    expect(cameThroughTunnel({ "cdn-loop": "other-cdn" })).toBe(false);
  });
});
