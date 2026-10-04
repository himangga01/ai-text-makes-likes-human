# -*- coding: utf-8 -*-
"""CTA detector + ledger for Korean text (T6, Super Sejong v2 research).

Pure standard library, Python >= 3.9, regular expressions only (no morphological analyser), so it can be
ported to the TypeScript pipeline or run inside the per-gate Python process.

Definition used here (operational, written down before labelling the test sample):
  A CTA unit is a sentence (or heading / button line) in which the AUTHOR directs, requests, advises or invites the
  READER to perform a future action, using an explicit directive construction.  Not CTA: greetings and blessings
  (안녕하세요, 건강하세요, 행복하시길 바랍니다), speaker commissives (정리해 보겠습니다, 안내해 드립니다),
  plain deontic statements (해야 합니다, 필요합니다 -- tracked separately as `deontic`), ability/option statements
  (할 수 있습니다, 가능합니다), directives inside quotation marks, and reported speech.

Force ladder (ordinal, our own design, see report):
  5 emphatic   directive + necessity/immediacy intensifier (꼭, 반드시, 절대, 지금 바로, 즉시 ...)
  4 directive  imperative (하세요/하십시오/하라), request (해 주세요, 해 주시기 바랍니다, 부탁드립니다), prohibition
  3 softened   trial (해 보세요), propositive (합시다, 해 볼까요), conditional offer (연락 주시면 안내해 드립니다)
  2 advisory   하는 것이 좋습니다, 권합니다/추천합니다, 어떨까요?, invitation (환영합니다)
  1 option     해 보는 것도 좋습니다, 하셔도 됩니다
  0 none
"""
import re
from collections import namedtuple

# --------------------------------------------------------------------------------------------
# sentence handling
# --------------------------------------------------------------------------------------------
_TERM = re.compile(r'[.!?。！？…]+["”’\')\]」』]*(?=\s|$)|(?<=[다요죠까니])\.(?=[가-힣])')


def split_units(text):
    """(sentence, is_heading_or_line, para_index).  A line without terminal punctuation is a unit of its own."""
    out = []
    para = 0
    blank_seen = False
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            blank_seen = True
            continue
        if blank_seen:
            para += 1
            blank_seen = False
        start, parts = 0, []
        for m in _TERM.finditer(line):
            parts.append(line[start:m.end()].strip())
            start = m.end()
        tail = line[start:].strip()
        if tail:
            parts.append(tail)
        line_unit = len(parts) == 1 and not _TERM.search(parts[0])
        for p in parts:
            if p:
                out.append((p, line_unit, para))
    return out


_QUOTE_PAIRS = [('“', '”'), ('‘', '’'), ('「', '」'), ('『', '』'), ('"', '"'), ("'", "'"), ('《', '》'), ('〈', '〉')]


def mask_quotes(s):
    """Replace quoted spans by 'ㅇ' of equal length so cues inside quotes never match.  Returns (masked, n_quoted)."""
    chars = list(s)
    n = 0
    for o, c in _QUOTE_PAIRS:
        i = 0
        while True:
            a = s.find(o, i)
            if a < 0:
                break
            b = s.find(c, a + 1)
            if b < 0:
                if o in '“‘「『' and len(s) - a - 1 >= 1:
                    for k in range(a + 1, len(s)):
                        chars[k] = 'ㅇ'
                    n += 1
                break
            if b - a - 1 >= 1:
                for k in range(a + 1, b):
                    chars[k] = 'ㅇ'
                n += 1
            i = b + 1
    return ''.join(chars), n


MAX_UNIT = 400
_TRAIL = re.compile(r'[\s.!?~…ㅎㅋㅠㅜ♡♥^)\]​"”’\'」』:;,]+$')
_LEAD = re.compile(r'^(?:[\s▶▷►☞👉✔✅※■□●○◆◇★☆•·\-–—>▼▽\[\(#*]+|\d{1,2}[.)]\s+)+(?=[가-힣A-Za-z0-9“‘"\'])')


def _clean_tail(s):
    return _TRAIL.sub('', s)


# --------------------------------------------------------------------------------------------
# exclusion lists (not CTA)
# --------------------------------------------------------------------------------------------
_GREET = re.compile(
    r'(?:안녕|수고|고생|건강|행복|평안|편안|평온|안락|무탈|건승|번창|행운|즐거운?|좋은\s*[가-힣]*\s*(?:하루|아침|저녁|밤|주말|연휴|휴일|오후|시간|날)|'
    r'복\s*많이|새해|메리|해피|잘\s*지내|잘\s*쉬|푹\s*쉬|따뜻하|포근하|힘내|파이팅|화이팅|좋은\s*꿈|평화|풍성|넉넉|여유로)'
    r'[가-힣\s]{0,14}(?:세요|십시오|시길|시기를?|시기\s*바랍니다|하시오|길\s*바랍니다|기를\s*바랍니다|시길\s*바랄게요|시기\s*바라요)?$')
_BLESS_STEM = re.compile(r'(?:건강하|행복하|평안하|편안하|안녕하|무탈하|풍요롭|평온하|즐거우|따뜻하|포근하|가득하|넘치|깃들|함께하|행운이|번창하|되시길|되시기를?|되었기를|되었길|됐기를|됐길|되길|되기를?|지내시|보내시|쉬시|웃으시|있으시길|있으시기를|있으시길|이루시|이루어지|이어지)')
_PHATIC_REQ = re.compile(r'(?:^|\s)(?:앞으로(?:도)?\s*)?(?:잘|많이|계속)\s*(?:부탁|사랑)\s*(?:드립니다|드려요|합니다|해요)$')
_COMMISSIVE = re.compile(r'(?:보겠습니다|보려고\s*합니다|드리겠습니다|드릴게요|드립니다|드려요|하겠습니다|할게요|볼게요|해\s*드립니다|해드립니다|해\s*드려요)$')
_REPORTED = re.compile(r'(?:라고|라는|하라고|으라고|자고|다고|냐고|며|면서|고서|라며|이라고)\s*(?:합니다|한다|했다|했습니다|하죠|말했|이야기|전했|밝혔|덧붙였|강조했|주장했|권했|조언했|안내했|설명했)')

