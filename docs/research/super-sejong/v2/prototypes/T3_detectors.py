"""T3 awkward-Korean detectors (research prototypes, Python 3.11, stdlib only).

Each detector returns spans (start, end) into the text. Families:
  N  = norm violation (orthography / spacing / grammar rule with a cited norm)
  A  = awkwardness (grammatical but unnatural; agreement, translationese, redundancy)
  S  = style preference
  T  = LLM tell (frequency signal, not an error)
Detectors marked existing=True are Python ports of rules already shipped in src/engine/super-sejong.ts.
"""
import re, json

H = '가-힣'


def coda(ch):
    """Final-consonant index of a Hangul syllable (0 = none, 4 = ㄴ, 8 = ㄹ), or -1."""
    o = ord(ch) - 0xAC00
    return o % 28 if 0 <= o < 11172 else -1


SENT_END = re.compile(r'(?<=[.!?。])\s+|\n+')


def sentences(text):
    out, pos = [], 0
    for m in SENT_END.finditer(text):
        if m.start() > pos:
            out.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text)))
    return out


class D:
    def __init__(self, id, fam, desc, rx=None, guard=None, fn=None, existing=False, flags=0):
        self.id, self.fam, self.desc, self.existing = id, fam, desc, existing
        self.rx = re.compile(rx, flags) if isinstance(rx, str) else rx
        self.guard, self.fn = guard, fn

    def find(self, text):
        if self.fn:
            return self.fn(text)
        out = []
        for m in self.rx.finditer(text):
            if self.guard and not self.guard(text, m):
                continue
            out.append((m.start(), m.end()))
        return out


# ---------------- N: orthography ----------------

SURNAMES = set('김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경')


def ryul_guard(t, m):
    # m.group(1) = preceding syllable, group(2) = 율|률
    prev, suf = m.group(1), m.group(2)
    c = coda(prev)
    want = '율' if c in (0, 4) else '률'
    if suf == want:
        return False
    # personal names: surname + 율/률 as a two-syllable word
    s = m.start()
    if prev in SURNAMES and (s == 0 or not re.match(f'[{H}]', t[s - 1])):
        return False
    # words where 률/율 is not the 率/律 suffix: 음률? (ㅁ->률 ok anyway); 효율 etc fine.
    return True

# fixed misspellings (표준국어대사전 / 한글 맞춤법); each tuple: (regex, correction)
FIXED = [
    (r'몇\s?일(?![본반])', '며칠'),            # 한글 맞춤법 제27항 붙임2 (며칠)
    (r'어떻해', '어떡해'),
    (r'왠(?!지)(?=[가-힣])', '웬'),            # 왠일/왠만 -> 웬일/웬만 (only 왠지 is correct)
    (r'웬지', '왠지'),
    (r'금새(?![가-힣]*[털])', '금세'),
    (r'(?<=[할줄갈올볼될울])께(?=[요\s.!?,~]|$)', 'ㄹ게'),   # 제53항
    (r'(?<=[할줄갈올볼될])껄(?=[요\s.!?,~]|$)', 'ㄹ걸'),
    (r'(?<=[할줄갈올볼될])\s?꺼(?:야|예요|에요|다|라고|든)', 'ㄹ 거'),
    (r'(?<![가-힣])(?:안\s?)?되요|됬|돼었|되서(?=[\s.,!?])', '돼요/됐/되어'),
    (r'설레임', '설렘'),
    (r'오랫만', '오랜만'),
    (r'희안', '희한'),
    (r'(?<![지])역활', '역할'),
    (r'(?<![가-힣])(?:일일|틈틈|번번|곰곰|깨끗|따뜻|느긋|버젓|의젓)히(?![가-힣])', '-이'),   # 제51항
    (r'(?<![가-힣])(?:꼼꼼|솔직|급급|조용|분명|가만|열심)이(?![가-힣])', '-히'),            # 제51항
    (r'갯수', '개수'), (r'뒷처리', '뒤처리'), (r'윗층', '위층'), (r'촛점', '초점'),
    (r'(?<![가-힣])댓가(?![가-힣]?지)', '대가'), (r'인삿말', '인사말'), (r'머릿말', '머리말'),
    (r'내노라', '내로라'), (r'어의(?:없|가 없)', '어이없'), (r'(?<![가-힣])구지(?=\s)', '굳이'),
    (r'(?:할|볼|될)려(?:고|면|는데|다가)(?![가-힣]*니)', '-려고'),
    (r'(?:있|없|했|였|겠|었|았)읍니다', '-습니다'),
    (r'(?:있|없|했|였|겠|었|았)슴(?![니다])', '-음'),
    (r'(?<![가-힣])거에요', '거예요'),
    (r'아니예요|아니였', '아니에요/아니었'),
    (r'않\s?(?:해|했|하[고는면지게니])|않\s?(?:돼|됐|된|될|되(?:요|어|었|는|면|지|니|겠))|않\s?(?:갔|간|가[고는면])', '안'),
    (r'(?<=지)\s?안(?:았|고|는|아|습|으)', '않'),
    (r'바램(?=[이을은으도]|[\s.,])', '바람'),
    (r'(?<![가-힣])뵈(?:요|요\.)', '봬요'),
]
_fixed = re.compile('|'.join(f'(?:{p})' for p, _ in FIXED))


