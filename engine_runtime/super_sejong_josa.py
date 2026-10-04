"""Super Sejong Engine: dependency-free Korean particle (josa) allomorph agreement.

Only mismatches a rewrite introduces are acted on (``gate``); errors already in the
source are the writer's and stay untouched. No word list is bundled: the optional
lexicon's licence is unverified, and without it the checker still covers non-Hangul
stems (digits, acronyms, units, symbols, brackets) and the unambiguous Hangul families.


Pure stdlib. Uses the Unicode syllable formula:  index = ord(c) - 0xAC00 ; final = index % 28 ; RIEUL final == 8.

Public API
    check(text, lexicon=None, min_conf='likely') -> list[Finding]
    gate(source, output, lexicon=None, min_conf='likely') -> list[Finding]   # findings the rewrite INTRODUCED
    Lexicon.load(path=None)                                                  # optional word data

Confidence of a finding
    certain : stem is a reading-determined non-Hangul stem (acronym, unit, %, >=3-digit number) or a known
              Hangul noun (lexicon) with a family that has no verb-ending homograph.
    likely  : plausible mismatch but the stem may be a name/OOV/model number (short integers, bracket stems,
              out-of-lexicon Hangul stems for 을/를, 와, 예요, 랑).
    low     : hint only (vowel stem + 이/과/이나, consonant stem + 가/는 with OOV stem, ...).
"""
from __future__ import annotations
import os
import re
import unicodedata
from dataclasses import dataclass

H0 = 0xAC00
RIEUL = 8


# ----------------------------------------------------------------------------- hangul arithmetic
def is_syl(c: str) -> bool:
    return '가' <= c <= '힣'


def final_of(c: str) -> int:
    return (ord(c) - H0) % 28


def syl_class(c: str) -> str:
    f = final_of(c)
    return 'V' if f == 0 else ('L' if f == RIEUL else 'C')


