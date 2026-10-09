// Pins the Super Sejong runtime files and the packaging of engine_runtime/sejong/** (DESIGN.md 4.5, 8.2 WP-14).
// vendor-engine.test.ts keeps pinning the legacy vendor tree until WP-18; this file is its v2 counterpart.
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { readFileSync, statSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  engineVersionAtLeast,
  ENGINE_VERSION_FILE,
  parseEngineVersion,
  readEngineVersion,
  SUPPORTED_ENGINE_SCHEMA
} from "../../src/engine/sejong/version.js";
import { CHECK_SCHEMA, PLAN_SCHEMA } from "../../src/engine/sejong/types.js";
import {
  assertSejongBundle,
  bytecodeFilter,
  listFiles,
  loadBundledSejong,
  parseSejongEngineVersion,
  readSejongEngineVersion,
  stageEngineRuntime
} from "../../scripts/engine-runtime.mjs";
import { pythonCommand } from "../helpers/python-command.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const root = path.resolve(".");
const engineRoot = path.join(root, "engine_runtime", "sejong");
const requireFromTest = createRequire(import.meta.url);
const text = (...parts: string[]) => readFileSync(path.join(root, ...parts), "utf8");
const roots: string[] = [];
async function scratch(prefix: string): Promise<string> {
  const dir = await makeTestRoot(prefix);
  roots.push(dir);
  return dir;
}
afterEach(async () => {
  await Promise.all(roots.splice(0).map(removeTestRoot));
});

/** Every file below `directory` (any extension), POSIX-style and relative, bytecode excluded. */
const sourceFiles = (directory: string) => listFiles(directory);

describe("Super Sejong runtime files", () => {
  // Bump together with a deliberate engine release: the version is recorded in every plan and in job state.
  it("pins ENGINE_VERSION: engine id, version and contract schema", async () => {
    expect(text("engine_runtime", "sejong", "ENGINE_VERSION")).toBe("id=super-sejong\nversion=2.1.0\nschema=1\n");
    expect(await readEngineVersion(engineRoot)).toEqual({ id: "super-sejong", version: "2.1.0", schema: 1 });
    expect(await readSejongEngineVersion(root)).toEqual({ id: "super-sejong", version: "2.1.0", schema: 1 });
  });

  it("keeps the version file in step with the TypeScript contract schema", async () => {
    const { schema } = await readEngineVersion(engineRoot);
    expect(SUPPORTED_ENGINE_SCHEMA).toBe(schema);
    expect(PLAN_SCHEMA).toBe(`sejong-plan/${schema}`);
    expect(CHECK_SCHEMA).toBe(`sejong-check/${schema}`);
    expect(ENGINE_VERSION_FILE).toBe("ENGINE_VERSION");
  });

  it("pins line endings of the version file so a Windows checkout cannot turn it into CRLF", () => {
    expect(text(".gitattributes")).toMatch(/^engine_runtime\/sejong\/ENGINE_VERSION text eol=lf$/m);
  });

  it("contains the contract files every later package builds on", async () => {
    // A floor, not the full list: later packages add modules and data files, which the packaging tests below cover.
    const required = [
      "ENGINE_VERSION",
      "__init__.py",
      "config.py",
      "io.py",
      "types.py",
      "schemas/plan.schema.json",
      "schemas/check.schema.json",
      "schemas/response.schema.json"
    ];
    await Promise.all(required.map(file => stat(path.join(engineRoot, file))));
    expect(await sourceFiles(engineRoot)).toEqual(expect.arrayContaining(required));
  });

  it("keeps engine_runtime/sejong importable as a package, not as a sys.path entry", async () => {
    // types.py and io.py would shadow the standard library if this directory itself were on sys.path.
    const files = await sourceFiles(engineRoot);
    expect(files).toContain("__init__.py");
    expect(files).toContain("types.py");
    expect(await readdir(path.join(root, "engine_runtime"))).toContain("sejong");
  });
});

