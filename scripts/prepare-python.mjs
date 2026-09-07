import { readFile, writeFile, mkdir, access } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export async function preparePython() {
  const lock = JSON.parse(await readFile(path.join(root, "python-runtime.json"), "utf8"));
  const resources = path.join(root, "build-resources");
  const destination = path.join(resources, "python");
  await mkdir(resources, { recursive: true });
  let archive;
  try { archive = await readFile(path.join(resources, "python-embed.zip")); } catch { /* download below */ }
  if (!archive || createHash("sha256").update(archive).digest("hex") !== lock.sha256) {
    const response = await fetch(lock.url, { signal: AbortSignal.timeout(60_000) });
    if (!response.ok) throw new Error(`Python download failed (${response.status})`);
    archive = Buffer.from(await response.arrayBuffer());
  }
  if (createHash("sha256").update(archive).digest("hex") !== lock.sha256) throw new Error("Python archive checksum mismatch");
  const archivePath = path.join(resources, "python-embed.zip");
  await writeFile(archivePath, archive);
  let previous;
  try { previous = JSON.parse(await readFile(path.join(destination, "runtime-lock.json"), "utf8")); } catch { /* initial extraction */ }
  if (previous && previous.sha256 !== lock.sha256) throw new Error("Use a fresh build-resources/python directory for the new Python pin");
  if (!previous) {
    const { extract } = require("@electron-internal/extract-zip");
    await extract(archivePath, { dir: destination });
    await writeFile(path.join(destination, "runtime-lock.json"), JSON.stringify(lock, null, 2));
  }
  await access(path.join(destination, "python.exe"));
  return destination;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(`Python prepared: ${await preparePython()}`);
}
