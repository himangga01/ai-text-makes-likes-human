import { existsSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import type { EngineChoice } from "../engine/model-policy.js";

/** Resolve native CLIs without invoking a shell or changing the user's login. */
export function resolveCli(kind: EngineChoice, configured = kind as string): string {
  if (configured !== kind) return configured;
  const extensions = process.platform === "win32" ? [".exe"] : [""];
  const candidates = (process.env.PATH ?? "").split(path.delimiter)
    .filter(Boolean).flatMap(directory => extensions.map(ext => path.join(directory.replace(/^"|"$/g, ""), kind + ext)));
  if (process.platform === "win32") {
    const local = process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
    candidates.push(path.join(os.homedir(), ".local", "bin", `${kind}.exe`));
    if (kind === "codex") candidates.push(path.join(local, "Programs", "OpenAI", "Codex", "bin", "codex.exe"));
  }
  return candidates.find(candidate => existsSync(candidate)) ?? configured;
}