# ----------------------------------------------------------------------------- non-Hangul readings
# letter names: only L(엘) R(알) M(엠) N(엔) end in a consonant
LETTER_CLASS = {c: 'V' for c in 'ABCDEFGHIJKOPQSTUVWXYZ'}
LETTER_CLASS.update({'L': 'L', 'R': 'L', 'M': 'C', 'N': 'C'})
SINO_DIGIT = {'0': 'C', '1': 'L', '2': 'V', '3': 'C', '4': 'V', '5': 'V', '6': 'C', '7': 'L', '8': 'L', '9': 'V'}
# English reading of a single digit attached to a name (EV6 식스, A1 원, 아이폰15 ...)
ENG_DIGIT = {'0': 'V', '1': 'C', '2': 'V', '3': 'V', '4': 'V', '5': 'V', '6': 'V', '7': 'C', '8': 'V', '9': 'C'}
GROUP_UNIT_CLASS = [None, 'C', 'C', 'V', 'C', 'V', 'V']  # 만 억 조 경 해 자
WORD_CLASS = {
    'NASA': 'V', 'NATO': 'V', 'FIFA': 'V', 'UNESCO': 'V', 'UNICEF': 'V', 'OPEC': 'C', 'ASEAN': 'C', 'JSON': 'C',
    'SQL': 'L', 'OLED': 'V', 'LINE': 'C', 'WHO': 'V', 'LED': 'V', 'MBTI': 'V', 'KAIST': 'V', 'POSTECH': 'V',
    'GOOGLE': 'L', 'EXCEL': 'L', 'APPLE': 'L', 'PYTHON': 'C', 'IPHONE': 'C', 'ANDROID': 'C', 'LINUX': 'V',
    'JAVA': 'V', 'FACEBOOK': 'C', 'YOUTUBE': 'V', 'TWITTER': 'V', 'INSTAGRAM': 'C', 'KAKAOTALK': 'C',
    'NAVER': 'V', 'KAKAO': 'V', 'SAMSUNG': 'C', 'MICROSOFT': 'V', 'WINDOWS': 'V', 'CHATGPT': 'V',
    'OPENAI': 'V', 'ANTHROPIC': 'C', 'CLAUDE': 'V', 'GEMINI': 'V', 'TENSORFLOW': 'L', 'PYTORCH': 'C',
    'GITHUB': 'C', 'DOCKER': 'V', 'REACT': 'C', 'WORD': 'V', 'WIFI': 'V', 'WI-FI': 'V',
    'IOS': 'V', 'MACOS': 'V', 'IPAD': 'V', 'AIRPODS': 'V', 'TIKTOK': 'C',
    'OECD': 'V', 'KOSPI': 'V', 'KOSDAQ': 'C', 'NASDAQ': 'C', 'NETFLIX': 'V', 'AMAZON': 'C', 'TESLA': 'V', 'UBER': 'V', 'ZOOM': 'C', 'SLACK': 'V', 'NOTION': 'C',
}
# all-caps tokens that are English words (reading unknown) -> never judged as spelled acronyms
ENGLISH_STOP = set('''UP ON IN AT BY TO GO SO NO OR IF IS OF AN AS BE DO HE ME MY WE US ALL AND ANY ARE BIG BOX BUT
CAN CUP DAY END FOR GET HOT HIT HOW KEY LOW MAX MIN MIX NEW NOT NOW OFF OLD ONE OUT PRO RUN SAY SEE TOP TWO USE WAY
WIN YES YOU APP BEST BACK COOL FREE GOOD HAND HANDS HOME LIFE LOVE MORE NEXT ONLY OPEN PLAY PLUS REAL SAFE SALE
SHOP SHOW STAR STOP TIME TRUE WORK ZERO NICE LIKE LIVE LOOK MADE MAKE'''.split())
UNIT_CLASS = {  # latin unit symbols as read in Korean (case-sensitive; 킬로그램/밀리그램/톤 end in a consonant)
    'km': 'V', 'cm': 'V', 'mm': 'V', 'm': 'V', 'ml': 'V', 'l': 'V', 'L': 'V', 'dl': 'V', 'kg': 'C', 'g': 'C',
    'mg': 'C', 't': 'C', 'kW': 'V', 'kWh': 'V', 'Hz': 'V', 'kHz': 'V', 'MHz': 'V', 'GHz': 'V', 'GB': 'V',
    'MB': 'V', 'KB': 'V', 'TB': 'V', 'kcal': 'V', 'ha': 'V', 'rpm': 'C', 'bpm': 'C', 'ppm': 'C', 'dB': 'L',
    'cc': 'V', 'mph': 'V', 'km/h': 'V', 'min': 'C',
}
# a single capital letter glued to a number (5G 4K 3D 1.2M 2L): letter name, or the unit reading when different
AMBIG_CAPITAL = {'M': {'C', 'V'}, 'L': {'L', 'V'}}
# ㎏(338F)=킬로그램 C, ㎎(338E)=밀리그램 C, ㎝(339D) ㎞(339E) ㎡(33A1) ㎥(33A5) vowel
SYMBOL_CLASS = {'%': 'V', '‰': 'V', '℃': 'V', '℉': 'V', '$': 'V', '€': 'V', '£': 'V',
                '₩': 'C', '¥': 'C', '¢': 'V',
                '㎏': 'C', '㎎': 'C', '㎝': 'V', '㎞': 'V', '㎡': 'V', '㎥': 'V'}


def number_class(num: str) -> str | None:
    """Class of the last pronounced syllable of an Arabic numeral read Sino-Korean."""
    s = num.replace(',', '').replace(' ', '')
    if '.' in s:
        ip, fp = s.split('.', 1)
        if not fp.isdigit() or set(fp) == {'0'}:
            return None
        return SINO_DIGIT[fp[-1]]
    if not s.isdigit():
        return None
    s = s.lstrip('0')
    if not s:
        return 'C'  # 영 / 공
    z = len(s) - len(s.rstrip('0'))
    if z == 0:
        return SINO_DIGIT[s[-1]]
    g = z // 4
    if g == 0:
        return 'C'  # 십 백 천
    return GROUP_UNIT_CLASS[g] if g < len(GROUP_UNIT_CLASS) else None


