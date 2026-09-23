from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_completion import CompletionError, validate_completion  # noqa: E402
from validate_reading_ledger import LedgerError, validate_ledger  # noqa: E402


def page_entry(page: int, annotations: list[str] | None = None) -> dict:
    return {
        "page": page,
        "sections": ["fixture"],
        "text_read": True,
        "equations_checked": "checked" if page == 2 else "not_present",
        "figures_checked": "checked" if page == 3 else "not_present",
        "tables_checked": "checked" if page == 4 else "not_present",
        "captions_checked": "checked" if page in (3, 4) else "not_present",
        "key_questions": [],
        "candidate_evidence": [],
        "selected_annotations": annotations or [],
        "rejected_fragments": [],
        "unresolved": [],
    }


def complete_figure_audit(page: int) -> dict:
    return {
        "figure_id": "Fig. 1",
        "pdf_page": page,
        "caption_read": True,
        "body_references": "not_present",
        "panels": "not_present",
        "visual_encodings": "not_present",
        "axes": "not_present",
        "legends": "not_present",
        "modules": "not_present",
        "arrows_and_flow": "not_present",
        "inputs": "not_present",
        "outputs": "not_present",
        "limitations_or_anomalies": "not_present",
        "annotation_regions": "not_present",
        "observed_claims": ["The figure was fully audited."],
        "text_formula_table_consistency": ["No inconsistency found."],
        "unresolved": [],
    }


def native_manifest(count: int = 2) -> dict:
    return {
        "page_count": 4,
        "annotation_count": count,
        "storage_mode": "zotero-native",
        "native_annotation_keys": [f"KEY{i}" for i in range(count)],
        "editable_verified": True,
        "deletable_verified": True,
        "locked_annotation_count": 0,
        "verified_at": "2026-07-23T12:00:00+08:00",
        "current_pdf_sha256": "FINALHASH",
        "memory_layer": {
            "enabled": True,
            "final_sha256": "FINALHASH",
            "note_memory_sentence_exact_match": True,
            "obsidian_uri_count": 1,
            "bridge_url_count": 1,
            "bridge_click_verified": True,
            "direct_obsidian_uri_count": 0,
            "embedded_markup_count": 0,
            "page_1_visual_render_verified": True,
        },
    }


def completed_verification(**overrides: bool) -> dict:
    verification = {
        "workflow_scope": "full",
        "note_completed": True,
        "pdf_position_verified": True,
        "note_contract_valid": True,
        "author_research_valid": True,
        "knowledge_links_valid": True,
        "pdf_memory_layer_verified": True,
        "memory_sentence_synced": True,
        "obsidian_uri_verified": True,
        "language_gate_report": {
            "valid": True,
            "receipt_sha256": "a" * 64,
        },
        "version_reconciliation_report": {
            "valid": True,
            "status": "not_required",
            "receipt_sha256": "b" * 64,
        },
    }
    verification.update(overrides)
    return verification

