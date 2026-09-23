from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_version_reconciliation import (  # noqa: E402
    validate_version_reconciliation,
)


def not_required_receipt() -> dict:
    return {
        "schema_version": 1,
        "status": "not_required",
        "conflict_detected": False,
        "formal_identity_verified": True,
    }


def verified_receipt(backup_path: Path, formal_hash: str) -> dict:
    return {
        "schema_version": 1,
        "status": "verified",
        "conflict_detected": True,
        "old_identity": {
            "parent_key": "OLDPARENT",
            "attachment_key": "OLDPDF",
            "pdf_sha256": "1" * 64,
            "preserved_recoverably": True,
            "retired_from_active_library": True,
        },
        "formal_identity": {
            "parent_key": "OLDPARENT",
            "attachment_key": "FORMALPDF",
            "pdf_sha256": formal_hash,
            "mime_type": "application/pdf",
            "page_count": 10,
            "source_url": "https://example.org/formal-paper",
        },
        "metadata_readback": {
            "title_verified": True,
            "authors_verified": True,
            "author_count": 7,
            "venue_verified": True,
            "year_verified": True,
            "doi_verified_or_not_available": True,
            "url_verified": True,
            "parent_readback_verified": True,
            "children_readback_verified": True,
            "active_attachment_verified": True,
        },
        "annotation_free_backup": {
            "path": str(backup_path),
            "sha256": formal_hash,
            "verified": True,
        },
        "evidence_rebuild": {
            "old_page_coordinates_invalidated": True,
            "reading_ledger_rebound": True,
            "annotations_rebuilt": True,
            "backlink_rebuilt": True,
        },
        "verified_at": "2026-09-08T12:00:00+08:00",
    }


class VersionReconciliationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.backup = self.root / "formal.clean.pdf"
        self.backup.write_bytes(b"%PDF-1.7\nformal fixture\n%%EOF\n")
        self.formal_hash = hashlib.sha256(self.backup.read_bytes()).hexdigest()

    def tearDown(self):
        self._tmp.cleanup()

    def verified_receipt(self) -> dict:
        return verified_receipt(self.backup, self.formal_hash)

    def write_receipt(self, receipt: dict) -> Path:
        path = self.root / "version-reconciliation.json"
        path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def test_no_conflict_can_be_explicitly_not_required(self):
        report = validate_version_reconciliation(not_required_receipt())
        self.assertTrue(report["valid"], report["failures"])

    def test_verified_formal_version_passes(self):
        report = validate_version_reconciliation(
            self.write_receipt(self.verified_receipt())
        )
        self.assertTrue(report["valid"], report["failures"])

    def test_verified_requires_old_parent_to_be_retired(self):
        receipt = self.verified_receipt()
        receipt["old_identity"]["retired_from_active_library"] = False
        report = validate_version_reconciliation(receipt)
        self.assertFalse(report["valid"])
        self.assertIn(
            "old_identity.retired_from_active_library must be true",
            report["failures"],
        )

    def test_pending_manual_retirement_is_valid_but_not_completion_ready(self):
        receipt = self.verified_receipt()
        receipt["status"] = "pending_manual_retirement"
        receipt["old_identity"]["retired_from_active_library"] = False
        receipt["manual_review"] = {
            "old_parent_key": "OLDPARENT",
            "required_action": "move old parent to Zotero trash",
            "reason": "local API is read-only and native UI is unavailable",
        }
        report = validate_version_reconciliation(receipt)
        self.assertTrue(report["valid"], report["failures"])
        self.assertFalse(report["completion_ready"])

    def test_conflict_cannot_be_marked_not_required(self):
        receipt = not_required_receipt()
        receipt["conflict_detected"] = True
        report = validate_version_reconciliation(receipt)
        self.assertFalse(report["valid"])
        self.assertIn(
            "version conflict cannot use not_required",
            report["failures"],
        )

    def test_formal_version_requires_distinct_attachment_and_old_preservation(self):
        receipt = self.verified_receipt()
        receipt["formal_identity"]["attachment_key"] = "OLDPDF"
        receipt["old_identity"]["preserved_recoverably"] = False
        report = validate_version_reconciliation(receipt)
        self.assertFalse(report["valid"])
        self.assertIn("formal attachment must be distinct from old attachment", report["failures"])
        self.assertIn("old attachment evidence must remain recoverable", report["failures"])

    def test_metadata_readback_and_evidence_rebuild_are_mandatory(self):
        receipt = self.verified_receipt()
        receipt["metadata_readback"]["authors_verified"] = False
        receipt["evidence_rebuild"]["backlink_rebuilt"] = False
        report = validate_version_reconciliation(receipt)
        self.assertFalse(report["valid"])
        self.assertIn("metadata_readback.authors_verified must be true", report["failures"])
        self.assertIn("evidence_rebuild.backlink_rebuilt must be true", report["failures"])

    def test_missing_or_stale_annotation_free_backup_is_rejected(self):
        receipt = self.verified_receipt()
        receipt["annotation_free_backup"]["path"] = str(
            self.root / "missing.clean.pdf"
        )
        report = validate_version_reconciliation(receipt)
        self.assertFalse(report["valid"])
        self.assertIn(
            "annotation_free_backup path does not exist",
            report["failures"],
        )

        receipt = self.verified_receipt()
        receipt["annotation_free_backup"]["sha256"] = "3" * 64
        report = validate_version_reconciliation(receipt)
        self.assertFalse(report["valid"])
        self.assertIn(
            "annotation_free_backup sha256 mismatch",
            report["failures"],
        )


if __name__ == "__main__":
    unittest.main()