describe("ENGINE_VERSION parsing", () => {
  const good = "id=super-sejong\nversion=2.0.0\nschema=1\n";

  it("accepts the canonical file and harmless layout variants", () => {
    const expected = { id: "super-sejong", version: "2.0.0", schema: 1 };
    for (const variant of [
      good,
      good.trimEnd(),
      good.replace(/\n/g, "\r\n"),
      `\n${good}\n\n`,
      "schema=1\nid=super-sejong\nversion=2.0.0\n",
      "id=super-sejong\n   \nversion=2.0.0\n\t\nschema=1\n"
    ]) {
      expect(parseEngineVersion(variant), JSON.stringify(variant)).toEqual(expected);
    }
    expect(parseEngineVersion("id=super-sejong\nversion=2.10.3-rc.1\nschema=12\n")).toEqual({
      id: "super-sejong",
      version: "2.10.3-rc.1",
      schema: 12
    });
  });

  it("rejects anything that is not exactly id, version and schema", () => {
    for (const bad of [
      "",
      "\n\n",
      "version=2.3.2\ncommit=9747f036cdc28a1a8aea4dc71fef1f7846eb96f7\n",
      "id=super-sejong\nversion=2.0.0\n",
      `${good}commit=abc\n`,
      `id=super-sejong\n${good}`,
      "id=other\nversion=2.0.0\nschema=1\n",
      "id=super-sejong\nversion=2.0\nschema=1\n",
      "id=super-sejong\nversion=02.0.0\nschema=1\n",
      "id=super-sejong\nversion=v2.0.0\nschema=1\n",
      "id=super-sejong\nversion=2.0.0 \nschema=1\n",
      "id=super-sejong\nversion=2.0.0\nschema=0\n",
      "id=super-sejong\nversion=2.0.0\nschema=01\n",
      "id=super-sejong\nversion=2.0.0\nschema=12345\n",
      "id=super-sejong\nversion=2.0.0\nschema= 1\n",
      "id = super-sejong\nversion = 2.0.0\nschema = 1\n",
      "id=super-sejong\nversion=2.0.0\nschema=1\nstray line\n"
    ]) {
      expect(() => parseEngineVersion(bad), JSON.stringify(bad)).toThrow(/^ENGINE_VERSION:/);
    }
  });

  it("compares versions with the minimum, ranking a pre-release of the minimum below it", () => {
    expect(engineVersionAtLeast("2.0.0")).toBe(true);
    expect(engineVersionAtLeast("2.0.1")).toBe(true);
    expect(engineVersionAtLeast("2.1.0-rc.1")).toBe(true);
    expect(engineVersionAtLeast("10.0.0")).toBe(true);
    expect(engineVersionAtLeast("1.99.99")).toBe(false);
    expect(engineVersionAtLeast("2.0.0-rc.1")).toBe(false);
    expect(engineVersionAtLeast("2.3.2", "2.3.2")).toBe(true);
    expect(engineVersionAtLeast("2.3.1", "2.3.2")).toBe(false);
    expect(() => engineVersionAtLeast("2.0", "2.0.0")).toThrow();
    expect(() => engineVersionAtLeast("2.0.0", "2.0.0-rc.1")).toThrow();
  });

  // The Python reader is the authority (it runs at import); the TypeScript reader and the packaging helper must
  // agree with it on every file, including the odd ones.
  it("agrees with the Python reader and the packaging helper on a shared corpus", async () => {
    const char = (code: number) => String.fromCharCode(code);
    const corpus: Record<string, string> = {
      canonical: good,
      noTrailingNewline: good.trimEnd(),
      crlf: good.replace(/\n/g, "\r\n"),
      loneCarriageReturn: good.replace(/\n/g, "\r"),
      blankAndSpaceLines: `\n  \n${good}\t\n`,
      reordered: "schema=1\nversion=2.0.0\nid=super-sejong\n",
      prerelease: "id=super-sejong\nversion=2.1.0-rc.1\nschema=3\n",
      unicodeLineSeparators: `id=super-sejong${char(0x2028)}version=2.0.0${char(0x85)}schema=1\n`,
      nbspBlankLine: `id=super-sejong\n${char(0xa0)}\nversion=2.0.0\nschema=1\n`,
      unitSeparatorBlankLine: `id=super-sejong\n${char(0x1f)}\nversion=2.0.0\nschema=1\n`,
      bomPrefix: `${char(0xfeff)}${good}`,
      bomLine: `id=super-sejong\n${char(0xfeff)}\nversion=2.0.0\nschema=1\n`,
      vendorFormat: "version=2.3.2\ncommit=9747f036cdc28a1a8aea4dc71fef1f7846eb96f7\n",
      empty: "",
      missingSchema: "id=super-sejong\nversion=2.0.0\n",
      extraKey: `${good}commit=abc\n`,
      duplicateKey: `id=super-sejong\n${good}`,
      wrongId: "id=other\nversion=2.0.0\nschema=1\n",
      shortVersion: "id=super-sejong\nversion=2.0\nschema=1\n",
      leadingZeroVersion: "id=super-sejong\nversion=02.0.0\nschema=1\n",
      trailingSpace: "id=super-sejong\nversion=2.0.0 \nschema=1\n",
      schemaZero: "id=super-sejong\nversion=2.0.0\nschema=0\n",
      schemaLeadingZero: "id=super-sejong\nversion=2.0.0\nschema=01\n",
      schemaTooLong: "id=super-sejong\nversion=2.0.0\nschema=12345\n",
      spacedEquals: "id = super-sejong\nversion = 2.0.0\nschema = 1\n",
      strayLine: `${good}stray\n`,
      emptyKey: `=x\n${good}`,
      equalsInValue: "id=super-sejong\nversion=2.0.0\nschema=1=1\n"
    };
    const dir = await scratch("version-corpus-");
    const names = Object.keys(corpus);
    await Promise.all(names.map((name, index) => writeFile(path.join(dir, `${index}.txt`), corpus[name] as string, "utf8")));
    const script =
      "import json,sys; sys.path.insert(0, sys.argv[1])\n" +
      "from engine_runtime.sejong import read_engine_version\n" +
      "out = []\n" +
      "for i in range(int(sys.argv[3])):\n" +
      "    try: out.append(read_engine_version(__import__('pathlib').Path(sys.argv[2]) / f'{i}.txt'))\n" +
      "    except ValueError: out.append(None)\n" +
      "print(json.dumps(out))\n";
    const python = JSON.parse(
      execFileSync(pythonCommand, ["-c", script, root, dir, String(names.length)], {
        encoding: "utf8",
        env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" }
      })
    ) as Array<{ id: string; version: string; schema: number } | null>;

    const attempt = (parse: (value: string) => unknown) => (value: string) => {
      try {
        return parse(value);
      } catch {
        return null;
      }
    };
    names.forEach((name, index) => {
      const value = corpus[name] as string;
      expect(attempt(parseEngineVersion)(value), `TypeScript reader, ${name}`).toEqual(python[index]);
      expect(attempt(parseSejongEngineVersion)(value), `packaging helper, ${name}`).toEqual(python[index]);
    });
    // The corpus must exercise both outcomes, or the comparison proves nothing.
    expect(python.filter(item => item !== null).length).toBeGreaterThanOrEqual(8);
    expect(python.filter(item => item === null).length).toBeGreaterThanOrEqual(15);
  });
});