def _latin_alts(word: str, digit_ctx: bool):
    up = word.upper()
    if up in WORD_CLASS:
        return {WORD_CLASS[up]}
    if word in UNIT_CLASS and (digit_ctx or (len(word) > 1 and word.islower())):
        return {UNIT_CLASS[word]}
    letters = [c for c in word if c.isalpha() and c.isascii()]
    if not letters:
        return None
    if word == word.upper() and up not in ENGLISH_STOP:
        if len(letters) == 3 and letters[1] in 'AEIOU' and letters[0] not in 'AEIOU' and letters[2] not in 'AEIOU':
            return None  # CVC (MAG, POP, SOS): may be read as a word
        if len(letters) <= 3 or not any(c in 'AEIOU' for c in letters[1:]):
            return {LETTER_CLASS[letters[-1].upper()]}
    return None


PARTICLE_END = set('는은이가을를에의로와과도만서고다요며나면')


def _digit_alts(stem: str, prev_tok: str = ''):
    """stem ends with an ASCII digit. Return (alts, conf_cap) or None to skip."""
    fr = re.search(r'(\d+)/(\d+)$', stem)
    if fr:  # 1/4 is read 사분의 일: the numerator ends the reading
        cl = number_class(fr.group(1))
        return ({cl}, 'likely') if cl else None
    m = re.search(r'\d[\d,.]*$', stem)
    num = m.group(0).rstrip(',.') if m else stem[-1]
    start = m.start() if m else len(stem) - 1
    prev = stem[start - 1] if start > 0 else ''
    attached = bool(prev) and ((prev.isascii() and prev.isalpha()) or is_syl(prev) or (prev == '-' and start > 1))
    if not attached:
        # "GPT 3", "iPhone 15": a number following a Latin word is a model number read in English or Sino
        before = stem[:start] if start > 0 else (prev_tok or '')
        pc = before.rstrip()[-1:]
        if pc.isascii() and pc.isalpha():
            attached = True
        elif is_syl(pc) and pc not in PARTICLE_END:  # 시즌 3 / 아이오닉 6: bare name + model number
            attached = True
    digits = re.sub(r'\D', '', num)
    if attached:
        if len(digits) == 1:
            return {SINO_DIGIT[digits], ENG_DIGIT[digits]}, 'likely'
        return None
    cl = number_class(num)
    if cl is None:
        return None
    plain_short = ('.' not in num and ',' not in num and len(digits) <= 2)
    return {cl}, ('likely' if plain_short else 'certain')


def tail_alts(stem: str, prev_tok: str = ''):
    """Possible sound classes of the end of `stem`: (set of 'V'/'C'/'L', kind, conf_cap) or None."""
    if not stem:
        return None
    c = stem[-1]
    if is_syl(c):
        return {syl_class(c)}, 'hangul', 'certain'
    if c in SYMBOL_CLASS:
        return {SYMBOL_CLASS[c]}, 'symbol', 'certain'
    if stem.endswith('%p'):
        return {'V'}, 'symbol', 'certain'
    if c.isascii() and c.isdigit():
        r = _digit_alts(stem, prev_tok)
        return (r[0], 'digit', r[1]) if r else None
    if c.isascii() and c.isalpha():
        if '=' in stem:
            return None
        m = re.search(r'[A-Za-z][A-Za-z&./-]*$', stem)
        w = (m.group(0) if m else c).strip('./&-') or c
        pre = stem[:m.start()] if m else ''
        digit_ctx = (bool(pre) and pre[-1].isdigit()) or bool(re.fullmatch(r'[\d.,]+', prev_tok or ''))
        if pre and pre[-1].isdigit() and w not in UNIT_CLASS:
            if len(w) == 1 and w.isupper():  # 5G 4K 3D: the letter name (M, L also read as units)
                return (AMBIG_CAPITAL.get(w) or {LETTER_CLASS[w]}), 'latin', 'certain'
            if (w.isupper() and len(w) <= 2 and re.fullmatch(r'[A-Z0-9&-]+', stem[:m.end()] if m else stem)
                    and not w.upper() in ENGLISH_STOP):  # M2G B2G 3AC: last letter
                return (AMBIG_CAPITAL.get(w[-1]) or {LETTER_CLASS[w[-1]]}), 'latin', 'likely'
            return None  # alnum code like 3AC / CP9x: unknown reading
        a = _latin_alts(w, digit_ctx)
        return (a, 'latin', 'certain') if a else None
    return None


