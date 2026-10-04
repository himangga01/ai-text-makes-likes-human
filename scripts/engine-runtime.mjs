// Shared by the packaging scripts and their tests: stage engine_runtime/ for a bundle, read the Super Sejong
// version pin, and prove a bundle carries engine_runtime/sejong/** (DESIGN.md 4.3, WP-14).
// Plain Node, no dependencies; importing it has no side effects.
import { cp, readFile, readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";

export const SEJONG_ENGINE_ID = "super-sejong";
const SEJONG_DIR = path.join("engine_runtime", "sejong");

/** cp filter: Python bytecode is machine-specific and never ships. */
export const bytecodeFilter = source => !source.includes("__pycache__") && !source.endsWith(".pyc");

const SEMVER = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$/;
const SCHEMA = /^[1-9][0-9]{0,3}$/;
// Same boundaries as read_engine_version() in engine_runtime/sejong/__init__.py and version.ts.
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/;
const BLANK_LINE = /^[\t\v\f \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/;

/** {id, version, schema} from the text of engine_runtime/sejong/ENGINE_VERSION; throws on any other shape. */
export function parseSejongEngineVersion(text) {
  const entries = new Map();
  for (const line of text.split(LINE_BREAK)) {
    if (BLANK_LINE.test(line)) continue;
    const separator = line.indexOf("=");
    const key = separator < 0 ? "" : line.slice(0, separator);
    if (separator < 0 || entries.has(key)) throw new Error("ENGINE_VERSION: malformed line");
    entries.set(key, line.slice(separator + 1));
  }
  if ([...entries.keys()].sort().join(",") !== "id,schema,version") throw new Error("ENGINE_VERSION: keys must be exactly id, version, schema");
  const [id, version, schema] = [entries.get("id"), entries.get("version"), entries.get("schema")];
  if (id !== SEJONG_ENGINE_ID || !SEMVER.test(version) || !SCHEMA.test(schema)) throw new Error("ENGINE_VERSION: invalid id, version or schema");
  return { id, version, schema: Number(schema) };
}

export async function readSejongEngineVersion(root = process.cwd()) {
  return parseSejongEngineVersion(await readFile(path.join(root, SEJONG_DIR, "ENGINE_VERSION"), "utf8"));
}

/** Sorted POSIX-style relative paths of every file below `directory`, bytecode excluded; [] if it is absent. */
export async function listFiles(directory) {
  const entries = await readdir(directory, { recursive: true, withFileTypes: true }).catch(error => {
    if (error.code === "ENOENT") return [];
    throw error;
  });
  return entries.filter(entry => entry.isFile() && bytecodeFilter(path.join(entry.parentPath, entry.name)))
    .map(entry => path.relative(directory, path.join(entry.parentPath, entry.name)).split(path.sep).join("/")).sort();
}

/** Throws unless `bundleEngineRuntime` (the engine_runtime/ directory inside a bundle) holds every file of the
 * source engine_runtime/sejong/**, byte for byte, including a valid ENGINE_VERSION. Extra files are allowed. */
export async function assertSejongBundle(bundleEngineRuntime, root = process.cwd()) {
  const source = path.join(root, SEJONG_DIR);
  const files = await listFiles(source);
  if (!files.includes("ENGINE_VERSION")) throw new Error(`Source ${SEJONG_DIR}/ENGINE_VERSION is missing`);
  const missing = [];
  const different = [];
  for (const file of files) {
    const packed = await readFile(path.join(bundleEngineRuntime, "sejong", file)).catch(() => undefined);
    if (packed === undefined) missing.push(file);
    else if (!packed.equals(await readFile(path.join(source, file)))) different.push(file);
  }
  if (missing.length || different.length) {
    throw new Error(`Bundle ${path.basename(path.dirname(bundleEngineRuntime))}/engine_runtime/sejong differs from the source: ` +
      `missing [${missing.join(", ")}], changed [${different.join(", ")}]`);
  }
  parseSejongEngineVersion(await readFile(path.join(bundleEngineRuntime, "sejong", "ENGINE_VERSION"), "utf8"));
}

/** Copies engine_runtime/ to `destination` (the bundle's engine_runtime/ directory) and checks that
 * engine_runtime/sejong/** arrived. package-skills.mjs stages both host bundles through this. */
export async function stageEngineRuntime(destination, root = process.cwd()) {
  await cp(path.join(root, "engine_runtime"), destination, { recursive: true, filter: bytecodeFilter });
  await assertSejongBundle(destination, root);
}

/** Imports the bundled `sejong` package with `python` and returns its version, so a bundle that copied the files
 * but cannot load them (the package reads ENGINE_VERSION at import) fails here rather than in the field.
 * Only engine_runtime/ goes on sys.path, never engine_runtime/sejong itself (types.py and io.py would shadow the stdlib). */
export function loadBundledSejong(python, bundleEngineRuntime, options = {}) {
  const script = "import json,sys; sys.path.insert(0, sys.argv[1]); import sejong; " +
    "print(json.dumps({'id': sejong.ENGINE_ID, 'version': sejong.VERSION, 'schema': sejong.SCHEMA_VERSION}))";
  const result = spawnSync(python, ["-c", script, bundleEngineRuntime],
    { encoding: "utf8", windowsHide: true, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" }, ...options });
  if (result.status !== 0) throw new Error(`Bundled sejong package failed to import: ${(result.stderr || result.error?.message || "").trim().split("\n").pop()}`);
  return JSON.parse(result.stdout);
}
