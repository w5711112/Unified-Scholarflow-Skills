import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from merge_duplicates import merged_parent_data


class MergeDuplicateTests(unittest.TestCase):
    def test_authoritative_metadata_overwrites_incomplete_keep_and_unions_links(self):
        keep = {
            "key": "PDFKEEP",
            "version": 12,
            "title": "Paper",
            "DOI": "10.1234/paper",
            "creators": [],
            "date": "",
            "publicationTitle": "",
            "tags": [{"tag": "obsidian-paper-13"}],
            "collections": ["COLLECTION_KEEP"],
        }
        source = {
            "key": "METADATA",
            "version": 9,
            "title": "Paper（Journal, 2025）",
            "DOI": "10.1234/PAPER",
            "creators": [{"firstName": "A", "lastName": "Author", "creatorType": "author"}],
            "date": "2025-03",
            "publicationTitle": "Journal",
            "publisher": "Publisher",
            "tags": [{"tag": "source-tag"}],
            "collections": ["COLLECTION_SOURCE"],
        }
        merged = merged_parent_data(keep, source)
        self.assertEqual(merged["title"], source["title"])
        self.assertEqual(merged["DOI"], "10.1234/PAPER")
        self.assertEqual(merged["creators"], source["creators"])
        self.assertEqual(merged["date"], source["date"])
        self.assertEqual(merged["publicationTitle"], source["publicationTitle"])
        self.assertEqual({tag["tag"] for tag in merged["tags"]}, {"obsidian-paper-13", "source-tag"})
        self.assertEqual(set(merged["collections"]), {"COLLECTION_KEEP", "COLLECTION_SOURCE"})
        self.assertNotIn("key", merged)
        self.assertNotIn("version", merged)


if __name__ == "__main__":
    unittest.main()
