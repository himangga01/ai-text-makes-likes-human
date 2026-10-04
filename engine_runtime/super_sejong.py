"""Super Sejong Engine: deterministic Korean meaning invariants for rewrites.

Each text is reduced to meaning events with bounded regular expressions (no analyser):

  NEG      clause negations (않/없/아니, 안·못 + predicate), idioms and locative 안 removed
  CAN      ability/possibility (수 있다, 가능하다, 못 V, 수 없다, 불가능하다)  +/-
  DEONT    must / prohibited / not-needed / recommended; double negation that means
           obligation (~지 않으면 안 된다, ~지 않을 수 없다) counts as must
  HEDGE    추정, 보인다, 것 같다 ... ; CERTX 확실/불확실/반드시
  AX       lexical axes (about 45 antonym pairs: direction, stance, outcome, knowing ...);
           negation bound to an axis word flips its sign, so "가능하지 않다" == "불가능하다",
           "쉽지 않다" == "어렵다", "알지 못했다" == "몰랐다"
  QUANT    all/most/some quantifier classes;  BOUND (이상|이하|초과|미만|이내|최대|최소, value)
  ROLE     (agent, patient) frames with voice normalisation, converse verbs, focus particles,
           "A가 B보다" orientation, before/after order

Source and rewrite are compared event by event. These checks reject clear meaning drift;
they do not prove equivalence, and unknown synonyms on lexical axes are not flagged.
Evaluation (2026-10-04, pairs written by three different authors; see
docs/research/super-sejong/EVALUATION-2026-10-04.md): on a set nobody tuned on, overblock
11.7% and unsafe-accept 18.3%, against 38.3% and 40.0% for the first prototype.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from functools import lru_cache

# --------------------------------------------------------------------------
# sentence splitting
# --------------------------------------------------------------------------
_TERMINAL = re.compile(r'[.!?。！？…]+["”’\')\]」』]*(?=\s)|\n+')


def sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in _TERMINAL.finditer(text):
        # "3.5", "v1.2" never match because a terminal must be followed by whitespace.
        out.append(text[start:m.end()])
        start = m.end()
    out.append(text[start:])
    return [s.strip() for s in out if s.strip()]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _blank(m: 're.Match') -> str:
    return ' ' * (m.end() - m.start())


def _rule(text: str, pattern: 're.Pattern', events: list, event) -> str:
    def repl(m):
        events.append(event(m) if callable(event) else event)
        return ' ' * (m.end() - m.start())
    return pattern.sub(repl, text)


# Idioms that contain 않/없/못/아니 but are not negations of the clause.
_IDIOMS = re.compile(
    r'만\s+(?:[가-힣]+\s+){0,3}[가-힣]*는\s*것이\s*아니라|뿐만\s*아니라|뿐\s*아니라|뿐만\s*아니|못지않|머지않|다름\s*아닌|다름\s*아니라|아닌\s*게\s*아니라|'
    r'아니나\s*다를까|아니\s*땐|아닌\s*게\s*아니|잘못|못된|못난|'
    r'(?:다름|변함|어김|거침|끊임|끝|한|아낌|쓸데|쓸모|부질|빠짐|하릴|속절|영락|거리낌|이의|두말|의심할\s*여지|'
    r'쉴\s*새|소리|어쩔\s*수|하는\s*수|별\s*수|지체|주저|꼼짝|가차|다시|터무니|난데|느닷|이유|예외|사정)\s*없(?:이|는|다)?(?=$|[\s,.!?])|'
    r'(?:하는|할)\s*수\s*없이|아닌지|아닐까|아니냐|아닌가(?=\s*싶|\s*생각|\s*하는)|아니오|아니요')


# --------------------------------------------------------------------------
# axes: (name, positive regex alternatives, negative regex alternatives)
# Words are matched as plain substrings for >=2-syllable Sino-Korean words and at
# word start for short native stems. Negative-prefix forms (불합격) are listed in
# the negative side and blanked before the positive side is searched.
# --------------------------------------------------------------------------
_END = r'(?=[다고게은아으았었지습ᆸ며나네요]|$|\s)'   # adjective endings after a short stem
_AXES = [
    # direction / amount
    ('INC', r'증가|증대|증진|늘어|늘었|늘리|늘린|늘려|늘고|늘며|늘렸|급증|확충|상승|(?<![가-힣])오르(?=[다고며는])|올랐|올라|올려|올리(?=[다고며는])|올린|올렸|인상|높아|높였|높이(?=[다고며는])|높인|치솟|급등|증폭|확대|커지|커졌|넓어|넓히|넓혀|증설|가속|강화|강해|신장|상향|확장|부풀|성장|팽창|불어|늘어나|심화|격화|가중|고조',
     r'감소|감축|줄어|줄었|줄이|줄인|줄여|줄고|줄며|줄였|급감|하락|내렸|내려가|내리(?=[다고며는])|내린|떨어졌|떨어지|인하|낮아|낮췄|낮추|낮춰|낮춘|축소|둔화|작아|좁아|좁히|좁혀|약해|약화|완화|감속|하향|저하|위축|침체|하회|제한|억제|삭감|쇠퇴|감퇴|움츠'),
    ('SUP', r'찬성|동의(?!어)|지지|수락|수용|승인|허가|허락|허용|채택|가결|통과|합의|긍정|인정|옹호|동조|비준|환영|선호|호평|칭찬|칭송|격려|장려|포용|받아들|수긍|승낙|용인|공감|호응|찬동',
     r'반대|거절|거부|반려|부결|불허|금지|반박|부정(?![확적])|부인|불인정|기각|불승인|철회|반발|항의|배척|배제|비판|비난|질책|우려|불만|반감|규탄|질타|혹평|외면|거역|묵살|반론|이의'),
    ('GOOD', r'성공|개선|호전|향상|흑자|우수|양호|승리|합격|해결|회복|안정|안전|정상|유효|낙관|호조|활성|우세|진전|호황|순조|유리|이로운|이점|장점|강점|완화(?=되|해|했|한다)|치유|복구',
     r'실패|악화|적자|손실|손해|열등|불량|패배|패했|불합격|미해결|불안정|위험|비정상|무효|비관|부진|비활성|열세|퇴보|불황|불리|해로운|단점|약점|결함|훼손|손상|파손|고장'),
    ('OPEN', r'공개|개방|개최|개설|개통|가입|입장|입금|도입|신설|시작|개시|착수|출발|가동|(?<![가-힣])열(?=[었린어고려다])|오픈|개장|개막|출시|연결|접속|설치|생성|저장|보관|출석|참석|참가|입학|합류|승소|흡수',
     r'비공개|폐쇄|폐지|폐업|탈퇴|퇴장|출금|철폐|종료|마감|중단|도착|정지|(?<![가-힣])닫(?=[았힌아고혀다])|중지|취소|폐막|폐장|철수|단절|차단|제거|철거|삭제|소멸|폐기|결석|불참|졸업|이탈|패소|방출'),
    ('INCL', r'포함|추가|더했|더하(?=[다고며면여])|가산|합산|편입|선정|선발|채용|고용|영입',
     r'제외|(?<![가-힣])빼(?=[다고며어])|뺐|차감|공제|탈락|해고|퇴출|방출'),
    ('APPT', r'선임|임명|임용|승진|영전|발탁|복직', r'해임|파면|면직|강등|좌천|퇴임|사임|해촉|직위\s*해제'),
    ('BUYSELL', r'매수|구매|구입|사들|매입|(?<![가-힣])샀', r'매도|판매|처분|매각|양도|(?<![가-힣])팔(?=[았고다아])'),
    ('TRADE', r'수입(?!이\s*[늘줄])', r'수출'),
    ('GUILT', r'유죄|시인|자백', r'무죄'),
    ('TRUTH', r'진짜|진실|옳(?=[다고은았아])|올바르|정확|(?<![가-힣])맞(?=[다았는아고])|증명|입증', r'가짜|거짓|허위|틀렸|틀리|틀린|그르(?=[다고게])|오류|오답|부정확|허구|반증'),
    ('SIDE', r'공격|협력|협조|우호|동맹|화합|통합|연합', r'방어|대립|갈등|적대|분열|불화|분리|분단'),
    ('RANK', r'상위|최고|최상|선두|우위|장기|영구|전면|완전', r'하위|최저|최하|꼴찌|열위|단기|일시|부분|불완전|미흡'),
    ('MAGX', r'(?<![가-힣])높(?=[다은아고게이으았습지])|(?<![가-힣])많(?=[다은아고게으았습지이])|(?<![가-힣])(?:크(?=[다고게며지])|큰|커(?=[져졌지서요])|클|컸)|(?<![가-힣])긴(?=\s)|(?<![가-힣])길(?=[다고게어었지])|(?<![가-힣])넓(?=[다은어고게었지])|두껍|두꺼|무겁|무거|비싸|비싼|(?<![가-힣])빠르|(?<![가-힣])빨라|(?<![가-힣])빨랐|(?<![가-힣])강하|(?<![가-힣])강한|밝(?=[다은아고게았지])|뜨겁|뜨거(?=[운워웠])|(?<![가-힣])깊(?=[다은어고게었지])|굵(?=[다은어고게었지])|풍부|풍족|넉넉|(?<![가-힣])더\s|가장\s*높|가장\s*크|오래\s*(?:가|간|걸|지속)|(?<![가-힣])세(?=다|진|졌)',
     r'(?<![가-힣])낮(?=[다은아고게으았습지추])|(?<![가-힣])적(?=[다고게은어었지습])|(?<![가-힣])작(?=[다고게은아으았지습])|(?<![가-힣])짧|(?<![가-힣])좁(?=[다은아고게았지])|얇|가벼|가볍|(?<![가-힣])싸(?=[다고게])|(?<![가-힣])싼(?=\s)|(?<![가-힣])쌌|(?<![가-힣])느리|(?<![가-힣])느린|(?<![가-힣])느려|(?<![가-힣])약하|(?<![가-힣])약한|어둡|어두(?=[운워웠])|차갑|차가(?=[운워웠])|(?<![가-힣])얕|가늘|부족|빈약|(?<![가-힣])덜\s|모자라|모자란|빨리\s*(?:닳|소모|줄|식)|금방\s*(?:닳|식)'),
    ('EASE', r'(?<![가-힣])쉽|(?<![가-힣])쉬운|(?<![가-힣])쉬워|(?<![가-힣])쉬웠|수월|간단|용이|(?<![가-힣])편하|편리|단순',
     r'어렵|어려|힘들|까다롭|곤란|난해|복잡|번거롭|불편'),
    ('CERTX', r'확실|분명|명백|틀림없|확신|반드시|(?<![가-힣])꼭(?=\s)', r'불확실|불분명|불명확|불투명|모호'),
    # 모르다 is the lexical negation of 알다 ("알지 못했다" is normalised to it before the axes run).
    ('KNOW', r'(?<![가-힣])알(?=[았고다아는며지])(?!고리)|(?<![가-힣])안다(?=$|[\s.!?,])|(?<![가-힣])압니다', r'(?<![가-힣])모르|(?<![가-힣])몰랐|(?<![가-힣])몰라|(?<![가-힣])모른'),
]
_DEONT_OPTIONAL = re.compile(r'선택\s*사항|선택적|자율적으로|재량')
# The AX regexes are compiled with a negation-binding wrapper.
_NEG_SUFFIX = (r'(?P<suf>(?:하|되|이|인|한|해|했|된)?(?:지|게)?(?:는|도|가|를|은)?\s*(?:않|못(?:하|했|해|합|한)|못\s*한|아니|아닌|아닙)|'
               r'(?:은|ㄴ|는)?\s*(?:일|것|편|문제|상황)?(?:이|가)\s*(?:아니|아닌|아닙))')


def _compile_axes():
    out = {}
    for name, pos, neg in _AXES:
        out[name] = [(sign, re.compile(r'(?P<pre>(?:안|못)\s+)?(?P<w>' + words + r')' + _NEG_SUFFIX + r'?'))
                     for sign, words in ((-1, neg), (1, pos))]
    return out


_AXIS_RE = _compile_axes()
# Words that are positive on one axis but whose substring also occurs inside unrelated words.

# --------------------------------------------------------------------------
# event rules, applied in order
# --------------------------------------------------------------------------
_DOUBLE_NEG_OBLIG = re.compile(r'지\s*않으면\s*안\s*(?:된|됩|돼|되)|지\s*않을\s*수(?:가)?\s*없')
_KNOW_NOT = re.compile(r'(?<![가-힣])알지\s*못(?=하|했|해|합|한)')
_PROHIBIT = re.compile(r'(?:해서는|하면|하여서는|해선|하면은|하여선|어서는|아서는|으면|면|피우면|먹으면|가면|오면|넘으면)\s*안\s*(?:된|됩|돼|되)|안\s*됩니다|안됩니다|안돼|금지|불허|지\s*마(?:라|세요|십시오)|지\s*말(?:아야|라|고|자)|말아야')
_NOREQ = re.compile(r'(?:하지|지)\s*않아도\s*(?:된|됩|돼)|필요(?:가)?\s*없|필요하지\s*않|불필요|필요\s*없')
_OBLIG = re.compile(r'하여야|해야|돼야|되어야|되야|야\s*(?:한|합)|필요(?:가\s*있|하(?:다|며|고|지만|므로|여|니|ㅂ)|합|해|했|한\s*것)|필수|의무|반드시\s*[가-힣]*야')
_REC = re.compile(r'권장|권고|바람직|(?:것|편|게|면|는게|하는게)\s*(?:이|가)?\s*좋|좋겠')
_CAN_NEG = re.compile(r'(?<![가-힣])못\s+(?=[가-힣])|[가-힣]지\s*못|못하|(?<![가-힣])수(?:가|는|도)?\s*없|불가능|불가(?![피침결분])|가능(?:하)?지\s*(?:않|못)|가능성(?:이|은|도)?\s*(?:전혀|거의|별로)?\s*없|못다')
_CAN_POS = re.compile(r'(?<![가-힣])수(?:도|가|는)?\s*있|허용|허락|허가(?!증)|가능성(?:이|은|도)?\s*(?:있|충분)|가능(?!성)|도\s*(?:된다|됩니다|된다고|돼요|괜찮)')
_HEDGE = re.compile(r'기대(?:한|된|합|하)|가능성|확률|개연성|추정|추측|예상|예측|전망|짐작|것\s*같|(?<![이그저]렇)듯(?:하|\s|이)|아마|어쩌면|혹시|필시|대개|것으로\s*(?:보|판단|생각|여겨|예상|추정)|로\s*보이|보인다|보입니다|보이는|보이며|판단된|여겨진|로\s*판단|관측|공산')
_QUANT = [('ALL', re.compile(r'모든|모두|전부|전체|전원|항상|언제나|(?<![가-힣])늘\s|전\s*(?:지역|국민|직원|세계|국가|분야|학생)|전역|전국|누구나|누구든지?|무엇이든지?|언제든지?|어디든지?|어디서나')),
          ('MOST', re.compile(r'대부분|대다수|자주|흔히|거의\s*모|다수')),
          ('SOME', re.compile(r'일부|몇몇|가끔|때때로|간혹|종종|소수|드물게'))]

# --------------------------------------------------------------------------
# quantities with bounds
# --------------------------------------------------------------------------
_NATIVE = {'한': 1, '두': 2, '세': 3, '네': 4, '다섯': 5, '여섯': 6, '일곱': 7, '여덟': 8, '아홉': 9, '열': 10,
           '스무': 20, '스물': 20, '서른': 30, '마흔': 40, '쉰': 50}
_MULT = {'': 1, '천': 10**3, '백': 100, '만': 10**4, '억': 10**8, '조': 10**12}
_NUM = (r'(?:(?<![\d,.])\d[\d,]*(?:\.\d+)?\s*[천백만억조]?'
        r'|(?:열|스무|스물|서른|마흔|쉰)(?:\s*(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉))?|(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉))')
_BOUND_AFTER = re.compile(r'(?P<num>' + _NUM + r')\s*(?P<unit>[%A-Za-z가-힣]{0,3}?)\s*(?P<b>이상(?!하|한)|이하(?!하|한)|초과|미만|이내|넘(?=게|는|어|었|을)|안팎)')
_BOUND_BEFORE = re.compile(r'(?P<b>최대한?|최소|적어도|많아야|기껏해야)\s*(?:약\s*)?(?P<num>' + _NUM + r')')
_BOUND_KIND = {'이상': '>=', '이하': '<=', '초과': '>', '미만': '<', '이내': '<=', '넘': '>', '안팎': '~',
               '최대': '<=', '최대한': '<=', '최소': '>=', '적어도': '>=', '많아야': '<=', '기껏해야': '<='}


def _value(raw: str) -> str:
    raw = raw.strip()
    m = re.match(r'(\d[\d,]*(?:\.\d+)?)\s*([천백만억조]?)', raw)
    if m:
        return str(round(float(m.group(1).replace(',', '')) * _MULT[m.group(2)], 4))
    total = 0
    for word in re.findall(r'열|스무|스물|서른|마흔|쉰|한|두|세|네|다섯|여섯|일곱|여덟|아홉', raw):
        total += _NATIVE[word]
    return str(float(total)) if total else raw


# --------------------------------------------------------------------------
# feature extraction
# --------------------------------------------------------------------------
_SHORT_NEG = re.compile(r'(?<!\S)(안|못)\s+([가-힣]{1,32})(?=$|[\s.!?,…~])')
_SHORT_NEG_PREV = re.compile(r'([가-힣A-Za-z0-9]+)\s+$')
# Words that end a phrase before a negating 안/못: particles, endings, contracted topics, adverbs.
_NEG_CONTEXT = re.compile(r'(?:은|는|이|가|을|를|도|만|에|서|고|며|면|게|지|요|다|까|건|걸|난|넌|우린|전|아직|전혀|절대|거의|다시|잘|또|결코|별로|좀|아예|더|덜|왜|아무리)$')
_NOUN_PARTICLE_NEXT = re.compile(r'(?:에서|에게|으로|에|의|을|를|과|와)$')


def _short_negations(work: str):
    """(cue, predicate) pairs for 안/못 negating the next word, skipping locative 안 (건물 안 사람)."""
    out = []
    for m in _SHORT_NEG.finditer(work):
        prev = _SHORT_NEG_PREV.search(work[max(0, m.start() - 40):m.start()])
        bare_noun_before = bool(prev) and not _NEG_CONTEXT.search(prev.group(1))
        if m.group(1) == '안' and bare_noun_before and (_NOUN_PARTICLE_NEXT.search(m.group(2)) or not re.search(r'[다요어아니면고며서게지는은던겠까]$', m.group(2))):
            continue
        out.append((m.group(1), m.group(2)))
    return out
_ATTACHED_NEG = re.compile(r'(?<![가-힣])안됩니다(?=$|[\s.!?,])')
_NEG_PASSIVE = re.compile(r'되지\s*(?:않|못)|돼지\s*않|어지지\s*않|아지지\s*않')
_GENERIC_NEG = re.compile(r'않|없|아니|아닙|아닌|(?<=[와과])\s*(?:다르|다른|달라|달랐|달리)')


class Features:
    __slots__ = ('neg', 'negp', 'can_neg', 'bound', 'sets', 'axes', 'bounds', 'short')

    def __init__(self):
        self.neg = 0            # clause negations not explained by a lexicon word
        self.negp = 0           # of those, passive negations (되지 않는다) that may equal 못/수 없다
        self.can_neg = 0
        self.bound: Counter = Counter()      # axis -> negations bound to an axis word
        self.sets: dict[str, set] = {}
        self.axes: dict[str, Counter] = {}
        self.bounds: Counter = Counter()
        self.short: Counter = Counter()


# The bound noun 수 is often written attached ("할수 있다"). The CAN rules read it only after a space, so the
# spacing fix 할수 있다 -> 할 수 있다 looked like a new ability and a lost negation. Both sides are read with 수
# spaced after an attributive ㄹ ending; 할수록 and 할수밖에 are left alone.
_RIEUL_FINAL = ''.join(chr(0xAC00 + i * 28 + 8) for i in range(19 * 21))
_ATTACHED_SU = re.compile('([' + _RIEUL_FINAL + r'])수(?=(?:가|는|도)?\s*(?:있|없))')
# Same for 안 + 되다: attached 안되요/안돼요 read as no negation (or as a prohibition) while the spaced
# 안 돼요 read as a short negation, and the stems 되/돼 differed. 안 is spaced and 되요/됬 (always
# misspellings of 돼요/됐) are read as spelled correctly, on both sides.
_ATTACHED_AN = re.compile(r'(?<![가-힣])안(?=[되돼됐됩될된])')


def _spacing_normal(text: str) -> str:
    text = _ATTACHED_AN.sub('안 ', _ATTACHED_SU.sub(r'\1 수', text))
    return text.replace('되요', '돼요').replace('됬', '됐')


@lru_cache(maxsize=8192)
def features(text: str) -> Features:
    f = Features()
    work = _IDIOMS.sub(_blank, _spacing_normal(text))
    ev: list = []

    def add_bound(m):
        kind = _BOUND_KIND[m.group('b')]
        f.bounds[(kind, _value(m.group('num')))] += 1
        return ' ' * (m.end() - m.start())
    work = _BOUND_AFTER.sub(add_bound, work)
    work = _BOUND_BEFORE.sub(add_bound, work)

    # "줄이지 않으면 안 된다" and "하지 않을 수 없다" are obligations, not two negations.
    work = _rule(work, _DOUBLE_NEG_OBLIG, ev, ('DEONT', 'OBLIG'))
    work = _KNOW_NOT.sub(lambda m: '모르' + ' ' * (len(m.group(0)) - 2), work)
    work = _rule(work, _PROHIBIT, ev, ('CAN', -1))
    work = _rule(work, _NOREQ, ev, ('DEONT', 'NOREQ'))
    work = _rule(work, _OBLIG, ev, ('DEONT', 'OBLIG'))
    work = _rule(work, _REC, ev, ('DEONT', 'REC'))
    work = _rule(work, _DEONT_OPTIONAL, ev, ('DEONT', 'OPTIONAL'))
    work = _rule(work, _CAN_NEG, ev, ('CAN', -1))
    work = _rule(work, _CAN_POS, ev, ('CAN', 1))
    work = _rule(work, _HEDGE, ev, ('HEDGE', 1))
    for cls, rx in _QUANT:
        work = _rule(work, rx, ev, ('Q', cls))
    for kind, val in ev:
        f.sets.setdefault(kind, set()).add(val)
        if (kind, val) == ('CAN', -1):
            f.can_neg += 1

    # Lexicon axes. Each axis scans its own copy (a word may sit on two axes);
    # matched spans are blanked from the shared text afterwards.
    spans = []
    for name, rxs in _AXIS_RE.items():
        local = work
        for sign, rx in rxs:      # negative side first so that 불합격 is not read as 합격
            def hit(m, name=name, sign=sign):
                bound = bool(m.group('pre') or m.group('suf'))
                f.axes.setdefault(name, Counter())[-sign if bound else sign] += 1
                if bound:
                    f.bound[name] += 1
                spans.append(m.span())
                return ' ' * (m.end() - m.start())
            local = rx.sub(hit, local)
    if spans:
        chars = list(work)
        for lo, hi in spans:
            chars[lo:hi] = ' ' * (hi - lo)
        work = ''.join(chars)

    for cue, predicate in _short_negations(work):
        endings = ('습니다', '어요', '아요', '는다', '한다', '하다', '지만', '는데', '으며', '니까', '어서', '아서', '어도', '아도',
                   '다', '요', '고', '며', '면', '는', '던', '은', '어', '아', '서', '도', '게', '지')
        stem = next((predicate[:-len(e)] for e in endings if predicate.endswith(e) and len(predicate) > len(e)), predicate)
        f.short[(cue, stem)] += 1
    f.negp = len(_NEG_PASSIVE.findall(work))
    f.neg = len(_GENERIC_NEG.findall(work)) + len(_ATTACHED_NEG.findall(work)) + sum(f.short.values())
    return f


def polarity_count(text: str) -> int:
    """Backward compatible: number of clause negations (idioms excluded)."""
    work = _IDIOMS.sub(_blank, text)
    return len(_GENERIC_NEG.findall(work)) + len(_short_negations(work)) + len(_ATTACHED_NEG.findall(work))


def short_negation_targets(text: str) -> Counter:
    return features(text).short


def obligation_count(text: str) -> int:
    return len(_OBLIG.findall(text))


# --------------------------------------------------------------------------
# participants / roles
# --------------------------------------------------------------------------
_PARTICLES = ('께서', '에게서', '에게', '한테', '에서', '으로', '로', '은', '는', '이', '가', '을', '를', '도', '만', '뿐',
              '조차', '마저', '까지', '에', '의', '보다')
_VERBAL_END = set('하되시었았겠했됐')
_CONN_STOP = {'하지만', '그러나', '그리고', '또는', '따라서', '그런데', '그래서', '그러면', '그럼에도', '다만', '또한', '혹은',
              '그래도', '이는', '이것은', '그것은', '사실은', '예를', '만약', '아직도', '다시는', '결국은'}
_TOKEN = re.compile(r'[A-Za-z0-9가-힣]+')
_PASSIVE_PRED = re.compile(r'(?:되(?:었|였|어|며|고|는|다)|돼|됐|받(?:았|는|아)|당했|당하|당한|혔|렸|겼|힌|어졌|어진|아졌|여졌)')
_CONVERSE = [('BORROW', re.compile(r'빌렸|빌리|빌려\s*받')), ('LEND', re.compile(r'빌려\s*주|빌려\s*줬|대여했|대출해')),
             ('LEARN', re.compile(r'배웠|배우')), ('TEACH', re.compile(r'가르쳤|가르치|가르쳐')),
             ('BUY', re.compile(r'샀|사들|구매했|매입했')), ('SELL', re.compile(r'팔았|팔고|판매했|매각했')),
             ('GIVE', re.compile(r'주었|줬|건넸|수여했')), ('TAKE', re.compile(r'받았|받는다|받았다|수령했'))]
_CONVERSE_OPP = {'BORROW': 'LEND', 'LEND': 'BORROW', 'LEARN': 'TEACH', 'TEACH': 'LEARN', 'BUY': 'SELL', 'SELL': 'BUY',
                 'GIVE': 'TAKE', 'TAKE': 'GIVE'}


def _split_particle(token: str):
    for p in sorted(_PARTICLES, key=len, reverse=True):
        if token.endswith(p) and len(token) > len(p):
            stem = token[:-len(p)]
            if len(stem) < 2 and p in ('은', '는', '이', '가', '도', '만', '에', '의', '로', '으로', '에서', '뿐'):
                # one-syllable stems are mostly verb stems or pronouns ("그는", "이는")
                if p not in ('을', '를') and not (len(stem) == 1 and p in ('은', '는') and stem in '나너저우'):
                    continue
            if p in ('은', '는', '이', '가') and stem[-1] in _VERBAL_END:
                continue
            if p in ('도', '만') and (stem[-1] in _VERBAL_END or stem[-1] in '어아여지해'):
                continue
            if token in _CONN_STOP:
                return token, ''
            return stem, p
    return token, ''


def _frame(sentence: str):
    """Return (pairs, focus, predicate). pairs: set of (agent, other)."""
    tokens = _TOKEN.findall(sentence)
    if not tokens:
        return set(), {}, ''
    pred = tokens[-1]
    roles = []  # (stem, role)
    agent_by = None
    for i, tok in enumerate(tokens[:-1]):
        stem, p = _split_particle(tok)
        # A one-syllable noun is trusted only after a bare modifier word ("상대 팀을", "우리 집이").
        if not p and i > 0 and re.fullmatch(r'[가-힣](?:이|가|을|를|은|는|에게|도|만)', tok) and \
                re.fullmatch(r'[가-힣]{1,4}', tokens[i - 1]) and not _split_particle(tokens[i - 1])[1]:
            stem, p = tok[0], tok[1:]
        if not p:
            continue
        # "우리 팀이 상대 팀을": a short bare word before the noun belongs to the participant.
        if i > 0:
            prev_stem, prev_p = _split_particle(tokens[i - 1])
            if not prev_p and re.fullmatch(r'[가-힣]{1,4}', tokens[i - 1]) and tokens[i - 1] not in _CONN_STOP:
                stem = tokens[i - 1] + ' ' + stem
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ''
        if p == '에' and nxt.startswith('의하'):
            roles.append((stem, 'AGENT'))
        elif p in ('은', '는', '이', '가', '께서'):
            roles.append((stem, 'SUBJ'))
        elif p in ('을', '를'):
            roles.append((stem, 'OBJ'))
        elif p in ('에게', '한테', '에게서', '에'):
            roles.append((stem, 'DAT'))
        elif p == '에서':
            roles.append((stem, 'LOC'))
        elif p in ('도', '만', '조차', '마저'):
            roles.append((stem, 'FOCUS:' + p))
    focus: dict[str, set] = {}
    for stem, role in roles:
        if role.startswith('FOCUS:'):
            focus.setdefault(stem, set()).add(role[6:])
    subj = [s for s, r in roles if r == 'SUBJ']
    obj = [s for s, r in roles if r == 'OBJ']
    dat = [s for s, r in roles if r in ('DAT', 'AGENT')]
    agent = [s for s, r in roles if r == 'AGENT']
    light = bool(re.search(r'받(?:았|는|아|은)|당했|당하|당한', pred)) and bool(dat) and not agent
    passive = bool(_PASSIVE_PRED.search(pred)) and (bool(agent) or (bool(dat) and not obj) or light)
    pairs = set()
    if len(subj) == 1:
        if passive:
            target = agent or dat
            if len(target) == 1:
                pairs.add((target[0], subj[0]))
        else:
            if obj and len(obj) == 1:
                pairs.add((subj[0], obj[0]))
            if dat and len(dat) == 1:
                pairs.add((subj[0], dat[0]))
    return pairs, focus, pred


def _converse_class(pred: str):
    for name, rx in _CONVERSE:
        if rx.search(pred):
            return name
    return None


_COMPARE = re.compile(r'((?:[A-Za-z0-9가-힣]+\s+){0,1}[A-Za-z0-9가-힣]+)(?:이|가|은|는)\s+((?:[A-Za-z0-9가-힣]+\s+){0,1}[A-Za-z0-9가-힣]+?)(?:보다|에\s*비해|에\s*비하여)')
_COMPARE_REV = re.compile(r'((?:[A-Za-z0-9가-힣]+\s+){0,1}[A-Za-z0-9가-힣]+?)(?:보다|에\s*비해|에\s*비하여)\s+((?:[A-Za-z0-9가-힣]+\s+){0,1}[A-Za-z0-9가-힣]+)(?:이|가|은|는)')


def _comparisons(sentence: str) -> dict:
    """{frozenset({x,y}): orientation sign} for 'x가 y보다 <axis>' (sign = x more)."""
    if '보다' not in sentence and '비해' not in sentence and '비하여' not in sentence:
        return {}
    if len(sentence) > 2000:
        return {}
    f = features(sentence)
    sign = 0
    for name in ('MAGX', 'INC', 'GOOD', 'EASE'):
        c = f.axes.get(name)
        if c and (c[1] > 0) != (c[-1] > 0):
            sign = 1 if c[1] else -1
            break
    out = {}
    if '더 ' in sentence or '덜 ' in sentence:
        pass
    pairs = []
    for m in _COMPARE.finditer(sentence):
        pairs.append((m.group(1), m.group(2)))
    for m in _COMPARE_REV.finditer(sentence):
        pairs.append((m.group(2), m.group(1)))
    for x, y in pairs:
        key = tuple(sorted((x, y)))
        out[key] = (sign if (x, y) == key else -sign)
    return out


# before/after event ordering
_AFTER = re.compile(r'(?P<L>[^,.]{1,30}?)\s*(?:한\s*뒤에?|한\s*후에?|이후에?|뒤에|후에|한\s*다음)\s+(?P<R>[^,.]{1,30})')
_BEFORE = re.compile(r'(?P<L>[^,.]{1,30}?)\s*(?:하기\s*전에|하기\s*이전에|하기\s*직전에|전에|이전에?|직전에)\s+(?P<R>[^,.]{1,30})')
_FIRST = re.compile(r'먼저\s*(?P<A>[^,.]{1,30}?)(?:하고|한\s*뒤|하며|한\s*다음|하고서)\s*나중에\s*(?P<B>[^,.]{1,30})')


def _key(text: str) -> frozenset:
    return frozenset(w[:2] for w in _TOKEN.findall(text) if len(w) >= 2)


def _overlap(a: frozenset, b: frozenset) -> float:
    return len(a & b) / max(1, min(len(a), len(b)))


def _orderings(sentence: str):
    if len(sentence) > 2000 or not re.search(r'전에|이전|직전|뒤|후|다음|먼저', sentence):
        return []
    rels = []
    for m in _AFTER.finditer(sentence):
        rels.append((_key(m.group('L')), _key(m.group('R'))))      # L earlier than R
    for m in _BEFORE.finditer(sentence):
        rels.append((_key(m.group('R')), _key(m.group('L'))))      # R earlier than L
    for m in _FIRST.finditer(sentence):
        rels.append((_key(m.group('A')), _key(m.group('B'))))
    return [r for r in rels if r[0] and r[1]]


def _order_swapped(before: str, after: str) -> bool:
    # A source ordering counts as swapped only when its best swapped match beats its best straight match.
    # Comparing every pair flagged an unchanged sentence with two frames ("…하기 전에 … 한 후에 …") as a swap,
    # because one frame matched the other frame reversed, and the identical text was rolled back.
    ra, rb = _orderings(before), _orderings(after)
    for e1, l1 in ra:
        straight = max((_overlap(e1, e2) + _overlap(l1, l2) for e2, l2 in rb), default=0.0)
        swapped = max((_overlap(e1, l2) + _overlap(l1, e2) for e2, l2 in rb), default=0.0)
        if swapped > straight and swapped >= 1.0:
            return True
    return False


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
_STRICT_SETS = ('CAN', 'DEONT', 'HEDGE', 'Q')


def _polarity_differs(a: Features, b: Features) -> bool:
    ta, tb = a.neg + sum(a.bound.values()), b.neg + sum(b.bound.values())
    if a.negp or b.negp:                       # 되지 않는다 may be 못/수 없다
        ta, tb = ta + a.can_neg, tb + b.can_neg
    if ta != tb:
        diff = ta - tb
        explained = 0
        for name in a.axes.keys() & b.axes.keys():
            na, nb = a.axes[name][1] - a.axes[name][-1], b.axes[name][1] - b.axes[name][-1]
            if na * nb > 0:                    # same effective direction on both sides
                explained += a.bound[name] - b.bound[name]
        if explained != diff:
            return True
    if a.short and b.short and sum(a.short.values()) == sum(b.short.values()) and a.short != b.short:
        return True
    return False


def _feature_diff(a: Features, b: Features) -> set:
    reasons = set()
    if _polarity_differs(a, b):
        reasons.add('polarity')
    ca, cb = a.sets.get('CAN', set()), b.sets.get('CAN', set())
    if a.negp or b.negp:
        ca, cb = ca - {-1}, cb - {-1}
    if ca != cb:
        reasons.add('modality')
    for cls in ('HEDGE', 'DEONT'):
        if a.sets.get(cls, set()) != b.sets.get(cls, set()):
            reasons.add('modality')
    if a.sets.get('Q', set()) != b.sets.get('Q', set()):
        reasons.add('lexical')
    if a.bounds != b.bounds:
        reasons.add('lexical')
    for name in set(a.axes) | set(b.axes):
        xa, xb = a.axes.get(name, Counter()), b.axes.get(name, Counter())
        na, nb = xa[1] - xa[-1], xb[1] - xb[-1]
        if xa and xb and (na * nb < 0 or ((na == 0) != (nb == 0) and (xa[1] and xa[-1] or xb[1] and xb[-1]))):
            reasons.add('lexical')
        if name == 'CERTX' and bool(xa) != bool(xb):
            reasons.add('modality')
    return reasons


def _pairs_for(source, candidate, aligned):
    if aligned is not None:
        return [(a, b) for a, b in aligned if a and b], all(a and b for a, b in aligned)
    left, right = sentences(source), sentences(candidate)
    if len(left) == len(right):
        return list(zip(left, right)), True
    return [], False


def _reasons(source: str, candidate: str, aligned) -> set:
    reasons = _feature_diff(features(source), features(candidate))
    pairs, one_to_one = _pairs_for(source, candidate, aligned)
    if one_to_one:
        for before, after in pairs:
            reasons |= _feature_diff(features(before), features(after))
    return reasons


def changed_polarity(source: str, candidate: str, aligned=None) -> bool:
    return 'polarity' in _reasons(source, candidate, aligned)


def changed_sentence_modality(source: str, candidate: str, aligned=None) -> bool:
    return 'modality' in _reasons(source, candidate, aligned)


def changed_lexical_polarity(source: str, candidate: str, aligned=None) -> bool:
    if 'lexical' in _reasons(source, candidate, aligned):
        return True
    pairs, _ = _pairs_for(source, candidate, aligned)
    for before, after in pairs:
        ca, cb = _comparisons(before), _comparisons(after)
        if any(k in cb and ca[k] and cb[k] and ca[k] != cb[k] for k in ca):
            return True
        if _order_swapped(before, after):
            return True
    return False


def changed_participant_roles(source: str, candidate: str, aligned=None) -> bool:
    pairs, _ = _pairs_for(source, candidate, aligned)
    for before, after in pairs:
        pa, fa, va = _frame(before)
        pb, fb, vb = _frame(after)
        ca, cb = _converse_class(va), _converse_class(vb)
        converse = bool(ca and cb and _CONVERSE_OPP.get(ca) == cb)
        swapped = any((p[1], p[0]) in pb and p not in pb for p in pa)
        if swapped != converse and (swapped or pa & pb):
            return True
        if re.search(r'것이\s*아니라|뿐|물론', before + ' ' + after):
            continue
        for stem in fa.keys() & fb.keys():
            if fa[stem] != fb[stem]:
                return True
        # focus particle moved onto/off a noun that exists on both sides
        for stem in fa.keys() - fb.keys():
            if stem in after and not any(stem in k for k in fb):
                if re.search(re.escape(stem) + r'(?:을|를|은|는|이|가)(?=\s|$)', after):
                    return True
    return False


# --------------------------------------------------------------------------
# document level
# --------------------------------------------------------------------------
_LEAD = re.compile(r'^(?:그래서|그리고|하지만|그러나|또한|따라서|그런데|그러므로|그렇지만|다만|또)\s*')


def _bigrams(text: str) -> Counter:
    s = re.sub(r'\s+', '', text)
    return Counter(s[i:i + 2] for i in range(len(s) - 1))


def _covered(sentence: str, whole: Counter, threshold: float = 0.5) -> bool:
    grams = _bigrams(_LEAD.sub('', sentence))
    total = sum(grams.values())
    if not total:
        return True
    return sum(min(c, whole[g]) for g, c in grams.items()) / total >= threshold


def document_sentence_drift(source: str, candidate: str) -> bool:
    before, after = sentences(source), sentences(candidate)
    if len(before) != len(after):
        whole = _bigrams(candidate)
        if not before or not after or any(not _covered(s, whole) for s in before):
            return True            # a source sentence vanished
        # split/merge: only the document-wide events can be compared
        return bool(_feature_diff(features(source), features(candidate)))
    aligned = list(zip(before, after))
    return (bool(_reasons(source, candidate, aligned)) or changed_lexical_polarity(source, candidate, aligned) or
            changed_participant_roles(source, candidate, aligned))




def mode() -> str:
    """SUPER_SEJONG_MODE: enforce (default) blocks, shadow only reports, off skips.

    Shadow mode lets an operator measure how often these guards would block real
    rewrites before trusting them; the codes carry no document text.
    """
    value = os.environ.get("SUPER_SEJONG_MODE", "enforce").strip().lower()
    return value if value in ("enforce", "shadow", "off") else "enforce"
