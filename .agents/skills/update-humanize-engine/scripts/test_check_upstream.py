"""Offline behavioral checks using temporary Git repositories."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_upstream import inspect


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return result.stdout.strip()


def commit(root: Path) -> str:
    git(root, "add", ".")
    git(root, "-c", "user.name=Skill Fixture", "-c",
        "user.email=skill-test@example.invalid", "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


class UpstreamChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="humanize-skill-test-")
        self.root = Path(self.temporary.name).resolve()
        self.upstream = self.root / "fork with spaces"
        self.project = self.root / "portal with spaces"
        self.upstream.mkdir()
        self.project.mkdir()
        for directory in (self.upstream, self.project):
            git(directory, "init", "-q", "-b", "main")
        (self.upstream / "rules.txt").write_text("initial rules", encoding="utf-8")
        self.pin = commit(self.upstream)
        self.vendor = self.project / "vendor/humanize-engine"
        self.vendor.mkdir(parents=True)
        (self.project / "scripts").mkdir()
        (self.project / "scripts/sync-engine.ps1").write_text("# fixture", encoding="utf-8")
        (self.project / "package.json").write_text(
            json.dumps({"name": "ai-text-makes-likes-human"}), encoding="utf-8"
        )
        self.marker = self.vendor / "ENGINE_VERSION"
        self.marker.write_text(f"version=2.3.2\ncommit={self.pin}\n", encoding="utf-8")
        (self.vendor / "UPSTREAM.md").write_text(
            f"Source: {self.upstream.as_uri()}\n", encoding="utf-8"
        )
        self.project_head = commit(self.project)

    def tearDown(self):
        expected_parent = Path(tempfile.gettempdir()).resolve()
        if self.root.parent != expected_parent or not self.root.name.startswith("humanize-skill-test-"):
            raise RuntimeError("Unexpected fixture cleanup path")
        self.temporary.cleanup()

    def check(self, ref="HEAD"):
        return inspect(self.project, self.upstream.as_uri(), ref, self.upstream)

    def test_unchanged_remote_is_noop(self):
        result = self.check()
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(result["resolved_ref"], "refs/heads/main")
        self.assertFalse(result["worktree_dirty"])
        self.assertEqual(git(self.project, "rev-parse", "HEAD"), self.project_head)
        self.assertFalse((self.project / ".git/FETCH_HEAD").exists())

    def test_new_commit_with_same_version_is_detected_without_mutation(self):
        original_marker = self.marker.read_bytes()
        (self.upstream / "rules.txt").write_text("updated rules", encoding="utf-8")
        newest = commit(self.upstream)
        result = self.check()
        self.assertEqual(result["status"], "update_available")
        self.assertEqual(result["pinned_version"], "2.3.2")
        self.assertEqual(result["latest_commit"], newest)
        self.assertEqual(self.marker.read_bytes(), original_marker)
        self.assertEqual(git(self.project, "status", "--porcelain"), "")
        self.assertFalse((self.project / ".git/FETCH_HEAD").exists())

    def test_source_migration_is_distinct_from_code_update(self):
        (self.vendor / "UPSTREAM.md").write_text(
            "Source: https://github.com/epoko77-ai/im-not-ai\n", encoding="utf-8"
        )
        result = self.check()
        self.assertEqual(result["status"], "provenance_update_required")
        self.assertTrue(result["source_migration_required"])
        self.assertFalse(result["update_available"])

    def test_dirty_files_survive_inspection(self):
        note = self.project / "unfinished.txt"
        note.write_bytes(b"local work must remain")
        before = git(self.project, "status", "--porcelain")
        self.assertTrue(self.check()["worktree_dirty"])
        self.assertEqual(note.read_bytes(), b"local work must remain")
        self.assertEqual(git(self.project, "status", "--porcelain"), before)

    def test_explicit_branch_and_missing_branch(self):
        git(self.upstream, "branch", "preview")
        self.assertEqual(self.check("refs/heads/preview")["latest_commit"], self.pin)
        with self.assertRaises(RuntimeError):
            self.check("refs/heads/nonexistent")

    def test_malformed_pin_is_not_reported_as_current(self):
        self.marker.write_text("version=2.3.2\ncommit=bad\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_service_and_ref_patterns_are_rejected(self):
        with self.assertRaises(ValueError):
            self.check("refs/heads/*")
        (self.project / "package.json").write_text('{"name":"unrelated"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.check()

    def test_different_hash_without_history_is_not_an_upgrade(self):
        (self.upstream / "rules.txt").write_text("updated", encoding="utf-8")
        commit(self.upstream)
        result = inspect(self.project, self.upstream.as_uri())
        self.assertEqual(result["status"], "history_required")
        self.assertTrue(result["commit_difference"])
        self.assertFalse(result["update_available"])

    def test_old_remote_branch_is_identified_as_a_downgrade(self):
        git(self.upstream, "branch", "lagging", self.pin)
        (self.upstream / "rules.txt").write_text("new rules", encoding="utf-8")
        newest = commit(self.upstream)
        self.marker.write_text(f"version=2.3.2\ncommit={newest}\n", encoding="utf-8")
        result = self.check("refs/heads/lagging")
        self.assertEqual(result["status"], "upstream_behind")
        self.assertEqual(result["behind_commits"], 1)
        self.assertFalse(result["update_available"])

    def test_missing_base_cannot_be_assumed_to_be_an_upgrade(self):
        self.marker.write_text("version=2.3.2\ncommit=" + "0" * 40 + "\n", encoding="utf-8")
        result = self.check()
        self.assertEqual(result["status"], "history_required")
        self.assertEqual(result["history_reason"], "pinned_commit_missing")
        self.assertFalse(result["update_available"])

    def test_shallow_history_is_not_reported_as_divergence(self):
        (self.upstream / "rules.txt").write_text("new rules", encoding="utf-8")
        newest = commit(self.upstream)
        (self.upstream / ".git/shallow").write_text(newest + "\n", encoding="ascii")
        result = self.check()
        self.assertEqual(result["status"], "history_required")
        self.assertEqual(result["history_reason"], "incomplete_shallow_history")
        self.assertFalse(result["update_available"])

    def test_divergent_history_needs_review(self):
        (self.upstream / "rules.txt").write_text("main change", encoding="utf-8")
        newest = commit(self.upstream)
        self.marker.write_text(f"version=2.3.2\ncommit={newest}\n", encoding="utf-8")
        tree = git(self.upstream, "rev-parse", self.pin + "^{tree}")
        side = git(self.upstream, "-c", "user.name=Skill Fixture", "-c", "user.email=skill-test@example.invalid", "commit-tree", tree, "-p", self.pin, "-m", "side branch")
        git(self.upstream, "update-ref", "refs/heads/side", side)
        result = self.check("refs/heads/side")
        self.assertEqual(result["status"], "history_diverged")
        self.assertEqual((result["behind_commits"], result["ahead_commits"]), (1, 1))
        self.assertFalse(result["update_available"])


if __name__ == "__main__":
    unittest.main()
