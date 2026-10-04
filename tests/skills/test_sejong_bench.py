"""Independent scorer of Super Sejong v2 (WP-15a, scripts/sejong-bench/).

Pins the metamorphic self-test of T7 section 7 (identity 0/92, gold 92/92, the damage table), the
scorer's statuses on constructed records, the $BENCH write guard, the no-text metrics guard and the
rule that the scorer imports no engine code. Text in this file is constructed; no owner text.
"""
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = ROOT / "scripts" / "sejong-bench"
sys.path.insert(0, str(BENCH_DIR))
import bench_io  # noqa: E402
import bench_text  # noqa: E402
import damage  # noqa: E402
import score  # noqa: E402
import selftest  # noqa: E402
import voicefeat  # noqa: E402

try:
    import kiwipiepy  # noqa: F401
    HAVE_KIWI = True
except Exception:  # pragma: no cover - the product Python has no Kiwi
    HAVE_KIWI = False

HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
FORBIDDEN_IMPORTS = {"engine_runtime", "sejong", "src", "workflow", "super_sejong", "super_sejong_josa", "skill_gateway",
                     "skill_bridge", "comma_guard", "quantities", "documents", "sejong_cli"}


def run_cli(*argv, env=None):
    """score.main(argv) with BENCH (and friends) set; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    saved = dict(os.environ)
    try:
        os.environ.update(env or {})
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = score.main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return code, out.getvalue(), err.getvalue()


def mini(text, gold, **extra):
    """A hand-written seed record (constructed text) with the fields score_item reads."""
    rec = {"id": "T-1", "key": "T1", "family": "T1", "item_type": "injected", "genre": "blog", "voice_stratum": "haera",
           "text": text, "gold_text": gold, "gold_text_optin_colloquial_fix": None, "expect_edit": True,
           "injections": [], "protected_spans": [], "protected_tokens": [], "cta": [], "meaning_invariants": [], "probes": []}
    rec.update(extra)
    return rec


def injection(text, before, fix, **extra):
    start = text.index(before)
    inj = {"id": "i1", "category": "REDUN", "primary": True, "span": [start, start + len(before)], "before": before,
           "gold_fix": fix, "acceptable_fixes": [], "defect_regex": re.escape(before), "voice_effect": []}
    inj.update(extra)
    return inj


class BackendCase(unittest.TestCase):
    """Base: runs each test under the regex backend unless a test switches it."""
    backend = "off"

    @classmethod
    def setUpClass(cls):
        cls._saved = voicefeat._MODE
        voicefeat.set_backend(cls.backend)

    @classmethod
    def tearDownClass(cls):
        voicefeat.set_backend(cls._saved)


class SelfTestRegex(BackendCase):
    """T7 section 7 reproduced with the regex voice backend (the product Python has no Kiwi)."""

    def test_headline_numbers(self):
        items = selftest.seed_items()
        self.assertEqual(len(items), 206)
        arms = selftest.run_arms(items)
        identity = arms["identity writer, default config"]
        self.assertEqual((identity["primary_fixed"], identity["primary"], identity["changed_outputs"]), (0, 92, 0))
        gold = arms["gold writer, default config"]
        self.assertEqual((gold["primary_fixed"], gold["primary"]), (92, 92))
        self.assertEqual(gold["clean_sentences_touched"], 0)
        self.assertEqual(gold["voice_violations"], 0)
        self.assertEqual((gold["cta_present"], gold["cta_explicit"]), (46, 46))
        self.assertEqual(gold["span_status"], {"FIXED_EXACT": 142})

    def test_every_pinned_number_of_t7_is_reproduced(self):
        items = selftest.seed_items()
        problems = selftest.compare(selftest.run_arms(items), selftest.run_damage(items), selftest.force_agreement(items))
        self.assertEqual(problems, [])

    def test_damage_table(self):
        table = selftest.run_damage(selftest.seed_items())
        expected = {"sentence level changed": (140, 134), "ending style flattened (거든요/더라고요 -> 습니다)": (11, 11),
                    "first-person marker dropped": (17, 17), "honorific -시- dropped": (3, 3),
                    "meaning flip (regex tier)": (22, 20), "explicit CTA replaced": (35, 35),
                    "collateral edit in a clean sentence": (202, 202),
                    "colloquial spelling corrected / CMC token stripped (default config)": (14, 14)}
        self.assertEqual({k: v[:2] for k, v in table.items()}, expected)
        # the six undetected level changes are the exempt voice-conflicting fixes; the two meaning misses are role swaps
        self.assertEqual(table["sentence level changed"][2], ["J60", "J61", "J62", "J64", "A10", "V11"])
        self.assertEqual(table["meaning flip (regex tier)"][2], ["T07", "T09"])

    def test_opt_in_colloquial_fix_is_over_editing_by_default_and_not_with_the_option(self):
        arms = selftest.run_arms(selftest.seed_items())
        default = arms["gold writer + opt-in colloquial fix, scored in default config (should be over-editing)"]
        optin = arms["gold writer + opt-in colloquial fix, scored with option ON"]
        self.assertEqual((default["protected_tokens_changed"], default["clean_sentences_touched"]), (10, 10))
        self.assertEqual((optin["protected_tokens_changed"], optin["optin_colloquial_fixed"]), (1, 9))  # 1 = fix inside a quotation
        self.assertEqual(optin["voice_violations"], 0)  # correcting 할께 -> 할게 is not a lost honorific

    def test_added_checks(self):
        self.assertEqual(selftest.extra_problems(selftest.seed_items()), [])

    def test_run_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(selftest.run(), 0)
        self.assertIn("reproduced exactly", out.getvalue())


@unittest.skipUnless(HAVE_KIWI, "kiwipiepy is not installed (optional)")
class SelfTestKiwi(BackendCase):
    """The same numbers with Kiwi (T7's own backend) when it is installed."""
    backend = "on"

    def test_every_pinned_number_of_t7_is_reproduced(self):
        self.assertTrue(voicefeat.backend_name().startswith("kiwi-"))
        items = selftest.seed_items()
        self.assertEqual(selftest.compare(selftest.run_arms(items), selftest.run_damage(items), selftest.force_agreement(items)), [])
        self.assertEqual(selftest.extra_problems(items), [])


class RepairStatuses(BackendCase):
    TEXT = "그는 학교에 갔었었다. 날씨가 좋았다."
    GOLD = "그는 학교에 갔었다. 날씨가 좋았다."

    def status(self, output):
        rec = mini(self.TEXT, self.GOLD, injections=[injection(self.TEXT, "갔었었다", "갔었다")])
        result = score.score_item(rec, output)
        return result["spans"][0]["status"], result

    def test_each_status(self):
        self.assertEqual(self.status(self.GOLD)[0], "FIXED_EXACT")
        self.assertEqual(self.status(self.TEXT)[0], "UNFIXED")
        self.assertEqual(self.status("그는 학교에 갔었다! 날씨가 좋았다.")[0], "FIXED_PROBABLE")
        self.assertEqual(self.status("그는 학교에 다녀왔다. 날씨가 좋았다.")[0], "REWRITTEN_ADJUDICATE")
        self.assertEqual(self.status("날씨가 좋았다.")[0], "DELETED")

    def test_acceptable_fix_counts_as_exact(self):
        inj = injection(self.TEXT, "갔었었다", "갔었다", acceptable_fixes=["다녀왔다"])
        rec = mini(self.TEXT, self.GOLD, injections=[inj])
        result = score.score_item(rec, "그는 학교에 다녀왔다. 날씨가 좋았다.")
        self.assertEqual(result["spans"][0]["status"], "FIXED_EXACT")

    def test_only_primary_injections_headline(self):
        rec = mini(self.TEXT, self.GOLD, injections=[injection(self.TEXT, "갔었었다", "갔었다", primary=False)])
        agg = score.aggregate([score.score_item(rec, self.GOLD)])
        self.assertEqual((agg["spans"], agg["primary"], agg["primary_fixed"]), (1, 0, 0))

    def test_collateral_counts_untouched_clean_sentences_only(self):
        _, clean = self.status(self.GOLD)
        self.assertEqual((clean["clean_sentences"], clean["clean_sentences_touched"]), (1, 0))
        _, touched = self.status("그는 학교에 갔었다. 물론 날씨가 좋았다.")
        self.assertEqual(touched["clean_sentences_touched"], 1)
        self.assertEqual(touched["touched_sentence_index"], [1])


class VoiceAndTokens(BackendCase):
    def test_voice_is_per_sentence_and_not_a_document_register(self):
        text = "회의는 오전에 시작합니다. 자료는 미리 읽어 오세요. 질문은 나중에 받겠습니다."
        mixed = score.score_item(mini(text, text), text)
        self.assertEqual((mixed["voice_comparable"], mixed["voice_violations"]), (3, 0))  # 합쇼체 + 해요체 stays mixed
        unified = score.score_item(mini(text, text), "회의는 오전에 시작합니다. 자료는 미리 읽어 오십시오. 질문은 나중에 받겠습니다.")
        self.assertEqual(unified["voice_violations"], 1)  # unifying the register is a violation, not a repair
        self.assertIn("ending", unified["voice_violations_by_feature"])

    def test_embedded_honorific_and_first_person_are_features(self):
        text = "저는 이 글을 씁니다. 궁금하신 분은 댓글을 남겨 주세요."
        dropped_si = score.score_item(mini(text, text), "저는 이 글을 씁니다. 궁금한 분은 댓글을 남겨 주세요.")
        self.assertEqual(dropped_si["voice_violations_by_feature"], {"honorific": 1})  # the live 궁금하신 -> 궁금한 case
        dropped_me = score.score_item(mini(text, text), "이 글을 씁니다. 궁금하신 분은 댓글을 남겨 주세요.")
        self.assertEqual(dropped_me["voice_violations_by_feature"], {"persona": 1})

    def test_voice_conflicting_fix_is_exempt_and_counted_apart(self):
        text = "원장님께서 말씀하셨어요. 오늘은 쉬어요."
        gold = "원장님께서 말씀했어요. 오늘은 쉬어요."
        inj = injection(text, "말씀하셨어요", "말씀했어요", voice_effect=["honorific"], primary=False)
        result = score.score_item(mini(text, gold, injections=[inj]), gold)
        self.assertEqual((result["voice_violations"], result["voice_violations_by_feature"]), (0, {"exempt_voice_conflicting_fix": 1}))

    def test_colloquial_and_cmc_tokens_are_protected_by_default(self):
        text = "내일 갈께요 ㅎㅎ 사진은 나중에 올릴게요."
        tokens = [{"id": "k1", "kind": "colloquial_spelling", "text": "갈께요", "spans": [[3, 6]],
                   "optional_fix": {"option": "fix_colloquial_spelling", "gold_fix": "갈게요"}},
                  {"id": "k2", "kind": "cmc", "text": "ㅎㅎ", "spans": [[7, 9]], "optional_fix": None}]
        rec = mini(text, text, protected_tokens=tokens, gold_text_optin_colloquial_fix="내일 갈게요 ㅎㅎ 사진은 나중에 올릴게요.")
        fixed = "내일 갈게요 ㅎㅎ 사진은 나중에 올릴게요."
        default = score.score_item(rec, fixed)
        self.assertEqual((default["protected_tokens_changed"], default["optin_colloquial_fixed"]), (1, 0))
        self.assertEqual(default["voice_violations"], 0)
        optin = score.score_item(rec, fixed, {"fix_colloquial_spelling": True})
        self.assertEqual((optin["protected_tokens_changed"], optin["optin_colloquial_fixed"]), (0, 1))
        cmc = score.score_item(rec, "내일 갈께요 사진은 나중에 올릴게요.")
        self.assertEqual(cmc["protected_tokens_changed"], 1)  # a stripped CMC token
        gone = score.score_item(rec, "내일 사진은 나중에 올릴게요.", {"fix_colloquial_spelling": True})
        self.assertGreaterEqual(gone["protected_tokens_changed"], 1)  # removing the token is not "fixing" it

    def test_quotations_must_stay_verbatim(self):
        text = "그가 말했다. “우리는 괜찮다고 했다” 나는 고개를 끄덕였다."
        quote = "“우리는 괜찮다고 했다”"
        rec = mini(text, text, protected_spans=[{"span": [text.index(quote), text.index(quote) + len(quote)], "reason": "quotation"}])
        self.assertEqual(score.score_item(rec, text)["quotes_changed"], 0)
        self.assertEqual(score.score_item(rec, text.replace("괜찮다고", "좋다고"))["quotes_changed"], 1)

    def test_regex_features_on_embedded_forms(self):
        f = voicefeat.features
        self.assertEqual(f("궁금하신 분은 문의하시면 됩니다.")["honorific"], ["si", "si"])
        self.assertEqual(f("미리 알려 주시기 바랍니다.")["honorific"], ["si"])
        self.assertEqual(f("원장님께서 학부모님들께 인사를 드립니다.")["honorific"], ["kkeseo", "kkeseo", "nim", "nim"])
        self.assertEqual(f("내일 갈께요.")["honorific"], [])  # 할께-type ending, not the particle 께
        self.assertEqual(f("가족과 함께 관리실에 갑니다.")["honorific"], [])
        self.assertEqual(f("제가 확인하겠습니다.")["persona"], ["저"])
        self.assertEqual(f("저 사람은 갑니다.")["persona"], [])  # demonstrative 저


class CtaAndMeaning(BackendCase):
    def cta_rec(self, text, force=3):
        sentence = "자세한 내용은 댓글로 문의해 주세요."
        start = text.index(sentence)
        return mini(text, text, cta=[{"id": "c1", "span": [start, start + len(sentence)], "text": sentence, "force": force,
                                       "cta_class": "explicit"}])

    def test_cta_presence_force_and_invention(self):
        text = "오늘은 여기까지 정리합니다. 자세한 내용은 댓글로 문의해 주세요."
        rec = self.cta_rec(text)
        kept = score.score_item(rec, text)["cta"][0]
        self.assertEqual((kept["present"], kept["weakened"], kept["strengthened"]), (True, False, False))
        gone = score.score_item(rec, "오늘은 여기까지 정리합니다. 자세한 내용은 아래와 같습니다.")["cta"][0]
        self.assertFalse(gone["present"])
        weaker = score.score_item(rec, "오늘은 여기까지 정리합니다. 자세한 내용은 댓글로 문의해 보세요.")["cta"][0]
        self.assertEqual((weaker["present"], weaker["weakened"]), (True, True))
        stronger = score.score_item(rec, "오늘은 여기까지 정리합니다. 자세한 내용은 반드시 댓글로 문의하셔야 합니다.")["cta"][0]
        self.assertTrue(stronger["strengthened"])
        free = mini("오늘은 여기까지 정리합니다. 내일 다시 씁니다.", "오늘은 여기까지 정리합니다. 내일 다시 씁니다.")
        self.assertEqual(score.score_item(free, free["text"])["cta_invented_sentences"], 0)
        invented = score.score_item(free, "오늘은 여기까지 정리합니다. 내일 다시 씁니다. 꼭 이웃추가를 눌러 주세요.")
        self.assertEqual(invented["cta_invented_sentences"], 1)

    def test_meaning_invariants_regex_tier_and_numbers(self):
        text = "신청은 3월 5일까지 하지 않아도 됩니다."
        inv = [{"id": "m1", "kind": "negation", "require_all": ["않아도"], "forbid_any": []},
               {"id": "m2", "kind": "number", "require_all": ["3월", "5일"], "forbid_any": []}]
        rec = mini(text, text, meaning_invariants=inv)
        ok = score.score_item(rec, text)
        self.assertEqual((ok["invariants_violated"], ok["numbers_dropped"], ok["numbers_added"]), (0, 0, 0))
        flipped = score.score_item(rec, "신청은 3월 5일까지 해야 합니다.")
        self.assertEqual(flipped["invariants_violated_ids"], ["m1"])
        changed = score.score_item(rec, "신청은 3월 8일까지 하지 않아도 됩니다.")
        self.assertEqual((changed["invariants_violated_ids"], changed["numbers_dropped"], changed["numbers_added"]), (["m2"], 1, 1))


class NaturalMode(BackendCase):
    DRAFT = ("오늘은 신청 방법을 정리합니다. 신청은 3월 5일까지 받습니다. 궁금하신 분은 댓글로 문의해 주세요. "
             "내일 갈께요 ㅎㅎ 사진도 올릴게요.")

    def test_identity_is_clean_and_derived_ledger_is_used(self):
        rec, m = score.score_natural(self.DRAFT, self.DRAFT, "N-x")
        self.assertEqual((m["changed"], m["clean_sentences_touched"], m["voice_violations"], m["numbers_dropped"]), (False, 0, 0, 0))
        kinds = sorted(t["kind"] for t in rec["protected_tokens"])
        self.assertEqual(kinds, ["cmc", "colloquial_spelling"])
        self.assertGreaterEqual(len(rec["cta"]), 1)

    def test_damage_is_detected_without_gold(self):
        _, m = score.score_natural(self.DRAFT, self.DRAFT.replace("궁금하신 분은", "궁금한 분은").replace("3월 5일", "3월 9일"), "N-x")
        self.assertEqual(m["touched_sentence_index"], [1, 2])
        self.assertEqual(m["voice_violations_by_feature"], {"honorific": 1})
        self.assertEqual((m["numbers_dropped"], m["numbers_added"]), (1, 1))
        self.assertEqual(m["touched_offsets"][0], [self.DRAFT.index("신청은"), self.DRAFT.index("받습니다.") + len("받습니다.")])


class BenchGuard(unittest.TestCase):
    def test_bench_must_be_outside_the_repository_and_any_git_work_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = bench_io.resolve_bench({"BENCH": tmp})
            self.assertEqual(ok, Path(tmp).resolve())
            self.assertEqual(bench_io.bench_path("metrics", "a.jsonl", env={"BENCH": tmp}), ok / "metrics" / "a.jsonl")
            nested = Path(tmp, "work", "bench")
            Path(tmp, "work", ".git").mkdir(parents=True)
            with self.assertRaises(bench_io.BenchError):
                bench_io.resolve_bench({"BENCH": str(nested)})
        for inside in (str(ROOT), str(ROOT / "docs"), str(BENCH_DIR / "out"), str(ROOT.parent)):
            with self.subTest(bench=inside), self.assertRaises(bench_io.BenchError):
                bench_io.resolve_bench({"BENCH": inside})

    def test_paths_cannot_escape_bench(self):
        with tempfile.TemporaryDirectory() as tmp:
            for parts in (("..", "x"), ("a", "..", "..", "x"), ("/etc", "x")):
                with self.subTest(parts=parts), self.assertRaises(bench_io.BenchError):
                    bench_io.bench_path(*parts, env={"BENCH": tmp})

    def test_default_bench_is_outside_the_repository(self):
        default = Path(bench_io.DEFAULT_BENCH)
        self.assertTrue(default.is_absolute())
        self.assertNotIn(ROOT.resolve(), [default, *default.parents])
        self.assertNotIn(default.resolve(), ROOT.resolve().parents)
        self.assertEqual(bench_io.resolve_bench({}), default.resolve())  # no BENCH set: the default passes its own guard

    def test_outputs_inside_the_repository_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli("score", "--outputs", str(BENCH_DIR / "score.py"), "--tag", "x", env={"BENCH": tmp})
            self.assertEqual(code, 2)
            self.assertIn("outside the repository", err)
            self.assertEqual(os.listdir(tmp), [])

    def test_metrics_records_hold_no_text(self):
        for good in ({"id": "SSB-001", "n": 3, "ok": True, "sha": "ab" * 32, "nested": {"status": "FIXED_EXACT"}, "x": None, "f": 0.5},):
            bench_io.check_metrics_record(good)
        for bad in ({"t": "한국어 문장"}, {"t": "x" * 121}, {"한": 1}, {"t": ["ok", "ㅋㅋ"]}, {"t": float("nan")}, {"t": b"x"}):
            with self.subTest(bad=repr(bad)[:30]), self.assertRaises(bench_io.BenchError):
                bench_io.check_metrics_record(bad)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(bench_io.BenchError):
                bench_io.write_metrics_jsonl("metrics/x.jsonl", [{"ok": 1}, {"t": "한글"}], env={"BENCH": tmp})
            self.assertEqual(os.listdir(tmp), [])  # nothing written when one record fails

    def test_labels(self):
        self.assertEqual(bench_io.check_label("arm-A.1", "arm"), "arm-A.1")
        for bad in ("", "a b", "한글", "x" * 41, "../x"):
            with self.subTest(label=bad), self.assertRaises(bench_io.BenchError):
                bench_io.check_label(bad, "arm")


class CliAndPersistence(BackendCase):
    def test_score_writes_metrics_only_under_bench(self):
        records, _ = score.load_seed()
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp, "private", "gold.jsonl")
            outputs.parent.mkdir()
            outputs.write_text("".join(json.dumps({"id": r["id"], "output": r["gold_text"]}, ensure_ascii=False) + "\n"
                                       for r in records), encoding="utf-8")
            before = sorted(p.name for p in BENCH_DIR.iterdir())
            code, out, err = run_cli("score", "--outputs", str(outputs), "--tag", "gold", "--arm", "stub-gold", env={"BENCH": tmp})
            self.assertEqual((code, err), (0, ""), out + err)
            self.assertEqual(sorted(p.name for p in BENCH_DIR.iterdir()), before)  # nothing written next to the scorer
            written = sorted(str(p.relative_to(tmp)) for p in Path(tmp).rglob("*") if p.is_file())
            self.assertEqual(written, ["metrics/gold.jsonl", "metrics/gold.summary.json", "private/gold.jsonl"])
            for name in ("metrics/gold.jsonl", "metrics/gold.summary.json"):
                self.assertIsNone(HANGUL.search(Path(tmp, name).read_text(encoding="utf-8")), name)
            lines = [json.loads(line) for line in Path(tmp, "metrics", "gold.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(lines), 206)
            first = lines[0]
            self.assertEqual(first["schema"], bench_io.METRICS_SCHEMA)
            self.assertEqual(first["sha256"]["output"], hashlib.sha256(records[0]["gold_text"].encode("utf-8")).hexdigest())
            self.assertEqual((first["arm"], first["voice_backend"], len(first["scorer"])), ("stub-gold", "regex", 16))
            summary = json.loads(Path(tmp, "metrics", "gold.summary.json").read_text(encoding="utf-8"))
            self.assertEqual((summary["total"]["primary_fixed"], summary["total"]["primary"]), (92, 92))
            self.assertEqual(summary["over_editing"]["changed"], 0)
            self.assertEqual(summary["records_without_output"], 0)

    def test_unknown_ids_are_refused_and_missing_outputs_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, "p", "bad.jsonl")
            bad.parent.mkdir()
            bad.write_text(json.dumps({"id": "NOPE-1", "output": "x"}) + "\n", encoding="utf-8")
            code, _, err = run_cli("score", "--outputs", str(bad), "--tag", "t", env={"BENCH": tmp})
            self.assertEqual(code, 2)
            self.assertIn("not seed ids", err)
            records, _ = score.load_seed()
            part = Path(tmp, "p", "part.jsonl")
            part.write_text(json.dumps({"id": records[0]["id"], "output": records[0]["text"]}, ensure_ascii=False) + "\n", encoding="utf-8")
            code, out, _ = run_cli("score", "--outputs", str(part), "--tag", "t", env={"BENCH": tmp})
            self.assertEqual(code, 0)
            self.assertIn("205 without output", out)

    def test_natural_mode_reads_drafts_read_only_and_persists_no_body(self):
        draft = NaturalMode.DRAFT
        edited = draft.replace("신청은 3월 5일까지 받습니다.", "신청은 3월 5일까지 접수합니다.")
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp, "private", "draft.txt"), Path(tmp, "private", "edited.txt")
            src.parent.mkdir()
            src.write_text(draft, encoding="utf-8")
            out.write_text(edited, encoding="utf-8")
            os.chmod(src, stat.S_IRUSR)
            os.chmod(out, stat.S_IRUSR)
            digest = bench_io.sha256_file(src)
            try:
                code, text, err = run_cli("natural", "--source", str(src), "--output", str(out), "--tag", "nat", env={"BENCH": tmp})
                self.assertEqual((code, err), (0, ""), text + err)
                self.assertEqual(bench_io.sha256_file(src), digest)
                metrics = Path(tmp, "metrics", "nat.jsonl").read_text(encoding="utf-8")
                summary = Path(tmp, "metrics", "nat.summary.json").read_text(encoding="utf-8")
                for blob in (metrics, summary, text):
                    self.assertIsNone(HANGUL.search(blob))
                    self.assertNotIn("접수", blob)
                row = json.loads(metrics)
                self.assertEqual(row["id"], "N-" + hashlib.sha256(draft.encode("utf-8")).hexdigest()[:12])
                self.assertEqual((row["touched_sentence_index"], row["item_type"]), ([1], "natural_draft"))
                self.assertEqual(sorted(str(p.relative_to(tmp)) for p in Path(tmp).rglob("*") if p.is_file()),
                                 ["metrics/nat.jsonl", "metrics/nat.summary.json", "private/draft.txt", "private/edited.txt"])
            finally:
                os.chmod(src, stat.S_IRUSR | stat.S_IWUSR)
                os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)

    def test_scorer_hash_names_the_judge_and_not_its_tests(self):
        names = [p.name for p in bench_io.scorer_files()]
        self.assertEqual(names, ["bench_io.py", "bench_text.py", "score.py", "voicefeat.py"])
        self.assertRegex(bench_io.scorer_sha256(), r"^[0-9a-f]{64}$")


