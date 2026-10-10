import { legacyRewriteOptions, type RewriteOptions } from './rewrite-policy.js';
import { sourceSentences } from './direct-text-fidelity.js';
import { EngineError } from './errors.js';
import { parseEngineResult, type CodexResult } from './codex-runner.js';

/** Exact, unique anchors avoid model-generated Unicode offsets and ambiguous edits.
 * Reconstruct locally; the normal restore and full-document gates still run. */
export function parseTextResult(raw: string, source: string, label = 'CLI', options?: RewriteOptions): CodexResult {
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
  const sentences = legacyRewriteOptions(options)?.inputKind === 'direct-text' ? sourceSentences(source) : undefined;
  let fidelityIssues = 0;
  const intervals: Array<{ at: number; before: string; after: string }> = [];
  for (const edit of value.edits) {
    if (!edit || typeof edit !== 'object' || Array.isArray(edit) ||
        Object.keys(edit).sort().join(',') !== 'after,before' ||
        typeof edit.before !== 'string' || !edit.before.length ||
        typeof edit.after !== 'string' || edit.after.length > 100000) return fail();
    const at = source.indexOf(edit.before);
    if (at < 0 || source.indexOf(edit.before, at + 1) !== -1) return fail();
    intervals.push({ at, before: edit.before, after: edit.after });
  }
  // Unique anchors fix each edit's position, so arrival order carries no meaning;
  // overlaps are still rejected below.
  intervals.sort((left, right) => left.at - right.at);
  let cursor = 0;
  const pieces: string[] = [];
  for (const edit of intervals) {
    const at = edit.at;
    if (at < cursor) return fail();
    if (sentences && edit.before !== edit.after) {
      // Trim unchanged disambiguating context before checking the local source span.
      let prefix = 0, suffix = 0;
      while (prefix < edit.before.length && prefix < edit.after.length && edit.before[prefix] === edit.after[prefix]) prefix++;
      while (suffix < edit.before.length - prefix && suffix < edit.after.length - prefix && edit.before[edit.before.length - suffix - 1] === edit.after[edit.after.length - suffix - 1]) suffix++;
      const start = at + prefix, end = at + edit.before.length - suffix;
      if (!sentences.some(sentence => start >= sentence.start && end <= sentence.end)) fidelityIssues++;
    }
    pieces.push(source.slice(cursor, at), edit.after);
    cursor = at + edit.before.length;
  }
  pieces.push(source.slice(cursor));
  const result = parseEngineResult(JSON.stringify({rewrittenText: pieces.join(''), warnings: value.warnings}), label);
  return fidelityIssues ? {...result, fidelityIssues} : result;
}
