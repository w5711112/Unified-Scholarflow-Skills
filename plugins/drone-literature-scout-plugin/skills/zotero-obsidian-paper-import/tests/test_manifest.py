import sys
from pathlib import Path
import unittest
import os

ROOT = Path(os.environ.get('PAPER_IMPORT_TEST_PROJECT_ROOT', Path(__file__).resolve().parents[5]))
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from paper_import import normalize_doi, parse_paper_index


class ManifestTests(unittest.TestCase):
    def test_extracts_contiguous_records_12_to_102(self):
        papers = parse_paper_index(ROOT / "01-核心论文精读.md", 12, 102)
        self.assertEqual(len(papers), 91)
        self.assertEqual(papers[0]["number"], 12)
        self.assertIn("EGO-Planner", papers[0]["title"])
        self.assertEqual(papers[-1]["number"], 102)

    def test_normalizes_doi_without_guessing(self):
        self.assertEqual(normalize_doi(" https://doi.org/10.1109/LRA.2021.3047728. "), "10.1109/lra.2021.3047728")
        self.assertIsNone(normalize_doi("Paper ID 65"))


if __name__ == "__main__":
    unittest.main()

