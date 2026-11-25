from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from publish.apply import apply_patch, commit_all
from publish.prepare import load_meta, load_patch, validate_meta
from scripts.common import HarnessError, render_prompt


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )


class PublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "config", "user.email", "test@local")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_apply_and_commit(self) -> None:
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        diff = git(self.repo, "diff", "--cached", "--binary").stdout
        git(self.repo, "reset", "--hard", "HEAD")
        patch = Path(self.tmp.name) / "patch.diff"
        patch.write_text(diff, encoding="utf-8")

        apply_patch(self.repo, patch)
        sha = commit_all(self.repo, "harness: test")
        self.assertEqual(len(sha), 40)
        self.assertEqual((self.repo / "README.md").read_text(encoding="utf-8"), "changed\n")

    def test_empty_patch_rejected(self) -> None:
        patch = Path(self.tmp.name) / "empty.diff"
        patch.write_text("", encoding="utf-8")
        with self.assertRaises(HarnessError):
            apply_patch(self.repo, patch)

    def test_meta_validation(self) -> None:
        artifact = Path(self.tmp.name) / "artifact"
        artifact.mkdir()
        meta = {
            "status": "success",
            "target": "sandbox",
            "issue": 7,
            "base_sha": "a" * 40,
            "route": "glm-5.3-flash-cloudflare",
        }
        (artifact / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (artifact / "patch.diff").write_text("diff\n", encoding="utf-8")
        loaded = load_meta(artifact)
        validate_meta(loaded, target="sandbox", issue=7)
        self.assertEqual(load_patch(artifact).name, "patch.diff")

        with self.assertRaises(HarnessError):
            validate_meta(loaded, target="core", issue=7)
        with self.assertRaises(HarnessError):
            validate_meta({**loaded, "status": "failed"}, target="sandbox", issue=7)

    def test_render_prompt(self) -> None:
        text = render_prompt("{{TITLE}}\n{{BODY}}", {"TITLE": "t", "BODY": "b"})
        self.assertEqual(text, "t\nb")


if __name__ == "__main__":
    unittest.main()
