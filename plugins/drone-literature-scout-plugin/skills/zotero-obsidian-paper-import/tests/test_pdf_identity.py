import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from safe_download import pdf_title_matches


class PdfIdentityTests(unittest.TestCase):
    def test_rejects_a_valid_but_wrong_pdf(self):
        self.assertTrue(pdf_title_matches("EGO-Planner: An ESDF-Free Gradient-Based Local Planner for Quadrotors", "EGO-Planner An ESDF-Free Gradient-Based Local Planner for Quadrotors"))
        self.assertFalse(pdf_title_matches("EGO-Planner: An ESDF-Free Gradient-Based Local Planner for Quadrotors", "Unrelated Paper about Quadrotor Control"))


if __name__ == "__main__":
    unittest.main()