# ----------------------------------------------------------------------------- lexicon
class Lexicon:
    def __init__(self, nouns=(), vstems=(), others=()):
        self.nouns = set(nouns)
        self.vstems = set(vstems)
        self.others = set(others)
        self.allwords = self.nouns | self.others | self.vstems

    @classmethod
    def load(cls, path: str | None = None) -> 'Lexicon':
        path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'josa_lexicon.txt')
        n, v, o = set(), set(), set()
        with open(path, encoding='utf8') as f:
            for line in f:
                t, _, w = line.rstrip('\n').partition('\t')
                (n if t == 'N' else v if t == 'V' else o).add(w)
        return cls(n, v, o)

    def known_word(self, w: str) -> bool:
        return w in self.allwords

    def verb_suffix(self, stem: str) -> bool:
        return any(len(stem) >= k and stem[-k:] in self.vstems for k in (1, 2, 3))

    def word_covering(self, core: str, ent_len: int) -> bool:
        """Some lexical word ends the token and covers the particle string (e.g. 물가, 진로, 신랑)."""
        for k in range(max(2, ent_len if ent_len >= 2 else 2), min(len(core), 7) + 1):
            if core[-k:] in self.allwords:
                return True
        return core in self.allwords


# ----------------------------------------------------------------------------- particle families
# name: (consonant form, vowel form, copula_type: consonant form after a vowel is legal)
FAMILIES = {
    'nom': ('이', '가', False),
    'top': ('은', '는', False),
    'acc': ('을', '를', False),
    'com': ('과', '와', False),
    'or': ('이나', '나', False),
    'and': ('이며', '며', True),
    'quo': ('이라', '라', True),
    'cop': ('이에요', '예요', True),
    'with': ('이랑', '랑', False),
    'inst': ('으로', '로', False),
}
TAILS = {
    'nom': [''], 'top': [''], 'acc': [''],
    'com': ['', '의', '는', '도', '만'],
    'or': [''], 'and': [''],
    'quo': ['고', '는', '면', '도', '서', '니', '란', '야', '서도', '고는'],
    'cop': [''], 'with': [''],
    'inst': ['', '서', '써', '부터', '는', '도', '만', '의', '까지', '서의', '부터는', '서는', '써는'],
}
ENTRIES = []
for _fam, (_cf, _vf, _cop) in FAMILIES.items():
    for _t in TAILS[_fam]:
        ENTRIES.append((_cf + _t, _fam, 'C', _cf, _t))
        ENTRIES.append((_vf + _t, _fam, 'V', _vf, _t))
ENTRIES.sort(key=lambda e: -len(e[0]))

JAMO_NAMES = ('기역', '니은', '디귿', '리을', '미음', '비읍', '시옷', '이응', '지읒', '치읓', '키읔', '티읕', '피읖', '히읗')
VOWEL_EUL_EXC = ('모을', '마을', '가을', '고을', '나을', '이을', '지을', '그을', '부을', '저을', '자을', '낫을')
SEUT_IRREG_EUN = ('모은', '지은', '나은', '이은', '그은', '부은', '저은', '자은')

OPENERS = '"\'“‘(<[{「『《〈'
CLOSE_PAIRS = {')': '(', ']': '[', '}': '{', '>': '<', '”': '“', '’': '‘', '」': '「', '』': '『', '》': '《', '〉': '〈',
               '"': '"', "'": "'"}
