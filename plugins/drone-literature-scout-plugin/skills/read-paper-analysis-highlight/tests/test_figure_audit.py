from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_reading_ledger import LedgerError, validate_ledger  # noqa: E402


def valid_figure_audit(page: int = 1) -> dict:
    return {
        "figure_id": "Fig. 1",
        "pdf_page": page,
        "caption_read": True,
        "body_references": [
            "Section III refers to the training/deployment split."
        ],
        "panels": ["single-panel pipeline"],
        "visual_encodings": [
            "green=ground truth",
            "blue=deployment observation",
        ],
        "axes": "not_present",
        "legends": ["training", "deployment", "forward", "backward"],
        "modules": ["depth encoder", "GRU", "MLP", "HOCBF filter", "PX4"],
        "arrows_and_flow": ["actor output -> HOCBF -> PX4"],
        "inputs": ["depth image", "proprioceptive state"],
        "outputs": ["normalized thrust", "attitude references"],
        "observed_claims": [
            "The safety filter is deployment-side, not actor training."
        ],
        "text_formula_table_consistency": [
            "The caption and method text agree on the actor output."
        ],
        "limitations_or_anomalies": [
            "The figure does not state the end-to-end sensing frequency."
        ],
        "annotation_regions": ["caption", "HOCBF-to-PX4 flow"],
        "unresolved": [],
    }


def page_entry(*, figures: str = "checked", captions: str = "checked") -> dict:
    return {
        "page": 1,
        "sections": ["fixture"],
        "text_read": True,
        "equations_checked": "not_present",
        "figures_checked": figures,
        "tables_checked": "not_present",
        "captions_checked": captions,
        "key_questions": [],
        "candidate_evidence": [],
        "selected_annotations": [],
        "rejected_fragments": [],
        "unresolved": [],
        "figure_audits": [valid_figure_audit()] if figures == "checked" else [],
    }


class FigureAuditTests(unittest.TestCase):
    def test_v4_rejects_checked_figures_without_audits(self):
        page = page_entry()
        page.pop("figure_audits")
        with self.assertRaisesRegex(LedgerError, "figure_audits"):
            validate_ledger([page], 1, schema_version=4)

    def test_v4_accepts_complete_figure_audit(self):
        report = validate_ledger([page_entry()], 1, schema_version=4)
        self.assertTrue(report["valid"])
        self.assertEqual(report["figure_audit_count"], 1)
        self.assertEqual(report["schema_version"], 4)

    def test_optional_visual_component_cannot_be_empty_list(self):
        page = page_entry()
        page["figure_audits"][0]["axes"] = []
        with self.assertRaisesRegex(LedgerError, "axes"):
            validate_ledger([page], 1, schema_version=4)

    def test_claims_and_consistency_cannot_be_empty(self):
        for field in ("observed_claims", "text_formula_table_consistency"):
            page = page_entry()
            page["figure_audits"][0][field] = []
            with self.subTest(field=field):
                with self.assertRaisesRegex(LedgerError, field):
                    validate_ledger([page], 1, schema_version=4)

    def test_figure_unresolved_blocks_completion(self):
        page = page_entry()
        page["figure_audits"][0]["unresolved"] = ["Panel b label unreadable"]
        with self.assertRaisesRegex(LedgerError, "unresolved"):
            validate_ledger([page], 1, schema_version=4)

    def test_page_without_figures_requires_empty_audit_list(self):
        page = page_entry(figures="not_present", captions="not_present")
        page["figure_audits"] = [valid_figure_audit()]
        with self.assertRaisesRegex(LedgerError, "must be empty"):
            validate_ledger([page], 1, schema_version=4)

    def test_figure_audit_requires_checked_captions(self):
        page = page_entry(captions="not_present")
        with self.assertRaisesRegex(LedgerError, "captions_checked"):
            validate_ledger([page], 1, schema_version=4)

    def test_figure_page_must_match_ledger_page(self):
        page = page_entry()
        page["figure_audits"][0]["pdf_page"] = 2
        with self.assertRaisesRegex(LedgerError, "pdf_page"):
            validate_ledger([page], 1, schema_version=4)

    def test_schema_v3_remains_compatible_without_figure_audits(self):
        page = page_entry()
        page.pop("figure_audits")
        report = validate_ledger([page], 1, schema_version=3)
        self.assertTrue(report["valid"])
        self.assertEqual(report["schema_version"], 3)


if __name__ == "__main__":
    unittest.main()
