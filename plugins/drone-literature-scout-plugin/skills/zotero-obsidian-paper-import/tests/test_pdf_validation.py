import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from paper_import import is_valid_pdf_bytes


class PdfValidationTests(unittest.TestCase):
    def test_accepts_pdf_magic_and_rejects_html(self):
        self.assertTrue(is_valid_pdf_bytes(b"%PDF-1.7\n%" + b"x" * 512))
        self.assertFalse(is_valid_pdf_bytes(b"<!doctype html>" + b"x" * 512))
        self.assertFalse(is_valid_pdf_bytes(b"%PDF-1.7"))


if __name__ == "__main__":
    unittest.main()

