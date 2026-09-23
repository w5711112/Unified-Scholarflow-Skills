from __future__ import annotations

import unittest
from pathlib import Path


SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-note-style"
    / "SKILL.md"
)


class ObsidianVisualRuntimeContractTests(unittest.TestCase):
    def test_windows_write_and_visual_review_failures_have_fixed_recovery(self):
        text = SKILL.read_text(encoding="utf-8")
        required = (
            "$ErrorActionPreference = 'Stop'",
            "New-Item -LiteralPath",
            "[System.IO.Directory]::CreateDirectory",
            "Copy-Item -LiteralPath",
            "源文件与目标文件的 SHA-256",
            "`--unidiff-zero`",
            "`view_image`",
            "`node_repl`",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