QUOTE_CLOSERS = set('”’」』》〉"\'')
PUNCT_END = set('.,!?;:…~·‥。、')
CONF_ORDER = {'low': 0, 'likely': 1, 'certain': 2}
STANDALONE_PARTICLES = {'이', '가', '은', '는', '과', '와', '의', '도', '만'}
DISTRICT_NEXT = ('의원', '후보', '지역구', '선거구', '위원장', '당협')
OPTIONAL_MARKS = {'이', '가', '은', '는', '을', '를', '과', '와', '으', '로', '으로', '이나', '이라', '라', '나', '이며', '며'}


@dataclass
class Finding:
    start: int
    end: int
    token: str
    stem: str
    particle: str
    expected: str
    family: str
    sound: str
    stem_kind: str
    confidence: str
    reason: str = ''

    def key(self):
        return (self.stem, self.particle)

    def __str__(self):
        return (f'{self.token}: {self.stem}+{self.particle} -> {self.stem}+{self.expected} '
                f'[{self.confidence}; {self.reason}]')


def _unmatched_close(s: str) -> bool:
    c = s[-1]
    return s.count(c) > s.count(CLOSE_PAIRS[c])


def _strip_ok(s: str) -> bool:
    c = s[-1]
    if c in PUNCT_END:
        return True
    if c in CLOSE_PAIRS:
        if c in ('"', "'"):
            return s.count(c) % 2 == 1
        return _unmatched_close(s)
    return False


def _decide(sound: str, fam: str, form: str):
    """Return (expected particle string without tail, mismatch?)."""
    cf, vf, cop = FAMILIES[fam]
    if fam == 'cop':
        if sound == 'V':
            return vf, False
        return cf, form == 'V'
    vowelish = sound in ('V', 'L') if fam == 'inst' else sound == 'V'
    if vowelish:
        return vf, (form == 'C' and not cop)
    return cf, form == 'V'


def check(text: str, lexicon: Lexicon | None = None, min_conf: str = 'likely') -> list[Finding]:
    if any('ᄀ' <= c <= 'ᇿ' for c in text):
        text = unicodedata.normalize('NFC', text)
    out: list[Finding] = []
    min_rank = CONF_ORDER[min_conf]
    prev_tok = ''
    for m in re.finditer(r'\S+', text):
        tok = m.group(0)
        lead = 0
        while lead < len(tok) and tok[lead] in OPENERS:
            lead += 1
        core = tok[lead:]
        end = len(core)
        while end > 0 and _strip_ok(core[:end]):
            end -= 1
        core = core[:end]
        if len(core) >= 2:
            f = _check_token(core, m.start() + lead, prev_tok, text, lexicon)
            if f and f.family == 'acc' and f.particle == '을' and f.stem_kind == 'hangul':
                nxt = re.match(r'\s+(\S+)', text[m.end():])
                if nxt and (nxt.group(1) in STANDALONE_PARTICLES or nxt.group(1).startswith(DISTRICT_NEXT)):
                    f = None  # 선거구 '을' (여수을 의원 / 여수을 이 ...): not a particle
            if f and CONF_ORDER[f.confidence] >= min_rank:
                out.append(f)
        prev_tok = tok
    return out


def _check_token(core, base_off, prev_tok, text, lex):
    for ent, fam, form, pform, tail in ENTRIES:
        if len(core) <= len(ent) or not core.endswith(ent):
            continue
        stem = core[:-len(ent)]
        r = _eval(core, stem, ent, fam, form, tail, base_off, prev_tok, text, lex)
        if r is None:
            continue
        return r or None
    return None


