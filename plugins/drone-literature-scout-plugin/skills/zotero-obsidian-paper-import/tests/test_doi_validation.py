import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from paper_import import accept_doi_candidate


class DoiValidationTests(unittest.TestCase):
    def test_accepts_exact_candidate(self):
        candidate = {"DOI": "10.1234/example", "title": "A Safe Planner", "author": "Kim", "venue": "RA-L", "year": "2025"}
        target = {"title": "A Safe Planner", "first_author": "Kim", "venue": "RA-L", "year": "2025"}
        self.assertTrue(accept_doi_candidate(candidate, target))

    def test_rejects_title_or_author_conflict(self):
        candidate = {"DOI": "10.1234/example", "title": "A Different Planner", "author": "Kim", "venue": "RA-L", "year": "2025"}
        target = {"title": "A Safe Planner", "first_author": "Lee", "venue": "RA-L", "year": "2025"}
        self.assertFalse(accept_doi_candidate(candidate, target))


if __name__ == "__main__":
    unittest.main()