# --------------------------------------------------------------------------------------------
# cue table.  Each: (form, base force, tier hint, compiled regex applied to the cleaned, quote-masked sentence)
# order matters: first match wins
# --------------------------------------------------------------------------------------------
V = r'[가-힣]'
Cue = namedtuple('Cue', 'form force rx')


def _c(form, force, pat):
    return Cue(form, force, re.compile(pat))


CUES = [
    # --- prohibition (4)
    _c('prohibitive', 4, r'(?:지|지를|지는)\s*(?:마세요|마십시오|마시기\s*바랍니다|마시길\s*바랍니다|마시기를\s*바랍니다|맙시다|말아\s*주세요|말아\s*주십시오|말아\s*주시기\s*바랍니다|마시기\s*바라요|마라|말라|말아라|마요|마시고|마셔요|마시오)$'),
    _c('prohibitive', 4, r'삼가(?:\s*주)?(?:세요|십시오|시기\s*바랍니다|시길\s*바랍니다|시오|해\s*주세요|주시기\s*바랍니다)$'),
    # --- request with benefactive 주다 (4)
    _c('request', 4, r'(?<=[가-힣])\s*주(?:세요|십시오|시기\s*(?:를\s*)?바랍니다|시길\s*바랍니다|시기\s*바라요|시기\s*바라겠습니다|시기\s*바랍니다만|시기를\s*부탁(?:드립니다|드려요|드리겠습니다)|시기\s*부탁(?:드립니다|드려요)|실래요|시겠어요|시겠습니까|시겠어|시오|라|렴|셔요|실\s*수\s*있(?:나요|을까요|습니까|으신가요|으세요|겠어요|겠습니까|을지요))$'),
    _c('request', 4, r'(?<=[가-힣])\s*주시면\s*(?:정말\s*|너무\s*|대단히\s*|매우\s*)?(?:감사하겠습니다|감사하겠어요|감사드리겠습니다|고맙겠습니다|고맙겠어요|감사드립니다|감사합니다|감사해요)$'),
    _c('request_wish', 3, r'(?<=[가-힣])\s*주시면\s*(?:정말\s*|너무\s*|대단히\s*|매우\s*)?(?:좋겠습니다|좋겠어요|좋을\s*것\s*같습니다|좋을\s*듯합니다|합니다)$'),
    # nominal request: N 부탁드립니다 / 협조 바랍니다 / 확인 요청드립니다
    _c('request', 4, r'(?<=[가-힣0-9)\]])\s*(?:부탁\s*(?:드립니다|드려요|드립니다만|합니다|드리겠습니다|드릴게요|해요|드려봅니다)|요청\s*(?:드립니다|드려요|합니다|드리겠습니다)|당부\s*(?:드립니다|드려요|합니다|드리겠습니다))$'),
    _c('request', 4, r'(?:협조|양해|참고|유의|주의|준수|확인|참석|참여|신청|제출|이용|문의|연락|이해|응원|관심|동참|공감|구독|공유|댓글|이웃추가|서로이웃|방문|숙지|조치|회신|검토|기재|작성|완료|납부|등록|보완)\s*(?:를|을)?\s*바랍니다$'),
    # --- 보실게요 = trial
    _c('trial', 3, r'(?<=[해어아여워봐써켜줘와가])\s*보(?:시)?(?:실게요|실께요)$'),
    # --- ill-formed -시-+ㄹ게요 used as an instruction (병원·매장 말투): directive force
    _c('imperative', 4, r'(?<=[가-힣])(?:시)?(?:실게요|실께요)$'),
    # --- trial imperative / request (3): 해 보세요
    _c('trial', 3, r'(?<=[해어아여워봐써켜줘와가춰쳐겨려져])\s*보(?:세요|십시오|시기\s*바랍니다|시길\s*바랍니다|시기를\s*바랍니다|시기\s*바라요|시오|시죠|시겠어요|시겠습니까|실래요|셔요|시면\s*좋겠습니다|시면\s*좋겠어요|시면\s*좋아요|시면\s*됩니다)$'),
    # honorific wish used as request: ...시기 바랍니다 / 시길 바랍니다 (blessings filtered afterwards)
    _c('request', 4, r'(?:시기를?|시길|도록|하기를|하길|기를|길)\s*바(?:랍니다|라요|랍니다만|라겠습니다|랄게요|랍니다요|란다|라며|라마|랄게)$'),
    # --- propositive / suggestion (3)
    _c('suggestion', 3, r'(?:합시다|봅시다|갑시다|읍시다|ㅂ시다|하시죠|보시죠|가시죠|해\s*봐요|해\s*볼까요|해봐요|해보자|해\s*보자|하자|(?<=[해펴아어여워려겨져쳐써나와가들켜])\s*보자|(?<=\s)보자|(?<=\s)가자|(?<=[어아여해])\s*가자|먹자|읽자|지키자|만들자)$'),
    _c('suggestion', 3, r'(?:함께|같이|다\s*같이)\s*[가-힣\s]{0,20}(?:볼까요|해볼까요|할까요|가볼까요|살펴볼까요|알아볼까요|짚어볼까요|풀어볼까요|이야기해볼까요|정리해볼까요|해요|해봐요|가요|봐요|합시다|하죠)$'),
    _c('suggestion', 3, r'(?:해|어|아|여|워)\s*볼까요$'),
    _c('suggestion', 2, r'[가-힣]\s*(?:는|ㄴ|은|ㄹ|을)\s*(?:건|것은|게|것이|거|걸|것도)\s*(?:어떨까요|어떠세요|어떠신가요|어떠십니까|어때요|어떻습니까|어떨까)$'),
    _c('suggestion', 2, r'(?:해|어|아|여|워|하|보|받|가|드|오)(?:시)?(?:면|다면)\s*(?:어떨까요|어떠세요|어떠신가요|어떠십니까|어떻습니까|좋을까요|좋겠습니까)$'),
    # --- option (1): checked BEFORE advisory because "~도 좋습니다" is weaker than "~는 것이 좋습니다"
    _c('option', 1, r'(?:해|하|보|받|드|가|써|주)\s*(?:보)?(?:시는\s*것도|는\s*것도|는\s*거도|셔도|보셔도|도)\s*(?:좋습니다|좋아요|좋겠습니다|좋겠어요|방법입니다|방법이에요|방법이 될 수 있습니다|괜찮습니다|괜찮아요|됩니다|돼요|무방합니다|나쁘지\s*않습니다)$'),
    _c('option', 1, r'[가-힣]\s*(?:셔도|보셔도|해도|하셔도|주셔도)\s*(?:됩니다|돼요|좋습니다|좋아요|괜찮습니다|괜찮아요|무방합니다)$'),
    _c('option', 1, r'(?:문의|상담|연락|전화|댓글|쪽지|메일|신청|예약|방문|질문)\s*(?:을|를|도)?\s*(?:남기실|하실|해\s*보실|해주실|해\s*주실|주실|하시는|남겨\s*주셔도|주셔도|해\s*주셔도)\s*(?:수\s*있습니다|수\s*있어요|\s*됩니다|\s*돼요)$'),
    # --- advisory (2)
    _c('advisory', 2, r'[가-힣]\s*(?:는|ㄴ|은|ㄹ|을)\s*(?:것이|게|건|편이|쪽이|방향이|게\s*훨씬|것이\s*더|것이\s*훨씬|편이\s*더|편이\s*훨씬)\s*(?:더\s*|훨씬\s*|가장\s*|아무래도\s*|보다\s*|한결\s*)?(?:좋습니다|좋겠습니다|좋아요|좋겠어요|좋을\s*것\s*같습니다|좋을\s*듯합니다|낫습니다|나아요|낫겠습니다|바람직합니다|바람직하겠습니다|바람직해요|안전합니다|현명합니다|유리합니다|안전해요|좋다|좋겠다|낫다|바람직하다)$'),
    _c('advisory', 2, r'(?:것을|기를|길|시길|시기를|도록|것이|것도)?\s*(?:권합니다|권해\s*드립니다|권해드립니다|권해요|권장합니다|권장드립니다|권장해요|권고합니다|권고드립니다|추천합니다|추천드립니다|추천해요|추천해\s*드립니다|추천해드립니다|추천드려요|제안드립니다|제안드려요|권장됩니다|권고됩니다|권유합니다|권유드립니다)$'),
    _c('advisory', 2, r'(?:것을|기를|길|시길|시기를)\s*(?:권한다|권장한다|권고한다|추천한다)$'),
    _c('advisory', 2, r'(?<=[가-힣])면\s*(?:더\s*|훨씬\s*)?(?:좋습니다|좋아요)$'),
    _c('advisory', 2, r'(?<=시)면\s*(?:더\s*|훨씬\s*)?(?:좋겠습니다|좋겠어요|좋을\s*것\s*같습니다|좋을\s*듯합니다)$'),
    _c('instruction', 2, r'(?<=시)면\s*(?:됩니다|돼요|되세요|되겠습니다)$'),
    _c('instruction', 2, r'(?:살펴|확인해|알아|찾아|읽어|대조해)보면\s*(?:됩니다|돼요|되겠습니다)$'),
    # --- invitation (2)
    _c('invitation', 2, r'(?:이웃|서로이웃|서이추|방문|문의|상담|댓글|소통|연락|구독|공감|질문|의견|협업|제휴|참여|신청)\S*\s*(?:은|는|도)?\s*(?:언제나|언제든(?:지)?|항상|언제라도|늘)?\s*(?:열려\s*있습니다|환영(?:합니다|해요|입니다|이에요)|환영)$'),
    # --- plain imperative (4)
    _c('imperative', 4, r'(?<=[가-힣])(?:세요|으세요|십시오|으십시오|셔요|시오|시옵소서|하라|해라|하거라|하렴|보라|봐라|보아라|읽어라|들어라|가라|오라|와라|써라|두라|지켜라|막아라|따르라|지키라|세우라|줄여라|높여라|올려라|내려라|멈춰라|기억하라|기억해라|서둘러라|서둘러요|서두르세요)$'),
    _c('imperative', 4, r'(?<![안못않]\s)(?<=[해아어여겨려켜져쳐녀])\s*줘$|(?<=[해아어여겨려켜져쳐녀])\s*주라$'),
]

