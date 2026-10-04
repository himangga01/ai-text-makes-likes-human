"""Shared loaders for T6 (CTA track). Python 3.9+ compatible (stdlib only)."""
import csv, json, re, os, sys, random
SP = '/private/tmp/claude-501/-Users-wisdom-wisdom-project-gpt-ai-text-makes-likes-human/e70a7860-b0c8-4bf4-999b-63b4ba6d0a8c/scratchpad'
T6 = SP + '/r5/T6'
BLOG = '/private/tmp/super-sejong-blog-corpus.json'          # 20 public posts of the owner (not copied into T6)
NEWS = SP + '/research/B/naver_news_test.csv'
KAT = SP + '/research/B/katfish_repo/katfish_dataset/'

_TERM = re.compile(r'[.!?。！？…]+["”’\')\]」』]*(?=\s|$)')

def split_sentences(text):
    """Line-aware sentence splitter. A line without terminal punctuation (heading) is one unit.
    Returns list of (sentence, is_heading)."""
    out = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        start = 0
        parts = []
        for m in _TERM.finditer(line):
            parts.append(line[start:m.end()].strip())
            start = m.end()
        tail = line[start:].strip()
        if tail:
            parts.append(tail)
        heading = (len(parts) == 1 and not _TERM.search(parts[0]) and len(line) < 80)
        for p in parts:
            if p:
                out.append((p, heading))
    return out

def load_blog():
    d = json.load(open(BLOG))
    return d['posts']

def load_news():
    rows = list(csv.DictReader(open(NEWS, encoding='utf-8')))
    return rows

def load_kat(g):
    return [json.loads(l) for l in open(KAT + g + '.jsonl')]