class Alignment(unittest.TestCase):
    def test_exact_dp_on_small_inputs(self):
        src = ["가나다라 마바사", "아자차카 타파하", "하나 둘 셋 넷 다섯"]
        self.assertEqual(bench_text.align(src, src), [0, 1, 2])
        self.assertEqual(bench_text.align(src, [src[0], src[2]]), [0, None, 1])
        self.assertEqual(bench_text.align(src, ["전혀 다른 문장입니다"]), [None, None, None])

    def test_segmentation_keeps_quotations_whole_and_cuts_cmc_runs(self):
        text = "그가 말했다. “지금 가자. 서둘러” 나는 따라갔다. 좋아요 ㅎㅎ 다음에 또 봐요."
        spans = [text[a:b] for a, b, _ in bench_text.segment(text)]
        self.assertEqual(spans, ["그가 말했다.", "“지금 가자. 서둘러” 나는 따라갔다.", "좋아요 ㅎㅎ", "다음에 또 봐요."])
        self.assertEqual([k for _, _, k in bench_text.segment("# 제목\n- 항목\n본문입니다.")], ["heading", "list", "prose"])


PATH_HACKS = [re.compile(r"^\s*(from|import)\s+(engine_runtime|sejong|src)\b"),
              re.compile(r"""(from|import|require)\s*\(?\s*['"][^'"]*(engine_runtime|src/engine|sejong/)"""),
              re.compile(r"sys\.path\.(insert|append)\(.*(engine_runtime|['\"]src['\"])")]


