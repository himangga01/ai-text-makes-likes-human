"""Super Sejong Engine v2 contracts (WP-0): schemas, fixtures, types, flags and the version file."""
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import sejong  # noqa: E402
from engine_runtime.sejong import config, io, types  # noqa: E402
from engine_runtime.sejong.config import Flags, family_mode, open_review_enabled, select_engine  # noqa: E402
from engine_runtime import super_sejong, workflow  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "sejong"
SCHEMAS = ROOT / "engine_runtime" / "sejong" / "schemas"
# The chunk text the plan-blog-medium fixture describes (5 sentences, one astral emoji).
BLOG_SOURCE = ("오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n"
               "현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n")
NO_EDIT_SOURCE = "회의는 오전 10시에 시작합니다. 자료는 미리 읽어 오세요.\n"
CHECKERS = {"plan": io.plan_problems, "check": io.check_problems, "response": io.response_problems}


def fixtures(kind):
    paths = sorted(FIXTURES.glob(f"{kind}-*.json"))
    assert paths, f"no {kind} fixtures"
    return [(path.name, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def codes_in_check(report):
    yield from report["hardFailures"]
    yield from report["shadowFailures"]
    for sentence in report["sentences"]:
        yield from sentence["codes"]
        yield from sentence["repairs"]
    for item in report["retry"]:
        for violation in item["violations"]:
            yield violation["code"]


class Fixtures(unittest.TestCase):
    def test_every_fixture_passes_schema_and_contract_checks(self):
        for kind, checker in CHECKERS.items():
            for name, data in fixtures(kind):
                with self.subTest(fixture=name):
                    self.assertEqual(checker(data), [])

    def test_plans_and_checks_round_trip_through_the_dataclasses_byte_for_byte(self):
        for kind, cls in (("plan", types.Plan), ("check", types.CheckReport)):
            for name, data in fixtures(kind):
                with self.subTest(fixture=name):
                    again = cls.from_json(data).to_json()
                    self.assertEqual(json.dumps(again, ensure_ascii=False), json.dumps(data, ensure_ascii=False))

    def test_plan_offsets_describe_the_source_text(self):
        for name, source in (("plan-blog-medium.json", BLOG_SOURCE), ("plan-no-edit.json", NO_EDIT_SOURCE)):
            plan = types.Plan.from_json(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
            with self.subTest(fixture=name):
                self.assertEqual(plan.chunk.source_sha256, hashlib.sha256(source.encode("utf-8")).hexdigest())
                self.assertEqual(plan.chunk.chars, len(source))
                units = source.encode("utf-16-le")
                for s in plan.sentences:
                    text = source[s.start:s.end]
                    self.assertEqual(units[2 * s.start_u16:2 * s.end_u16].decode("utf-16-le"), text)
                    self.assertTrue(text.strip() and text == text.strip())
                for fix in plan.deterministic:
                    self.assertEqual(source[fix.start:fix.end], fix.before)
                for span in plan.protected:
                    self.assertTrue(source[span.start:span.end].strip())
        # The emoji makes the UTF-16 offsets of the last sentence differ from the code-point offsets.
        last = types.Plan.from_json(json.loads((FIXTURES / "plan-blog-medium.json").read_text(encoding="utf-8"))).sentences[-1]
        self.assertEqual((last.start, last.end, last.start_u16, last.end_u16), (71, 95, 72, 96))

    def test_fixtures_carry_the_current_engine_version_and_schema(self):
        for name, data in fixtures("plan"):
            self.assertEqual(data["engine"], {"id": sejong.ENGINE_ID, "version": sejong.VERSION}, name)
            self.assertEqual(data["schema"], sejong.PLAN_SCHEMA, name)
        for name, data in fixtures("check"):
            self.assertEqual(data["schema"], sejong.CHECK_SCHEMA, name)
            self.assertEqual(list(data)[:5], ["gate", "hardFailures", "warningReasons", "policy", "shadowFailures"])

    def test_every_code_in_the_check_fixtures_is_lowercase(self):
        for name, data in fixtures("check"):
            for code in codes_in_check(data):
                self.assertTrue(types.is_code(code), f"{name}: {code}")


class Codes(unittest.TestCase):
    def test_code_regex(self):
        for good in ("voice_level", "a", "cta_force_weakened", "_", "x" * 60):
            self.assertTrue(types.is_code(good), good)
        for bad in ("", "Voice_level", "voice-level", "voice level", "voice1", "x" * 61, "voice_level\n",
                    "보이스", None, 3):
            self.assertFalse(types.is_code(bad), repr(bad))

    def test_schemas_use_the_same_code_pattern_as_the_typescript_parser(self):
        parser = (ROOT / "src" / "engine" / "python-engine.ts").read_text(encoding="utf-8")
        self.assertIn("/^[a-z_]{1,60}$/", parser)
        check = json.loads((SCHEMAS / "check.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(check["$defs"]["code"]["pattern"], "^[a-z_]{1,60}$")

    def test_uppercase_or_dashed_codes_are_rejected_everywhere(self):
        report = json.loads((FIXTURES / "check-retry.json").read_text(encoding="utf-8"))
        for mutate in (lambda r: r["shadowFailures"].append("VOICE_LEVEL"),
                       lambda r: r["hardFailures"].append("quote-altered"),
                       lambda r: r["sentences"][0]["repairs"].append("Voice_graft"),
                       lambda r: r["retry"][0]["violations"][0].update(code="voice level")):
            broken = copy.deepcopy(report)
            mutate(broken)
            self.assertTrue(io.check_problems(broken))

    def test_legacy_gate_policy_table_is_unchanged(self):
        for exit_code in range(4):
            for attempt in (1, 2):
                self.assertEqual(types.gate_policy(exit_code, attempt), workflow.decision(exit_code, attempt))


class ContractViolations(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((FIXTURES / "plan-blog-medium.json").read_text(encoding="utf-8"))

    def broken(self, mutate):
        data = copy.deepcopy(self.plan)
        mutate(data)
        return io.plan_problems(data)

    def test_schema_violations(self):
        cases = {
            "unknown root key": lambda p: p.update(extra=1),
            "missing key": lambda p: p.pop("seam"),
            "bad sentence id": lambda p: p["sentences"][0].update(id="s1"),
            "bad level": lambda p: p["sentences"][0]["voice"].update(level="haeyo"),
            "bool as int": lambda p: p["sentences"][0].update(start=True),
            "float offset": lambda p: p["sentences"][0].update(end=18.5),
            "bad sha": lambda p: p["chunk"].update(sourceSha256="ABC"),
            "boolean deterministic scope": lambda p: p["options"].update(deterministicFix=True),
            "bad genre": lambda p: p["options"].update(genre="news"),
            "force above 5": lambda p: p["ctaLedger"][0].update(force=6),
            "bad rule id": lambda p: p["findings"][0].update(rule="ssj-a01"),
            "duplicate rules": lambda p: p["requests"][0].update(rules=["SSJ-A01", "SSJ-A01"]),
            "share above 1": lambda p: p["profile"].update(share=1.5),
            "seam of three": lambda p: p["seam"].update(prev=[0, 0, 0]),
            "bad tier key": lambda p: p["stats"]["findingsByTier"].update(fix=1),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.assertTrue(self.broken(mutate))

    def test_cross_reference_violations(self):
        cases = {
            "needsModel disagrees": lambda p: p.update(needsModel=False),
            "openReview disagrees": lambda p: p["options"].update(openReview=False),
            "dangling finding": lambda p: p["sentences"][1]["findings"].append("F9"),
            "finding of another sentence": lambda p: p["findings"][0].update(sentence="S1"),
            "deterministic range": lambda p: p["deterministic"][0].update(end=49),
            "request rule without finding": lambda p: p["requests"][0]["rules"].append("SSJ-A02"),
            "two requests for one sentence": lambda p: p["requests"].append(dict(p["requests"][0], id="R2")),
            "overlapping sentences": lambda p: p["sentences"][1].update(start=10),
            "offset past chunk": lambda p: p["protected"][0].update(end=500),
            "duplicate finding id": lambda p: p["findings"].append(dict(p["findings"][0])),
            "cta not pointing back": lambda p: p["ctaLedger"][0].update(sentence="S4"),
            "chunk index above total": lambda p: p["chunk"].update(index=2),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.assertTrue(self.broken(mutate))

    def test_check_report_rules(self):
        retry = json.loads((FIXTURES / "check-retry.json").read_text(encoding="utf-8"))
        accept = json.loads((FIXTURES / "check-accept.json").read_text(encoding="utf-8"))
        cases = [
            (accept, lambda r: r.update(policy="retry")),
            (accept, lambda r: r["warningReasons"].update(codes=["P1_STYLE_TARGET"])),
            (accept, lambda r: r["hardFailures"].append("quote_altered")),
            (accept, lambda r: r.update(attempt=3)),
            (accept, lambda r: r["counts"].pop("voiceGrafts")),
            (accept, lambda r: r["counts"]["revertedByFamily"].update(style=1)),
            (retry, lambda r: r.update(attempt=2, policy="accept-with-warning")),
            (retry, lambda r: r["sentences"][1].update(status="accepted")),
            (retry, lambda r: r["retry"][0].update(violations=[])),
        ]
        for base, mutate in cases:
            broken = copy.deepcopy(base)
            mutate(broken)
            self.assertTrue(io.check_problems(broken))

    def test_response_rules(self):
        good = json.loads((FIXTURES / "response-replacements.json").read_text(encoding="utf-8"))
        for mutate in (lambda r: r["replacements"][0].update(id="X1"),
                       lambda r: r["replacements"][0].update(text=""),
                       lambda r: r["replacements"][0].update(extra="x"),
                       lambda r: r["replacements"][0].update(reason="x" * 61),
                       lambda r: r.pop("warnings"),
                       lambda r: r.update(edits=[])):
            broken = copy.deepcopy(good)
            mutate(broken)
            self.assertTrue(io.response_problems(broken))

    def test_both_response_schemas_are_identical(self):
        python = json.loads((SCHEMAS / "response.schema.json").read_text(encoding="utf-8"))
        typescript = json.loads((ROOT / "src/engine/sejong/response-schema.json").read_text(encoding="utf-8"))
        self.assertEqual(python, typescript)


class Validator(unittest.TestCase):
    def test_unsupported_keywords_fail_loudly(self):
        with self.assertRaises(io.SchemaError):
            io.validate("x", {"type": "string", "format": "email"})
        with self.assertRaises(io.SchemaError):
            io.validate(1, {"oneOf": [{"type": "integer"}]})

    def test_dollar_does_not_match_before_a_trailing_newline(self):
        self.assertEqual(io.validate("abc", {"pattern": "^[a-z]+$"}), [])
        self.assertTrue(io.validate("abc\n", {"pattern": "^[a-z]+$"}))

    def test_json_equality_separates_booleans_from_numbers(self):
        self.assertTrue(io.validate(True, {"enum": [0, 1]}))
        self.assertEqual(io.validate(1.0, {"const": 1}), [])
        self.assertEqual(io.validate([1, True], {"uniqueItems": True, "type": "array"}), [])

    def test_lengths_count_code_points(self):
        self.assertEqual(io.validate("😀", {"maxLength": 1}), [])

    def test_every_schema_only_uses_supported_keywords(self):
        for path in SCHEMAS.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            walk = [schema]
            while walk:
                node = walk.pop()
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in ("properties", "$defs"):
                            walk.extend(value.values())
                        elif key in ("items", "additionalProperties", "propertyNames") and isinstance(value, dict):
                            walk.append(value)
                        elif key == "anyOf":
                            walk.extend(value)
                    self.assertFalse(set(node) - io._KEYWORDS, f"{path.name}: {set(node) - io._KEYWORDS}")


class Files(unittest.TestCase):
    def test_text_round_trip_preserves_every_newline_form(self):
        text = "첫 줄\r\n둘째 줄\r셋째 줄\n마지막"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chunk.txt"
            io.write_text(path, text)
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))
            self.assertEqual(io.read_text(path), text)
            self.assertEqual(os.listdir(folder), ["chunk.txt"])

    def test_typed_plan_and_check_io(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = io.read_plan(FIXTURES / "plan-blog-medium.json")
            io.write_plan(Path(folder) / "plan-1.json", plan)
            self.assertEqual(io.read_plan(Path(folder) / "plan-1.json"), plan)
            report = io.read_check(FIXTURES / "check-retry.json")
            io.write_check(Path(folder) / "check-1-1.json", report)
            self.assertEqual(io.read_check(Path(folder) / "check-1-1.json"), report)
            plan.needs_model = False
            with self.assertRaises(io.ContractError):
                io.write_plan(Path(folder) / "bad.json", plan)
            self.assertFalse((Path(folder) / "bad.json").exists())

    def test_default_check_report_is_valid(self):
        report = types.CheckReport(gate={"exit_code": 0}, hard_failures=[], warning_reasons={"version": 1, "codes": []},
                                   policy="accept", shadow_failures=[])
        self.assertEqual(io.check_problems(report.to_json()), [])
        self.assertEqual(list(report.to_json())[:5], ["gate", "hardFailures", "warningReasons", "policy", "shadowFailures"])

    def test_optional_violation_fields_are_omitted_not_null(self):
        self.assertEqual(types.Violation("voice_level", detail="HAPSYO->HAEYO").to_json(),
                         {"code": "voice_level", "detail": "HAPSYO->HAEYO"})
        self.assertEqual(types.Violation.from_json({"code": "x", "detail": ""}).family, None)
        with self.assertRaises(ValueError):
            types.Violation.from_json({"code": "x", "detail": "", "Code": "y"})


class EngineVersion(unittest.TestCase):
    def test_version_file_format(self):
        raw = (ROOT / "engine_runtime" / "sejong" / "ENGINE_VERSION").read_text(encoding="utf-8")
        self.assertRegex(raw, r"\Aid=super-sejong\nversion=[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?\nschema=[1-9][0-9]*\n\Z")
        info = sejong.read_engine_version()
        self.assertEqual(info["id"], sejong.ENGINE_ID)
        self.assertEqual(info["version"], sejong.VERSION)
        self.assertEqual(sejong.PLAN_SCHEMA, f"sejong-plan/{info['schema']}")
        self.assertEqual(sejong.CHECK_SCHEMA, f"sejong-check/{info['schema']}")

    def test_malformed_version_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ENGINE_VERSION"
            for raw in ("version=2.0.0\n", "id=super-sejong\nversion=2.0\nschema=1\n",
                        "id=other\nversion=2.0.0\nschema=1\n", "id=super-sejong\nversion=2.0.0\nschema=1\nextra=1\n",
                        "id=super-sejong\nversion=02.0.0\nschema=1\n", "id=super-sejong\nversion=2.0.0\nschema=0\n"):
                path.write_text(raw, encoding="utf-8")
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    sejong.read_engine_version(path)

    def test_schema_ids_follow_the_version_file(self):
        for name, schema_id in (("plan", sejong.PLAN_SCHEMA), ("check", sejong.CHECK_SCHEMA)):
            schema = io.load_schema(name)
            self.assertEqual(schema["$id"], schema_id)
            self.assertEqual(schema["properties"]["schema"]["const"], schema_id)


class FlagsTable(unittest.TestCase):
    def test_defaults_keep_the_legacy_engine(self):
        flags = Flags.from_env({})
        self.assertEqual(flags, Flags())
        self.assertEqual((flags.engine, flags.mode, flags.gates, flags.v2_shadow, flags.fix_colloquial,
                          flags.deterministic_fix, flags.open_review, flags.genre_default, flags.worker, flags.kiwi,
                          flags.rejected),
                         ("legacy", "enforce", {}, False, False, "all", "medium", "general", False, "off", ()))
        self.assertEqual(select_engine({}), "legacy")

    def test_each_variable_accepts_exactly_its_documented_values(self):
        table = {
            "SUPER_SEJONG_ENGINE": ("engine", {"legacy": "legacy", "v2": "v2", " V2 ": "v2"}, "legacy"),
            "SUPER_SEJONG_MODE": ("mode", {"enforce": "enforce", "shadow": "shadow", "OFF": "off"}, "enforce"),
            "SUPER_SEJONG_V2_SHADOW": ("v2_shadow", {"0": False, "1": True}, False),
            "SUPER_SEJONG_FIX_COLLOQUIAL": ("fix_colloquial", {"0": False, "1": True}, False),
            "SUPER_SEJONG_DETERMINISTIC_FIX": ("deterministic_fix",
                                               {"all": "all", "edited-only": "edited-only", "off": "off"}, "all"),
            "SUPER_SEJONG_OPEN_REVIEW": ("open_review", {"medium": "medium", "strong": "strong", "always": "always",
                                                         "off": "off"}, "medium"),
            "SUPER_SEJONG_GENRE_DEFAULT": ("genre_default", {g: g for g in types.GENRES}, "general"),
            "SUPER_SEJONG_WORKER": ("worker", {"off": False, "on": True}, False),
        }
        for name, (attribute, valid, default) in table.items():
            for raw, expected in valid.items():
                with self.subTest(name=name, raw=raw):
                    flags = Flags.from_env({name: raw})
                    self.assertEqual(getattr(flags, attribute), expected)
                    self.assertEqual(flags.rejected, ())
            for raw in ("", "   "):
                self.assertEqual(getattr(Flags.from_env({name: raw}), attribute), default)
                self.assertEqual(Flags.from_env({name: raw}).rejected, ())
            for raw in ("true", "yes", "2", "v3", "edited_only", "legacy2"):
                with self.subTest(name=name, invalid=raw):
                    flags = Flags.from_env({name: raw})
                    self.assertEqual(getattr(flags, attribute), default)
                    self.assertEqual(flags.rejected, (name,))

    def test_mode_matches_the_v1_reader_under_legacy(self):
        for raw in (None, "", "enforce", "shadow", "off", " Shadow ", "bogus"):
            env = {} if raw is None else {"SUPER_SEJONG_MODE": raw}
            with self.subTest(raw=raw), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(Flags.from_env().mode, super_sejong.mode())

    def test_family_defaults_per_mode(self):
        expected = {
            "enforce": {"floor": "enforce", "runaway": "enforce", "meaning": "enforce", "voice": "enforce",
                        "cta": "enforce", "flow": "enforce", "clarity": "shadow", "norms": "enforce", "nli": "off"},
            "shadow": {"floor": "enforce", "runaway": "enforce", "meaning": "enforce", "voice": "shadow",
                       "cta": "shadow", "flow": "shadow", "clarity": "shadow", "norms": "shadow", "nli": "off"},
            "off": {"floor": "enforce", "runaway": "enforce", "meaning": "off", "voice": "off", "cta": "off",
                    "flow": "off", "clarity": "off", "norms": "off", "nli": "off"},
        }
        for mode, families in expected.items():
            flags = Flags.from_env({"SUPER_SEJONG_ENGINE": "v2", "SUPER_SEJONG_MODE": mode})
            self.assertEqual(set(families), set(types.FAMILIES))
            for family, family_expected in families.items():
                with self.subTest(mode=mode, family=family):
                    self.assertEqual(family_mode(flags, family), family_expected)
                    self.assertEqual(family_mode(flags, family.upper()), family_expected)

    def test_family_overrides(self):
        for family in config.OVERRIDABLE:
            for value in ("enforce", "shadow", "off"):
                for mode in ("enforce", "shadow", "off"):
                    env = {"SUPER_SEJONG_MODE": mode, f"SUPER_SEJONG_GATE_{family.upper()}": value}
                    flags = Flags.from_env(env)
                    expected = "shadow" if (family, value) == ("nli", "enforce") else value
                    with self.subTest(family=family, value=value, mode=mode):
                        self.assertEqual(family_mode(flags, family), expected)
                        self.assertEqual(flags.rejected, (f"SUPER_SEJONG_GATE_{family.upper()}",)
                                         if expected != value else ())
        flags = Flags.from_env({"SUPER_SEJONG_GATE_VOICE": "loud"})
        self.assertEqual((family_mode(flags, "voice"), flags.rejected), ("enforce", ("SUPER_SEJONG_GATE_VOICE",)))

    def test_nli_can_never_enforce(self):
        for mode in ("enforce", "shadow", "off"):
            for raw in (None, "enforce", "ENFORCE", "shadow", "off", "bogus"):
                env = {"SUPER_SEJONG_MODE": mode}
                if raw is not None:
                    env["SUPER_SEJONG_GATE_NLI"] = raw
                self.assertNotEqual(family_mode(Flags.from_env(env), "nli"), "enforce", env)
        self.assertEqual(family_mode(Flags.from_env({"SUPER_SEJONG_GATE_NLI": "enforce"}), "nli"), "shadow")

    def test_floor_and_runaway_cannot_be_disabled(self):
        flags = Flags.from_env({"SUPER_SEJONG_MODE": "off", "SUPER_SEJONG_GATE_FLOOR": "off",
                                "SUPER_SEJONG_GATE_RUNAWAY": "off"})
        self.assertEqual((family_mode(flags, "floor"), family_mode(flags, "runaway")), ("enforce", "enforce"))
        with self.assertRaises(ValueError):
            family_mode(flags, "style")

    def test_kiwi_runs_only_inside_the_worker(self):
        self.assertEqual(Flags.from_env({"SUPER_SEJONG_KIWI": "worker", "SUPER_SEJONG_WORKER": "on"}).kiwi, "worker")
        flags = Flags.from_env({"SUPER_SEJONG_KIWI": "worker"})
        self.assertEqual((flags.kiwi, flags.rejected), ("off", ("SUPER_SEJONG_KIWI",)))

    def test_open_review_by_strength(self):
        expected = {
            "medium": {"normal": False, "medium": True, "strong": True, "very-strong": True},
            "strong": {"normal": False, "medium": False, "strong": True, "very-strong": True},
            "always": {"normal": True, "medium": True, "strong": True, "very-strong": True},
            "off": {"normal": False, "medium": False, "strong": False, "very-strong": False},
        }
        for setting, strengths in expected.items():
            for strength, enabled in strengths.items():
                flags = Flags.from_env({"SUPER_SEJONG_OPEN_REVIEW": setting})
                self.assertEqual(open_review_enabled(flags, strength), enabled, (setting, strength))
                off = Flags.from_env({"SUPER_SEJONG_OPEN_REVIEW": setting, "SUPER_SEJONG_MODE": "off"})
                self.assertFalse(open_review_enabled(off, strength))
        with self.assertRaises(ValueError):
            open_review_enabled(Flags(), "extreme")
        self.assertFalse(config.suggest_requests_enabled(Flags.from_env({"SUPER_SEJONG_MODE": "off"})))

    def test_rejected_lists_names_in_a_stable_order_and_never_values(self):
        flags = Flags.from_env({"SUPER_SEJONG_KIWI": "worker", "SUPER_SEJONG_GATE_NLI": "enforce",
                                "SUPER_SEJONG_ENGINE": "secret-value", "SUPER_SEJONG_GATE_CTA": "x"})
        self.assertEqual(flags.rejected, ("SUPER_SEJONG_ENGINE", "SUPER_SEJONG_GATE_CTA", "SUPER_SEJONG_GATE_NLI",
                                          "SUPER_SEJONG_KIWI"))
        self.assertNotIn("secret-value", repr(flags))

    def test_reads_os_environ_by_default(self):
        with mock.patch.dict(os.environ, {"SUPER_SEJONG_ENGINE": "v2"}, clear=True):
            self.assertEqual(Flags.from_env().engine, "v2")
            self.assertEqual(select_engine(), "v2")


# Product files a work package has wired to v2 on purpose; each may only read the engine switch and the
# version file, and legacy stays the default. WP-14: preflight checks the ENGINE_VERSION of the selected engine.
# WP-10: sejong_cli.py is the v2 CLI itself; workflow.py imports sejong.verify only inside verify_v2(), which
# runs when SUPER_SEJONG_ENGINE=v2 (test_sejong_pipeline.WorkflowDispatch pins both branches).
WIRED = {"src/process/preflight.ts", "engine_runtime/sejong_cli.py", "engine_runtime/workflow.py"}
# WP-11b: the engine switch (config.ts reads SUPER_SEJONG_ENGINE, create-runtime.ts builds SejongEngine only for v2)
# and the v2 strength descriptions (rewrite-policy.ts serves them only when v2 is selected).
WIRED |= {"src/config.ts", "src/runtime/create-runtime.ts", "src/engine/rewrite-policy.ts"}
# WP-12: the Office engine picks the plan-driven prompt when SUPER_SEJONG_ENGINE=v2 (selectEngine) and builds it
# with sejong/document-prompt.ts; the Python half (engine_runtime/documents/) imports sejong lazily, only under v2.
WIRED |= {"src/documents/document-engine.ts"}
# WP-17: humanize-engine.ts holds the legacy shadow hook (inert unless SUPER_SEJONG_V2_SHADOW=1; it only reads
# the delivered text) and create-runtime.ts hands it the v2 adapter (tests/unit/sejong-shadow-*.test.ts pin the hook).
WIRED |= {"src/engine/humanize-engine.ts", "src/runtime/create-runtime.ts"}

# WP-13: skill_gateway.py runs v2 in process when SUPER_SEJONG_ENGINE=v2; it imports sejong lazily, only then
# (test_sejong_skill_path pins the switch, the recorded engine id and version, and the legacy default).
WIRED |= {"engine_runtime/skill_gateway.py"}


class NoRuntimeWiring(unittest.TestCase):
    def test_legacy_modules_do_not_import_the_v2_package(self):
        for path in list((ROOT / "engine_runtime").glob("*.py")) + list((ROOT / "src").rglob("*.ts")):
            if "sejong" in path.parts or path.relative_to(ROOT).as_posix() in WIRED:
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(re.search(r"(from|import)\s+[\w.]*\bsejong\b(?!_)|engine/sejong/|\./sejong/", text))


if __name__ == "__main__":
    unittest.main()