# declarative deontic statements are tracked, not counted as CTA
DEONTIC = re.compile(r'(?:하여야|해야|돼야|되어야|야)\s*(?:합니다|한다|해요|해|함|하겠습니다|할\s*것입니다|하며|하고|하는)|필요(?:가\s*있)?(?:합니다|하다|해요|하며|하고)|필수(?:입니다|이다|적입니다)|의무(?:입니다|이다)|반드시\s*[가-힣\s]*(?:합니다|한다|해야)')

# nominal button / link lines
_BTN_NOUN = re.compile(r'(?:구독|이웃\s*추가|서로\s*이웃(?:\s*추가)?|공감|좋아요|팔로우|신청|문의|상담|예약|다운로드|바로\s*가기|더\s*보기|자세히\s*보기|알아보기|신청하기|문의하기|상담하기|예약하기|구독하기|공유하기|저장하기|등록하기|가입하기|전화하기|전화\s*상담|상담\s*신청|방문하기|확인하기|조회하기|접수하기)$')
_BTN_MARK = re.compile(r'^[\s▶▷►☞👉✔✅※■□●○◆◇★☆•\[\(\-–—>▼▽]+')

# component lexicons ------------------------------------------------------------------------------------------
INTENS_NEC = re.compile(r'반드시|꼭꼭|꼭|절대로|절대|필히|무조건|제발|부디|철저히|꼼꼼히')
INTENS_IMM = re.compile(r'지금\s*바로|지금\s*당장|지금\s*즉시|당장|즉시|곧바로|바로|서둘러|빨리|빠르게|신속히|신속하게|하루빨리|서두르|지금\s+(?:[^\s]+\s+)?[^\s]*(?:하세요|하십시오|주세요|보세요)\s*[.!?]*$')
# sequencing / manner adverbs kept as content, not intensity
MODIFIERS = re.compile(r'먼저|우선|미리|사전에|가능하면|가능한\s*한|되도록|천천히|차근차근|한번|한\s*번|함께|같이|꼭|반드시|편하게|부담\s*없이|언제든(?:지)?|언제라도|자유롭게|가볍게|간단히|편히')
CHANNELS = re.compile(r'카카오톡|카톡|톡톡|네이버\s*톡톡|오픈\s*채팅|오픈카톡|오픈채팅|채널|쪽지|댓글|이메일|메일|문자|전화|홈페이지|프로필|링크|방문|DM|디엠|사이트|앱|어플|블로그|게시판|고객센터|콜센터|창구|민원실|우편|팩스')
URLS = re.compile(r'https?://\S+|www\.\S+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|@[A-Za-z0-9_.]{3,}|(?<![0-9])\d{2,4}-\d{3,4}-\d{4}(?![0-9])|(?<![0-9])1\d{3}-\d{4}(?![0-9])|[A-Za-z0-9-]+\.(?:go\.kr|or\.kr|co\.kr|com|net|kr)\b')
BENEFITS = re.compile(r'무료|무상|공짜|할인|혜택|사은품|증정|쿠폰|이벤트|지원금|면제|환급|적립|선착순|한정|특가|보상')
DEADLINE = re.compile(
    r'(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일(?:\s*(?:까지|부터|전|전까지|이내|안에|내|이전|이후))?'
    r'|\d{1,4}\s*(?:일|주|개월|달|시간|분)\s*(?:이내|안에|전까지|전에|내|전|후)'
    r'|이번\s*(?:주|달|분기|학기)\s*(?:안에|내|까지|중)?|오늘\s*(?:중|안에|까지)?|내일\s*(?:까지|안에)?|금주\s*(?:내|중)?|월말\s*(?:까지)?|연내|올해\s*(?:안에|내|까지)'
    r'|마감\s*(?:일|전|기한|시한)?[가-힣0-9\s]{0,6}(?:까지|전|에|내)?|기한\s*(?:내|안에|전|까지)?|신청\s*기간\s*(?:내|안에)?'
    r'|[가-힣0-9]+\s*(?:까지|전까지|이전에|이내에|안에)')