def engine_import_violations(name, text, suffix=".py"):
    """Lines of `text` that import engine code: AST for Python (import, from-import, relative import,
    importlib.import_module / __import__ with a string), a line grep for every file type."""
    found = []
    if suffix == ".py":
        for node in ast.walk(ast.parse(text, filename=name)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [("." * node.level) + (node.module or "")]
            elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__"):
                names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            for module in names:
                if module.startswith(".") or module.split(".")[0] in FORBIDDEN_IMPORTS:
                    found.append((node.lineno, module))
    for number, line in enumerate(text.splitlines(), 1):
        if any(pattern.search(line) for pattern in PATH_HACKS):
            found.append((number, line.strip()))
    return found


class Independence(unittest.TestCase):
    """The scorer is an independent judge: it imports no engine code (DESIGN.md 7.1, T7 section 3.1)."""

    def sources(self):
        files = [p for p in BENCH_DIR.rglob("*") if p.is_file() and p.suffix in (".py", ".mjs", ".js", ".ts", ".cjs")]
        self.assertGreaterEqual(len(files), 6)
        return files

    def test_scorer_imports_no_engine_code(self):
        for path in self.sources():
            with self.subTest(file=str(path.relative_to(BENCH_DIR))):
                self.assertEqual(engine_import_violations(path.name, path.read_text(encoding="utf-8"), path.suffix), [])

    def test_the_check_itself_catches_engine_imports(self):
        bad = ["from engine_runtime import workflow", "import engine_runtime.sejong.text", "from sejong import voice",
               "import sejong", "from src.engine import x", "import importlib\nimportlib.import_module('sejong.text')",
               "__import__('super_sejong')", "import sys\nsys.path.insert(0, 'engine_runtime')", "from . import score",
               "from super_sejong import changed_polarity", "const x = require('../../src/engine/sejong/prompt')"]
        for snippet in bad:
            with self.subTest(snippet=snippet):
                suffix = ".js" if snippet.startswith("const") else ".py"
                self.assertTrue(engine_import_violations("x", snippet, suffix), snippet)
        for snippet in ("import re\nimport json", "from bench_text import align", "import voicefeat", "# from engine_runtime import x"):
            with self.subTest(clean=snippet):
                self.assertEqual(engine_import_violations("x", snippet), [])

    def test_modules_import_only_each_other_and_the_standard_library(self):
        ours = {p.stem for p in BENCH_DIR.glob("*.py")}
        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        optional = {"kiwipiepy", "jsonschema"}  # imported inside try/except only
        for path in BENCH_DIR.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for module in modules:
                    top = module.split(".")[0]
                    with self.subTest(file=path.name, module=module):
                        self.assertTrue(top in ours or top in optional or top == "__future__" or stdlib is None or top in stdlib, top)


if __name__ == "__main__":
    unittest.main()