def fixed_guard(t, m):
    s = m.group(0)
    if s.startswith('바램'):
        # 빛바램 / 색바램 are legitimate nouns of 바래다
        return not re.search(r'(?:빛|색|퇴색)\s?$', t[max(0, m.start() - 3):m.start()])
    if s.startswith('되서'):
        return True
    if '이예요' in s:
        return True
    return True


def iyeyo_fn(t):
    # consonant-final noun + 이예요 -> 이에요; 이였다 after consonant-final syllable -> 이었다
    out = []
    for m in re.finditer(r'([가-힣])이(예요|였)', t):
        if coda(m.group(1)) > 0:
            out.append((m.start(), m.end()))
    return out

# ---------------- N: spacing (한글 맞춤법 제42항 의존 명사, 제47항 보조 용언) ----------------

def bound_noun_fn(t):
    out = []
    # 할수 있다 / 할수밖에 : ㄹ-final syllable + 수 + 있/없/밖에
    for m in re.finditer(r'([가-힣])수\s?(?:있|없|밖에)', t):
        if coda(m.group(1)) == 8 and m.group(1) not in '술횟실':
            out.append((m.start(), m.end()))
    # 하는것 / 할것 / 한것 : ㄴ/ㄹ-final syllable + 것 (not 날것 들것 탈것 별것 생것)
    for m in re.finditer(r'([가-힣])것', t):
        prev = m.group(1)
        if coda(prev) in (4, 8) and prev not in '날들탈별생산군헌':
            # require the syllable before to be part of a modifier, not a noun (e.g. 물건, 사건 do not end in 것)
            out.append((m.start(), m.end()))
    # 할때 : ㄹ-final syllable + 때
    for m in re.finditer(r'([가-힣])때(?!기|문)', t):
        if coda(m.group(1)) == 8 and m.group(1) not in '물볼':
            out.append((m.start(), m.end()))
    return sorted(set(out))


AUX_ANH = r'(?<![마머못])지않(?=[가-힣])'

# ---------------- N/A: particles ----------------

ROLE_NOUNS = '학생|부모|사람|선생님|교사|친구|선배|후배|리더|국민|시민|어른|자녀|아이|전문가|엄마|아빠|일원|대표|회원|인간|개인|당사자|주체|구성원|한국인|기업|단체|공무원|의사|변호사|행정사|소비자|청소년|여성|남성|가장|책임자|담당자|보호자|어머니|아버지|형|누나|언니|오빠|동생|직원|팀원|팀장|선수|작가|독자'
ROSEO = rf'(?:함|됨|시킴|짐|줌)으로서|(?<![가-힣])이로서(?=[\s,])|(?:{ROLE_NOUNS})(?:으로|로)써(?![가-힣])'

INANIMATE = '정부|회사|기업|국가|나라|사회|학교|기관|단체|업체|정당|국회|법원|지자체|당국|환경|지구|자연|세계|조직|위원회|협회|병원|은행|가게|매장|식물|나무|시스템|플랫폼|제품|서비스|지역|도시|공동체|산업|시장경제|경제|대학|교육청|법인|센터'
EGE = rf'(?<![가-힣])(?:{INANIMATE})에게(?!서)'

EGE_ISSEO = r'(?:에게|에겐|한테)\s?있어(?:서)?(?![가-힣]*[다요])'

# object + passive verbal noun: 국회의원 300명을 선출되었다 (NIKL 공공언어 바로 쓰기 2022, p.11)
OBJ_PASSIVE = r'(?<=[을를])\s(?!잘못|안|못|참|헛|덜|잘|일관)([가-힣][가-힣])(?<!게)되(?:었|어|는|다|며|고|면|기|지|도록|니)'

