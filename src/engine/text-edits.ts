import { EngineError } from './errors.js';
import { parseEngineResult, type CodexResult } from './codex-runner.js';

/** Exact, unique anchors avoid model-generated Unicode offsets and ambiguous edits.
 * Reconstruct locally; the normal restore and full-document gates still run. */
export function parseTextResult(raw: string, source: string, label = 'CLI'): CodexResult {
  const fail = (): never => { throw new EngineError('ENGINE_OUTPUT_INVALID', false, `${label} text edits are invalid or ambiguous`); };
  let value: Record<string, unknown>;
  try { value = JSON.parse(raw); } catch { return fail(); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail();
  // Previous full-text protocol remains readable for existing integrations.
  if (!('edits' in value)) return parseEngineResult(raw, label);
  if (Object.keys(value).some(key => !['rewrittenText', 'edits', 'warnings'].includes(key)) ||
      typeof value.rewrittenText !== 'string' || !Array.isArray(value.edits) || value.edits.length > 200) return fail();
  if (value.rewrittenText.length) {
    if (value.edits.length) return fail();
    return parseEngineResult(raw, label);
  }
  let cursor = 0;
  const pieces: string[] = [];
  for (const edit of value.edits) {
    if (!edit || typeof edit !== 'object' || Array.isArray(edit) ||
        Object.keys(edit).sort().join(',') !== 'after,before' ||
        typeof edit.before !== 'string' || !edit.before.length ||
        typeof edit.after !== 'string' || edit.after.length > 100000) return fail();
    const at = source.indexOf(edit.before);
    if (at < cursor || at < 0 || source.indexOf(edit.before, at + 1) !== -1) return fail();
    pieces.push(source.slice(cursor, at), edit.after);
    cursor = at + edit.before.length;
  }
  pieces.push(source.slice(cursor));
  return parseEngineResult(JSON.stringify({rewrittenText: pieces.join(''), warnings: value.warnings}), label);
}
