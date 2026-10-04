"""Per-sentence voice features (말투) for evaluation: speech level, honorific markers, humble forms, first-person markers,
sentence-final ending class. Owner decision (4 Oct 2026): voice is preserved per sentence, never against a document register.
Kiwi (offline evaluation only, Apache-2.0 in 0.24.0) is used for -시-, 께서, 님 and first-person pronouns; without Kiwi a regex fallback is used."""
import re
try:
    from kiwipiepy import Kiwi
    _K = Kiwi()
except Exception:  # pragma: no cover
    _K = None

CMC = re.compile(r"(?:[ㅎㅋㅠㅜ]{2,}|\^{2,}|\^_\^|~+)")
LEX_HON = re.compile(r"(드세요|드셔|드셨|드십|주무세요|주무셔|주무셨|계세요|계셔|계십|계셨|잡수|말씀하)")
HUMBLE = re.compile(r"(드립니다|드려요|드릴|드렸|드리겠|드리고|드리며|드리는|여쭤|여쭙|여쭈|뵙|저희|저는|제가|제게|저도|저의)")
FIRST_PERSON = ("저", "나", "우리", "저희", "필자", "내", "제")


def strip_tail(s):
    t = s.strip()
    for _ in range(4):
        t = re.sub(r'[\s"“”‘’「」』\)\]]+$', '', t)
        t = re.sub(r'[.?!…]+$', '', t)
        t = CMC.sub(lambda m: "" if m.end() == len(t) else m.group(0), t) if CMC.search(t) and CMC.search(t).end() == len(t) else t
        t = re.sub(r'(?:[ㅎㅋㅠㅜ]+|\^+|~+)$', '', t).rstrip()
    return t


ENDINGS = [  # (class, regex on stripped tail). Order matters: most specific first.
    ("hapsyo_q", r"(습니까|ㅂ니까|[가-힣]니까)$"),
    ("hapsyo_imp", r"(십시오|십시요)$"),
    ("hapsyo_prop", r"(읍시다|습시다|ㅂ시다|[가-힣]시다)$"),
    ("hapsyo_decl", r"(습니다|[가-힣]니다)$"),
    ("haeyo_deolagoyo", r"더라고요$"),
    ("haeyo_geodeunyo", r"거든요$"),
    ("haeyo_janayo", r"잖아요$"),
    ("haeyo_neyo", r"네요$"),
    ("haeyo_gunyo", r"군요$"),
    ("haeyo_jyo", r"(죠|지요)$"),
    ("haeyo_lgeyo", r"[게께]요$"),
    ("haeyo_lkkayo", r"까요$"),
    ("haeyo_ndeyo", r"[는은ㄴ]?데요$"),
    ("haeyo_seyo", r"(세요|셔요)$"),
    ("haeyo_generic", r"요$"),
    ("haera_q", r"(니|냐|는가|ㄴ가|은가|까)$"),
    ("haeche_deola", r"더라$"),
    ("haeche_geoya", r"(거야|건데|거든|잖아)$"),
    ("haera_decl", r"다$"),
    ("haeche_generic", r"[어아야지네게께래대군걸데]$"),
]
_COMPILED = [(n, re.compile(r)) for n, r in ENDINGS]


def level_from_class(c):
    if c is None:
        return "other"
    p = c.split("_")[0]
    return {"hapsyo": "hapsyo", "haeyo": "haeyo", "haera": "haera", "haeche": "haeche"}.get(p, "other")


def ending_class(sentence):
    t = strip_tail(sentence)
    if not t:
        return None
    if t.endswith("아니다"):
        return "haera_decl"
    for name, rx in _COMPILED:
        if rx.search(t):
            if name.startswith("hapsyo") and not (t.endswith(("습니다", "습니까", "십시오", "십시요", "읍시다", "습시다")) or (len(t) >= 3 and "가" <= t[-3] <= "힣" and (ord(t[-3]) - 0xAC00) % 28 == 17)):
                continue  # 아니다 / 하니까 etc. are not 합쇼체
            return name
    if len(t) > 1 and "가" <= t[-1] <= "힣" and (ord(t[-1]) - 0xAC00) % 28 == 0:
        return "haeche_open"  # open-syllable plain ending (와, 봐, 줘, 해 ...)
    return None


def honorific_markers(sentence):
    """Multiset (sorted list) of honorific markers: -시- count matters, so losing one of two is a change."""
    marks = []
    if _K is not None:
        for t in _K.tokenize(sentence):
            if t.tag == "EP" and t.form in ("시", "으시"):
                marks.append("si")
            elif t.form in ("께서", "께") and t.tag.startswith("J"):
                marks.append("kkeseo")
            elif t.tag == "XSN" and t.form == "님":
                marks.append("nim")
    else:
        marks += ["si"] * len(re.findall(r"(셨|세요|십니다|십니까|십시오|으시|시겠)", sentence))
        marks += ["kkeseo"] * len(re.findall(r"께서?", sentence))
        marks += ["nim"] * sentence.count("님")
    marks += ["lexical"] * len(LEX_HON.findall(sentence))
    return sorted(marks)


def humble_markers(sentence):
    return frozenset(m.group(0) for m in HUMBLE.finditer(sentence) if m.group(0) not in ("저는", "제가", "제게", "저도", "저의", "저희"))


def persona_markers(sentence):
    out = set()
    if _K is not None:
        for t in _K.tokenize(sentence):
            if t.tag == "NP" and t.form in ("저", "나", "우리", "저희", "내"):
                out.add(t.form if t.form != "내" else "나")
            elif t.tag == "NNG" and t.form == "필자":
                out.add("필자")
    else:
        for w in ("저희", "저는", "제가", "필자", "우리", "나는", "내가"):
            if w in sentence:
                out.add(w)
    return frozenset(out)


def features(sentence_narration):
    c = ending_class(sentence_narration)
    return {"level": level_from_class(c), "ending": c, "honorific": honorific_markers(sentence_narration),
            "humble": sorted(humble_markers(sentence_narration)), "persona": sorted(persona_markers(sentence_narration))}


def diff_features(a, b):
    return [k for k in ("level", "ending", "honorific", "humble", "persona") if a[k] != b[k]]
