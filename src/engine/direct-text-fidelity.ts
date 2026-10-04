/** Deterministic, conservative protection; this is not a semantic equivalence model. */
export interface SourceSentence { start: number; end: number; text: string; protected: boolean; concepts: string[] }
const segmenter = new Intl.Segmenter('ko', { granularity: 'sentence' });
const functionalNouns = new Set(['것','이것','그것','저것','수','중','등','점','경우','작업','수행','방식','부분','측면','통해','대해',
  // Light nouns of 하다/되다 constructions; dropping them is the usual fix ("진행이 가능하다" → "할 수 있다").
  '진행','실시','시행']);
// Match the complete remainder of a token, never just a particle-like prefix
// in a new compound such as 문제의식 or 자료가치. Unknown forms fail closed.
const conceptSuffixes = new Set([
  '했는지', '했는지에', '됐는지', '됐는지에',
  '', '의', '을', '를', '은', '는', '이', '가', '에', '로', '으로', '에서', '에게',
  '도', '만', '과', '와', '이다', '이며', '이고',
  '에는', '에도', '에만', '에서는', '에서도', '에서만',
  '에게는', '에게도', '에게만', '로는', '로도', '로만', '으로는', '으로도', '으로만',
  '와는', '과는', '와도', '과도', '와의', '과의',
  '만은', '만을', '만이', '만의', '만으로', '만으로도', '만으로는',
  '로부터', '로부터는', '로부터도', '으로부터', '으로부터는', '으로부터도',
  // The same noun used as a 하다/되다 verb keeps the concept ("인정이 됩니다" → "인정됩니다").
  '합니다', '했습니다', '하였습니다', '됩니다', '됐습니다', '되었습니다', '하였다', '되었다',
  '하는', '되는', '한', '된', '할', '될', '하면', '되면', '해야', '돼야', '되어야', '하여야', '하므로', '되므로',
  '하여', '되어', '해', '돼', '하기', '되기', '함', '됨'
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
function hasProtectedMeaning(text: string): boolean {
  if (/금지|불가|불허|허용|의무/u.test(text)) return true;
  if (/[0-9'"“”‘’「」『』]/u.test(text)) return true;
  if (/수\s*(?:있|없)|(?:해|하여|어|아)야|않|없|아니|가능|추정|판단|듯|것\s*같|것으로\s*보|(?<!가지)(?<!갖)고\s*있/u.test(text)) return true;
  if (/(?:^|\s)(?:안|못)\s|[가-힣]+면(?:\s|,)|경우|때문|조건|이후|이전|전까지|후에|따라서/u.test(text)) return true;
  return false;
}
function risky(text: string): boolean {
  if (hasProtectedMeaning(text)) return true;
  // Multiple explicit subjects can hide object/value swaps despite unchanged noun sets.
  const subjects = [...text.matchAll(/([가-힣A-Za-z]+)(?:은|는|이|가)(?=\s)/gu)].filter(match => !isAdnominalVerb(match[0]));
  return subjects.length > 1;
}
// The elements that make a sentence protected. A protected sentence may be rephrased only when all of them
// survive unchanged. Freezing whole sentences kept about 72% of the owner's blog sentences from any edit;
// meaning beyond these markers is still checked by the Python gate (negation, modality, roles, numbers).
// Markers are compared by meaning class, not wording: "진행이 가능하며" → "할 수 있으며" keeps a possibility and
// "누락되는 경우에는" → "누락되면" keeps a condition. Earlier patterns win, and matched text is blanked so
// "불가능" counts once as impossibility.
const markerClasses: Array<[RegExp, string]> = [
  [/불가능|수\s*없|불가/gu, 'CANNOT'],
  [/금지|불허/gu, 'FORBID'],
  [/허용/gu, 'ALLOW'],
  [/의무|(?:해|하여|어|아|여)야/gu, 'MUST'],
  [/수\s*있|가능/gu, 'CAN'],
  [/추정|판단|듯|것\s*같|것으로\s*보/gu, 'HEDGE'],
  [/않|아니|없|(?:^|\s)(?:안|못)(?=\s)/gu, 'NEG'],
  [/(?<=[가-힣])면(?=\s|,)|경우|조건/gu, 'COND'],
  [/때문|따라서/gu, 'CAUSE'],
  [/이후|이전|전까지|후에/gu, 'ORDER'],
  [/(?<!가지)(?<!갖)고\s*있/gu, 'PROG']
];
function protectedElements(text: string): string {
  let rest = text;
  const markers: string[] = [];
  for (const [pattern, label] of markerClasses) {
    rest = rest.replace(pattern, match => { markers.push(label); return ' '.repeat(match.length); });
  }
  // Numbers and quotation marks keep their order: swapping two values ("12건 … 20건") changes the facts.
  const numbers = text.match(/[0-9]+(?:[.,:][0-9]+)*/gu) ?? [];
  const quotes = text.match(/['"“”‘’「」『』]/gu) ?? [];
  return `${markers.sort().join('|')}#${numbers.join('|')}#${quotes.join('')}`;
}
function explicitSubjects(text: string): string[] {
  // "N이 되다/아니다" marks a complement, not a second subject ("인정이 됩니다", "문제가 아닙니다").
  return [...text.matchAll(/([가-힣A-Za-z]+)(?:은|는|이|가)(?=\s)(?!\s+(?:[되돼됩됐될된]|아니|아닙|아닌))/gu)]
    .filter(match => !isAdnominalVerb(match[0])).map(match => match[0]);
}
function argumentNouns(text: string): string[] {
  const nouns: string[] = [];
  for (const token of text.match(/[가-힣A-Za-z0-9]+/gu) ?? []) {
    if (isAdnominalVerb(token)) continue;
    const noun = token.match(/^([가-힣A-Za-z0-9]+?)(?:에게|에서|으로|은|는|이|가|을|를|에|로|와|과|의)$/u)?.[1];
    if (noun && !functionalNouns.has(noun)) nouns.push(noun);
  }
  return nouns;
}
/** Nouns that still appear in the rewrite keep their relative order, so no two participants or values swapped. */
function argumentOrderPreserved(original: string, rewritten: string): boolean {
  const tokens = rewritten.match(/[가-힣A-Za-z0-9]+/gu) ?? [];
  let last = -1;
  for (const noun of argumentNouns(original)) {
    const position = tokens.findIndex(token => token.startsWith(noun));
    if (position < 0) continue;
    const next = tokens.findIndex((token, index) => index > last && token.startsWith(noun));
    if (next < 0) return false;
    last = next;
  }
  return true;
}
/** A rewritten protected sentence must keep its numbers (in order), quotation marks and possibility/negation/
 * obligation/condition markers by class. With several explicit subjects its nouns must also keep their order,
 * because values and roles can swap between subjects without any marker changing. */
export function preservesProtectedElements(original: string, rewritten: string): boolean {
  if (protectedElements(original) !== protectedElements(rewritten) || !preservesVoice(original, rewritten)) return false;
  return explicitSubjects(original).length < 2 || argumentOrderPreserved(original, rewritten);
}
// Voice lock (owner decision: every sentence keeps its own 말투 and honorifics). A minimal port of the Super
// Sejong v2 voice gate: speech level of the final ending, honorific -시- count, question/request/propositive mood,
// stance ending, humble verbs and CMC marks. On the v2 pair set it flags 2/64 preserving pairs (both real -시-
// losses) and catches 49/64 drifts; sentence splits, merges and quote changes are caught by the other guards.
const quotedSpan = /“[^”]*”|"[^"]*"|‘[^’]*’|'[^']*'|「[^」]*」|『[^』]*』/gu;
function sentenceEnd(text: string): string {
  return text.replace(quotedSpan, ' ').trim().replace(/[\s"”’')\]」』.!?。…~^ㅋㅎㅠㅜ]+$/u, '');
}
function speechLevel(text: string): string | undefined {
  const end = sentenceEnd(text);
  if (!end) return undefined;
  if (/(?:니다|니까|십시오|시오|십시다|합시다|읍시다|옵니다)$/u.test(end)) return 'hapsyo';
  if (/(?:요|죠)$/u.test(end) && !/(?:필요|중요|수요|주요)$/u.test(end)) return 'haeyo';
  if (/(?:다|까|냐|구나|자|라)$/u.test(end)) return 'haera';
  return undefined;
}
const honorificNoun = /(?:[출대자당통혁최확과정갱경헌배송수발전]신|신청|신고|신규|신뢰|신속|마시|마셨|마셔|가르치|실시|제시|표시|개시|무시|지시|명시|게시|감시|전시|동시|당시|즉시|수시|역시|다시|혹시|서울시|도시|시시|교시|응시|착시|중시|간주시)(?=[는가도를의에]|\s|$)/gu;
const honorificSi = /(?<=[가-힣])(?:시(?=[는고면며기지어겠었다]|$)|셨|셔|세요|십|신(?=\s|$|가|건|데|지|다))|계시|계셔|계세|계십|계신|드시|드셔|주무시|께서/gu;
function honorifics(text: string): number {
  return text.replace(quotedSpan, ' ').replace(/[^가-힣\s]+/gu, ' ').replace(honorificNoun, ' ').match(honorificSi)?.length ?? 0;
}
function voiceSignature(text: string): string {
  const question = /\?\s*["”’)]*\s*$/u.test(text.replace(quotedSpan, ' ').trim());
  const end = sentenceEnd(text);
  const request = !question && /(?:세요|십시오|주세요|마세요|바랍니다|부탁드립니다|해라|하라|보세요|주십시오)$/u.test(end);
  const propositive = /(?:자|십시다|합시다|읍시다)$/u.test(end);
  const stance = end.match(/(?:더라고요?|거든요?|잖아요?|네요|군요|답니다|랍니다|지요|죠)$/u)?.[0]?.replace(/요$/u, '') ?? '';
  const humble = text.match(/드리|드립|드려|드렸|여쭈|여쭙|여쭤|뵙|뵈|뵐|모시|모셔/gu)?.length ?? 0;
  const marks = (text.match(/[ㅋㅎㅠㅜ]+|\^\^|~/gu) ?? []).join('');
  return [honorifics(text), question, request, propositive, stance, humble, marks].join('|');
}
/** The rewritten sentence keeps the source sentence's speech level, honorifics, mood, stance and marks. */
export function preservesVoice(original: string, rewritten: string): boolean {
  const before = speechLevel(original), after = speechLevel(rewritten);
  if (before && after && before !== after) return false;
  return voiceSignature(original) === voiceSignature(rewritten);
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
function permitsFunctionalProcessOmission(source: string, candidate: string): boolean {
  const construction = /(?<![가-힣])([가-힣]+)하는 과정(?:에서|에 있어서)(?![가-힣])/gu;
  const matches = [...source.matchAll(construction)];
  // Every process reference must be functional; a second substantive reference
  // cannot disappear merely because a functional one is also present.
  if (!matches.length || /(?<![가-힣])과정[가-힣]*/u.test(source.replace(construction, ''))) return false;
  const tokens: string[] = candidate.match(/[가-힣]+/gu) ?? [];
  const retained = [...candidate.matchAll(construction)].map(match => match[1]);
  return matches.every(match => tokens.includes(`${match[1]}하면서`) || tokens.includes(`${match[1]}하며`) || retained.includes(match[1]));
}

// The noun used as a 하다/되다/받다 verb ("요청이 이루어질" → "요청받을") keeps the concept; a new compound
// noun ("문제의식", "자료가치") does not, because its remainder starts with another syllable.
const verbalStem = /^(하|한|할|함|합|해|했|되|된|될|됨|됩|돼|됐|받)(.*)$/u;
const verbalTails = new Set(['', '다', '니다', '습니다', '는', '은', '을', '고', '며', '면', '서', '어', '아', '여', '야', '도',
  '지', '기', '게', '요', '어요', '아요', '었다', '았다', '었고', '았고', '었습니다', '았습니다', '는지', '는데', '으면', '으며',
  '므로', '니까', '지만', '면서', '도록', '려면', '어서', '아서', '여서', '던', '었던', '았던', '는다']);
function isVerbalRealization(remainder: string): boolean {
  const match = remainder.match(verbalStem);
  return Boolean(match && verbalTails.has(match[2]!));
}
function preservesConcepts(original: SourceSentence, rewritten: SourceSentence, suffixes = conceptSuffixes): boolean {
  const tokens = rewritten.text.match(/[가-힣]+/gu) ?? [];
  return original.concepts.every(term => (term === '과정' && permitsFunctionalProcessOmission(original.text, rewritten.text)) || tokens.some(token =>
    token.startsWith(term) && (suffixes.has(token.slice(term.length)) || isVerbalRealization(token.slice(term.length)))
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

// "...", "⋯" and "…" are one mark; respelling it must not change sentence counts.
function normalizeEllipsis(value: string): string {
  return value.replace(/\.{3}|⋯/gu, '…');
}

function lineSentenceCount(value: string): number {
  return [...segmenter.segment(normalizeEllipsis(value))].filter(item => item.segment.trim()).length;
}

/** Sentences for counting and comparison only; offsets refer to the normalized text. */
function comparableSentences(value: string): SourceSentence[] {
  return sourceSentences(normalizeEllipsis(value));
}

// Prompt delimiters carry a 32-hex nonce; echoing one means the model copied the envelope.
const promptBoundary = /(?:BEGIN|END)_(?:SOURCE|CANDIDATE)_[0-9a-f]{32}/gu;

function bigrams(text: string): Map<string, number> {
  const characters = Array.from(text.replace(/\s+/gu, ''));
  const counts = new Map<string, number>();
  for (let index = 0; index + 1 < characters.length; index++) {
    const key = characters[index]! + characters[index + 1]!;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

function similarity(left: Map<string, number>, right: Map<string, number>): number {
  let overlap = 0, total = 0;
  for (const [key, count] of left) { overlap += Math.min(count, right.get(key) ?? 0); total += count; }
  for (const count of right.values()) total += count;
  return total ? 2 * overlap / total : 0;
}

/** Extra verbatim copies of a source sentence. A copy is an in-place rewrite
 * only when an equally similar source sentence left the output (e.g. "가지고
 * 있다" rewritten into an existing "가진다"); splits never copy a whole sentence. */
function duplicatedSentences(before: SourceSentence[], after: SourceSentence[]): number {
  const counts = (items: SourceSentence[]) => items.reduce((map, item) => map.set(item.text, (map.get(item.text) ?? 0) + 1), new Map<string, number>());
  const sourceCounts = counts(before), outputCounts = counts(after);
  const missing = [...sourceCounts].flatMap(([text, count]) => Array(Math.max(0, count - (outputCounts.get(text) ?? 0))).fill(bigrams(text)) as Map<string, number>[]);
  let violations = 0;
  for (const [text, count] of outputCounts) {
    const extra = count - (sourceCounts.get(text) ?? 0);
    if (extra <= 0 || !sourceCounts.has(text)) continue;
    const grams = bigrams(text);
    let explained = 0;
    for (let index = 0; index < missing.length && explained < extra; index++) {
      if (similarity(grams, missing[index]!) >= 0.5) { missing.splice(index--, 1); explained++; }
    }
    if (explained < extra) violations++;
  }
  return violations;
}

/** Direct text only: a slot now holds another source sentence verbatim and no
 * longer resembles its own original. */
function movedSentences(before: SourceSentence[], after: SourceSentence[]): number {
  let violations = 0;
  after.forEach((sentence, index) => {
    const own = before[index];
    if (sentence.text === own?.text || !before.some((other, otherIndex) => otherIndex !== index && other.text === sentence.text)) return;
    if (!own || similarity(bigrams(sentence.text), bigrams(own.text)) < 0.5) violations++;
  });
  return violations;
}

/** Nearby rewritten sentences that clearly match a different source slot. The
 * window and margins keep in-place rewrites of parallel sentences acceptable. */
function reorderedSentences(before: SourceSentence[], after: SourceSentence[]): number {
  const sourceGrams = before.map(sentence => bigrams(sentence.text));
  let violations = 0;
  after.forEach((sentence, index) => {
    if (index >= before.length || sentence.text === before[index]!.text) return;
    // A verbatim copy of a sentence that still stands in its own slot is an
    // in-place rewrite into identical wording, not a reorder; duplicatedSentences judges it.
    if (before.some((other, otherIndex) => otherIndex !== index && other.text === sentence.text && after[otherIndex]?.text === other.text)) return;
    const grams = bigrams(sentence.text);
    const own = similarity(grams, sourceGrams[index]!);
    for (let other = Math.max(0, index - 3); other <= Math.min(before.length - 1, index + 3); other++) {
      if (other === index) continue;
      const score = similarity(grams, sourceGrams[other]!);
      if (score >= 0.85 && score - own >= 0.2) { violations++; return; }
    }
  });
  return violations;
}

/** Structure guard shared by every input kind: paragraph layout, Markdown
 * markers, prompt echo and duplicated sentences. File inputs may split or merge
 * sentences (the rulebook prescribes it); dropped content is the Python gate's. */
export function checkStructuralFidelity(source: string, candidate: string): number {
  let violations = 0;
  const sourceLines = source.split('\n'), outputLines = candidate.split('\n');
  if (sourceLines.length !== outputLines.length) violations++;
  sourceLines.forEach((line, index) => {
    const output = outputLines[index];
    if (output === undefined) return;
    if (Boolean(line.trim()) !== Boolean(output.trim())) violations++;
    if (lineMarker(line) !== lineMarker(output)) violations++;
  });
  if ((candidate.match(promptBoundary)?.length ?? 0) > (source.match(promptBoundary)?.length ?? 0)) violations++;
  return violations + duplicatedSentences(comparableSentences(source), comparableSentences(candidate));
}

export interface ProtectedSentenceRestoration {
  rewrittenText: string;
  restoredProtectedSentences: number;
}

/** Restore only mechanically aligned protected sentences whose protected elements changed. Ambiguous candidates
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
    if (original.text === replacement.text || preservesProtectedElements(original.text, replacement.text)) continue;
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
  const before = comparableSentences(source), after = comparableSentences(candidate);
  let violations = checkStructuralFidelity(source, candidate);
  // Direct text forbids splitting and merging sentences, so counts must match.
  const outputLines = candidate.split('\n');
  source.split('\n').forEach((line, index) => {
    const output = outputLines[index];
    if (output === undefined) return;
    if (lineSentenceCount(line) !== lineSentenceCount(output)) violations++;
    if (/^\s*#{1,6}\s/u.test(line) && line !== output) violations++;
  });
  if (before.length !== after.length) violations++;
  violations += movedSentences(before, after);
  violations += reorderedSentences(before, after);
  for (let index = 0; index < before.length; index++) {
    const original = before[index]!, rewritten = after[index];
    if (!rewritten) continue;
    if (original.protected && original.text !== rewritten.text && !preservesProtectedElements(original.text, rewritten.text)) violations++;
    // Protection is bidirectional: a factual statement must not become a
    // negative, obligation, possibility or condition during an ordinary rewrite.
    if (!original.protected && hasProtectedMeaning(rewritten.text)) violations++;
    if (!preservesConcepts(original, rewritten)) violations++;
    if (original.text !== rewritten.text && !preservesVoice(original.text, rewritten.text)) violations++;
  }
  return { violations, protectedSentences: before.filter(sentence => sentence.protected).length };
}
