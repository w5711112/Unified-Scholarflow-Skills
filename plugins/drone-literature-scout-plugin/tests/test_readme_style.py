import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[3]


class ReadmeStyleContractTests(unittest.TestCase):
    README_PATHS = (
        WORKSPACE / "skill-with-plugin" / "README.md",
        WORKSPACE / "skill-with-plugin" / "README.md",
        WORKSPACE / "skill-with-plugin" / "drone-literature-scout-plugin" / "README.md",
    )

    def test_active_readmes_use_obsidian_note_style_structure(self):
        for path in self.README_PATHS:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("\u5148\u7ed9\u7ed3\u8bba", text, path)
            self.assertIn("\u4f7f\u7528\u6211\u7684 Obsidian \u8bed\u8a00\u98ce\u683c", text, path)
            self.assertIn("obsidian-note-style", text, path)
            self.assertRegex(text, r"## .*\u8fb9\u754c", path)
            self.assertTrue(
                "## \u9a8c\u8bc1" in text or "## \u4ea4\u4ed8\u524d\u68c0\u67e5" in text,
                path,
            )

    def test_deleted_archive_is_not_referenced_by_active_readmes(self):
        for path in self.README_PATHS:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u5386\u53f2\u5f52\u6863", text, path)


if __name__ == "__main__":
    unittest.main()


