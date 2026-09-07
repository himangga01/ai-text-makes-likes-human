import { build } from "esbuild";
import { preparePython } from "./prepare-python.mjs";
import { prepareIcon } from "./prepare-icon.mjs";
import { access } from "node:fs/promises";
import { spawnSync } from "node:child_process";
try { await access("node_modules/electron/dist/electron.exe"); } catch {
  const installed = spawnSync(process.execPath, ["node_modules/electron/install.js"], { stdio: "inherit", windowsHide: true });
  if (installed.status !== 0) throw new Error("Electron runtime preparation failed");
}
await preparePython();
await prepareIcon();
await build({ entryPoints: ["desktop/main.ts", "desktop/worker.ts", "desktop/preload.ts"], outdir: "desktop-dist", outExtension: { ".js": ".cjs" }, bundle: true, platform: "node", target: "node22", format: "cjs", external: ["electron"], sourcemap: false });
console.log("Electron main, worker and isolated preload built.");
