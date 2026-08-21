import { execFileSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(".");

function cmd(scriptAndArgs: string): string {
  return execFileSync("cmd.exe", ["/d", "/c", scriptAndArgs], {
    cwd: root,
    encoding: "utf8",
    windowsHide: true
  });
}

function powershell(script: string): string {
  return execFileSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      path.join(root, "scripts", script),
      "-WhatIf"
    ],
    { cwd: root, encoding: "utf8", windowsHide: true }
  );
}

describe("Windows operator scripts", () => {
  it("checks every host dependency and Codex login without installing", () => {
    const output = cmd("setup-portal.cmd --check");
    expect(output).toContain("CHECK_OK");
    expect(output).toContain("Node.js");
    expect(output).toContain("Python");
    expect(output).toContain("Codex login");
  });

  it("reports a start plan that uses npm.cmd and localhost 3210", () => {
    const output = cmd("start-portal.cmd --dry-run");
    expect(output).toContain("npm.cmd start");
    expect(output).toContain("http://localhost:3210");
    expect(output).not.toContain("npm.ps1");
  });

  it("limits the firewall creation plan to Private TCP 3210", () => {
    const output = powershell("allow-lan-firewall.ps1");
    expect(output).toContain("CREATE");
    expect(output).toContain("AI Text Humanize Portal (Private TCP 3210)");
    expect(output).toContain("Private");
    expect(output).toContain("TCP");
    expect(output).toContain("3210");
  });

  it("removes only the exact portal firewall rule", () => {
    const output = powershell("remove-lan-firewall.ps1");
    expect(output).toBe(
      "REMOVE|AI Text Humanize Portal (Private TCP 3210)\r\n"
    );
  });
});
