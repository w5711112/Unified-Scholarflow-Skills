import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus_tools import (  # noqa: E402
    audit_record,
    deduplicate_records,
    is_official_record_url,
    is_reviewed_fulltext_url,
    merge_records,
    parse_csv_rows,
    parse_markdown_rows,
)
from clean_main_csv import strict_audit  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"
WHITELIST = {"ICRA", "RAL", "IROS", "TRO"}


class CorpusToolsTests(unittest.TestCase):
    def test_merge_deduplicates_title_url_and_doi(self):
        existing = parse_csv_rows(FIXTURES / "sample_unified.csv")
        incoming = parse_markdown_rows(FIXTURES / "sample_total.md")

        merged, decisions = merge_records(existing, incoming)

        self.assertEqual(len(merged), 3)
        self.assertEqual(sum(d["decision"] == "duplicate" for d in decisions), 2)
        self.assertIn("New Unique Paper", {row["title"] for row in merged})

    def test_audit_rejects_arxiv_only_and_unknown_venue(self):
        arxiv = audit_record(
            {"source": "arXiv", "url": "https://arxiv.org/abs/1", "title": "Paper"},
            WHITELIST,
        )
        unknown = audit_record(
            {"source": "IEEE", "url": "https://ieeexplore.ieee.org/document/1", "title": "Paper"},
            WHITELIST,
        )

        self.assertEqual(arxiv["status"], "reject")
        self.assertEqual(unknown["status"], "needs_verification")

    def test_parse_csv_preserves_commas_inside_abstract(self):
        rows = parse_csv_rows(FIXTURES / "sample_unified.csv")
        self.assertIn("comma", rows[0]["abstract"])

    def test_parse_markdown_keeps_official_url_and_numeric_citation_separate(self):
        rows = parse_markdown_rows(FIXTURES / "sample_total.md")
        self.assertEqual(rows[0]["url"], "https://doi.org/10.1000/accepted")
        self.assertEqual(rows[0]["citation"], "5")

    def test_deduplicate_records_keeps_richer_official_record(self):
        records = [
            {
                "title": "Same Paper",
                "source": "ICRA",
                "url": "https://arxiv.org/abs/2601.00001",
                "abstract": "",
                "citation": "2",
            },
            {
                "title": "Same Paper",
                "source": "ICRA",
                "url": "https://doi.org/10.1109/IROS.2026.1234567",
                "abstract": "A complete abstract.",
                "citation": "5",
            },
        ]
        clean, decisions = deduplicate_records(records)

        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["url"], "https://doi.org/10.1109/IROS.2026.1234567")
        self.assertEqual(clean[0]["abstract"], "A complete abstract.")
        self.assertEqual(decisions[1]["decision"], "duplicate")

    def test_open_fulltext_url_accepts_arxiv_copy_but_record_url_policy_stays_strict(self):
        self.assertTrue(is_reviewed_fulltext_url("https://arxiv.org/pdf/2503.00496"))
        self.assertFalse(is_official_record_url("https://arxiv.org/pdf/2503.00496"))

    def test_official_record_url_accepts_doi_and_publisher_hosts(self):
        self.assertTrue(is_official_record_url("https://doi.org/10.1109/LRA.2026.3674011"))
        self.assertTrue(is_official_record_url("https://openaccess.thecvf.com/content/CVPR2026/paper.html"))
        self.assertFalse(is_official_record_url("https://arxiv.org/abs/2601.00001"))

    def test_strict_audit_rejects_summary_instead_of_complete_original_abstract(self):
        record = {
            "title": "Verified Paper",
            "source": "ICRA",
            "venue_time": "2025",
            "url": "https://doi.org/10.1109/ICRA.2025.1234567",
            "abstract": "A brief assistant summary.",
            "citation": "0",
            "lab_group": "",
        }
        decision = strict_audit(record)
        self.assertEqual(decision["status"], "reject")
        self.assertIn("complete original abstract", decision["reason"])


if __name__ == "__main__":
    unittest.main()