# ---------------- A: agreement (호응) ----------------

NEG = re.compile(r'아닙|아님|어려|힘든|힘듭|힘들|드뭅|않|(?<![가-힣])안\s?[가-힣]|(?<![가-힣])안(?=[\s.])|못|없|아니|아닌|아냐|아녜|말(?:고|라|아|자|것)|모르|모른|몰라|몰랐|불가능|어렵|힘들|싫|금물|드물|쉽지|는커녕|\?|뿐이|만\s|밖에')


def neg_adverb_fn(t):
    out = []
    for s, e in sentences(t):
        sent = t[s:e]
        for m in re.finditer(r'(?<![가-힣])(결코|그다지|좀처럼|도무지|도저히|차마|절대로|전혀)(?![가-힣])', sent):
            rest = sent[m.end():]
            if m.group(1) == '전혀' and re.match(r'\s*(?:다르|다른|달라|달랐|달리|다릅|새롭|새로운|딴|반대|예상\s?밖|의외|생소|낯설|무관|별개|엉뚱|상반)', rest):
                continue
            if not NEG.search(rest):
                out.append((s + m.start(), s + m.end()))
    return out


def birok_fn(t):
    out = []
    conc = re.compile(r'지만|지마는|더라도|[ㄹ을]지라도|지라도|[어아여해]도|어도|아도|해도|여도|라도|[ㄴ은]들|으나|(?<=[가-힣])나[\s,]|망정|에도\s?불구|ㄴ데도|는데도|은데도|면서도|음에도|임에도|되|이지만|이나')
    for s, e in sentences(t):
        sent = t[s:e]
        for m in re.finditer(r'(?<![가-힣])비록(?![가-힣])', sent):
            if not conc.search(sent[m.end():]):
                out.append((s + m.start(), s + m.end()))
    return out


def amuri_fn(t):
    out = []
    for s, e in sentences(t):
        sent = t[s:e]
        for m in re.finditer(r'(?<![가-힣])아무리(?![가-힣])', sent):
            rest = sent[m.end():]
            if not re.search(r'[가-힣]도(?![가-힣])|[가-힣]도[요록]?|더라도|[ㄴ은는]들|지만|봐야|해야|라도|지라도|[가-힣]도\s', rest):
                out.append((s + m.start(), s + m.end()))
    return out


def manyak_fn(t):
    out = []
    cond = re.compile(r'면|다면|라면|거든|[ㄹ을]\s?경우|경우|시에|때|이라도|되면|이면|한다면|하면|진다면')
    for s, e in sentences(t):
        sent = t[s:e]
        for m in re.finditer(r'(?<![가-힣])(만약|만일)(?:에)?(?![가-힣의])', sent):
            rest = sent[m.end():]
            if re.match(r'\s*(?:을|를|의|에\s?대비|에\s?대한)', rest):
                continue
            if not cond.search(rest):
                out.append((s + m.start(), s + m.end()))
    return out


def waenya_fn(t):
    out = []
    reason = re.compile(r'때문|[니으]니까|[이]니까|니까|해서[이였]|어서[이였]|아서[이였]|서다|서이다|서예요|서입니다|기에|므로|거든|[ㄴ는]다는\s?것|이유')
    for s, e in sentences(t):
        sent = t[s:e]
        for m in re.finditer(r'(?<![가-힣])(왜냐하면|왜냐면|왜냐하면은)(?![가-힣])', sent):
            if not reason.search(sent[m.end():]):
                out.append((s + m.start(), s + m.end()))
    return out


TOPIC_HEADS = '꿈|목표|소망|바람|생각|이유|장점|단점|문제점|문제|특징|목적|계획|주장|의견|결론|핵심|요지|취지|원인|역할|각오|다짐'
TOPIC_RX = re.compile(rf'(?:^|[\s"“(])(?:(?:제|나의|내|저의|우리의|우리|그|이|그것의|이것의)\s)?(?:[가-힣]+\s)?({TOPIC_HEADS})(?:은|는)\s')
NOMINAL_END = re.compile(r'(?:것|거|점|때문|기|음|ㅁ|데|바|뿐|셈|터|수|따름|차례|중|이유|목표|꿈|생각|희망|소망|하나)\s?(?:이다|입니다|이에요|예요|이야|다|이었다|였다|이었습니다|였습니다|이죠|이지요|일\s?것이다|일\s?겁니다|이라고\s?생각)|(?:이다|입니다|이에요|예요|였다|이었다|였습니다|이었습니다|이죠|이야|다는\s?것이다|에\s?있다|에\s?있습니다|이라고\s?(?:생각|본다|봅니다)|이라\s?(?:생각|본다)|와\s?같다|과\s?같다|같습니다)\s*[.!?…"”)]*$')
VERBAL_END = re.compile(r'(?:싶다|싶습니다|싶어요|싶었다|싶었습니다|한다|합니다|했다|했습니다|해야\s?한다|해야\s?합니다|하겠다|하겠습니다|좋겠다|좋겠습니다|되었다|되었습니다|됐다|된다|됩니다|갔다|왔다|생각한다|생각합니다|생각했다|생각했습니다)\s*[.!?…"”)]*$')


