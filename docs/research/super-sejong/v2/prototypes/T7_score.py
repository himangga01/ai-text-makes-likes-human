"""Deterministic item scorer for the seed benchmark (T7). Tier-1 metrics only: no model calls, no engine code.

score_item(record, output_text) -> dict of per-item metrics. The same scorer runs on both arms; the LLM judge and the human
audit are separate tiers and are not implemented here. Sentence alignment is monotone DP on character-bigram Dice.
"""
import re, sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_seed import segment, voice_profile, QUOTE
from voicefeat import diff_features

NUM = re.compile(r"\d[\d,.]*")


def sentences(text):
    return [(a, b, text[a:b]) for a, b, kind in segment(text)], [kind for _, _, kind in segment(text)]


def bigrams(s):
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def dice(a, b):
    x, y = bigrams(a), bigrams(b)
    if not x or not y:
        return 0.0
    return 2 * len(x & y) / (len(x) + len(y))


def align(src, out, floor=0.3):
    """Monotone alignment of sentence lists. Returns list m where m[i] = index into out or None."""
    n, m = len(src), len(out)
    sim = [[dice(src[i], out[j]) for j in range(m)] for i in range(n)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim[i - 1][j - 1]
            take = best[i - 1][j - 1] + s if s >= floor else -1
            best[i][j] = max(best[i - 1][j], best[i][j - 1], take)
    res = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        s = sim[i - 1][j - 1]
        if s >= floor and abs(best[i][j] - (best[i - 1][j - 1] + s)) < 1e-9:
            res[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return res


def force_of(sentence):
    """Heuristic CTA force 0-4 from the sentence tail (placeholder for the T6 detector; tuned on the seed ledger)."""
    s = sentence
    base = 0
    if s.strip().rstrip(".!") in ("안녕하세요", "수고하세요", "감사합니다"):
        return 0  # greeting formulas are not calls to action
    if s.rstrip().endswith("?"):
        return 1 if re.search(r"(하세요|해 주|알려|말씀)", s) else 0
    if re.search(r"([가-힣] 보(세요|시기 바랍니다|시길 바랍니다)|추천(합니다|해요|드려요)|편이 (좋|안전))", s):
        base = 2
    elif re.search(r"(주세요|주십시오|주시기 바랍니다|주시길 바랍니다|주시면|부탁|바랍니다|하실게요|하시기 바랍니다|바라겠습니다)", s):
        base = 3
    elif re.search(r"(해야 (합니다|해요|한다)|하여야 (합니다|한다|하겠습니다)|하셔야 합니다|하십시오|하세요|(?<!주)세요|지켜 주)", s):
        base = 4
    if base and base < 4 and re.search(r"(꼭|반드시|지금 바로|서둘러|즉시)", s):
        base += 1
    return base


def score_item(rec, out, opts=None):
    """opts: {'fix_colloquial_spelling': bool} (default False: colloquial spellings and CMC tokens are protected)."""
    opts = opts or {}
    text, gold = rec["text"], rec["gold_text"]
    if opts.get("fix_colloquial_spelling") and rec.get("gold_text_optin_colloquial_fix"):
        gold = rec["gold_text_optin_colloquial_fix"]
    S, skind = sentences(text)
    G, _ = sentences(gold)
    O, _ = sentences(out)
    src = [t for _, _, t in S]
    oth = [t for _, _, t in O]
    gld = [t for _, _, t in G]
    al = align(src, oth)
    res = {"id": rec["id"], "changed": out != text, "sentences": len(src), "unaligned_source_sentences": sum(1 for a in al if a is None),
           "output_sentences": len(oth)}

    def sidx(pos):
        for k, (a, b, _) in enumerate(S):
            if a <= pos < b:
                return k
        return None
    # ---- awkwardness repair ----
    spans = []
    inj_sent = set()
    for inj in rec["injections"]:
        k = sidx(inj["span"][0])
        inj_sent.add(k)
        status = "DELETED"
        if k is not None and al[k] is not None:
            o = oth[al[k]]
            g = gld[k] if k < len(gld) and len(gld) == len(src) else None
            acc_ok = False
            for acc in inj["acceptable_fixes"]:
                a_, b_ = inj["span"]
                if acc.endswith("."):
                    alt = acc
                else:
                    sa, sb, _ = S[k]
                    alt = text[sa:a_] + acc + text[b_:sb]
                if o.strip() == alt.strip():
                    acc_ok = True
            if g is not None and o.strip() == g.strip() or acc_ok:
                status = "FIXED_EXACT"
            elif re.search(inj["defect_regex"], o):
                status = "UNFIXED"
            elif g is not None and dice(o, g) >= 0.6:
                status = "FIXED_PROBABLE"
            else:
                status = "REWRITTEN_ADJUDICATE"
        spans.append({"id": inj["id"], "category": inj["category"], "primary": inj["primary"], "status": status})
    res["spans"] = spans
    # ---- collateral edits on sentences without an injection ----
    clean = [k for k in range(len(src)) if k not in inj_sent and skind[k] == "prose"]
    touched = [k for k in clean if al[k] is None or oth[al[k]].strip() != src[k].strip()]
    res["clean_sentences"] = len(clean)
    res["clean_sentences_touched"] = len(touched)
    # ---- voice: strictly per aligned sentence (level, ending class, honorific, humble, first-person); never a document register ----
    vp = voice_profile(text)
    ovp = voice_profile(out)
    exempt = {sidx(inj["span"][0]) for inj in rec["injections"] if inj.get("voice_effect")}
    comparable = 0
    per = collections.Counter()
    sent_viol = 0
    for k, sv in enumerate(vp):
        if sv["kind"] != "prose" or sv["level"] == "quote_only" or k >= len(al):
            continue
        j = al[k]
        if j is None or j >= len(ovp):
            continue
        if k in exempt:
            per["exempt_voice_conflicting_fix"] += 1
            continue
        comparable += 1
        diffs = diff_features(sv["features"], ovp[j]["features"])
        if diffs:
            sent_viol += 1
            for d_ in diffs:
                per[d_] += 1
    res["voice_comparable"] = comparable
    res["voice_violations"] = sent_viol
    res["voice_violations_by_feature"] = dict(per)
    # ---- protected tokens: colloquial spellings and CMC tokens ----
    qspans = [p["span"] for p in rec["protected_spans"]]
    prot_lost = prot_fixed = prot_n = 0
    for pt in rec["protected_tokens"]:
        prot_n += 1
        inq = any(a <= pt["spans"][0][0] and pt["spans"][0][1] <= b for a, b in qspans) if pt["spans"] else False
        lost = max(0, text.count(pt["text"]) - out.count(pt["text"]))
        optin = opts.get("fix_colloquial_spelling") and pt["kind"] == "colloquial_spelling" and pt["optional_fix"] and not inq
        if optin:
            if pt["optional_fix"]["gold_fix"] in out and pt["text"] not in out:
                prot_fixed += 1
        elif lost:
            prot_lost += 1
    res["protected_tokens"] = prot_n
    res["protected_tokens_changed"] = prot_lost
    res["optin_colloquial_fixed"] = prot_fixed
    quotes = [text[p["span"][0]:p["span"][1]] for p in rec["protected_spans"]]
    res["quotes"] = len(quotes)
    res["quotes_changed"] = sum(1 for q in quotes if q not in out)
    # ---- CTA ----
    ctas = []
    for c in rec["cta"]:
        k = sidx(c["span"][0])
        o = oth[al[k]] if k is not None and al[k] is not None else None
        f_out = force_of(o) if o else 0
        ctas.append({"id": c["id"], "cta_class": c["cta_class"], "force_gold": c["force"], "force_out": f_out,
                     "present": bool(o) and f_out > 0, "weakened": bool(o) and 0 < f_out < c["force"], "strengthened": bool(o) and f_out > c["force"]})
    res["cta"] = ctas
    invented = 0
    if not rec["cta"] and rec["item_type"] != "composite_document":
        src_force = {force_of(s) > 0 for s in src}
        invented = sum(1 for k, s in enumerate(oth) if force_of(s) > 0 and not any(force_of(src[i]) > 0 and al[i] == k for i in range(len(src))))
    res["cta_invented_sentences"] = invented
    # ---- meaning invariants (lenient regex tier) ----
    bad = []
    for m in rec["meaning_invariants"]:
        if any(not re.search(x, out) for x in m["require_all"]) or any(re.search(x, out) for x in m["forbid_any"]):
            bad.append(m["id"])
    res["invariants"] = len(rec["meaning_invariants"])
    res["invariants_violated"] = len(bad)
    return res