COND_CLAUSE = re.compile(r'((?:[^,.!?]*?)(?:면|다면|라면|이라면|이면|거든|ㄴ다면|는\s*경우|ㄹ\s*경우|을\s*경우|하시다면|시다면|실\s*때|할\s*때|하실\s*때|는\s*경우에는))\s*[,]?\s*')
TIMING = re.compile(r'[가-힣0-9]+\s*(?:전에|후에|이후에|이전에|뒤에|직전에|직후에|동안|때까지|하기\s*전)')
AUDIENCE = re.compile(r'여러분|독자|이웃님|고객님|분들|님들|이웃\s*여러분|방문자|학부모님|대표님|담당자님?')

ENGAGE_N = re.compile(r'이웃|서로이웃|서이추|공감|좋아요|하트|댓글|구독|팔로우|공유|스크랩|저장|알림|관심|응원|놀러|소통|방문|추천\s*버튼|리포스트')
CONTACT_N = re.compile(r'문의|상담|연락|전화|예약|신청|접수|견적|의뢰|카톡|톡톡|이야기\s*나눠|말씀|메일|쪽지|방문|오세요|찾아|연락처|컨설팅|진단|가입|등록\s*신청')
NAV_N = re.compile(r'링크|클릭|눌러|누르|아래|참고|참조|함께\s*(?:읽|보|확인)|다음\s*글|이전\s*글|포스팅|글도|확인해\s*보|읽어\s*보|이동|바로가기|더\s*보기|자세히|다운로드|내려받')

UnitT = namedtuple('UnitT', 'idx para text form force tier polarity level honorific action actions obj condition timing deadline channel benefit intensity modifiers heading quoted audience span')