def topic_pred_fn(t):
    out = []
    for s, e in sentences(t):
        sent = t[s:e].strip()
        if len(sent) > 160:
            continue
        m = TOPIC_RX.search(sent[:40])
        if not m:
            continue
        head = m.group(1)
        tail = sent[-30:]
        if NOMINAL_END.search(tail):
            continue
        if VERBAL_END.search(tail):
            off = t.find(sent, s)
            out.append((off + m.start(1), off + m.end(1) + 1))
    return out


def honorific_fn(t):
    out = []
    hon = re.compile(r'(?<=[가-힣])(?:시|셨|세|셔|십|신|실|심)|계시|계셨|계신|드시|드셨|잡수|주무|돌아가|여쭈|여쭙|모시|뵙|뵈|드리|드렸|올리|께서는?\s?[가-힣]+(?:이다|입니다)')
    for s, e in sentences(t):
        sent = t[s:e]
        m = re.search(r'[가-힣]께서', sent)
        if not m:
            continue
        rest = sent[m.end():]
        # predicate of the 께서 clause: up to the first clause-final ending; approximate by the last 12 chars
        tail = rest.strip()[-14:]
        if not hon.search(rest):
            out.append((s + m.start(), s + m.end()))
    return out

# ---------------- A: double passive, causative ----------------

DOUBLE_PASSIVE = r'(?<![가-힣])[가-힣]{0,6}(?:되어|보여|쓰여|잊혀|불려|나뉘어|읽혀|짜여)(?:지(?:다|는|고|며|면|게|기|지|어|었)|진|졌)'


def dp_guard(t, m):
    return not re.match(r'^(?:[가-힣]{0,6})?(?:이루어|만들어|그려|놓여|둘러|쌓여|이어)', m.group(0))

SIKIDA = r'(?:소개|설득|입금|주차|접수|전달|완화|충족|확장|자동화|취소|금지|해소|분리|연결|대입|진행|개선|단축|접목)\s?시(?:키|켜|킨|킬|켰|킴)'

# ---------------- A: translationese ----------------
GAJANG_HANA = r'가장\s(?:[가-힣]+\s){0,4}?[가-힣]+\s?(?:것|곳|사람|요소|방법|문제|이유|도시|나라|국가|분야|기업|사례|원인|작품|과제|수단|기술|특징|부분|측면|가치)?\s?중(?:의|에)?\s?(?:하나|한\s?가지|한\s?명|한\s?곳|하나로)'
PILYO_RO = r'(?:을|를)\s필요로\s(?:하|한|했|합)'
E_DAREUM = r'에\s?다름\s?(?:아니|아닌|없)'
E_WICHI = r'에\s위치(?:한|하고|하며|해|하는|합니다)'
ROINHAE = r'(?:으로|로)\s인(?:해|하여|한)(?![가-힣])'
DOUBLE_PART_UI = r'(?:에서의|으로의|로의|와의|과의|에의|에게의|로부터의|에\s?대한\s?것의)'
GEUNYEO = r'(?<![가-힣])그녀(?:는|가|의|를|에게|와|도|만)?(?![가-힣])'
ANEUMYEON = r'지\s않으면\s안\s?(?:된다|됩니다|돼|되는|되었다|되며)'
PILYOGA = r'[ㄹ할될볼갈줄을]\s필요가\s있'
GANEUNG_MAKE = r'(?:을|를)\s가능하게\s(?:만들|한|하|해|했)'
ESSEO_ISSEO = r'(?:함|됨|하기|되기)에\s+있어서?|(?<=[가-힣][는은]\s)데\s+있어서?|(?:에|에서)\s+있어서(?=[는의도])'
CLEFT = r'[는은]\s것은\s[^.!?\n]{1,60}?(?:것이다|것입니다|것이에요|거예요|것이죠)'
LIST_AND = r'[가-힣A-Za-z]+(?:[와과])?,\s[가-힣A-Za-z ]{1,15},\s그리고\s[가-힣A-Za-z]+'
SENT_IDNEUN = r'(?:^|(?<=[.!?]\s)|(?<=\n))이는\s'
NAGAYA = r'(?:해|어|아|여)\s?나가야\s?(?:할|합니다|한다|하겠)|해야\s할\s것(?:이다|입니다)'
DANSUN_NEOMEO = r'단순(?:히|한)\s[^.!?\n]{0,30}?(?:을|를)\s넘어'
BBUNMAN = r'뿐만\s?아니라'
JUNGYOSEONG = r'(?<![가-힣])[가-힣]{1,6}의\s중요성'
ENUM = r'(?:^|(?<=[.!?]\s)|(?<=\n))(?:첫째|둘째|셋째|첫\s?번째로|두\s?번째로|세\s?번째로)[,\s]'

