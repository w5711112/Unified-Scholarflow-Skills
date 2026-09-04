import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from paper_import import read_zotero_items


class ZoteroPaginationTests(unittest.TestCase):
    def test_reads_all_zotero_pages(self):
        first_page = [{"key": str(i)} for i in range(100)]
        second_page = [{"key": str(i)} for i in range(100, 123)]

        with patch(
            "paper_import.fetch_json",
            side_effect=[first_page, second_page],
        ) as fetch:
            items = read_zotero_items()

        self.assertEqual(len(items), 123)
        self.assertEqual(items[-1]["key"], "122")
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("start=100", fetch.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()