def _speech_level(ending):
    if re.search(r'(?:십시오|ㅂ시다|습니다|ㅂ니다|바랍니다|드립니다|하시오|시옵소서|겠습니까|합시다|입니다)$', ending):
        return 'hapsyo'
    if re.search(r'(?:세요|해요|예요|죠|까요|어요|아요|래요|요)$', ending):
        return 'haeyo'
    if re.search(r'(?:하라|해라|하거라|하렴|자|라|다|렴|거라)$', ending):
        return 'haera'
    if re.search(r'(?:줘|봐|해)$', ending):
        return 'hae'
    return 'other'


_PART = re.compile(r'(?:을|를|은|는)$')
_PART_ANY = re.compile(r'(?:을|를|은|는|이|가|도|만|에|에게|에서|으로|로|와|과|께|께서|까지|부터|조차|마저|보다)$')


def _norm_action(tok):
    """strip verbal endings from an eojeol and return the nominal/verbal root ("문의해" -> "문의")"""
    t = re.sub(r'[,·]$', '', tok.strip())
    for _ in range(3):
        n = re.sub(r'(?:해서|하여서|하시고|하시는|하신|하실|하셔|하시|하여|하고|하며|하면|하는|하기|하자|하라|한\s*뒤|한\s*후|해|하|시고|시는|시|고|며|면|어서|아서|어|아|여)$', '', t)
        if n == t or len(n) == 0:
            break
        t = n
    return _PART.sub('', t) or t


def action_key(a):
    a = re.sub(r'[^가-힣A-Za-z0-9]', '', a or '')
    return a[:2]


_NOMINAL_ACTION = re.compile(r'(?:협조|양해|참고|유의|주의|준수|확인|참석|참여|신청|제출|이용|문의|연락|이해|응원|관심|동참|공감|구독|공유|댓글|이웃추가|서로이웃|방문|숙지|조치|회신|검토|기재|작성|완료|납부|등록|보완)$')


def _extract(raw, masked, m, form):
    core_raw = raw[:m.start()] if m is not None else raw
    core_raw = core_raw.rstrip()
    cond, rest_raw = None, core_raw
    cm = COND_CLAUSE.match(core_raw)
    if cm:
        cond = cm.group(1).strip()
        rest_raw = core_raw[cm.end():]
    toks = re.findall(r'[가-힣A-Za-z0-9·]+', rest_raw)
    action, obj = '', None
    if toks:
        action = _norm_action(toks[-1])
        # "문의를 해 주세요": last eojeol is only the light verb "해"; take the verbal noun before it
        if action in ('', '해', '하', '보', '보시', '보시길', '보시기', '보셔', '오', '와', '두', '놓', '가', '주') and len(toks) >= 2:
            action = _norm_action(toks[-2])
    om = list(re.finditer(r'([가-힣A-Za-z0-9·]+?)(?:을|를)(?=\s|$)', rest_raw))
    if om:
        obj = om[-1].group(1)
    # nominal requests ("협조 바랍니다", "관심 부탁드립니다"): the action is the noun before the cue
    pre_full = re.sub(r'\s*(?:을|를)?\s*(?:바랍니다|바라요|부탁(?:\s*\S*)?|요청(?:\s*\S*)?|당부(?:\s*\S*)?)$', '', raw[:m.end()].rstrip()) if m is not None else rest_raw
    nominal_req = bool(m is not None and (re.match(r'\s*(?:부탁|요청|당부)', m.group(0)) or re.match(_NOMINAL_ACTION.pattern[:-1], m.group(0).strip())))
    nm = _NOMINAL_ACTION.search(re.sub(r'(?:을|를)\s*$', '', pre_full))
    if nm and nominal_req and (not action or action in ('', '해', '하') or _NOMINAL_ACTION.search(action) is None):
        action = nm.group(0)
    if nominal_req:
        rest_raw = pre_full if m is not None else rest_raw
    # chained / coordinated actions (문의하시고 신청하세요, 공감과 댓글 부탁드립니다)
    actions = []
    parts = re.split(r'((?:하시고|하고|하며|하시며|해서|한\s*뒤|한\s*후|하신\s*후|하신\s*뒤|고|며)\s+|(?<=[가-힣])(?:과|와|및)\s+|\s*[,·]\s*)', rest_raw)
    pieces = parts[0::2]
    delims = parts[1::2] + ['']
    for k, piece in enumerate(pieces):
        w = re.findall(r'[가-힣A-Za-z0-9]+', piece)
        if not w:
            continue
        last_piece = (k == len(pieces) - 1)
        d = delims[k]
        verbal_link = bool(re.match(r'(?:하시고|하고|하며|하시며|해서|한\s*뒤|한\s*후|하신\s*후|하신\s*뒤|고|며)', d.strip())) if d else False
        coord_noun = bool(d) and not verbal_link
        if not (last_piece or verbal_link or (nominal_req and coord_noun)):
            continue
        if not nominal_req and re.search(r'(?:을|를)$', w[-1]):
            continue  # object of a verbal predicate, not an action
        cand = _norm_action(re.sub(r'(?:을|를)$', '', w[-1]) if nominal_req else w[-1])
        if cand and len(cand) >= 2 and not re.search(r'(?:것|수|때|점|등|중|내용|부분|곳|분|번|개)$', cand):
            actions.append(cand)
    if action and action_key(action) not in {action_key(x) for x in actions}:
        actions.append(action)
    seen, uniq = set(), []
    for x in actions:
        k = action_key(x)
        if k and k not in seen:
            seen.add(k)
            uniq.append(x)
    return dict(action=action, actions=uniq, obj=obj, condition=cond)