# ---------------- existing shipped rules (Python ports) ----------------
IMPORTANCE = r'(?:는|은|ㄹ|할|될|볼)\s*것이\s*(?:매우\s+|가장\s+|무엇보다\s+)?(?:중요|필수적|필요|바람직)(?:하|합|한|해)|중요한\s+(?:역할|도구|요소|열쇠|과제)(?=[을를이가은는입\s,.])'
CONCLUDING = r'(?:^|(?<=[.!?]\s)|(?<=\n))(?:결론적으로|요약하자면|요약하면|종합하면|정리하자면)(?=[\s,])'
DEMO_THROUGH = r'(?<![가-힣])이를\s+통(?:해서?|하여)(?![가-힣])'
BOILER = r'(?:알아보|살펴보|짚어보|다뤄보|정리해\s*보|소개해\s*드리|알려\s*드리)(?:겠습니다|겠다|도록\s*하겠습니다|도록\s*하겠다)|(?:알아볼|살펴볼)까요|(?:알아|살펴)봅시다'
ROLE = r'역할을\s+(?:하|한|합|했|해|수행|담당)'


def role_guard(t, m):
    return not re.search(r'주인공|배역|악역|조연|주연|배우|연기|캐릭터|직책', t[max(0, m.start() - 12):m.start()])


# redundancy lexicon (enabled, not allowed, not contested) from the 2026-10-04 lexicon data
LEX = '/Users/wisdom/wisdom_project/gpt/ai-text-makes-likes-human/.worktrees/super-sejong-engine/docs/research/super-sejong/data/2026-10-04/lexicon'


def _redundancy():
    d = json.load(open(f'{LEX}/redundancy.json', encoding='utf8'))
    # RD_haebyeon_ga dropped: 해변가 is a 표준국어대사전 headword (=바닷가); RD_busang_danghada is contested.
    pats = [e['pattern'] for e in d['entries'] if e.get('enabled') and e.get('allowed') is False and e['id'] not in ('RD_haebyeon_ga', 'RD_busang_danghada')]
    return re.compile('|'.join(f'(?:{p})' for p in pats))

