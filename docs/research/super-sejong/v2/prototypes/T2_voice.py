"""Voice signature (말투) prototype for Super Sejong v2 - track T2.

Two backends:
  * regex  - dependency-free, operates on the last Hangul eojeol of the sentence (product candidate).
  * kiwi   - uses kiwipiepy 0.24 morphemes (offline evaluation / reference).

Public API
  split_sentences(text) -> list[Seg]           (kind = body | heading | list | quote | verse-ish)
  signature(sentence, backend='regex') -> dict  (level, mood, ending, hon_si, humble, persona, ...)
  profile(text, backend='regex') -> dict       (document voice profile)

Levels (fine): HAPSYO 하십시오체, HAEYO 해요체, HAERA 해라체(+하라체), HAE 해체(반말), HAO 하오체, HAGE 하게체,
               NOMINAL 명사형/개조식 종결, NONE (fragment, connective ending, no predicate).
Tiers (for the gate): HIGH = {HAPSYO, HAEYO} ; LOW = {HAERA, HAE} ; PERSONA = {HAO, HAGE} ; NOMINAL ; NONE.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE, NOMINAL, NONE = (
    'HAPSYO', 'HAEYO', 'HAERA', 'HAE', 'HAO', 'HAGE', 'NOMINAL', 'NONE')
LEVELS = (HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE, NOMINAL, NONE)
FINITE = (HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE)
TIER = {HAPSYO: 'HIGH', HAEYO: 'HIGH', HAERA: 'LOW', HAE: 'LOW', HAO: 'PERSONA', HAGE: 'PERSONA',
        NOMINAL: 'NOMINAL', NONE: 'NONE'}
DECL, INTERR, IMPER, PROPOS, EXCL = 'DECL', 'INTERR', 'IMPER', 'PROPOS', 'EXCL'


def jong(ch: str) -> int:
    """Final-consonant index of a precomposed Hangul syllable (0 = none, 8 = ㄹ, 16 = ㅁ, 17 = ㅂ)."""
    c = ord(ch) - 0xAC00
    return c % 28 if 0 <= c < 11172 else -1


def is_hangul(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3


# ---------------------------------------------------------------- segmentation
QUOTE_RE = re.compile(r'"[^"\n]{0,600}"|“[^”\n]{0,600}”|‘[^’\n]{0,600}’|「[^」\n]{0,600}」|『[^』\n]{0,600}』'
                      r"|'[^'\n]{2,600}'")
LIST_RE = re.compile(r'^\s*(?:[-*+•·▪○●■□▶▷◆◇✔✓※☞→]|\d{1,2}[.)]|\(\d{1,2}\)|[가-하][.)]|[①-⑳])\s*')
HEAD_RE = re.compile(r'^\s*(?:#{1,6}\s|\[[^\]]{1,40}\]\s*$|【|<[^>]{1,40}>\s*$|제\s*\d+\s*[조장절항]|[IVX]+\.\s|Q\d*[.:]|A\d*[.:])')
TRAIL_RE = re.compile(r'(?:\s|[.!?。…~～,;:"”’\'」』)\]）】>*\-_=+/\\|♡♥★☆^]|ㅎ|ㅋ|ㅠ|ㅜ|;|\(웃음\)|\(\^\^\)|'
                      r'[\U0001F300-\U0001FAFF☀-➿]|[:;]-?[)(DP])+$')
EMO_RE = re.compile(r'ㅎ{2,}|ㅋ{2,}|ㅠ+|ㅜ{2,}|\^\^|\^_\^|;;+|~{1,}|!{2,}|\?{2,}|[\U0001F300-\U0001FAFF☀-➿]|\(웃음\)|><')


@dataclass
class Seg:
    text: str
    kind: str      # body | heading | list | quote
    par: int


def split_sentences(text: str):
    """Split into sentence-like segments. Quoted spans are kept inside their sentence (masked for splitting)."""
    out = []
    pars = re.split(r'\n\s*\n', text.strip())
    for pi, par in enumerate(pars):
        for line in par.split('\n'):
            if not line.strip():
                continue
            kind = 'body'
            if HEAD_RE.match(line):
                kind = 'heading'
            elif LIST_RE.match(line):
                kind = 'list'
            masked = QUOTE_RE.sub(lambda m: '\x00' * len(m.group(0)), line)
            starts, last = [], 0
            for m in re.finditer(r'(?<=[.!?。…])[\'"”’)\]」』]*\s+(?=\S)|(?<=[요다죠까])\s{2,}(?=\S)', masked):
                starts.append((last, m.end()))
                last = m.end()
            starts.append((last, len(line)))
            for a, b in starts:
                s = line[a:b].strip()
                if s:
                    k = kind
                    if k == 'body':
                        stripped = TRAIL_RE.sub('', s)
                        if stripped and QUOTE_RE.fullmatch(stripped.strip()):
                            k = 'quote'
                    out.append(Seg(s, k, pi))
    return out


def mask_quotes(s: str) -> str:
    """Replace embedded quotations by a neutral token unless the whole sentence is a quotation."""
    whole = re.sub(r'[\s.!?。…]+$', '', s.strip())
    if QUOTE_RE.fullmatch(whole):
        return whole[1:-1]
    core = TRAIL_RE.sub('', s).strip()
    m = QUOTE_RE.fullmatch(core)
    if m:
        return core[1:-1]
    return QUOTE_RE.sub('인용', s)


# ---------------------------------------------------------------- regex backend
NOUN_YO = ('필요', '중요', '주요', '개요', '수요', '소요', '요요', '강요', '동요', '불필요', '요구', '사요')
KIN_NI = ('어머니', '할머니', '언니', '미니', '데니', '사니', '서니', '마니', '보니', '하니', '고니', '아니')
NOUN_JA = ('남자', '여자', '의자', '과자', '모자', '숫자', '투자', '사자', '기자', '환자', '학자', '자자', '이자',
           '부자', '왕자', '자자', '문자', '한자', '감자', '상자', '액자', '혼자', '제자', '주자', '타자', '저자')
PROPOS_STEM = re.compile(r'(?:하|보|가|먹|오|쓰|읽|두|해|봐|나|들|자|잊|알|살|찾|떠나|만들|기억하|시작하|나누|생각해|'
                         r'정리하|살펴보|알아보|확인하|돌아보|이야기하|말하|쉬|걷|놀|웃|뛰|모이|지키|버리|챙기|줄이|늘리)자$')
HAO_SO = re.compile(r'(?:있|없|었|았|였|했|겠|됐|좋|같|싶|맞|않|봤|왔|갔|줬|랐|잖|럽|렇|겁|답|쁘|프|르)소$|(?:었|았|였|했|있|없)수$')
HAO_O = re.compile(r'(?:하|이|되|가|보|주|오|그러|그렇|아니|어떠|마|두|쓰|나)오$')
LOW_FINAL_DA = re.compile(r'다$')
HAGE_CTX = re.compile(r'자네|안녕하신가|이 사람아|여보게')


CUTE_CODA = {'엉': '어', '얌': '야', '당': '다', '징': '지', '넹': '네', '용': '요', '앙': '아', '행': '해'}


def final_word(sentence: str) -> tuple[str, str]:
    """(last eojeol with trailing punctuation/emoticons/parenthetical citations removed, trailing chars)."""
    s = mask_quotes(sentence).strip()
    core = s
    while True:
        prev = core
        core = re.sub(r'\s*[(（][^()（）]{0,80}[)）][.!?。…~]*$', '', core)  # (행정심판법 제27조), (웃음), kaomoji
        core = TRAIL_RE.sub('', core)
        core = re.sub(r'[^가-힣A-Za-z0-9%]+$', '', core)                  # any other trailing symbols
        core = re.sub(r'\s+(?:ㅎ+|ㅋ+|ㅠ+|ㅜ+|허허+|하하+|호호+|헤헤+|글쎄|참|뭐)$', '', core)  # laughter / trailing interjection
        if core == prev:
            break
    tail = s[len(core):]
    m = re.search(r'([가-힣A-Za-z0-9%]+)$', core)
    w = m.group(1) if m else ''
    if w and EMO_RE.search(sentence) and w[-1] in CUTE_CODA and len(w) >= 2:
        w = w[:-1] + CUTE_CODA[w[-1]]
    return w, tail


def regex_level(sentence: str) -> tuple[str, str]:
    """(level, ending-label) from the final eojeol."""
    w, tail = final_word(sentence)
    if sentence.rstrip().endswith((',', '，')):
        return NONE, 'comma-continuation'
    if not w or not is_hangul(w[-1]):
        if w and re.search(r'[0-9A-Za-z%]$', w):
            return NOMINAL, 'non-hangul'
        return NONE, ''
    # HAPSYO: -(스)ㅂ니다 / -(스)ㅂ니까 / -십시오 / -답니다
    if len(w) >= 3 and w[-2:] in ('니다', '니까') and (jong(w[-3]) == 17 or w[-3] in '습읍'):
        return HAPSYO, ('답니다' if w.endswith(('답니다', '랍니다', '냅니다', '잡니다')) else 'ㅂ니' + w[-1])
    if w.endswith(('십시오', '십시요', '옵소서', '나이다', '나이까', '십시다')):
        return HAPSYO, w[-3:]
    if len(w) >= 3 and w.endswith('시다') and jong(w[-3]) == 17:        # 갑시다 / 합시다 (NIKL: 하오체 청유)
        return HAO, 'ㅂ시다'
    # HAEYO
    if w.endswith(('요', '죠')) and not w.endswith(NOUN_YO):
        for e in ('더라고요', '거든요', '잖아요', '는데요', '던데요', '네요', '군요', '걸요', '게요', '래요', '대요',
                  '나요', '까요', '지요', '세요', '셔요', '예요', '에요', '고요', '어요', '아요', '여요', '해요', '워요', '와요', '줘요', '봐요'):
            if w.endswith(e):
                return HAEYO, e
        return HAEYO, w[-1]
    # HAO
    if w.endswith('시오') or w.endswith('구려') or HAO_SO.search(w) or (len(w) >= 2 and HAO_O.search(w)):
        return HAO, w[-2:]
    # HAGE
    if w.endswith(('다네', '라네', '는가네', '게나', '함세', '감세', '줌세', '봄세', '하세', '가세', '보세', '구먼', '구만', '로구먼')):
        return HAGE, w[-2:]
    if w.endswith('게') and len(w) >= 2 and jong(w[-2]) != 8 and re.search(r'(?:오|가|하|보|주|앉|들|먹|쉬|오시|두)게$', w) and '!' not in tail and '자네' in sentence:
        return HAGE, '게'
    if w.endswith(('는가', 'ㄴ가', '던가')) or (len(w) >= 2 and w.endswith('가') and jong(w[-2]) == 4 and '?' in tail):
        return (HAGE if HAGE_CTX.search(sentence) else HAERA), '는가'
    # HAERA
    if w.endswith('다'):
        if w.endswith(('는다', '었다', '았다', '였다', '했다', '겠다', '이다', '한다', '된다', '있다', '없다', '않다', '같다', '싶다', '렵다', '롭다', '스럽다')):
            return HAERA, w[-2:]
        if len(w) >= 2 and (jong(w[-2]) == 4 or w[-2] in '하되이있없않같좋많크작높낮쉽어렵다르기바쁘'):
            return HAERA, '다'
        if w in ('바다', '사다', '마다') or w.endswith(('보다', '마다', '부터다')):
            return (NOMINAL if w.endswith('마다') else HAERA), '다'
        return HAERA, '다'
    if w.endswith(('구나', '로구나', '는구나', '더라', '도다', '노라', '느냐', '으냐', '려무나', '렴')):
        return HAERA, w[-2:]
    if w.endswith('냐') or (w.endswith('니') and '?' in tail and not w.endswith(KIN_NI)) or w.endswith(('으랴', 'ㄹ쏘냐')):
        return HAERA, w[-1]
    if w.endswith(('어라', '아라', '거라', '너라', '여라', '해라', '하라', '봐라', '줘라', '와라', '워라')):
        return HAERA, '어라'
    if w.endswith('자') and not w.endswith(NOUN_JA) and PROPOS_STEM.search(w):
        return HAERA, '자'
    # HAE (해체 / 반말)
    if w.endswith(('니깐', '라니까', '다니까', '라니깐')):
        return HAE, '니까'
    if w.endswith(('는지', '은지', '을지', '던지')) and '?' in tail:
        return HAE, '는지'
    if w in ('가', '해', '봐', '와', '줘', '돼', '놔', '써', '싫어', '좋아', '슬퍼', '아파', '기뻐', '바빠', '예뻐') or w.endswith(('러가', '어가', '아가', '야해', '고해', '해야해', '슬퍼', '아파', '기뻐', '바빠', '예뻐', '고파', '나빠')):
        return HAE, '어'
    for e in ('더라고', '거든', '잖아', '는데', '던데', '은데', '을걸', '는걸', '을게', '을래', '을까', '군', '니까'):
        if w.endswith(e):
            if e == '니까' and len(w) >= 3 and jong(w[-3]) == 17:
                break
            return HAE, e
    if len(w) >= 2 and w[-1] in '게래까걸' and jong(w[-2]) == 8:               # 할게, 갈래, 할까, 할걸
        return HAE, 'ㄹ' + w[-1]
    if len(w) >= 2 and w.endswith('네') and not w.endswith(('자네', '우리네', '아이네', '저네')):
        return HAE, '네'
    if len(w) >= 2 and w.endswith('대') and (jong(w[-2]) == 4 or w[-2] in '했였었았이') and not w.endswith(('시대', '세대', '대대', '최대', '최소한대')):
        return HAE, '대'
    if w.endswith(('었지', '았지', '였지', '겠지', '했지', '됐지', '하지', '되지', '있지', '없지', '않지', '같지', '좋지',
                   '맞지', '그렇지', '이지', '거지', '그치', '알지', '봤지', '거야', '이야', '잖니')):
        return HAE, w[-1]
    if len(w) >= 2 and w.endswith('지') and jong(w[-2]) == 20:            # 렸지, 겠지, 했지 (past/future + 지)
        return HAE, '지'
    if w.endswith('나') and '?' in tail and len(w) >= 2:
        return HAE, '나'
    if len(w) >= 2 and w[-1] in '어아여해워와줘봐돼봬셔져쳐펴켜려써' and not w.endswith(('언어', '단어', '영어', '고어', '숭어', '오징어',
                                                                    '포아', '아시아', '여아', '남아', '미아', '하여', '위하여', '대하여', '통하여', '의하여')):
        return HAE, '어'
    if w.endswith('야') and len(w) >= 2 and (jong(w[-2]) == 0 or w[-2] == '이') and not w.endswith(('분야', '시야', '야야', '하여야', '해야', '어야', '아야')):
        return HAE, '야'
    # NOMINAL (명사형·개조식) vs NONE (connective / fragment)
    if (jong(w[-1]) == 16 and len(w) >= 2) or w.endswith(('음', '기', '것', '중', '예정', '필요', '가능', '불가', '완료', '기준')):
        return NOMINAL, 'ㅁ/기/명사'
    if re.search(r'(?:고|며|면|서|해서|하여|지만|는데|면서|도록|려고|으나|니|거나|든지|든가|자마자|듯|게|지|ㄴ지|는지|을지|ㄹ지|이나|나|로|으로|에|에서|에게|을|를|이|가|은|는|와|과|도|만|의|및|등)$', w):
        return NONE, 'connective/particle'
    return NOMINAL, '명사'


# ---------------------------------------------------------------- kiwi backend
_kiwi = None


def kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


EF_MAP = [  # (predicate on EF form, level)
    (lambda f: f.endswith(('ᆸ니다', '습니다', 'ᆸ니까', '습니까', '답니다', '랍니다', '냅니다', '잡니다', 'ᆸ시오', '십시오', '나이다', '옵소서', '십시다')), HAPSYO),
    (lambda f: f in ('ᆸ시다', '읍시다'), HAO),
    (lambda f: f.endswith(('요', '죠')), HAEYO),
    (lambda f: f in ('오', '소', '구려', '시오', '으오', '으시오', '소서'), HAO),
    (lambda f: f in ('네',) , HAE),
    (lambda f: f in ('다네', 'ᆫ다네', '는다네', '라네', '게', '게나', '세', 'ᆷ세', '음세', '는가', 'ᆫ가', '던가', '은가'), HAGE),
    (lambda f: f.endswith(('다', '라', '냐', '구나', '도다', '노라', '자', '렴', '려무나', '랴', '느냐')) or f in ('니',), HAERA),
]


def kiwi_level(sentence: str) -> tuple[str, str, dict]:
    info = {'hon_si': False}
    if sentence.rstrip().endswith((',', '，')):
        return NONE, 'comma-continuation', info
    s = mask_quotes(sentence)
    s = re.sub(r'\s*[(（][^()（）]{0,80}[)）]\s*([.!?。]*)\s*$', r'\1', s)   # trailing citation / kaomoji
    toks = kiwi().tokenize(s)
    i = len(toks) - 1
    while i >= 0 and (toks[i].tag in ('SF', 'SP', 'SS', 'SSO', 'SSC', 'SE', 'SO', 'SW', 'W_EMOJI', 'Z_CODA', 'Z_SIOT', 'IC', 'JKV')
                      or toks[i].form in ('ㅎㅎ', 'ㅋㅋ', 'ㅠㅠ')):
        if toks[i].tag == 'JKV':                      # vocative: 그대여, 비야 -> no predicate
            return NONE, 'vocative', info
        i -= 1
    if i < 0:
        return NONE, '', info
    last = toks[i]
    j = i
    while j >= 0 and toks[j].tag in ('EP', 'EF', 'EC', 'JX', 'VX', 'XSV', 'XSA', 'ETM', 'NNB', 'VCP', 'ETN', 'VV', 'VA', 'VA-I', 'VV-I', 'VX-I'):
        if toks[j].tag == 'EP' and toks[j].form in ('시', '으시'):
            info['hon_si'] = True
        if toks[j].tag.startswith(('VV', 'VA')) and toks[j].form in ('계시', '드시', '주무시', '잡수시'):
            info['hon_si'] = True
        if toks[j].tag.startswith(('VV', 'VA')) and j < i - 3:
            break
        j -= 1
    info['pred_tag'] = next((t.tag for t in reversed(toks[:i + 1]) if t.tag.startswith(('VV', 'VA', 'VCP', 'VCN', 'XSA', 'XSV'))), '')
    if last.tag == 'JX' and last.form == '요':
        return HAEYO, (toks[i - 1].form if i else '') + '요', info
    f = last.form
    if last.tag in ('EF', 'EC'):
        if f in ('세요', '으세요', '셔요'):
            info['hon_si'] = True
        if f in ('소', '수', '잖소', '구려', '오', '으오', '시오', '으시오') and (last.tag == 'EF' or i == len(toks) - 1 or toks[i + 1].tag.startswith('S') or toks[i + 1].tag.startswith('Z')):
            return HAO, f, info
        if f in ('ᆸ시다', '읍시다') and i >= 1 and toks[i - 1].tag == 'EP' and toks[i - 1].form in ('시', '으시'):
            return HAPSYO, '십시다', info
        if f in ('구먼', '는구먼', '구만', '는구만', '로구먼'):
            return HAGE, f, info
        if f == '네':
            return (HAGE if HAGE_CTX.search(s) else HAE), f, info
        if f in ('는가', 'ᆫ가', '던가', '은가'):
            return (HAGE if HAGE_CTX.search(s) else HAERA), f, info
        if f == '나':
            return HAE, f, info
        if f == '게' and not HAGE_CTX.search(s):
            return HAE, f, info
        if last.tag == 'EF':
            for pred, lv in EF_MAP:
                if pred(f):
                    return lv, f, info
            return HAE, f, info                       # 어/지/군/거든/잖아/ᆯ게/ᆯ까/는데/는지 ...
        # EC in final position: Kiwi tags some sentence-final 해체 endings as EC
        if f in ('어', '아', '여', '는데', 'ᆫ데', '던데', '거든', '지', '는지', '니까', '니깐', '라니까', '다니까'):
            return HAE, f, info
        return NONE, 'EC', info
    if last.tag == 'ETN' or last.tag.startswith('N') or last.tag in ('SN', 'SL', 'SH', 'XSN', 'NR', 'XR'):
        return NOMINAL, last.tag, info
    return NONE, last.tag, info


# ---------------------------------------------------------------- shared features
PERSONA_RE = {
    'first_humble': re.compile(r'(?<![가-힣])(?:저는|저도|저를|저만|저에게|저한테|제가|제\s|저희|저의|저로서)'),
    'first_plain': re.compile(r'(?<![가-힣])(?:나는|나도|나를|내가|나에게|나한테|나의|나만)(?![가-힣])'),
    'first_we': re.compile(r'(?<![가-힣])우리(?:는|가|의|도|를|에게|\s)'),
    'first_author': re.compile(r'필자|본인은|글쓴이|본 블로그|이 블로그'),
    'self_intro': re.compile(r'[가-힣]{2,4}\s?(?:행정사|변호사|세무사|노무사|선생님|원장|대표|작가|기자)입니다'),
}
ADDRESSEE_RE = re.compile(r'(?<![가-힣])(?:여러분|고객님|학부모님|부모님|선생님|회원님|이웃님|독자님|당신|자네|그대|너는|너도|네가|너를|너희)')
HUMBLE_RE = re.compile(r'드리|드립|드려|드렸|여쭈|여쭙|여쭤|뵙|뵈|뵐|모시|모셔|말씀드|올리겠|올립니다|올려요')
HON_LEX_RE = re.compile(r'께서|계시|계셔|계세요|계십|드시|드세요|주무시|잡수|돌아가시|말씀(?!드)|여쭈|님(?:이|께|은|는|도|의|을|들)?')
SI_RE = re.compile(r'(?:[하가오보주되있알받읽쓰찾]|[가-힣])(?:시|셨|셔|세|십|실|신|실)(?:니다|습니다|어요|요|다|고|면|는|ㄴ|지|게|죠|까|었|겠|ㅂ|기|길)?')
DISCOURSE_RE = re.compile(r'(?<![가-힣])(?:사실|솔직히|아무튼|어쨌든|근데|그런데|그러니까|그니까|자,|음,|아,|와,|헐|참,|뭐,|글쎄|진짜|정말|완전|아이고|에휴|어머)(?![가-힣])')
# Deliberate colloquial spellings / CMC lexemes (owner decision 2: preserved by default, normalising is opt-in).
COLLOQ_RE = re.compile(r'(?<=[가-힣])께(?=요|[\s.!?~]|$)|(?<![가-힣])(?:넹|넵|넴|웅|응응|걍|젤|넘|쫌|담에|첨|암튼|글구|그쵸|머)(?![가-힣])'
                       r'|(?:니당|어용|아용|해용|세용|네용|했당|었당|았당|좋당|같당|이당|해여|어여|아여|세여|네여|이징|거징|했엉|었엉|았엉|해앙|거양|이얌|거얌)(?=[\s.!?~ㅋㅎㅠ^]|$)')
DISCOURSE_INITIAL_RE = re.compile(r'^(?:[\s"“‘\'(]*)(?:사실|솔직히|아무튼|암튼|어쨌든|뭐|아이고|에휴|어머|와|음|아|참|글쎄|그니까|자|헐)(?=[\s,.!?~]|$)')
DISCOURSE_ANY_RE = re.compile(r'(?<![가-힣])(?:진짜|완전|대박|솔직히)(?![가-힣]*(?:와|과|를|을|이|가)\s)(?=[\s,.!?~]|$)')


def cmc_tokens(sentence: str) -> list:
    """Ordered list of CMC/colloquial tokens of a sentence (quotes masked). Part of the per-sentence voice signature."""
    t = mask_quotes(sentence)
    toks = [('emo', m.group(0)[:2]) for m in EMO_RE.finditer(t)]
    toks += [('spell', m.group(0)) for m in COLLOQ_RE.finditer(t)]
    toks += [('disc', m.group(0).strip(' "“‘\'(')) for m in DISCOURSE_INITIAL_RE.finditer(t.strip())]
    toks += [('disc', m.group(0)) for m in DISCOURSE_ANY_RE.finditer(t)]
    return sorted(toks)


BLOG_ENDINGS = ('더라고요', '거든요', '잖아요', '네요', '군요', '죠', '지요', '답니다', '랍니다', '는데요', '걸요', '게요', '대요', '래요', '나요', '까요')


HON_SI_PRED = re.compile(r'(?:[가-힣])(?:시(?=[다고면는지겠오죠기길며어게네]|$|ᆫ|ᆯ)|셨|셔|세요|십|신(?=\s|가|건|$|데|지)|실(?=\s|게|래|까|$))'
                         r'|계시|계셔|계세|계십|계신|드시|드셔|드세|주무시|잡수')
HON_SI_NOUN = re.compile(r'(?:[출대자당통혁최확과정갱경헌배송수발전]신|신청|신고|신규|신뢰|신속|마시|마셨|마셔|가르치|실시|제시|표시|개시|무시|지시|명시|게시|감시|전시|동시|당시|즉시|수시|역시|다시|혹시|서울시|도시|시시|교시|응시|착시|중시|간주시)(?:[는가도를의에]|\s|$)')


def regex_hon_si(sentence: str) -> bool:
    """-시- in the final predicate complex (last two eojeols), quotes masked."""
    core = re.sub(r'[^가-힣\s]+', ' ', mask_quotes(sentence)).split()
    if not core:
        return False
    tail = core[-1]
    if len(core) >= 2 and re.match(r'(?:것|거|건|겁|게|겐|싶|있|않|없|같)', core[-1]):
        tail = core[-2] + ' ' + core[-1]
    tail = HON_SI_NOUN.sub(' ', tail)
    return bool(HON_SI_PRED.search(tail))


def mood_of(sentence: str, level: str, ending: str) -> str:
    _, tail = final_word(sentence)
    w = final_word(sentence)[0]
    if w in ('안녕하세요', '안녕하십니까', '안녕하시오', '안녕하신가', '안녕하셨어요', '안녕하셨습니까'):
        return INTERR if '?' in tail else DECL
    if '?' in tail or w.endswith(('니까', '나요', '까요', '가요', '는지요', '을까', '할까', '냐', '느냐', '는가', 'ㄴ가', '던가')) \
            or ending in ('ᆸ니까', '습니까', '냐', '느냐', 'ᆯ까', 'ᆯ까요', '을까요', 'ᆫ가요', '나요', '는가', 'ᆫ가', '니'):
        return INTERR
    if w.endswith(('십시오', '시오', '어라', '아라', '거라', '너라', '여라', '해라', '하라', '세요', '셔요', '십시요')) and level != NOMINAL:
        if w.endswith(('세요', '셔요')) and re.search(r'(?:이세요|계세요|으세요\?|분이세요|하시네요)$', w):
            return DECL
        if w.endswith(('세요', '셔요')) and re.search(r'(?:친절하|바쁘|좋으|크|젊으|예쁘|많으|높으|멋지|훌륭하|대단하|아프|편찮으|이|이시|분이)(?:세요|셔요)$', w):
            return DECL
        return IMPER
    if w.endswith(('마오', '마시오', '마십시오')):
        return IMPER
    if w.endswith(('ㅂ시다', '십시다', '하자', '보자', '가자', '읍시다')) or ending in ('자', 'ㅂ시다', '십시다') or (len(w) >= 3 and w.endswith('시다') and jong(w[-3]) == 17):
        return PROPOS
    if w.endswith(('구나', '군요', '군', '구먼', '도다', '네요', '구려')) and '!' in tail:
        return EXCL
    if '!' in tail and w.endswith(('구나', '군')):
        return EXCL
    return DECL


def signature(sentence: str, backend: str = 'regex', kind: str = 'body') -> dict:
    if backend == 'kiwi':
        level, ending, info = kiwi_level(sentence)
        hon_si = info['hon_si']
    else:
        level, ending = regex_level(sentence)
        hon_si = level in FINITE and regex_hon_si(sentence)
    persona = sorted(k for k, r in PERSONA_RE.items() if r.search(sentence))
    return {
        'level': level, 'tier': TIER[level], 'ending': ending,
        'mood': mood_of(sentence, level, ending) if level in FINITE else None,
        'hon_si': bool(hon_si), 'humble': bool(HUMBLE_RE.search(sentence)),
        'persona': persona, 'addressee': sorted(set(ADDRESSEE_RE.findall(sentence))),
        'discourse': sorted(set(m.group(0).rstrip(',') for m in DISCOURSE_RE.finditer(sentence))),
        'emo': len(EMO_RE.findall(sentence)),
        'cmc': cmc_tokens(sentence),
        'blog_ending': None if final_word(sentence)[0].endswith('바랍니다') else next((e for e in BLOG_ENDINGS if final_word(sentence)[0].endswith(e)), None),
        'kind': kind,
    }


def profile(text: str, backend: str = 'regex') -> dict:
    from collections import Counter
    segs = split_sentences(text)
    lv = Counter()
    moods = Counter()
    endings = Counter()
    persona = Counter()
    emo = 0
    for sg in segs:
        sig = signature(sg.text, backend, sg.kind)
        if sg.kind == 'body':
            lv[sig['level']] += 1
            if sig['mood']:
                moods[sig['mood']] += 1
            if sig['blog_ending']:
                endings[sig['blog_ending']] += 1
        for p in sig['persona']:
            persona[p] += 1
        emo += sig['emo']
    finite = {k: v for k, v in lv.items() if k in FINITE}
    n = sum(finite.values())
    dom = max(finite, key=finite.get) if finite else None
    share = finite[dom] / n if n else 0
    return {'n_body': sum(lv.values()), 'levels': dict(lv), 'dominant': dom, 'dominant_share': round(share, 3),
            'mixed_high': bool(finite.get(HAPSYO) and finite.get(HAEYO)), 'moods': dict(moods),
            'blog_endings': dict(endings), 'persona': dict(persona), 'emoticons': emo}


# ---------------------------------------------------------------- baselines for comparison
def ts_sentence_speech_level(sentence: str):
    """Port of sentenceSpeechLevel() in src/engine/super-sejong.ts (commit 4b6a7a9)."""
    bare = re.sub(r'[\s"”’\')\]」』.!?。…~]+$', '', sentence.strip())
    if not bare:
        return None
    if re.search(r'(?:니다|니까|십시오|시오|ㅂ시다|옵니다)$', bare):
        return HAPSYO
    if re.search(r'(?:요|죠)$', bare):
        return HAEYO
    if re.search(r'(?:다|까|냐|구나|자|라)$', bare):
        return HAERA
    return None