def _tier(raw):
    if ENGAGE_N.search(raw) and not CONTACT_N.search(raw):
        return 'engage'
    if CONTACT_N.search(raw):
        return 'contact'
    if NAV_N.search(raw):
        return 'navigate'
    return 'task'


def classify_sentence(raw, heading=False):
    """Return (cue, match, masked_clean, quoted_flag) or None."""
    s = _LEAD.sub('', raw.strip())
    if len(s) > MAX_UNIT:
        s = s[-MAX_UNIT:]          # run-on "sentence": every cue is end-anchored, so only the tail can matter
    masked, nq = mask_quotes(s)
    clean = _clean_tail(masked)
    if not clean:
        return None
    # an opening quotation mark without its closing mark (the quote continues in the next sentence)
    if re.match(r'^[“‘「『]', s) and not re.search(r'[”’」』]', s):
        return ('QUOTED', None, clean, True)
    # whole sentence is a quotation => not the author's CTA
    stripped = s.strip()
    wholly_quoted = bool(re.match(r'^[“‘"\'「『].*[”’"\'」』][.!?]*$', stripped)) and nq == 1 and len(re.sub(r'ㅇ', '', clean)) < 4
    if wholly_quoted:
        return ('QUOTED', None, clean, True)
    for cue in CUES:
        m = cue.rx.search(clean)
        if m:
            return (cue, m, clean, nq > 0)
    # "다음 서류를 준비하세요: 신분증, 인감도장." -- the directive precedes a colon list
    if ':' in clean or '：' in clean:
        head = re.split(r'[:：]', clean, 1)[0].rstrip()
        for cue in CUES:
            m = cue.rx.search(head)
            if m:
                return (cue, m, head, nq > 0)
    return None


def _exclusions(cue, m, clean, raw):
    # blessing / greeting
    if _GREET.search(clean):
        return 'greeting'
    if cue.form in ('request', 'imperative', 'trial') and _BLESS_STEM.search(clean[-24:]):
        # "행복하시길 바랍니다", "건강하세요", "좋은 하루 되세요"
        return 'blessing'
    if _PHATIC_REQ.search(clean):
        return 'phatic'
    if _REPORTED.search(clean):
        return 'reported'
    if cue.form == 'suggestion' and re.search(r'어떻게|무엇|왜|누가|언제|어디|어느|얼마|어떤|몇', clean):
        return 'wh_question'
    if cue.form == 'advisory' and re.search(r'(?:추천|권장)합니다$', clean) and re.search(r'(?:어플리케이션|애플리케이션|시스템|서비스|알고리즘|모델|프로그램|플랫폼|앱|엔진|장치|기기|공고|규정|지침|기준|기관|제도)', clean):
        return 'system_description'
    if cue.form == 'instruction' and re.search(r'(?:라고|다고|거라고|것이라고)\s*(?:보|생각하|이해하|여기)시면\s*(?:됩니다|돼요|되겠습니다)$', clean):
        return 'explanation'
    if cue.form == 'request' and re.search(r'(?:길|기를|기)\s*바(?:랍니다|란다|라요)$', clean) and not re.search(r'시(?:길|기를?)\s*바', clean) and not re.search(r'주(?:길|기를)\s*바', clean) and not re.search(r'우리\s*모두|모두\s*(?:가|는|다)|다\s*함께|함께|각자', clean):
        return 'society_wish'
    if cue.form == 'request' and re.search(r'[◇◆]', raw) and re.search(r'부탁\s*드(?:리겠습니다|릴게요|립니다)$', clean):
        return 'transcript'
    if cue.form == 'request' and re.search(r'수\s*있(?:기를|길|도록)\s*바', clean):
        return 'ability_wish'
    if cue.form == 'instruction' and re.search(r'(?:생각|이해|여기|간주|판단)(?:하)?시면\s*(?:됩니다|돼요)$', clean):
        return 'mental_verb'
    return None


_COND_HINT = re.compile(r'시면|신다면|시다면|시는\s*경우')


def _cond_offer(clean, raw):
    if not _COND_HINT.search(clean):
        return None
    # "연락 주시면 안내해 드립니다" / "댓글로 남겨 주시면 답변드리겠습니다"
    m = re.search(r'[가-힣]{1,8}\s*(?:해\s*)?(?:주|하|해주|드리)(?:시면|신다면|시다면|시는\s*경우)[^.!?]{0,120}?(?:하겠습니다|드리겠습니다|드립니다|드릴게요|드리겠어요|안내|답변|도와|상담|연락|확인|검토|알려|회신|돕겠습니다|도와드리|도와\s*드리|응답|조언|반영|처리|접수|참고|살펴볼\s*수\s*있|도와드릴\s*수\s*있|수\s*있습니다|수\s*있어요)', clean)
    return m


def _nominal_button(raw, clean, is_line):
    if not is_line:
        return None
    t = _BTN_MARK.sub('', raw.strip())
    t = re.sub(r'[\]\)>]+$', '', t).strip()
    if len(t) > 26 or re.search(r'[.!?]', t):
        return None
    marked = bool(_BTN_MARK.match(raw.strip())) and raw.strip()[:1] in '▶▷►☞👉✔✅※■□●○◆◇★☆•[(>'
    if _BTN_NOUN.search(t) and (marked or len(t.split()) <= 3):
        return t
    return None