DETECTORS = [
    # N
    D('N_RYUL', 'N', '율/률 after vowel/ㄴ vs other codas (맞춤법 제11항 붙임1)', r'([가-힣])(율|률)', guard=ryul_guard),
    D('N_FIXED_MISSPELLING', 'N', 'fixed misspelling lexicon (며칠, 웬, ㄹ게, 돼요, 거예요, -이/-히 ...)', _fixed, guard=fixed_guard),
    D('N_IEYO', 'N', 'consonant-final noun + 이예요/이였 -> 이에요/이었', fn=iyeyo_fn),
    D('N_BOUND_NOUN_SPACING', 'N', '할수 있다 / 하는것 / 할때 (제42항)', fn=bound_noun_fn),
    D('N_AUX_ANH_SPACING', 'N', '-지않 -> -지 않 (제47항 원칙; 않다 is not attachable)', AUX_ANH),
    D('N_ROSEO_ROSSEO', 'N', '로서/로써 confusion (제57항)', ROSEO),
    D('N_OBJ_PASSIVE', 'N', 'object particle + passive 되다 (명을 선출되었다)', OBJ_PASSIVE),
    # A agreement
    D('A_NEG_ADVERB', 'A', '결코/별로/전혀/... without negative predicate', fn=neg_adverb_fn),
    D('A_BIROK', 'A', '비록 without concessive ending', fn=birok_fn),
    D('A_AMURI', 'A', '아무리 without -어도/-더라도', fn=amuri_fn),
    D('A_MANYAK', 'A', '만약/만일 without conditional', fn=manyak_fn),
    D('A_WAENYA', 'A', '왜냐하면 without 때문/-니까 in the same sentence', fn=waenya_fn),
    D('A_TOPIC_PRED', 'A', '꿈/목표/이유는 ... + verbal predicate (주술 호응)', fn=topic_pred_fn),
    D('A_HONORIFIC', 'A', '께서 subject without honorific predicate', fn=honorific_fn),
    D('A_EGE_INANIMATE', 'A', 'inanimate noun + 에게 (-> 에)', EGE),
    D('A_DOUBLE_PASSIVE', 'A', 'double passive (shipped DOUBLE_PASSIVE)', DOUBLE_PASSIVE, guard=dp_guard, existing=True),
    D('A_SIKIDA', 'A', 'needless -시키다 (소개시키다 ...)', SIKIDA),
    D('A_REDUNDANCY', 'A', 'redundancy lexicon (겹말), 2026-10-04 data', _redundancy()),
    # A/S translationese
    D('A_GAJANG_HANA', 'A', '가장 ~ 중 하나', GAJANG_HANA),
    D('A_EGE_ISSEO', 'A', '~에게 있어(서)', EGE_ISSEO),
    D('A_PUBLIC_FRAME', 'A', '~에 있어서 (shipped PUBLIC_LANGUAGE_FRAME)', ESSEO_ISSEO, existing=True),
    D('S_PILYO_RO', 'S', '~을 필요로 하다', PILYO_RO),
    D('S_E_DAREUM', 'S', '~에 다름 아니다', E_DAREUM),
    D('S_E_WICHI', 'S', '~에 위치한', E_WICHI),
    D('S_ROINHAE', 'S', '~로 인해', ROINHAE),
    D('S_DOUBLE_PART_UI', 'S', '~에서의/~로의/~와의', DOUBLE_PART_UI),
    D('S_GEUNYEO', 'S', '그녀', GEUNYEO),
    D('S_ANEUMYEON', 'S', '~지 않으면 안 된다', ANEUMYEON),
    D('S_PILYOGA', 'S', '~할 필요가 있다', PILYOGA),
    D('S_GANEUNG_MAKE', 'S', '~을 가능하게 하다/만들다', GANEUNG_MAKE),
    D('S_CLEFT', 'S', '~는 것은 ~것이다', CLEFT),
    D('S_LIST_AND', 'S', 'A, B, 그리고 C', LIST_AND),
    D('S_SENT_INEUN', 'S', 'sentence-initial 이는', SENT_IDNEUN, flags=re.M),
    # T
    D('T_IMPORTANCE', 'T', 'shipped IMPORTANCE_FORMULA', IMPORTANCE, existing=True),
    D('T_CONCLUDING', 'T', 'shipped CONCLUDING_SIGNPOST', CONCLUDING, existing=True, flags=re.M),
    D('T_DEMO_THROUGH', 'T', 'shipped DEMONSTRATIVE_THROUGH', DEMO_THROUGH, existing=True),
    D('T_BOILERPLATE', 'T', 'shipped BOILERPLATE_ANNOUNCE', BOILER, existing=True),
    D('T_ROLE', 'T', 'shipped ROLE_FORMULA', ROLE, guard=role_guard, existing=True),
    D('T_NAGAYA', 'T', 'obligation closing (~해 나가야 할 것입니다)', NAGAYA),
    D('T_DANSUN_NEOMEO', 'T', '단순히 ~을 넘어', DANSUN_NEOMEO),
    D('T_BBUNMAN', 'T', '뿐만 아니라', BBUNMAN),
    D('T_JUNGYOSEONG', 'T', 'X의 중요성', JUNGYOSEONG),
    D('T_ENUM', 'T', '첫째/둘째 enumeration', ENUM, flags=re.M),
]


# ---------------- v2 additions (after the first hand-check round) ----------------

def _full(sent):
    s = sent.rstrip()
    return bool(s) and s[-1] in '.!?。"”\''


