/** Deterministic, conservative protection; this is not a semantic equivalence model. */
export interface SourceSentence { start: number; end: number; text: string; protected: boolean; concepts: string[] }
const segmenter = new Intl.Segmenter('ko', { granularity: 'sentence' });
const functionalNouns = new Set(['것','이것','그것','저것','수','중','등','점','경우','작업','수행','방식','부분','측면','통해','대해']);
function isAdnominalVerb(token: string): boolean {
  return /(?:하는|되는|있는|없는|않는)$/u.test(token);
}
function concepts(text: string): string[] {
  const terms: string[] = [];
  for (const token of text.match(/[가-힣]+/gu) ?? []) {
    if (isAdnominalVerb(token)) continue;
    const match = token.match(/^([가-힣]+?)(?:에서|에게|으로|에는|에서는|이다|이며|이고|의|을|를|은|는|이|가|에|로)$/u);
    const noun = match?.[1];
    if (noun && noun.length >= 2 && !functionalNouns.has(noun)) terms.push(noun);
  }
  return [...new Set(terms)];
}
function risky(text: string): boolean {
  if (/[0-9'"“”‘’「」『』]/u.test(text)) return true;
  if (/수\s*(?:있|없)|(?:해|하여|어|아)야|않|없|아니|가능|추정|판단|듯|것\s*같|것으로\s*보|(?<!가지)(?<!갖)고\s*있/u.test(text)) return true;
  if (/(?:^|\s)(?:안|못)\s|[가-힣]+면(?:\s|,)|경우|때문|조건|이후|이전|전까지|후에|따라서/u.test(text)) return true;
  // Multiple explicit subjects can hide object/value swaps despite unchanged noun sets.
  const subjects = [...text.matchAll(/([가-힣A-Za-z]+)(?:은|는|이|가)(?=\s)/gu)].filter(match => !isAdnominalVerb(match[0]));
  return subjects.length > 1;
}
export function sourceSentences(source: string): SourceSentence[] {
  const result: SourceSentence[] = [];
  let lineStart = 0;
  for (const line of source.split('\n')) {
    for (const item of segmenter.segment(line)) {
      const text = item.segment.trim();
      if (!text) continue;
      const start = lineStart + item.index + item.segment.indexOf(text);
      result.push({ start, end: start + text.length, text, protected: risky(text), concepts: concepts(text) });
    }
    lineStart += line.length + 1;
  }
  return result;
}
export interface FidelityReport { violations: number; protectedSentences: number }
export function checkDirectTextFidelity(source: string, candidate: string): FidelityReport {
  const before = sourceSentences(source), after = sourceSentences(candidate);
  let violations = 0;
  const sourceLines = source.split('\n'), outputLines = candidate.split('\n');
  if (sourceLines.length !== outputLines.length) violations++;
  sourceLines.forEach((line, index) => {
    const output = outputLines[index];
    if (output === undefined) return;
    if (Boolean(line.trim()) !== Boolean(output.trim())) violations++;
    const marker = line.match(/^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s?)/u)?.[0];
    const other = output.match(/^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s?)/u)?.[0];
    if (marker !== other || (/^\s*#{1,6}\s/u.test(line) && line !== output)) violations++;
    const count = (value:string) => [...segmenter.segment(value)].filter(item => item.segment.trim()).length;
    if (count(line) !== count(output)) violations++;
  });
  if (before.length !== after.length) violations++;
  for (let index = 0; index < before.length; index++) {
    const original = before[index]!, rewritten = after[index];
    if (!rewritten) continue;
    if (original.protected && original.text !== rewritten.text) violations++;
    if (original.concepts.some(term => !(rewritten.text.match(/[가-힣]+/gu) ?? []).some(token => token === term || new RegExp(`^${term}(?:에서|에게|으로|이다|이며|이고|의|을|를|은|는|이|가|에|로|도|과|와|만)`, 'u').test(token)))) violations++;
  }
  return { violations, protectedSentences: before.filter(sentence => sentence.protected).length };
}