def detect(text):
    """Return a list of CTA units (dicts) plus bookkeeping for `deontic` counts."""
    units, deontic = [], 0
    ui = 0
    for idx, (sent, is_line, para) in enumerate(split_units(text)):
        raw = sent if len(sent) <= MAX_UNIT else sent[-MAX_UNIT:]
        res = classify_sentence(raw, is_line)
        form, force, m, clean, quoted = None, 0, None, None, False
        why_not = None
        if res is None:
            nb = _nominal_button(raw, _clean_tail(mask_quotes(_LEAD.sub('', raw.strip()))[0]), is_line)
            if nb:
                form, force = 'nominal', 3
                clean = nb
            else:
                co = _cond_offer(_clean_tail(mask_quotes(_LEAD.sub('', raw.strip()))[0]), raw)
                if co:
                    form, force = 'conditional_offer', 3
                    m = co
                    clean = _clean_tail(mask_quotes(_LEAD.sub('', raw.strip()))[0])
                else:
                    if DEONTIC.search(raw):
                        deontic += 1
                    continue
        elif res[0] == 'QUOTED':
            continue
        else:
            cue, m, clean, quoted = res
            why_not = _exclusions(cue, m, clean, raw)
            if why_not:
                continue
            form, force = cue.form, cue.force
            # commissive statements ("안내해 드립니다") never reach here; request forms w/ 드리 are not in CUES
        # prefer the conditional-offer reading when a conditional request precedes a promise
        if form not in ('conditional_offer', 'nominal'):
            co = _cond_offer(clean, raw)
            if co and form in ('imperative', 'request') and False:
                pass
        s_clean = clean
        comp = _extract(raw, s_clean, m if form not in ('nominal',) else None, form)
        if form == 'nominal':
            comp = dict(action=_norm_action(re.sub(r'(?:하기|보기|가기|받기)$', '', clean)) or clean, actions=[_norm_action(clean) or clean], obj=None, condition=None)
        if form == 'conditional_offer':
            cm = re.search(r'([가-힣\s]{0,24}?(?:문의|연락|상담|전화|댓글|쪽지|톡|메일|의견|질문|말씀|이야기|연락처|신청|예약|방문|남겨|알려|물어|요청|의뢰))', clean)
            act = _norm_action(cm.group(1).split()[-1]) if cm else ''
            comp = dict(action=act, actions=[act] if act else [], obj=None, condition=None)
        nec = INTENS_NEC.search(raw if form != 'nominal' else '')
        imm = INTENS_IMM.search(raw if form != 'nominal' else '')
        intensity = []
        if nec:
            intensity.append('necessity')
        if imm and form in ('imperative', 'request', 'prohibitive', 'trial', 'conditional_offer'):
            intensity.append('immediacy')
        if form == 'prohibitive' and re.search(r'절대|결코|함부로|임의로', raw):
            intensity.append('necessity') if 'necessity' not in intensity else None
        f = force
        if intensity and form in ('imperative', 'request', 'prohibitive'):
            f = min(5, force + 1)
        elif intensity and form in ('trial', 'suggestion') and 'necessity' in intensity:
            f = min(5, force + 1)
        tail = (m.group(0) if (m is not None and hasattr(m, 'group')) else clean)
        honor = bool(re.search(r'시|세요|십시오|드립니다|드려요|바랍니다|실래요|겠습니까', tail))
        tier = _tier(raw)
        units.append(dict(
            idx=ui, sent_idx=idx, para=para, text=raw.strip(), form=form, force=f, base_force=force,
            tier=tier, polarity='-' if form == 'prohibitive' else '+',
            level=_speech_level(_clean_tail(clean)), honorific=honor,
            action=comp['action'], actions=comp['actions'], object=comp['obj'], condition=comp['condition'],
            timing=[x.strip() for x in TIMING.findall(raw)],
            deadline=sorted({x.strip() for x in DEADLINE.findall(raw) if x.strip()}),
            channel=sorted({re.sub(r'\s+', '', x) for x in CHANNELS.findall(raw)} | {x for x in URLS.findall(raw)}),
            benefit=sorted(set(BENEFITS.findall(raw))),
            intensity=sorted(set(intensity)),
            modifiers=sorted({re.sub(r'\s+', '', x) for x in MODIFIERS.findall(raw)}),
            heading=is_line, quoted=quoted,
            audience=bool(AUDIENCE.search(raw)),
        ))
        ui += 1
    return units, deontic


_DEON_ACTION = re.compile(r'([가-힣]{2,}?)(?:하여야|해야|하셔야|하시어야|돼야|되어야|야)\s*(?:합니다|한다|해요|함|하겠습니다|할\s*것입니다|하며|하고|하는|하므로)|([가-힣]{2,})(?:이|가|도|은|는)?\s*필요(?:합니다|하다|해요|하며|하고)')


def deontic_units(text):
    """Plain obligation statements (해야 합니다 / 필요합니다): not CTA, tracked because rewrites convert between them and imperatives."""
    out = []
    for idx, (sent, is_line, para) in enumerate(split_units(text)):
        masked, _ = mask_quotes(sent)
        m = DEONTIC.search(masked)
        if not m:
            continue
        am = _DEON_ACTION.search(masked)
        act = ''
        if am:
            g = am.group(1) or am.group(2) or ''
            act = _norm_action(g.split()[-1] if g.split() else g)
            # for "서류를 확인해야 합니다" group(1) is the verbal noun
        out.append(dict(sent_idx=idx, para=para, text=sent.strip(), action=act, key=action_key(act)))
    return out


_OFFER = re.compile(r'(?:도와|안내|상담|검토|지원|컨설팅|대행|진행|돕|답변|조언|연결|설명|확인)(?:해)?\s*(?:드리겠습니다|드립니다|드려요|드릴게요|드리고\s*있습니다|드리겠어요|해드립니다|해\s*드립니다)$')


