/** Deterministic, conservative protection; this is not a semantic equivalence model. */
export interface SourceSentence { start: number; end: number; text: string; protected: boolean; concepts: string[] }
const segmenter = new Intl.Segmenter('ko', { granularity: 'sentence' });
const functionalNouns = new Set(['것','이것','그것','저것','수','중','등','점','경우','작업','수행','방식','부분','측면','통해','대해']);
// Match the complete remainder of a token, never just a particle-like prefix
// in a new compound such as 문제의식 or 자료가치. Unknown forms fail closed.
const conceptSuffixes = new Set([
  '', '의', '을', '를', '은', '는', '이', '가', '에', '로', '으로', '에서', '에게',
  '도', '만', '과', '와', '이다', '이며', '이고',
  '에는', '에도', '에만', '에서는', '에서도', '에서만',
  '에게는', '에게도', '에게만', '로는', '로도', '로만', '으로는', '으로도', '으로만',
  '와는', '과는', '와도', '과도', '와의', '과의',
  '만은', '만을', '만이', '만의', '만으로', '만으로도', '만으로는',
  '로부터', '로부터는', '로부터도', '으로부터', '으로부터는', '으로부터도'
]);
// Used only to prove that a changed protected sentence still occupies its
// original slot before literal restoration. This does not widen the ordinary
// concept fidelity gate below.
const restorationConceptSuffixes = new Set([
  ...conceptSuffixes,
  '하다', '한다', '했다', '하고', '하며', '하여', '해',
  '되다', '된다', '됐다', '되고', '되며', '되어', '돼'
]);
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
function preservesConcepts(original: SourceSentence, rewritten: SourceSentence, suffixes = conceptSuffixes): boolean {
  const tokens = rewritten.text.match(/[가-힣]+/gu) ?? [];
  return original.concepts.every(term => tokens.some(token =>
    token.startsWith(term) && suffixes.has(token.slice(term.length))
  ));
}

function couldCorrespondForRestoration(original: SourceSentence, rewritten: SourceSentence): boolean {
  return original.text === rewritten.text || (
    original.concepts.length > 0 && preservesConcepts(original, rewritten, restorationConceptSuffixes)
  );
}

function lineMarker(value: string): string | undefined {
  return value.match(/^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s?)/u)?.[0];
}

function lineSentenceCount(value: string): number {
  return [...segmenter.segment(value)].filter(item => item.segment.trim()).length;
}

export interface ProtectedSentenceRestoration {
  rewrittenText: string;
  restoredProtectedSentences: number;
}

/** Restore only mechanically aligned protected sentences. Ambiguous candidates
 * are returned untouched so the existing retry/rollback path remains active. */
export function restoreProtectedSentences(source: string, candidate: string): ProtectedSentenceRestoration {
  const sourceLines = source.split('\n'), candidateLines = candidate.split('\n');
  if (sourceLines.length !== candidateLines.length) {
    return { rewrittenText: candidate, restoredProtectedSentences: 0 };
  }
  for (let index = 0; index < sourceLines.length; index++) {
    const original = sourceLines[index]!, rewritten = candidateLines[index]!;
    if (Boolean(original.trim()) !== Boolean(rewritten.trim()) ||
        lineSentenceCount(original) !== lineSentenceCount(rewritten) ||
        lineMarker(original) !== lineMarker(rewritten) ||
        (/^\s*#{1,6}\s/u.test(original) && original !== rewritten)) {
      return { rewrittenText: candidate, restoredProtectedSentences: 0 };
    }
  }

  const originals = sourceSentences(source), rewritten = sourceSentences(candidate);
  if (originals.length !== rewritten.length) {
    return { rewrittenText: candidate, restoredProtectedSentences: 0 };
  }
  const changedProtected: Array<{ original: SourceSentence; rewritten: SourceSentence }> = [];
  for (let index = 0; index < originals.length; index++) {
    const original = originals[index]!, replacement = rewritten[index]!;
    if (!original.protected) {
      if (original.text !== replacement.text && (
        !original.concepts.length ||
        !preservesConcepts(original, replacement) ||
        originals.some((other, otherIndex) =>
          otherIndex !== index && other.protected && couldCorrespondForRestoration(other, replacement)
        )
      )) {
        return { rewrittenText: candidate, restoredProtectedSentences: 0 };
      }
      continue;
    }
    if (original.text === replacement.text) continue;
    // A changed protected sentence needs at least one recognized lexical anchor;
    // sentence counts alone are never treated as proof of correspondence.
    if (!original.concepts.length || !preservesConcepts(original, replacement, restorationConceptSuffixes)) {
      return { rewrittenText: candidate, restoredProtectedSentences: 0 };
    }
    const couldBelongElsewhere = originals.some((other, otherIndex) =>
      otherIndex !== index && couldCorrespondForRestoration(other, replacement)
    );
    if (couldBelongElsewhere) {
      return { rewrittenText: candidate, restoredProtectedSentences: 0 };
    }
    changedProtected.push({ original, rewritten: replacement });
  }
  if (!changedProtected.length) {
    return { rewrittenText: candidate, restoredProtectedSentences: 0 };
  }

  let repaired = candidate;
  for (const pair of changedProtected.sort((left, right) => right.rewritten.start - left.rewritten.start)) {
    repaired = repaired.slice(0, pair.rewritten.start) + pair.original.text + repaired.slice(pair.rewritten.end);
  }
  if (checkDirectTextFidelity(source, repaired).violations > 0) {
    return { rewrittenText: candidate, restoredProtectedSentences: 0 };
  }
  return { rewrittenText: repaired, restoredProtectedSentences: changedProtected.length };
}

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
    if (!preservesConcepts(original, rewritten)) violations++;
  }
  return { violations, protectedSentences: before.filter(sentence => sentence.protected).length };
}
