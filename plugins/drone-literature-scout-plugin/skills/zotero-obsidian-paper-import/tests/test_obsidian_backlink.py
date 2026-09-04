import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from paper_import import update_source_line


class ObsidianBacklinkTests(unittest.TestCase):
    def test_replaces_only_zotero_pdf_link(self):
        line = "- **来源**：[下载网页链接](https://example.org/paper)，[DOI](https://doi.org/10.1234/x)。A- ^paper-x"
        updated = update_source_line(line, "ABC12345")
        self.assertIn("[下载网页链接](https://example.org/paper)", updated)
        self.assertIn("[DOI](https://doi.org/10.1234/x)", updated)
        self.assertIn("zotero://open-pdf/library/items/ABC12345", updated)

    def test_does_not_create_link_without_attachment_key(self):
        line = "- **来源**：[下载网页链接](https://example.org/paper)，[DOI](https://doi.org/10.1234/x)。A- ^paper-x"
        self.assertEqual(update_source_line(line, None), line)


if __name__ == "__main__":
    unittest.main()

