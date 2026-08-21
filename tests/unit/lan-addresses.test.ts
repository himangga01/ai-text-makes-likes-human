import type { NetworkInterfaceInfo } from "node:os";
import { describe, expect, it } from "vitest";
import { listLanUrls } from "../../src/network/lan-addresses.js";

function ipv4(address: string, internal = false): NetworkInterfaceInfo {
  return {
    address,
    netmask: "255.255.255.0",
    family: "IPv4",
    mac: "00:11:22:33:44:55",
    internal,
    cidr: `${address}/24`
  };
}

describe("listLanUrls", () => {
  it("returns stable Wi-Fi and Ethernet URLs while excluding virtual adapters", () => {
    const interfaces: NodeJS.Dict<NetworkInterfaceInfo[]> = {
      "Wi-Fi": [ipv4("192.168.0.14")],
      Ethernet: [ipv4("10.0.0.8"), ipv4("10.0.0.8")],
      Loopback: [ipv4("127.0.0.1", true)],
      "vEthernet (WSL)": [ipv4("172.22.64.1")],
      DockerNAT: [ipv4("172.17.0.1")],
      LinkLocal: [ipv4("169.254.10.2")]
    };

    expect(listLanUrls(3210, interfaces)).toEqual([
      "http://10.0.0.8:3210",
      "http://192.168.0.14:3210"
    ]);
  });
});
