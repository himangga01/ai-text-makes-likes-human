/** Super Sejong Engine: bounded, source-anchored Korean style hypotheses.
 * Findings guide model attention; they are never automatic edits or quality scores.
 * start/end are UTF-16 offsets into the exact string passed to diagnoseKoreanStyle
 * (in the pipeline: the chunk source, not the whole document).
 */
export type StyleRuleId =
  | 'PROCESS_NOMINALIZATION' | 'PUBLIC_LANGUAGE_FRAME'
  | 'IMPORTANCE_FORMULA' | 'CONCLUDING_SIGNPOST' | 'DEMONSTRATIVE_THROUGH' | 'ROLE_FORMULA'
  | 'BOILERPLATE_ANNOUNCE' | 'DOUBLE_PASSIVE' | 'CAUSAL_LEAD'
  | 'INTENSIFIER_CLUSTER' | 'THROUGH_CLUSTER' | 'JEOK_CLUSTER' | 'CAPABILITY_HEDGE_CLUSTER'
  | 'CONNECTOR_RUN' | 'ENDING_MONOTONY';

export interface StyleFinding {
  ruleId: StyleRuleId;
  start: number;
  end: number;
}

interface Span { start: number; end: number }
const MAX_FINDINGS = 12;
const HANGUL = /[가-힣]/u;

/* ---------- protected text and prose ranges ---------- */

function markProtected(mask: Uint8Array, start: number, end: number): void {
  mask.fill(1, Math.max(0, start), Math.min(mask.length, end));
}

function isProtected(mask: Uint8Array, start: number, end: number): boolean {
  for (let i = start; i < end; i++) if (mask[i]) return true;
  return false;
}

/** Quote pairs that may continue across single line breaks but never across a blank line. */
function protectQuotes(source: string, mask: Uint8Array): void {
  const pairs: RegExp[] = [
    new RegExp(String.raw`"[^"\n]*(?:\n[^"\n]+){0,5}"`, 'gu'),
    /“[^”]{0,600}”/gu, /‘[^’]{0,600}’/gu, /「[^」]{0,600}」/gu, /『[^』]{0,600}』/gu,
    // Straight single quotes count as quotes only when they open at a boundary
    // (not an apostrophe inside a word such as don't) and close before a non-ASCII-word char.
    /(?<![A-Za-z0-9가-힣])'[^'\n]{1,300}'(?![A-Za-z0-9])/gu
  ];
  for (const expression of pairs)
    for (const match of source.matchAll(expression)) {
      // A pair crossing a blank line is a stray quote, not a quotation.
      if (/\n[ \t]*\n/u.test(match[0])) continue;
      markProtected(mask, match.index, match.index + match[0].length);
    }
}

/** Inline code with a linear scan: an opening backtick run closes at the next run of the same length
 * within 400 units on the same line (a regex with a backreference is quadratic on long backtick runs). */
function protectInlineCode(source: string, mask: Uint8Array): void {
  const n = source.length;
  let i = 0;
  while (i < n) {
    if (source.charAt(i) !== '`') { i++; continue; }
    let j = i;
    while (j < n && source.charAt(j) === '`') j++;
    const length = j - i;
    let k = j, closed = -1;
    const limit = Math.min(n, j + 400);
    while (k < limit && source.charAt(k) !== '\n') {
      if (source.charAt(k) === '`') {
        let m = k;
        while (m < n && source.charAt(m) === '`') m++;
        if (m - k === length) { closed = m; break; }
        k = m;
      } else k++;
    }
    if (closed >= 0) { markProtected(mask, i, closed); i = closed; } else i = j;
  }
}

function protectInline(source: string, mask: Uint8Array): void {
  protectInlineCode(source, mask);
  const inline: RegExp[] = [
    /\]\([^)\n]{0,2000}\)/gu,                     // link / image destination
    /\[\^[^\]\n]{1,40}\]/gu,                      // footnote reference or label
    /(?:https?|ftp):\/\/[^\s<>)\]]+/gu,           // bare URL
    /<\/?[A-Za-z][^>\n]{0,300}>/gu,               // HTML tag / autolink
    /\{\{[^}\n]{1,200}\}\}|\$\$?[^$\n]{1,200}\$\$?/gu // template / math literal
  ];
  for (const expression of inline)
    for (const match of source.matchAll(expression)) markProtected(mask, match.index, match.index + match[0].length);
}

