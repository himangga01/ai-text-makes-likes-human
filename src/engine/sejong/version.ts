/** Super Sejong Engine version pin (DESIGN.md 4.1, 5.2; T1 report section 2 "Version pin").
 *
 * engine_runtime/sejong/ENGINE_VERSION keeps the vendor's key=value format with different keys:
 *   id=super-sejong   X.Y.Z   schema=N
 * This module follows the rules of read_engine_version() in engine_runtime/sejong/__init__.py (exactly
 * these three keys, no duplicates, no whitespace around keys or values) so both languages accept and
 * reject the same files; tests/unit/sejong-engine-files.test.ts compares them on a shared corpus.
 * A file of any other shape is a packaging error, never a reason to guess.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { ENGINE_ID, PLAN_SCHEMA } from './types.js';

export interface EngineVersion {
  id: typeof ENGINE_ID;
  version: string;
  schema: number;
}

export const ENGINE_VERSION_FILE = 'ENGINE_VERSION';
/** Oldest engine the product accepts when v2 is selected (DESIGN 4.5: `super-sejong` >= 2.0.0). */
export const MINIMUM_ENGINE_VERSION = '2.0.0';
/** Contract schema this build's TypeScript types and parsers read ("sejong-plan/N" -> N). */
export const SUPPORTED_ENGINE_SCHEMA = Number(PLAN_SCHEMA.slice(PLAN_SCHEMA.indexOf('/') + 1));

const SEMVER = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?$/;
const SCHEMA = /^[1-9][0-9]{0,3}$/;
// Python str.splitlines() boundaries and str.isspace(): kept identical so a file means the same in both readers.
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/;
const BLANK_LINE = /^[\t\v\f \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/;

/** Parses the text of an ENGINE_VERSION file; throws Error('ENGINE_VERSION: ...') when it is not valid. */
export function parseEngineVersion(text: string): EngineVersion {
  const entries = new Map<string, string>();
  for (const line of text.split(LINE_BREAK)) {
    if (BLANK_LINE.test(line)) continue;
    const separator = line.indexOf('=');
    const key = separator < 0 ? '' : line.slice(0, separator);
    if (separator < 0 || entries.has(key)) throw new Error('ENGINE_VERSION: malformed line');
    entries.set(key, line.slice(separator + 1));
  }
  if ([...entries.keys()].sort().join(',') !== 'id,schema,version') {
    throw new Error('ENGINE_VERSION: keys must be exactly id, version, schema');
  }
  const id = entries.get('id');
  const version = entries.get('version');
  const schema = entries.get('schema');
  if (id !== ENGINE_ID || version === undefined || !SEMVER.test(version) || schema === undefined || !SCHEMA.test(schema)) {
    throw new Error('ENGINE_VERSION: invalid id, version or schema');
  }
  return { id, version, schema: Number(schema) };
}

/** Reads `<engineRoot>/ENGINE_VERSION`; engineRoot is engine_runtime/sejong (src/config.ts `engineRoot`). */
export async function readEngineVersion(engineRoot: string): Promise<EngineVersion> {
  return parseEngineVersion(await readFile(path.join(engineRoot, ENGINE_VERSION_FILE), 'utf8'));
}

/** True when `version` (X.Y.Z[-pre]) is at least `minimum` (X.Y.Z, no pre-release part).
 * A pre-release of the minimum itself ranks below it, as in semantic versioning. */
export function engineVersionAtLeast(version: string, minimum: string = MINIMUM_ENGINE_VERSION): boolean {
  const current = SEMVER.exec(version);
  const required = SEMVER.exec(minimum);
  if (!current || !required || required[4] !== undefined) throw new Error('engine version comparison needs X.Y.Z[-pre] and X.Y.Z');
  for (let index = 1; index <= 3; index += 1) {
    const a = Number(current[index]);
    const b = Number(required[index]);
    if (a !== b) return a > b;
  }
  return current[4] === undefined;
}