class ReadingCompletionTests(unittest.TestCase):
    def test_obsidian_only_scope_cannot_reach_completed_status(self):
        pages = [page_entry(page) for page in range(1, 5)]
        with self.assertRaisesRegex(CompletionError, "workflow_scope"):
            validate_completion(
                pages,
                native_manifest(),
                completed_verification(workflow_scope="obsidian-only"),
                "已AI全文读",
            )

    def test_completed_status_requires_valid_language_gate_report(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for value in (None, {"valid": False, "receipt_sha256": "a" * 64}):
            verification = completed_verification()
            verification["language_gate_report"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(CompletionError, "language gate"):
                    validate_completion(
                        pages,
                        native_manifest(),
                        verification,
                        "已AI全文读",
                    )

    def test_receipt_hashes_must_be_lowercase_sha256(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for field in (
            "language_gate_report",
            "version_reconciliation_report",
        ):
            verification = completed_verification()
            verification[field]["receipt_sha256"] = "z" * 64
            with self.subTest(field=field):
                with self.assertRaisesRegex(CompletionError, "report"):
                    validate_completion(
                        pages,
                        native_manifest(),
                        verification,
                        "已AI全文读",
                    )

    def test_version_conflict_requires_verified_reconciliation_report(self):
        pages = [page_entry(page) for page in range(1, 5)]
        verification = completed_verification()
        verification["version_reconciliation_report"] = {
            "valid": False,
            "status": "VERSION_CONFLICT",
            "receipt_sha256": "b" * 64,
        }
        with self.assertRaisesRegex(CompletionError, "version reconciliation"):
            validate_completion(
                pages,
                native_manifest(),
                verification,
                "已AI全文读",
            )

    def test_ledger_requires_every_page_once(self):
        with self.assertRaises(LedgerError):
            validate_ledger([page_entry(1), page_entry(3), page_entry(4)], 4)

    def test_ledger_rejects_unresolved_visual_or_text(self):
        pages = [page_entry(page) for page in range(1, 5)]
        pages[2]["unresolved"] = ["Figure 2 labels unreadable"]
        with self.assertRaises(LedgerError):
            validate_ledger(pages, 4)

    def test_ledger_has_no_annotation_count_quota(self):
        pages = [page_entry(page) for page in range(1, 5)]
        pages[0]["selected_annotations"] = []
        pages[1]["selected_annotations"] = [f"a{i}" for i in range(40)]
        report = validate_ledger(pages, 4)
        self.assertEqual(report["selected_annotation_count"], 40)

    def test_external_annotations_block_completed_status(self):
        pages = [page_entry(page) for page in range(1, 5)]
        manifest = native_manifest()
        manifest["storage_mode"] = "external-staging"
        with self.assertRaisesRegex(CompletionError, "zotero-native"):
            validate_completion(
                pages,
                manifest,
                completed_verification(),
                "已AI全文读",
            )

    def test_locked_or_uneditable_annotations_block_completed_status(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for field, value in (
            ("editable_verified", False),
            ("deletable_verified", False),
            ("locked_annotation_count", 1),
        ):
            manifest = native_manifest()
            manifest[field] = value
            with self.subTest(field=field):
                with self.assertRaises(CompletionError):
                    validate_completion(
                        pages,
                        manifest,
                        completed_verification(),
                        "已AI全文读",
                    )

    def test_native_key_count_must_equal_annotation_count(self):
        pages = [page_entry(page) for page in range(1, 5)]
        manifest = native_manifest(2)
        manifest["native_annotation_keys"] = ["ONLYONE"]
        with self.assertRaisesRegex(CompletionError, "count"):
            validate_completion(
                pages,
                manifest,
                completed_verification(),
                "已AI全文读",
            )

    def test_completed_status_requires_note_and_position_verification(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for verification in (
            completed_verification(note_completed=False),
            completed_verification(pdf_position_verified=False),
        ):
            with self.assertRaises(CompletionError):
                validate_completion(
                    pages, native_manifest(), verification, "已AI全文读"
                )

    def test_completed_status_requires_note_author_and_knowledge_contracts(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for field in (
            "note_contract_valid",
            "author_research_valid",
            "knowledge_links_valid",
            "pdf_memory_layer_verified",
            "memory_sentence_synced",
            "obsidian_uri_verified",
        ):
            with self.subTest(field=field):
                verification = completed_verification()
                verification.pop(field)
                with self.assertRaisesRegex(CompletionError, field):
                    validate_completion(
                        pages,
                        native_manifest(),
                        verification,
                        "已AI全文读",
                    )

                verification[field] = False
                with self.assertRaisesRegex(CompletionError, field):
                    validate_completion(
                        pages,
                        native_manifest(),
                        verification,
                        "已AI全文读",
                    )
    def test_completed_status_requires_verified_memory_layer(self):
        pages = [page_entry(page) for page in range(1, 5)]
        manifest = native_manifest()
        manifest.pop("memory_layer")
        with self.assertRaisesRegex(CompletionError, "memory_layer"):
            validate_completion(
                pages, manifest, completed_verification(), "已AI全文读"
            )

    def test_completed_status_requires_verified_zotero_bridge_click(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for field, value in (
            ("bridge_url_count", 0),
            ("bridge_click_verified", False),
            ("direct_obsidian_uri_count", 1),
        ):
            manifest = native_manifest()
            manifest["memory_layer"][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(CompletionError, field):
                    validate_completion(
                        pages,
                        manifest,
                        completed_verification(),
                        "已AI全文读",
                    )

    def test_completion_preserves_v4_figure_audit_evidence(self):
        pages = [page_entry(page) for page in range(1, 5)]
        for page in pages:
            page["figure_audits"] = []
        pages[2]["figure_audits"] = [complete_figure_audit(3)]
        report = validate_completion(
            pages,
            native_manifest(),
            completed_verification(),
            "已AI全文读",
        )
        self.assertEqual(report["ledger"]["schema_version"], 4)
        self.assertEqual(report["ledger"]["figure_audit_count"], 1)

    def test_all_gates_allow_completed_status(self):
        pages = [page_entry(page) for page in range(1, 5)]
        report = validate_completion(
            pages,
            native_manifest(),
            completed_verification(),
            "已AI全文读",
        )
        self.assertEqual(report["status"], "已AI全文读")


if __name__ == "__main__":
    unittest.main()
