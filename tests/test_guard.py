from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from guard.check import check, load_rules

ROOT = Path(__file__).resolve().parents[1]
RULES = load_rules(ROOT / "guard" / "rules.yml")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )


class GuardTest(unittest.TestCase):
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

    def stage(self) -> tuple[Path, int]:
        git(self.repo, "add", "-A")
        diff = git(self.repo, "diff", "--cached", "--binary").stdout
        patch = Path(self.tmp.name) / "patch.diff"
        patch.write_text(diff, encoding="utf-8")
        return patch, patch.stat().st_size

    def run_guard(self, *, target: str = "sandbox", labels: set[str] | None = None):
        patch, size = self.stage()
        return check(
            self.repo,
            target=target,
            labels=labels or set(),
            rules=RULES,
            patch_bytes=size,
            kernel_paths=["guard/", "verify/", ".github/"],
            use_gitleaks=False,
        )

    def test_normal_change_ok(self) -> None:
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        report = self.run_guard()
        self.assertTrue(report["ok"], report["violations"])

    def test_env_file_denied(self) -> None:
        (self.repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
        report = self.run_guard()
        self.assertFalse(report["ok"])
        self.assertTrue(any(".env" in v for v in report["violations"]))

    def test_tests_require_label(self) -> None:
        tests = self.repo / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
        report = self.run_guard()
        self.assertFalse(report["ok"])
        report = self.run_guard(labels={"allow-tests"})
        self.assertTrue(report["ok"], report["violations"])

    def test_core_kernel_requires_approval(self) -> None:
        path = self.repo / "guard"
        path.mkdir()
        (path / "rules.yml").write_text("deny_paths: []\n", encoding="utf-8")
        report = self.run_guard(target="core")
        self.assertTrue(report["ok"], report["violations"])
        self.assertTrue(report["requires_approval"])
        self.assertIn("guard/rules.yml", report["approval_paths"])

    def test_symlink_denied(self) -> None:
        os.symlink("README.md", self.repo / "link")
        report = self.run_guard()
        self.assertFalse(report["ok"])
        self.assertTrue(any("symlink" in v for v in report["violations"]))

    def test_binary_denied(self) -> None:
        (self.repo / "blob.bin").write_bytes(b"\x00\x01\x02")
        report = self.run_guard()
        self.assertFalse(report["ok"])
        self.assertTrue(any("binary" in v for v in report["violations"]))

    def test_dependency_requires_label(self) -> None:
        (self.repo / "requirements.txt").write_text("requests\n", encoding="utf-8")
        report = self.run_guard()
        self.assertFalse(report["ok"])
        report = self.run_guard(labels={"allow-deps"})
        self.assertTrue(report["ok"], report["violations"])

    def test_text_rename_is_not_binary(self) -> None:
        git(self.repo, "mv", "README.md", "README2.md")
        report = self.run_guard()
        self.assertTrue(report["ok"], report["violations"])


if __name__ == "__main__":
    unittest.main()
