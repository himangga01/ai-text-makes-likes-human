import "./build-desktop.mjs";
import { build, Platform, Arch } from "electron-builder";
import { createHash } from "node:crypto";
import { readFile, writeFile, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { assertSejongBundle, readSejongEngineVersion } from "./engine-runtime.mjs";
// Fail before the build when the Super Sejong version pin is missing or malformed.
const sejong = await readSejongEngineVersion();
await build({ targets: Platform.WINDOWS.createTarget(["portable"], Arch.x64), config: "electron-builder.yml", publish: "never" });
// engine_runtime/ is bundled through the extraResources filter in electron-builder.yml, which once dropped files
// without a .py/.json extension (ENGINE_VERSION). electron-builder leaves the unpacked app beside the portable EXE.
const unpackedEngine = path.join("release", "win-unpacked", "resources", "engine", "engine_runtime");
if (existsSync(unpackedEngine)) await assertSejongBundle(unpackedEngine);
else console.warn(`${unpackedEngine} not found: engine_runtime/sejong was not verified in the unpacked app`);
const pkg = JSON.parse(await readFile("package.json", "utf8"));
const file = path.join("release", `HumanizeKR-${pkg.version}-win-x64.exe`);
const data = await readFile(file);
const hash = createHash("sha256").update(data).digest("hex");
await writeFile(file + ".sha256", `${hash}  ${path.basename(file)}\n`);
await writeFile("release/build-info.json", JSON.stringify({ appVersion: pkg.version, electron: pkg.devDependencies.electron,
  documentParser: JSON.parse(await readFile('python-document-deps.lock.json','utf8')),
  python: JSON.parse(await readFile("python-runtime.json", "utf8")), engine: (await readFile("vendor/humanize-engine/ENGINE_VERSION", "utf8")).trim(),
  sejongEngine: sejong, artifact: path.basename(file), bytes: data.length, sha256: hash, signed: false }, null, 2));
console.log(`Portable EXE: ${file} (${data.length} bytes)\nSHA256: ${hash}`);