describe("skill bundles carry engine_runtime/sejong/**", () => {
  it("stages every file of engine_runtime/sejong byte for byte, ENGINE_VERSION included", async () => {
    const stage = await scratch("skill-stage-");
    const destination = path.join(stage, "engine_runtime");
    await stageEngineRuntime(destination);

    const expected = await sourceFiles(engineRoot);
    expect(expected).toContain("ENGINE_VERSION");
    expect(await sourceFiles(path.join(destination, "sejong"))).toEqual(expected);
    for (const file of expected) {
      expect((await readFile(path.join(destination, "sejong", file))).equals(await readFile(path.join(engineRoot, file))), file).toBe(true);
    }
    // The legacy runtime still ships beside it.
    for (const file of ["workflow.py", "skill_gateway.py", "super_sejong.py", "documents/workflow.py"]) {
      await stat(path.join(destination, file));
    }
  });

  it("copies files of any extension and leaves Python bytecode out", async () => {
    const source = await scratch("skill-source-");
    const sejong = path.join(source, "engine_runtime", "sejong");
    await mkdir(path.join(sejong, "__pycache__"), { recursive: true });
    await mkdir(path.join(sejong, "data"), { recursive: true });
    await cp(path.join(engineRoot, "ENGINE_VERSION"), path.join(sejong, "ENGINE_VERSION"));
    await writeFile(path.join(sejong, "__init__.py"), "# package\n");
    await writeFile(path.join(sejong, "THIRD_PARTY.md"), "MIT notice\n");
    await writeFile(path.join(sejong, "requirements-worker.txt"), "kiwipiepy==0.24.0\n");
    await writeFile(path.join(sejong, "data", "words.json"), "[]\n");
    await writeFile(path.join(sejong, "__pycache__", "x.cpython-314.pyc"), "bytecode");

    const destination = path.join(source, "bundle", "engine_runtime");
    await stageEngineRuntime(destination, source);

    expect(await sourceFiles(path.join(destination, "sejong"))).toEqual([
      "ENGINE_VERSION", "THIRD_PARTY.md", "__init__.py", "data/words.json", "requirements-worker.txt"
    ]);
    await expect(stat(path.join(destination, "sejong", "__pycache__"))).rejects.toThrow();
    expect(bytecodeFilter("/x/sejong/__pycache__/a.pyc")).toBe(false);
    expect(bytecodeFilter("/x/sejong/a.pyc")).toBe(false);
    expect(bytecodeFilter("/x/sejong/a.py")).toBe(true);
  });

  it("refuses a bundle that lost a file, changed one or carries a bad version", async () => {
    const stage = await scratch("skill-broken-");
    const destination = path.join(stage, "engine_runtime");
    await stageEngineRuntime(destination);
    const version = path.join(destination, "sejong", "ENGINE_VERSION");
    const original = await readFile(version);

    await rm(version);
    await expect(assertSejongBundle(destination)).rejects.toThrow(/missing \[ENGINE_VERSION\]/);

    await writeFile(version, "id=super-sejong\nversion=2.0.0\nschema=1\n\n");
    await expect(assertSejongBundle(destination)).rejects.toThrow(/changed \[ENGINE_VERSION\]/);

    await writeFile(version, original);
    await expect(assertSejongBundle(destination)).resolves.toBeUndefined();
    await rm(path.join(destination, "sejong", "types.py"));
    await expect(assertSejongBundle(destination)).rejects.toThrow(/missing \[types\.py\]/);
  });

  it("imports in a bundle with the interpreter that will run it, and not without ENGINE_VERSION", async () => {
    const stage = await scratch("skill-import-");
    const destination = path.join(stage, "engine_runtime");
    await stageEngineRuntime(destination);

    expect(loadBundledSejong(pythonCommand, destination)).toEqual(await readSejongEngineVersion(root));

    await rm(path.join(destination, "sejong", "ENGINE_VERSION"));
    expect(() => loadBundledSejong(pythonCommand, destination)).toThrow(/failed to import/);
  });

  it("is what package-skills.mjs and verify-skill-packages.mjs use for both host bundles", () => {
    const packager = text("scripts", "package-skills.mjs");
    expect(packager).toMatch(/for \(const host of \["claude", "codex"\]\)/);
    expect(packager).toContain('await stageEngineRuntime(path.join(destination, "engine_runtime"))');
    expect(packager).toMatch(/distribution\.json[\s\S]*sejongEngine: sejong/);
    expect(packager).toContain("readSejongEngineVersion()");
    // The legacy vendor tree still ships until WP-18.
    expect(packager).toContain('"vendor/humanize-engine"');

    const verifier = text("scripts", "verify-skill-packages.mjs");
    expect(verifier).toContain('assertSejongBundle(path.join(skill, "engine_runtime"))');
    expect(verifier).toContain('loadBundledSejong(python, path.join(skill, "engine_runtime")');
    expect(verifier).toContain("distribution.sejongEngine");
  });

  it("makes the Python test runner stop early when the version file is unusable", () => {
    const runner = text("scripts", "python-tests.mjs");
    expect(runner).toContain("readSejongEngineVersion(root)");
    expect(runner).toContain("process.exit(1)");
  });
});

