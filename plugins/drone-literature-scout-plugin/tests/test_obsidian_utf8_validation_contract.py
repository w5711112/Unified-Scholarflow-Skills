from __future__ import annotations

import unittest
from pathlib import Path


SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-note-style"
    / "SKILL.md"
)


class ObsidianUtf8ValidationContractTests(unittest.TestCase):
    def test_chinese_skill_validation_forces_utf8_instead_of_locale_default(self):
        text = SKILL.read_text(encoding="utf-8")
        for phrase in (
            "quick_validate.py",
            "python -X utf8",
            "UnicodeDecodeError",
            "GBK",
            "不能改写成 ANSI",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
