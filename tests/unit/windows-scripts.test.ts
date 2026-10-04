import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(".");

function cmd(scriptAndArgs: string, extraPath?: string): string {
  const env = { ...process.env };
  if (extraPath) {
    const key = Object.keys(env).find(name => name.toLowerCase() === "path") ?? "Path";
    env[key] = `${extraPath}${path.delimiter}${env[key] ?? ""}`;
  }
  return execFileSync("cmd.exe", ["/d", "/c", scriptAndArgs], {
    cwd: root,
    encoding: "utf8",
    windowsHide: true,
    env
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

describe.skipIf(process.platform !== "win32")("Windows operator scripts", () => {
  it("checks every host dependency and Codex login without installing", () => {
    const fixture = mkdtempSync(path.join(os.tmpdir(), "humanize-codex-fixture-"));
    try {
      writeFileSync(path.join(fixture, "codex.cmd"), "@echo off\r\nif /I \"%~1\"==\"login\" if /I \"%~2\"==\"status\" exit /b 0\r\nexit /b 1\r\n");
      const output = cmd("setup-portal.cmd --check", fixture);
      expect(output).toContain("CHECK_OK");
      expect(output).toContain("Node.js");
      expect(output).toContain("Python");
      expect(output).toContain("Codex login");
    } finally { rmSync(fixture, { recursive: true, force: true }); }
  });

  it("reports a start plan that uses npm.cmd and localhost 7882", () => {
    const output = cmd("start-portal.cmd --dry-run");
    expect(output).toContain("npm.cmd start");
    expect(output).toContain("http://localhost:7882");
    expect(output).not.toContain("npm.ps1");
  });

  it("limits the firewall creation plan to Private TCP 7882", () => {
    const output = powershell("allow-lan-firewall.ps1");
    expect(output).toContain("CREATE");
    expect(output).toContain("AI Text Humanize Portal (Private TCP 7882)");
    expect(output).toContain("Private");
    expect(output).toContain("TCP");
    expect(output).toContain("7882");
  });

  it("removes only the exact portal firewall rule", () => {
    const output = powershell("remove-lan-firewall.ps1");
    expect(output).toBe(
      "REMOVE|AI Text Humanize Portal (Private TCP 7882)\r\n"
    );
  });
});