def offer_units(text):
    """Service offers/promises ("검토해 드립니다", "도와드리겠습니다"): not a request, but they carry the closing CTA's value proposition."""
    out = []
    for idx, (sent, is_line, para) in enumerate(split_units(text)):
        masked, _ = mask_quotes(sent)
        clean = _clean_tail(masked)
        if _OFFER.search(clean):
            out.append(dict(sent_idx=idx, para=para, text=sent.strip()))
    return out


# --------------------------------------------------------------------------------------------
# wording findings (awkward CTA wording; fix suggestions are deterministic and force-neutral)
# --------------------------------------------------------------------------------------------
def spacing_rule_ok(stem_syllables):
    return stem_syllables


WORDING = [
    # (code, regex, message, fix-template or None, evidence)
    ('SILGE', re.compile(r'([가-힣]+)(?:시)?(?:실게요|실께요)'), '-시-와 -ㄹ게요(화자의 약속·의지)가 결합한 비문법적 요청. 해요체 명령/요청으로 고친다 (NIKL: -ㄹ게는 약속·의지)', 'imperative', 'NIKL 308180 + own reasoning'),
    ('LGGE', re.compile(r'(?:할|갈|볼|줄|올|드릴|해드릴|드릴)께요'), "-ㄹ께요 → -ㄹ게요 (NIKL 308180)", None, 'NIKL 308180'),
    ('HAYEO_JUSIGI', re.compile(r'하여\s*주(?:시기|십시오|시길|시면)'), '"하여 주시기 바랍니다"는 격식 공문 어투. 블로그·해요체 문서에서는 "해 주시기"로 통일 (오류는 아님)', None, 'register; NIKL 공문서 길잡이 revises similar forms but does not call it an error'),
    ('SPACING_JUSEYO', re.compile(r'([가-힣]{2,})해주(?:세요|십시오|시기|시길|시면|실래요|시겠어요)'), '"-해주세요": 본용언 활용형이 3음절 이상이면 "해 주세요"로 띄어 쓴다 (한글 맞춤법 47항; NIKL 331217)', None, 'NIKL 331217, 326874'),
    ('SPACING_NOUN_JUSEYO', re.compile(r'(?:연락|문의|답변|회신|댓글|말씀|조언)주(?:세요|십시오|시기|시면)'), '명사 + "주다"는 띄어 쓴다 ("연락 주세요")', None, 'own reasoning from 한글 맞춤법 (noun + 주다 are two words)'),
    ('NOMINAL_HA', re.compile(r'([가-힣]{2,})(?:를|을)\s+(?:해|하여)\s*(?:주|보)(?:세요|십시오|시기|시길)'), '"N을 해 주세요" 명사+하다 분리: "N해 주세요"로 줄일 수 있다 (의미·강도 동일)', None, 'own reasoning'),
    ('OBJECT_HONORIFIC', re.compile(r'(?:[가-힣0-9]+(?:원|개|번|분|건))\s*(?:되시겠습니다|이십니다|이세요)|(?:나오|되|있|없)(?:셨습니다|십니다|세요)\b'), '사물 높임 후보 ("3만원 되십니다", "커피 나오셨습니다"). 규범에 한계가 없어 NIKL도 단정하지 않음 → 사람이 아닌 주어는 제안 수준', None, 'NIKL 332098 (no norm; speakers differ)'),
    ('BARAE', re.compile(r'바래(?:요|서|며)|바래\s*(?:봅니다|봐요)'), '"바래요" → "바라요" (바라다의 활용; 비표준 표기)', None, 'own reasoning; verify against 표준국어대사전 before auto-fix'),
]


def wording_findings(text):
    out = []
    for code, rx, msg, fix, ev in WORDING:
        for m in rx.finditer(text):
            out.append(dict(code=code, span=m.group(0), start=m.start(), message=msg, evidence=ev))
    return out


# --------------------------------------------------------------------------------------------
# deterministic, force-neutral repairs (idempotent; applied outside quotation marks only)
# --------------------------------------------------------------------------------------------
SAFE_REPAIRS = [
    ('SPACING_JUSEYO', re.compile(r'([가-힣]{2,})해주(?=세요|십시오|시기|시길|시면|실래요|시겠어요)'), r'\1해 주'),
    ('SPACING_NOUN_JUSEYO', re.compile(r'(연락|문의|답변|회신|댓글|말씀|조언)주(?=세요|십시오|시기|시면)'), r'\1 주'),
    ('LGGE', re.compile(r'(?<=[가-힣])(할|갈|볼|줄|올|드릴|해드릴)께요'), r'\1게요'),
    ('SILGE', re.compile(r'(?<=[가-힣])실(?:게|께)요'), '세요'),
]


def safe_repair(text):
    """Apply the SAFE_REPAIRS to unquoted text.  Returns (new_text, list of applied codes).  Idempotent."""
    masked, _ = mask_quotes(text)
    edits = []
    for code, rx, repl in SAFE_REPAIRS:
        for m in rx.finditer(masked):
            edits.append((m.start(), m.end(), m.expand(repl), code))
    edits.sort()
    out, last, applied = [], 0, []
    for a, b, new, code in edits:
        if a < last:
            continue          # overlapping edit: skip (first one wins)
        out.append(text[last:a]); out.append(new); last = b; applied.append(code)
    out.append(text[last:])
    return ''.join(out), applied


if __name__ == '__main__':
    import sys, json
    t = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1], encoding='utf-8').read()
    u, d = detect(t)
    print(json.dumps(u, ensure_ascii=False, indent=1))
    print('deontic statements:', d)