/** Maximal runs of prose lines (no blank line between), so a rule may match across a soft wrap. */
function proseRanges(source: string, mask: Uint8Array): Span[] {
  const ranges: Span[] = [];
  let fence: string | undefined, offset = 0, open: Span | undefined, previousBlank = true, inList = false, inCode = false;
  const close = () => { if (open) ranges.push(open); open = undefined; };
  for (const line of source.split('\n')) {
    const lineEnd = offset + line.length;
    const fenceMatch = /^\s*(```+|~~~+)/u.exec(line);
    let prose = false;
    if (fence !== undefined) {
      if (fenceMatch && fenceMatch[1]!.charAt(0) === fence.charAt(0) && fenceMatch[1]!.length >= fence.length) fence = undefined;
      markProtected(mask, offset, lineEnd);
    } else if (fenceMatch) {
      fence = fenceMatch[1]!;
      markProtected(mask, offset, lineEnd);
    } else if (!line.trim()) {
      previousBlank = true; inCode = false;
    } else {
      const indented = /^(?: {4,}|\t)/u.test(line);
      const listItem = /^\s*(?:[-*+]|\d{1,9}[.)])\s+/u.exec(line);
      if (inCode || (indented && previousBlank && !inList)) {
        inCode = true;
        markProtected(mask, offset, lineEnd);
      } else if (/^\s{0,3}#{1,6}(?:\s|$)/u.test(line) || /^\s{0,3}>/u.test(line)) {
        inList = false;
      } else if (/^\s*\|.*\|\s*$/u.test(line) || /^\s*[:\-| ]{3,}\s*$/u.test(line) && line.includes('|')) {
        markProtected(mask, offset, lineEnd);
      } else if (/^\s{0,3}\[[^\]\n]+\]:\s*\S/u.test(line) && !/^\s{0,3}\[\^/u.test(line)) {
        markProtected(mask, offset, lineEnd);
      } else if (/^\s{0,3}(?:[-*_]\s*){3,}$/u.test(line)) {
        inList = false;
      } else {
        if (listItem) { markProtected(mask, offset, offset + listItem[0].length); inList = true; }
        else if (!indented) inList = false;
        const footnote = /^\s{0,3}\[\^[^\]\n]+\]:\s*/u.exec(line);
        if (footnote) markProtected(mask, offset, offset + footnote[0].length);
        prose = true;
      }
      previousBlank = false;
    }
    if (prose) {
      if (open) open.end = lineEnd; else open = { start: offset, end: lineEnd };
    } else close();
    offset = lineEnd + 1;
  }
  close();
  return ranges;
}

/* ---------- rule tables ---------- */

type Guard = (source: string, start: number, end: number) => boolean;
interface PatternRule { ruleId: StyleRuleId; expression: RegExp; lead?: number; guard?: Guard; }
interface ClusterRule { ruleId: StyleRuleId; expression: RegExp; min: number; window: number; guard?: Guard; }

const before = (source: string, start: number, length: number) => source.slice(Math.max(0, start - length), start);

// Pattern rules: one finding per hit. `lead` extends the finding left over up to N Hangul
// characters (the governing word) without a backtracking-prone prefix in the expression.
const patternRules: PatternRule[] = [
  { ruleId: 'PROCESS_NOMINALIZATION', expression: /하는\s+과정에서/gu, lead: 24, guard: (s, a) => HANGUL.test(s.charAt(a - 1)) },
  // Plain "X에 있어서" is often locative + -어서 (집에 있어서, 서랍에 있어서), so only the
  // unambiguous public-prose frames are flagged: nominalized clauses, "~는 데 있어서", and
  // the frame followed by 는/의/도 (교육에 있어서는, 정책에 있어서의).
  { ruleId: 'PUBLIC_LANGUAGE_FRAME', lead: 24, guard: (s, a) => s.charAt(a) === '데' || HANGUL.test(s.charAt(a - 1)),
    expression: /(?:함|됨|하기|되기)에\s+있어서|(?<=[가-힣](?:는|은)\s)데\s+있어서|(?:에|에서)\s+있어서(?=는|의|도)/gu },
  { ruleId: 'IMPORTANCE_FORMULA', lead: 12,
    expression: /(?:는|은|ㄹ|할|될|볼)\s*것이\s*(?:매우\s+|가장\s+|무엇보다\s+)?(?:중요|필수적|필요|바람직)(?:하|합|한|해)|중요한\s+(?:역할|도구|요소|열쇠|과제)(?=[을를이가은는입\s,.])/gu },
  { ruleId: 'CONCLUDING_SIGNPOST',
    expression: /(?:^|(?<=[.!?]\s)|(?<=\n))(?:결론적으로|요약하자면|요약하면|종합하면|정리하자면)(?=[\s,])/gu },
  { ruleId: 'DEMONSTRATIVE_THROUGH', expression: /(?<![가-힣])이를\s+통(?:해서?|하여)(?![가-힣])/gu },
  { ruleId: 'ROLE_FORMULA', expression: /역할을\s+(?:하|한|합|했|해|수행|담당)/gu,
    // Acting / game roles are literal uses.
    guard: (s, a) => !/주인공|배역|악역|조연|주연|배우|연기|캐릭터|직책/u.test(before(s, a, 12)) },
  { ruleId: 'BOILERPLATE_ANNOUNCE',
    expression: /(?:알아보|살펴보|짚어보|다뤄보|정리해\s*보|소개해\s*드리|알려\s*드리)(?:겠습니다|겠다|도록\s*하겠습니다|도록\s*하겠다)|(?:알아볼|살펴볼)까요|(?:알아|살펴)봅시다/gu },
  { ruleId: 'DOUBLE_PASSIVE',
    // 되다/보이다/쓰이다/잊히다/불리다/나뉘다/읽히다/짜이다 already passive + 지다. 이루어지다, 만들어지다 are lexical and excluded.
    expression: /(?<![가-힣])[가-힣]{0,6}(?:되어|보여|쓰여|잊혀|불려|나뉘어|읽혀|짜여)(?:지(?:다|는|고|며|면|게|기|지|어|었)|진|졌)/gu,
    guard: (s, a, e) => !/^(?:[가-힣]{0,6})?(?:이루어|만들어|그려|놓여|둘러|쌓여|이어)/u.test(s.slice(a, e)) },
  { ruleId: 'CAUSAL_LEAD', expression: /(?:으로|로)\s+이어(?:질|지|진|집니다|졌)(?![가-힣])/gu, lead: 10 }
];

// Cluster rules: a finding only appears when `min` hits fall inside `window` UTF-16 units of one paragraph.
const intensifier = /(?<![가-힣])(?:매우|다양한|효과적(?:인|으로)?|적극적(?:인|으로)?|지속적(?:인|으로)?|체계적(?:인|으로)?|종합적(?:인|으로)?|획기적(?:인|으로)?|핵심적(?:인)?|중요한|필수적(?:인|이다)?|긍정적(?:인)?|다각적(?:인|으로)?)(?![가-힣])/gu;
const jeok = /(?<![가-힣])(?!목적|표적|국적|성적|실적|면적|체적)[가-힣]{2,8}적(?:인|으로)(?![가-힣])/gu;
const clusterRules: ClusterRule[] = [
  { ruleId: 'INTENSIFIER_CLUSTER', expression: intensifier, min: 3, window: 250 },
  { ruleId: 'THROUGH_CLUSTER', expression: /[을를]\s+통(?:해서?|하여|한|하며)(?![가-힣])/gu, min: 2, window: 250,
    // 이를 통해 has its own rule.
    guard: (s, a) => !/(?:^|[^가-힣])이$/u.test(before(s, a, 2)) },
  { ruleId: 'JEOK_CLUSTER', expression: jeok, min: 3, window: 150 },
  { ruleId: 'CAPABILITY_HEDGE_CLUSTER', expression: /[가-힣]\s+수\s+있(?:다|습니다|으며|는|고|을)/gu, min: 4, window: 300,
    // Only after an ㄹ-ending stem (할/될/볼/갈/쓸 ...): Hangul final consonant index 8.
    guard: (s, a) => (s.charCodeAt(a) - 0xAC00) % 28 === 8 }
];

const PRIORITY: StyleRuleId[] = [
  'DOUBLE_PASSIVE', 'IMPORTANCE_FORMULA', 'CONCLUDING_SIGNPOST', 'BOILERPLATE_ANNOUNCE', 'ROLE_FORMULA',
  'DEMONSTRATIVE_THROUGH', 'CONNECTOR_RUN', 'INTENSIFIER_CLUSTER', 'JEOK_CLUSTER', 'THROUGH_CLUSTER',
  'ENDING_MONOTONY', 'CAPABILITY_HEDGE_CLUSTER', 'CAUSAL_LEAD', 'PROCESS_NOMINALIZATION', 'PUBLIC_LANGUAGE_FRAME'
];

/* ---------- sentence rules ---------- */

interface Sentence { start: number; end: number; range: number }

/** Linear sentence splitter. A terminator counts only before whitespace, end of range or a closing quote,
 * so decimals (3.5), versions (v1.2) and abbreviations followed by a letter do not split. */
function sentencesIn(source: string, ranges: Span[]): Sentence[] {
  const out: Sentence[] = [];
  ranges.forEach((range, index) => {
    let start = range.start;
    for (let i = range.start; i < range.end; i++) {
      const c = source.charAt(i);
      if (c === '\n' && i + 1 >= range.end) continue;
      if (c === '.' || c === '!' || c === '?' || c === '。') {
        let j = i + 1;
        while (j < range.end && /[.!?"”’')\]」』]/u.test(source.charAt(j))) j++;
        if (j >= range.end || /\s/u.test(source.charAt(j))) {
          pushSentence(out, source, start, j, index);
          start = j; i = j - 1;
        }
      }
    }
    pushSentence(out, source, start, range.end, index);
  });
  return out;
}

function pushSentence(out: Sentence[], source: string, start: number, end: number, range: number): void {
  while (start < end && /\s/u.test(source.charAt(start))) start++;
  while (end > start && /\s/u.test(source.charAt(end - 1))) end--;
  if (end > start) out.push({ start, end, range });
}

const connectorStart = /^[\s"“‘'(「]*((?:또한|따라서|그러므로|이에\s*따라|더불어|아울러|결과적으로|결론적으로))(?=[,\s])/u;

function connectorRun(source: string, sentences: Sentence[], accept: (span: Span) => boolean): StyleFinding[] {
  const findings: StyleFinding[] = [];
  const isConnector: Array<Span | undefined> = sentences.map(sentence => {
    const match = connectorStart.exec(source.slice(sentence.start, Math.min(sentence.end, sentence.start + 24)));
    if (!match || !match[1]) return undefined;
    const offset = sentence.start + match[0].length - match[1].length;
    // match[0] ends right after the connector word because the lookahead is zero-width.
    return { start: offset, end: offset + match[1].length };
  });
  for (let i = 1; i < sentences.length; i++) {
    const here = isConnector[i];
    if (!here || !accept(here)) continue;
    let count = 1;
    for (let j = i - 1; j >= 0 && j >= i - 2 && sentences[j]!.range === sentences[i]!.range; j--) if (isConnector[j]) count++;
    if (count >= 2) findings.push({ ruleId: 'CONNECTOR_RUN', start: here.start, end: here.end });
  }
  return findings;
}

const ENDING_RUN = 5;
function endingMonotony(source: string, sentences: Sentence[], mask: Uint8Array): StyleFinding[] {
  const findings: StyleFinding[] = [];
  let previousKey = '', run = 0, previousRange = -1;
  for (const sentence of sentences) {
    let end = sentence.end;
    while (end > sentence.start && /[.!?"”’')\]」』。]/u.test(source.charAt(end - 1))) end--;
    const tail = source.slice(Math.max(sentence.start, end - 3), end);
    const key = /^[가-힣]{3}$/u.test(tail) && !isProtected(mask, end - 1, end) ? tail : '';
    if (key && key === previousKey && sentence.range === previousRange) run++; else run = key ? 1 : 0;
    previousKey = key; previousRange = sentence.range;
    if (run === ENDING_RUN) {
      let from = end;
      while (from > sentence.start && !/\s/u.test(source.charAt(from - 1)) && end - from < 16) from--;
      findings.push({ ruleId: 'ENDING_MONOTONY', start: from, end: sentence.end });
    }
  }
  return findings;
}

/* ---------- assembly ---------- */

function patternFindings(source: string, rule: PatternRule): Span[] {
  const hits: Span[] = [];
  for (const match of source.matchAll(rule.expression)) {
    let start = match.index, end = start + match[0].length;
    if (rule.guard && !rule.guard(source, start, end)) continue;
    if (rule.lead) {
      const limit = Math.max(0, start - rule.lead);
      while (start > limit && HANGUL.test(source.charAt(start - 1))) start--;
    }
    hits.push({ start, end });
  }
  return hits;
}

function clusterFindings(source: string, rule: ClusterRule, ranges: Span[], accept: (span: Span) => boolean): Span[] {
  const out: Span[] = [];
  let r = 0;
  const hits: Array<Span & { range: number }> = [];
  for (const match of source.matchAll(rule.expression)) {
    const start = match.index, end = start + match[0].length;
    while (r < ranges.length && ranges[r]!.end <= start) r++;
    if (r >= ranges.length || start < ranges[r]!.start) continue;
    if (rule.guard && !rule.guard(source, start, end)) continue;
    if (accept({ start, end })) hits.push({ start, end, range: r });
  }
  for (let i = 0; i < hits.length;) {
    let j = i;
    while (j + 1 < hits.length && hits[j + 1]!.range === hits[i]!.range && hits[j + 1]!.start - hits[i]!.start <= rule.window) j++;
    if (j - i + 1 >= rule.min) { out.push({ start: hits[i]!.start, end: hits[j]!.end }); i = j + 1; } else i++;
  }
  return out;
}

/** Every finding, ordered by position, without the prompt-size cap. Exposed for measurement and tests. */
export function collectKoreanStyleFindings(source: string): StyleFinding[] {
  if (!source) return [];
  const mask = new Uint8Array(source.length);
  protectQuotes(source, mask);
  protectInline(source, mask);
  const ranges = proseRanges(source, mask);
  const inProse = (span: Span) => {
    let low = 0, high = ranges.length - 1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (span.start < ranges[mid]!.start) high = mid - 1;
      else if (span.start >= ranges[mid]!.end) low = mid + 1;
      else return span.end <= ranges[mid]!.end;
    }
    return false;
  };
  const accept = (span: Span) => inProse(span) && !isProtected(mask, span.start, span.end);
  const findings: StyleFinding[] = [];
  for (const rule of patternRules)
    for (const span of patternFindings(source, rule))
      if (accept(span)) findings.push({ ruleId: rule.ruleId, ...span });
  for (const rule of clusterRules)
    for (const span of clusterFindings(source, rule, ranges, accept))
      findings.push({ ruleId: rule.ruleId, ...span });
  const sentences = sentencesIn(source, ranges);
  findings.push(...connectorRun(source, sentences, accept), ...endingMonotony(source, sentences, mask));
  return findings.sort((a, b) => a.start - b.start || a.end - b.end);
}

/** SUPER_SEJONG_MODE=off disables the style hints; enforce and shadow keep them. */
export function superSejongEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return (env.SUPER_SEJONG_MODE ?? '').trim().toLowerCase() !== 'off';
}

// Short Korean guidance per rule, shown to the model next to each flagged excerpt.
export const STYLE_RULE_GUIDANCE: Record<StyleRuleId, string> = {
  PROCESS_NOMINALIZATION: '"~하는 과정에서"는 문맥상 시간·계기 표현(~하다가, ~하면서 등)이 더 자연스러운지 검토',
  PUBLIC_LANGUAGE_FRAME: '"~에 있어서"는 "~에서", "~할 때" 등으로 줄일 수 있는지 검토',
  IMPORTANCE_FORMULA: '"~하는 것이 중요합니다"류 상투적 강조는 구체적인 이유나 행동으로 바꿀 수 있는지 검토',
  CONCLUDING_SIGNPOST: '"결론적으로·요약하자면" 같은 형식적 맺음말이 꼭 필요한지 검토',
  DEMONSTRATIVE_THROUGH: '"이를 통해"는 앞 문장과 자연스럽게 잇거나 주어를 살려 쓸 수 있는지 검토',
  ROLE_FORMULA: '"~한 역할을 하다"는 핵심 동사로 바로 쓸 수 있는지 검토',
  BOILERPLATE_ANNOUNCE: '"알아보겠습니다·살펴보겠습니다" 같은 안내 문구가 내용 없이 쓰였는지 검토',
  DOUBLE_PASSIVE: '이중 피동(되어지다·보여지다 등)은 단일 피동이나 능동으로 바꿀 수 있는지 검토',
  CAUSAL_LEAD: '"~로 이어지다"가 반복되면 인과를 구체적인 동사로 밝힐 수 있는지 검토',
  INTENSIFIER_CLUSTER: '"매우·다양한·효과적인" 같은 꾸밈말이 몰려 있어 줄이거나 구체화할 수 있는지 검토',
  THROUGH_CLUSTER: '"~을 통해"가 가까이 반복되어 일부를 다른 표현으로 바꿀 수 있는지 검토',
  JEOK_CLUSTER: '"~적인/~적으로"가 몰려 있어 일부를 풀어 쓸 수 있는지 검토',
  CAPABILITY_HEDGE_CLUSTER: '"~할 수 있다"가 몰려 있어 사실이면 단정형으로, 가능성이면 하나로 줄일 수 있는지 검토',
  CONNECTOR_RUN: '문장 첫머리 접속어(또한·따라서 등)가 이어져 일부를 빼거나 문장을 이을 수 있는지 검토',
  ENDING_MONOTONY: '같은 종결 어미가 다섯 문장 이상 이어져 일부 어미를 바꿀 수 있는지 검토'
};

export function diagnoseKoreanStyle(source: string, limit = MAX_FINDINGS): StyleFinding[] {
  const cap = Math.max(0, Math.min(Math.trunc(limit) || 0, MAX_FINDINGS));
  if (!cap) return [];
  const all = collectKoreanStyleFindings(source);
  // Overlapping single-phrase findings: the higher-priority rule keeps the phrase.
  // `all` is sorted by start, so a short finding can only collide with neighbours that start within 40 units.
  const rank = (id: StyleRuleId) => PRIORITY.indexOf(id);
  const dropped = new Uint8Array(all.length);
  for (let i = 0; i < all.length; i++)
    for (let j = i + 1; j < all.length && all[j]!.start < all[i]!.start + 40; j++) {
      const x = all[i]!, y = all[j]!;
      if (x.ruleId === y.ruleId || x.end - x.start > 40 || y.end - y.start > 40 || y.start >= x.end || x.start >= y.end) continue;
      dropped[rank(x.ruleId) <= rank(y.ruleId) ? j : i] = 1;
    }
  const kept = all.filter((_, index) => !dropped[index]);
  if (kept.length <= cap) return kept.sort((a, b) => a.start - b.start || a.end - b.end);
  // Over the cap: round-robin across rules in priority order so one frequent rule cannot crowd out the rest.
  const buckets = new Map<StyleRuleId, StyleFinding[]>();
  for (const finding of kept.sort((a, b) => a.start - b.start)) buckets.set(finding.ruleId, [...(buckets.get(finding.ruleId) ?? []), finding]);
  const order = [...buckets.keys()].sort((a, b) => rank(a) - rank(b));
  const chosen: StyleFinding[] = [];
  for (let round = 0; chosen.length < cap; round++) {
    let added = false;
    for (const id of order) {
      const next = buckets.get(id)![round];
      if (next && chosen.length < cap) { chosen.push(next); added = true; }
    }
    if (!added) break;
  }
  return chosen.sort((a, b) => a.start - b.start || a.end - b.end);
}

/* ---------- document register (speech level) ---------- */

export type SpeechLevel = '합쇼체' | '해요체' | '해라체';

/** Speech level of one sentence's final predicate, or undefined for headings, nominal lines and others. */
export function sentenceSpeechLevel(sentence: string): SpeechLevel | undefined {
  const bare = sentence.trim().replace(/[\s"”’')\]」』.!?。…~]+$/u, '');
  if (!bare) return undefined;
  if (/(?:니다|니까|십시오|시오|ㅂ시다|옵니다)$/u.test(bare)) return '합쇼체';
  if (/(?:요|죠)$/u.test(bare)) return '해요체';
  if (/(?:다|까|냐|구나|자|라)$/u.test(bare)) return '해라체';
  return undefined;
}

/** Dominant speech level of body sentences outside quotes, headings and list markers. A level is
 * dominant only with at least three classified sentences and a 60% share; mixed documents return undefined. */
export function documentRegister(source: string): SpeechLevel | undefined {
  const counts = new Map<SpeechLevel, number>();
  let total = 0;
  for (const rawLine of source.split('\n')) {
    if (/^\s{0,3}(?:#{1,6}\s|>)|^\s*(?:[-*+•·]|\d{1,2}[.)])\s/u.test(rawLine)) continue;
    // Quoted speech keeps its own level; mask it so a quote never decides the narration level.
    const line = rawLine.replace(/"[^"\n]{0,600}"|“[^”\n]{0,600}”|‘[^’\n]{0,600}’|「[^」\n]{0,600}」|『[^』\n]{0,600}』/gu, 'Q');
    for (const sentence of line.split(/(?<=[.!?。])\s+/u)) {
      const level = sentenceSpeechLevel(sentence);
      if (!level) continue;
      counts.set(level, (counts.get(level) ?? 0) + 1);
      total++;
    }
  }
  if (total < 3) return undefined;
  for (const [level, count] of counts) if (count / total >= 0.6) return level;
  return undefined;
}

/** Position of a chunk in a document that was split for rewriting. */
export interface ChunkPromptContext {
  index: number;
  total: number;
  register?: SpeechLevel;
}
