import "./build-desktop.mjs";
import { build, Platform, Arch } from "electron-builder";
import { createHash } from "node:crypto";
import { readFile, writeFile, readdir } from "node:fs/promises";
import path from "node:path";
await build({ targets: Platform.WINDOWS.createTarget(["portable"], Arch.x64), config: "electron-builder.yml", publish: "never" });
const pkg = JSON.parse(await readFile("package.json", "utf8"));
const file = path.join("release", `HumanizeKR-${pkg.version}-win-x64.exe`);
const data = await readFile(file);
const hash = createHash("sha256").update(data).digest("hex");
await writeFile(file + ".sha256", `${hash}  ${path.basename(file)}\n`);
await writeFile("release/build-info.json", JSON.stringify({ appVersion: pkg.version, electron: pkg.devDependencies.electron,
  python: JSON.parse(await readFile("python-runtime.json", "utf8")), engine: (await readFile("vendor/humanize-engine/ENGINE_VERSION", "utf8")).trim(),
  artifact: path.basename(file), bytes: data.length, sha256: hash, signed: false }, null, 2));
console.log(`Portable EXE: ${file} (${data.length} bytes)\nSHA256: ${hash}`);