def waenya2_fn(t):
    out = []
    reason = re.compile(r'때문|니까|니깐|해서[이였]|어서[이였]|아서[이였]|서다|서이다|서예요|서입니다|기에|므로|거든|잖|이유|탓')
    for s, e in sentences(t):
        sent = t[s:e]
        if not _full(sent):
            continue
        for m in re.finditer(r'(?<![가-힣])(왜냐하면|왜냐면|왜냐하면은)(?![가-힣])', sent):
            if not reason.search(sent[m.end():]):
                out.append((s + m.start(), s + m.end()))
    return out


def manyak2_fn(t):
    out = []
    cond = re.compile(r'면|다면|라면|거든|경우|시에|때|이라도|해도|라도|더라도|든지|ㄴ다면')
    for s, e in sentences(t):
        sent = t[s:e]
        if not _full(sent):
            continue
        for m in re.finditer(r'(?<![가-힣])(만약|만일)(?:에)?(?![가-힣의])', sent):
            rest = sent[m.end():]
            if re.match(r'\s*(?:을|를|의|에\s?대비|에\s?대한)', rest):
                continue
            if not cond.search(rest):
                out.append((s + m.start(), s + m.end()))
    return out


THOUGHT_SUBJ = re.compile(r'(?:^|[\s,])(?:제|저의|나의|내|우리의|필자의)\s?(?:생각|의견|입장|주장)(?:은|는)\s')
THOUGHT_END = re.compile(r'(?:생각|판단)(?:한다|합니다|해요|했다|했습니다|된다|됩니다|돼요|이\s?든다|이\s?듭니다)\s*[.!?…"”)]*$')


def thought_double_fn(t):
    """제 생각은 ~ 생각합니다 : subject 'my opinion' + predicate 'I think' (주어-서술어 호응)."""
    out = []
    for s, e in sentences(t):
        sent = t[s:e].rstrip()
        m = THOUGHT_SUBJ.search(sent)
        if m and THOUGHT_END.search(sent):
            out.append((s + m.start(), s + m.end()))
    return out


DREAM_SUBJ = re.compile(r'(?:^|[\s,])(?:제|저의|나의|내|우리의)\s?(?:꿈|목표|소망|바람|소원|희망)(?:은|는)\s')
DREAM_END = re.compile(r'(?:싶다|싶습니다|싶어요|싶었다|싶었습니다|겠다|겠습니다|할\s?것이다|하고\s?있다|한다|합니다|했다|했습니다)\s*[.!?…"”)]*$')


def dream_sipda_fn(t):
    """제 꿈은 의사가 되고 싶습니다 : 꿈/목표 subject + verbal predicate."""
    out = []
    for s, e in sentences(t):
        sent = t[s:e].rstrip()
        m = DREAM_SUBJ.search(sent)
        if m and DREAM_END.search(sent) and not re.search(r'(?:것|거|기)(?:이다|입니다|예요|이에요)', sent[-20:]):
            out.append((s + m.start(), s + m.end()))
    return out


REASON_SUBJ = re.compile(r'(?:^|[\s,"“])(?:그\s|이\s|그런\s|이런\s|[가-힣]+[는은]\s|[가-힣]+[한된]\s)?이유(?:는|로는)\s(?!간단|다양|여러|무엇|뭘|분명|많|크게|두\s|세\s|다음|아래|이렇|명확|복합|단순)')
REASON_OK = re.compile(r'때문|서이다|서입니다|서였|서예요|서야|기에|라서|이기|해서|어서|아서|니까|므로|탓|덕분|위해서|위함|이다|입니다|이었다|였다|예요|이에요|것')


def reason_no_ttaemun_fn(t):
    """그 이유는 ~ 했다 : 이유 subject whose predicate is not a reason/nominal predicate."""
    out = []
    for s, e in sentences(t):
        sent = t[s:e].rstrip()
        if not _full(sent):
            continue
        m = REASON_SUBJ.search(sent)
        if not m:
            continue
        if not REASON_OK.search(sent[m.end():]):
            out.append((s + m.start(), s + m.end()))
    return out


_kiwi = None


def iyeyo2_fn(t):
    """이였/이예요 after a consonant-final syllable, confirmed with Kiwi: the noun before the copula must not itself end in 이."""
    global _kiwi
    out = []
    cands = [m for m in re.finditer(r'([가-힣])이(예요|였)', t) if coda(m.group(1)) > 0]
    if not cands:
        return out
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    for m in cands:
        ws = t.rfind(' ', 0, m.start()) + 1
        we = m.end()
        word = t[ws:we + 4]
        toks = _kiwi.tokenize(word)
        ok = False
        for i, tk in enumerate(toks):
            if tk.tag == 'VCP' and i > 0 and toks[i - 1].tag.startswith('N') and not toks[i - 1].form.endswith('이'):
                ok = True
        if ok:
            out.append((m.start(), m.end()))
    return out