describe("desktop bundle carries engine_runtime/sejong/**", () => {
  // electron-builder's own matcher (pinned at 26.15.3 in package.json) decides what extraResources copies.
  const { FileMatcher } = requireFromTest("app-builder-lib/out/fileMatcher.js") as {
    FileMatcher: new (from: string, to: string, expand: (value: string) => string, patterns: string[]) => {
      createFilter(): (file: string, stat: import("node:fs").Stats) => boolean;
    };
  };
  const yaml = requireFromTest("js-yaml") as { load(source: string): { extraResources: Array<string | { from?: string; to?: string; filter?: string[] }> } };
  const resources = yaml.load(text("electron-builder.yml")).extraResources;
  const entry = resources.find((item): item is { from: string; to: string; filter?: string[] } => typeof item === "object" && item.from === "engine_runtime");

  /** Files of `directory` that electron-builder would copy: the file and every directory above it must pass. */
  async function shipped(directory: string): Promise<string[]> {
    const filter = new FileMatcher(directory, path.join(directory, "..", "out"), value => value, entry?.filter ?? []).createFilter();
    const passes = (file: string) => filter(file, statSync(file));
    const files = (await readdir(directory, { recursive: true, withFileTypes: true })).filter(item => item.isFile());
    return files
      .map(item => path.join(item.parentPath, item.name))
      .filter(file => {
        for (let dir = path.dirname(file); dir !== directory; dir = path.dirname(dir)) if (!passes(dir)) return false;
        return passes(file);
      })
      .map(file => path.relative(directory, file).split(path.sep).join("/"))
      .sort();
  }

  it("maps engine_runtime to engine/engine_runtime inside the app resources", () => {
    expect(entry).toBeDefined();
    expect(entry?.to).toBe("engine/engine_runtime");
    // preflight reads <projectRoot>/engine_runtime/sejong/ENGINE_VERSION and the app's projectRoot is resources/engine.
    expect(text("desktop", "main.ts")).toContain('path.join(process.resourcesPath, "engine")');
  });

  it("copies every file of engine_runtime, ENGINE_VERSION and files without a .py or .json extension included", async () => {
    const expected = await sourceFiles(path.join(root, "engine_runtime"));
    expect(expected).toContain("sejong/ENGINE_VERSION");
    expect(await shipped(path.join(root, "engine_runtime"))).toEqual(expected);
  });

  it("applies the same filter to files that only exist later: data, notices, requirements, and no bytecode", async () => {
    const dir = await scratch("desktop-filter-");
    for (const file of [
      "sejong/ENGINE_VERSION",
      "sejong/__init__.py",
      "sejong/THIRD_PARTY.md",
      "sejong/requirements-worker.txt",
      "sejong/data/misspellings.json",
      "sejong/__pycache__/types.cpython-314.pyc",
      "documents/__pycache__/model.cpython-314.pyc"
    ]) {
      await mkdir(path.dirname(path.join(dir, file)), { recursive: true });
      await writeFile(path.join(dir, file), "x");
    }
    expect(await shipped(dir)).toEqual([
      "sejong/ENGINE_VERSION",
      "sejong/THIRD_PARTY.md",
      "sejong/__init__.py",
      "sejong/data/misspellings.json",
      "sejong/requirements-worker.txt"
    ]);
  });

  it("is what package-desktop.mjs verifies and records", () => {
    const packager = text("scripts", "package-desktop.mjs");
    expect(packager).toContain('path.join("release", "win-unpacked", "resources", "engine", "engine_runtime")');
    expect(packager).toContain("assertSejongBundle(unpackedEngine)");
    expect(packager).toContain("sejongEngine: sejong");
    expect(packager).toContain("readSejongEngineVersion()");
    // Legacy vendor pin stays in build-info until WP-18.
    expect(packager).toContain("vendor/humanize-engine/ENGINE_VERSION");
  });
});
