import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { MAX_OFFICE_FILE_BYTES, OFFICE_LIMIT_CODE } from '../../src/documents/limits.js';
import { MAX_INPUT_CHARS } from '../../src/engine/input-limits.js';

/** A module-level `NAME = value` of a Python file, evaluated as JavaScript (the values are numbers and strings
 * written the same way in both languages: `50 * 1024**2`, `100_000`, `'DOCUMENT_TOO_LARGE'`). */
function python(file: string, name: string): unknown {
  const match = readFileSync(file, 'utf8').match(new RegExp(`^${name} = ([^#\\n]+)`, 'm'));
  if (!match) throw new Error(`${name} is not defined in ${file}`);
  return new Function(`return (${match[1]!.trim()});`)();
}

it('keeps the Office limits of Python and TypeScript the same', () => {
  // The portal, the app and the MCP server check the file size before Python sees the file; the Gateway prints
  // Python's limit errors with the code the TypeScript surfaces report.
  expect(python('engine_runtime/documents/package.py', 'MAX_FILE')).toBe(MAX_OFFICE_FILE_BYTES);
  expect(python('engine_runtime/documents/package.py', 'LIMIT_CODE')).toBe(OFFICE_LIMIT_CODE);
  // The extracted-text limit of a document is the text input limit of the portal.
  expect(python('engine_runtime/documents/model.py', 'MAX_CHARS')).toBe(MAX_INPUT_CHARS);
});
