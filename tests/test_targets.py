from __future__ import annotations

import unittest
from pathlib import Path

from guard.check import load_rules
from scripts.common import TARGETS_DIR, load_target, matches_any

ROOT = Path(__file__).resolve().parents[1]


class TargetsTest(unittest.TestCase):
    def test_targets_are_valid(self) -> None:
        for path in TARGETS_DIR.glob("*.yml"):
            manifest = load_target(path.stem)
            self.assertIn("/", manifest["repo"])
            self.assertTrue(manifest["branch"])
            for check in manifest["verify"]:
                self.assertTrue(check["name"])
                self.assertTrue(check["run"])

    def test_sandbox_manifest(self) -> None:
        manifest = load_target("sandbox")
        self.assertEqual(manifest["repo"], "beassaf01/harness-sandbox")
        self.assertFalse(manifest["require_native_ci"])

    def test_core_kernel_paths(self) -> None:
        manifest = load_target("core")
        self.assertIn("guard/", manifest["kernel_paths"])
        self.assertIn(".github/", manifest["kernel_paths"])
        self.assertTrue(manifest["require_native_ci"])

    def test_matches_any(self) -> None:
        self.assertTrue(matches_any(".env.local", [".env*"]))
        self.assertTrue(matches_any("tests/test_x.py", ["tests/**"]))
        self.assertTrue(matches_any("deep/tests/test_x.py", ["test_*.py"]))
        self.assertFalse(matches_any("README.md", ["tests/**"]))

    def test_guard_rules(self) -> None:
        rules = load_rules(ROOT / "guard" / "rules.yml")
        self.assertIn(".env*", rules["deny_paths"])
        self.assertIn("tests/**", rules["protected_tests"])
        self.assertEqual(rules["limits"]["max_files"], 300)


if __name__ == "__main__":
    unittest.main()
