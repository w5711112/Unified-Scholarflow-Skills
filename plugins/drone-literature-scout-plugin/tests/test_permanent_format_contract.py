import csv
import sys
import unittest
from pathlib import Path
from test_support import writable_test_directory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus_tools import CSV_FIELDS, validate_record_integrity, validate_csv_file  # noqa: E402
from generate_core_docs import generate_analysis, generate_summary  # noqa: E402


class PermanentFormatContractTests(unittest.TestCase):
    def test_record_integrity_rejects_question_placeholders_and_date_field_shift(self):
        row = {field: "" for field in CSV_FIELDS}
        row.update({
            "title": "A paper",
            "source": "RAL",
            "url": "https://doi.org/10.1109/LRA.2026.1234567",
            "abstract": "A" * 300,
            "abstract_source_url": "https://doi.org/10.1109/LRA.2026.1234567",
            "method_evidence": "????",
            "experiment_evidence": "2026-07-14",
        })
        errors = validate_record_integrity(row)
        self.assertTrue(any("placeholder" in item for item in errors))
        self.assertTrue(any("verification_date" in item for item in errors))

    def test_csv_file_requires_exact_schema_and_utf8_evidence(self):
        with writable_test_directory() as temp:
            path = Path(temp) / "bad.csv"
            path.write_text("title,venue_time\nA,2026\n", encoding="utf-8")
            errors = validate_csv_file(path)
            self.assertTrue(any("15" in item for item in errors))

    def test_generated_markdown_uses_chinese_template_headings(self):
        rows = [{
            "title": "A paper?",
            "venue_time": "2026",
            "source": "RAL",
            "abstract": "A" * 300,
            "url": "https://doi.org/10.1109/LRA.2026.1234567",
            "abstract_source_url": "https://doi.org/10.1109/LRA.2026.1234567",
            "fulltext_status": "abstract_only",
            "fulltext_url": "",
            "method_evidence": "",
            "compute_evidence": "",
            "experiment_evidence": "",
        }]
        summary = generate_summary(rows, "2026-07-14")
        analysis = generate_analysis(rows, "2026-07-14")
        for text in (summary, analysis):
            self.assertNotIn("Strict search cycle log", text)
            self.assertNotIn("This-cycle evidence table", text)
            self.assertNotIn("Scheme A preference gates", text)
            self.assertNotIn("Isaac Lab minimum viable route", text)
            self.assertNotIn("????", text)
        self.assertIn("本轮严格检索记录", summary)
        self.assertIn("方案 A 偏好硬门槛", analysis)


if __name__ == "__main__":
    unittest.main()