ROLE_ADJ = r'(?:중요한|큰|핵심적인|결정적인|주요한|필수적인|중대한|막대한|지대한|중추적인|핵심|중요)\s(?:[가-힣]+\s)?역할을\s+(?:하|한|합|했|해|수행|담당)'


def boiler_guard(t, m):
    # quoted commitments in news: "면밀히 살펴보겠다"고 말했다
    return not re.match(r'\s?[”"’\']?\s?(?:고|라고|며|면서|는|던)(?![가-힣])', t[m.end():m.end() + 6])


def nagaya_guard(t, m):
    return not re.match(r'\s?[”"’\']?\s?(?:고|며|면서|는|던)(?![가-힣])', t[m.end():m.end() + 6]) and not re.match(r'다?\s?[”"]?\s?(?:고|며|는)\s', t[m.end():m.end() + 6])


DETECTORS_V2 = {
    'N_IEYO': D('N_IEYO', 'N', 'consonant-final noun + 이예요/이였 (Kiwi-confirmed copula)', fn=iyeyo2_fn),
    'A_WAENYA': D('A_WAENYA', 'A', '왜냐하면 without reason ending in a full sentence', fn=waenya2_fn),
    'A_MANYAK': D('A_MANYAK', 'A', '만약/만일 without conditional (full sentences)', fn=manyak2_fn),
    'A_THOUGHT_DOUBLE': D('A_THOUGHT_DOUBLE', 'A', '제 생각은 ~ 생각합니다', fn=thought_double_fn),
    'A_DREAM_SIPDA': D('A_DREAM_SIPDA', 'A', '제 꿈은 ~ 싶습니다', fn=dream_sipda_fn),
    'A_REASON_NO_TTAEMUN': D('A_REASON_NO_TTAEMUN', 'A', '이유는 ~ (no 때문/nominal end)', fn=reason_no_ttaemun_fn),
    'T_ROLE_ADJ': D('T_ROLE_ADJ', 'T', 'adjective + 역할을 하다 (narrowed ROLE_FORMULA)', ROLE_ADJ),
    'T_BOILERPLATE': D('T_BOILERPLATE', 'T', 'shipped BOILERPLATE_ANNOUNCE minus quoted commitments', BOILER, guard=boiler_guard, existing=True),
    'T_NAGAYA': D('T_NAGAYA', 'T', 'obligation closing minus quoted speech', NAGAYA, guard=nagaya_guard),
}
_ids = [d.id for d in DETECTORS]
for k, v in DETECTORS_V2.items():
    if k in _ids:
        DETECTORS[_ids.index(k)] = v
    else:
        DETECTORS.append(v)
DETECTORS = [d for d in DETECTORS if d.id != 'A_TOPIC_PRED']


# v3: 이유는 ~ : drop existential/negated predicates (이유는 없다, 이유는 되지 않는다) and nominal predicates;
# keep sentences whose final predicate is verbal (비롯된다고 생각합니다, 근거가 됩니다, 확신이 있어요 ...).
REASON_BAD_TAIL = re.compile(r'(?:없|아니|아닌|되지|못|않|있을|(?:말|밝|전|설명|강조)[했한하]|[”"])')
NOMINAL_TAIL = re.compile(r'(?:[가-힣](?:이다|다|입니다|이에요|예요|였다|이었다)|\?|하나다)\s*[.!”"]*$')


def reason3_fn(t):
    out = []
    for s, e in sentences(t):
        sent = t[s:e].rstrip()
        if not _full(sent) or '?' in sent:
            continue
        m = REASON_SUBJ.search(sent)
        if not m:
            continue
        rest = sent[m.end():]
        if REASON_OK.search(rest):
            continue
        tail = rest[-14:]
        if REASON_BAD_TAIL.search(tail) or NOMINAL_TAIL.search(rest) and not re.search(r'(?:한다|합니다|된다|됩니다|했다|했습니다)\s*[.!]*$', rest):
            continue
        if re.search(r'이유로는', sent[m.start():m.end()]):
            continue
        out.append((s + m.start(), s + m.end()))
    return out

DETECTORS = [d if d.id != 'A_REASON_NO_TTAEMUN' else D('A_REASON_NO_TTAEMUN', 'A', '이유는 ~ + verbal predicate (no 때문)', fn=reason3_fn) for d in DETECTORS]