def _bracket_alts(stem, base_off, text):
    """stem ends with a closer: sound alternatives of the bracket content and the word before the bracket."""
    closer = stem[-1]
    opener = CLOSE_PAIRS[closer]
    ci = base_off + len(stem) - 1
    lim = max(0, ci - 120)
    oi = -1
    if closer in ('"', "'"):
        oi = text.rfind(opener, lim, ci)
    else:
        depth, i = 0, ci - 1
        while i >= lim:
            ch = text[i]
            if ch == closer:
                depth += 1
            elif ch == opener:
                if depth == 0:
                    oi = i
                    break
                depth -= 1
            i -= 1
    inner = text[oi + 1:ci] if oi >= 0 else stem[:-1]
    if inner[-1:].isspace():
        return None, inner  # stray space before the closing quote: malformed source
    alts = set()
    ia = tail_alts(inner.rstrip()) if inner.strip() else None
    if ia is None:
        return None, inner
    quote = closer in QUOTE_CLOSERS
    if ia:
        alts |= ia[0]
    if not quote and oi >= 0:
        b = text[:oi].rstrip(' ')
        wm = re.search(r'\S+$', b)
        base = wm.group(0) if wm else ''
        while base and (_strip_ok(base) or base[-1] in CLOSE_PAIRS):
            base = base[:-1]
        if base:
            ba = tail_alts(base)
            if ba:
                alts |= ba[0]
    return (alts or None), inner


def _eval(core, stem, ent, fam, form, tail, base_off, prev_tok, text, lex):
    """Finding | False (stop: legal or skipped) | None (try the next shorter entry)."""
    last = stem[-1]
    if last in CLOSE_PAIRS and not is_syl(last):
        if fam == 'quo':
            return False
        alts, inner = _bracket_alts(stem, base_off, text)
        if not alts or inner.strip() in OPTIONAL_MARKS:
            return False
        kind, cap = 'bracket', 'likely'
    else:
        r = tail_alts(stem, prev_tok)
        if r is None:
            return False
        alts, kind, cap = r
    if kind == 'digit' and ent == '가' and (re.search(r'[로길동]\d{1,2}$', stem) or (
            re.fullmatch(r'\d{1,2}', stem) and prev_tok[-1:] in ('로', '길', '동'))):
        return False  # address suffix: 명동1가, 중앙로 1가
    verdicts = [_decide(s, fam, form) for s in sorted(alts)]
    if not all(v[1] for v in verdicts):
        return False
    exp = verdicts[0][0]
    sound = sorted(alts)[0]
    start = base_off + len(core) - len(ent)
    if kind == 'hangul':
        conf, reason = _hangul_conf(core, stem, ent, fam, form, sound, lex)
        if conf is None:
            return False
    else:
        conf, reason = cap, f'{kind} stem read as ending {"/".join(sorted(alts))}'
    return Finding(start, start + len(ent), core, stem, ent, exp + tail, fam, sound, kind, conf, reason)


def tail_of(ent, fam):
    cf, vf, _ = FAMILIES[fam]
    for base in (cf, vf):
        if ent.startswith(base) and ent[len(base):] in TAILS[fam]:
            return ent[len(base):]
    return ''


