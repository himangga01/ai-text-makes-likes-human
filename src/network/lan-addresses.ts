import {
  networkInterfaces,
  type NetworkInterfaceInfo
} from "node:os";
import { isAllowedClientAddress } from "./private-address.js";

const VIRTUAL_INTERFACE = /(?:docker|vethernet|wsl|loopback|hyper-v)/iu;

export function listLanUrls(
  port: number,
  interfaces: NodeJS.Dict<NetworkInterfaceInfo[]> = networkInterfaces()
): string[] {
  const addresses = new Set<string>();

  for (const [name, infos] of Object.entries(interfaces)) {
    if (VIRTUAL_INTERFACE.test(name)) continue;
    for (const info of infos ?? []) {
      const isIpv4 = info.family === "IPv4";
      if (!isIpv4 || info.internal) continue;
      if (info.address.startsWith("169.254.")) continue;
      if (!isAllowedClientAddress(info.address)) continue;
      if (info.address.startsWith("127.")) continue;
      addresses.add(info.address);
    }
  }

  return [...addresses]
    .sort((left, right) => left.localeCompare(right, "en"))
    .map(address => `http://${address}:${port}`);
}