def _hangul_conf(core, stem, ent, fam, form, sound, lex):
    """(confidence, reason) or (None, why-suppressed) for a Hangul stem."""
    if form == 'V':  # consonant / ㄹ stem + vowel-form particle
        if fam == 'quo' and sound == 'L':
            return None, '달라고/말라고 verb forms'
        if fam == 'and' and sound == 'L':
            return None, '알며 verb forms'
        if lex is None:
            if fam in ('acc', 'com', 'cop', 'with'):
                return 'likely', 'consonant stem + vowel form (no lexicon)'
            return None, 'needs lexicon (verb endings, -가 words, road names)'
        if lex.word_covering(core[:len(core) - len(tail_of(ent, fam))], len(ent) - len(tail_of(ent, fam))):
            return None, 'lexical word'
        noun = stem in lex.nouns
        if final_of(stem[-1]) == 20:
            return None, 'past-tense stem (았/었/했 + 나/는/며)'
        if fam in ('top', 'or', 'and', 'quo', 'nom', 'inst') and lex.verb_suffix(stem):
            return None, 'verb stem'
        if fam == 'nom' and final_of(stem[-1]) == 4:
            return None, '-ㄴ가 ending (인가, 는가, 누군가)'
        if fam in ('acc', 'com', 'cop'):
            return ('certain' if noun else 'likely'), 'consonant stem + vowel form'
        if fam in ('inst', 'with'):
            return 'low', '로/랑 after consonant (road/place names, mimetic words)'
        if fam in ('nom', 'quo'):  # -가 (價/家/街/歌) is a productive noun suffix: hint only
            return 'low', 'consonant stem + 가/라: productive -가 suffix words'
        if noun and len(stem) >= 2:
            return 'certain', 'known noun, consonant final + vowel form'
        return ('likely' if noun else 'low'), 'short/OOV stem + vowel form'
    # vowel stem (or ㄹ for 으로) + consonant form
    if fam == 'inst':
        if lex is not None and core in lex.allwords:
            return None, 'lexical'
        noun = lex is not None and stem in lex.nouns
        return ('certain' if noun else 'likely'), '으로 after vowel/ㄹ'
    if fam == 'acc':
        if any(core.endswith(w) for w in VOWEL_EUL_EXC) or core.endswith(JAMO_NAMES) or (lex and lex.word_covering(core, 2)):
            return None, 'lexical 을'
        if lex is None:
            return 'likely', 'vowel stem + 을 (no lexicon)'
        return ('certain' if stem in lex.nouns else 'likely'), 'vowel stem + 을'
    if lex is None:
        return None, 'needs lexicon'
    noun = stem in lex.nouns
    if fam != 'top' and core in lex.allwords:
        return None, 'lexical word'
    if fam == 'top' and lex.word_covering(core, len(ent)):
        return None, 'lexical word'
    if fam == 'top':
        if core.endswith(SEUT_IRREG_EUN):
            return None, 'ㅅ-irregular adnominal'
        if noun and len(stem) >= 2:
            return 'likely', 'known noun, vowel final + 은 (could be a person name: 유해은)'
        if len(stem) >= 2:
            return 'low', 'OOV vowel stem + 은 (names, verbs)'
        return None, 'short vowel stem + 은 (나은, 지은)'
    if fam == 'com' and len(stem) >= 2 and not noun:
        return 'low', 'OOV vowel stem + 과'
    if not noun:
        return None, 'stem not a known noun'
    if lex.known_word(stem + ent[0]) and ent[0] in ('이', '과'):
        return None, 'alternate parse is a word (나이, 차이, 결과)'
    return 'low', 'vowel stem + consonant form (이/과/이나/이랑): ambiguous (科 suffix, names, loanwords)'


# ----------------------------------------------------------------------------- gate
def gate(source: str, output: str, lexicon: Lexicon | None = None, min_conf: str = 'likely') -> list[Finding]:
    """Findings in `output` that the rewrite introduced: the same (stem, particle) pair is not flagged in `source`."""
    src_keys: dict = {}
    for f in check(source, lexicon, 'low'):
        src_keys[f.key()] = src_keys.get(f.key(), 0) + 1
    res = []
    for f in check(output, lexicon, min_conf):
        if src_keys.get(f.key(), 0) > 0:
            src_keys[f.key()] -= 1
            continue
        res.append(f)
    return res


def repair(text: str, findings: list[Finding]) -> str:
    """Apply the expected allomorph for each finding (call with the same text that produced the findings)."""
    out = text
    for f in sorted(findings, key=lambda f: -f.start):
        out = out[:f.start] + f.expected + out[f.end:]
    return out


def main() -> int:
    """Repair particle mismatches the rewrite introduced; same CLI shape as the restore scripts."""
    import argparse
    import json
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True)
    parser.add_argument('--after', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    with open(args.before, encoding='utf-8', newline='') as file:
        source = file.read()
    with open(args.after, encoding='utf-8', newline='') as file:
        output = file.read()
    off = os.environ.get('SUPER_SEJONG_MODE', '').strip().lower() == 'off'
    findings = [] if off else gate(source, output, None, 'likely')
    if findings:
        output = repair(output, findings)
    with open(args.out, 'w', encoding='utf-8', newline='') as file:
        file.write(output)
    if args.json:
        print(json.dumps({'repaired': len(findings)}), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
