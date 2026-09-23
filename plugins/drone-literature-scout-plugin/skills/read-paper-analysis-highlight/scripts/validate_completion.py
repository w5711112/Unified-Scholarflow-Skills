from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from validate_reading_ledger import validate_ledger
from validate_language_gate import validate_language_gate


_ZOTERO_VALIDATOR_DIR = (
    Path(__file__).parents[2]
    / "zotero-obsidian-paper-import"
    / "scripts"
)
if str(_ZOTERO_VALIDATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_ZOTERO_VALIDATOR_DIR))
from validate_version_reconciliation import (  # noqa: E402
    validate_version_reconciliation,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class CompletionError(ValueError):
    """Raised when a paper is not ready for the completed-reading status."""


def validate_completion(
    pages: list[dict[str, Any]] | dict[str, Any],
    manifest: dict[str, Any],
    verification: dict[str, Any],
    desired_status: str,
) -> dict[str, Any]:
    page_count = int(manifest.get("page_count", 0))
    if isinstance(pages, dict):
        ledger_pages = pages["pages"]
        schema_version = int(pages.get("schema_version", 3))
    else:
        ledger_pages = pages
        schema_version = (
            4 if any("figure_audits" in entry for entry in pages) else 3
        )
    ledger_report = validate_ledger(
        ledger_pages, page_count, schema_version=schema_version
    )
    if desired_status != "已AI全文读":
        return {
            "status": desired_status,
            "ledger": ledger_report,
            "complete": False,
        }

    failures: list[str] = []
    if verification.get("workflow_scope") != "full":
        failures.append("workflow_scope must be full")
    language_gate_report = verification.get("language_gate_report")
    if (
        not isinstance(language_gate_report, dict)
        or language_gate_report.get("valid") is not True
        or not isinstance(language_gate_report.get("receipt_sha256"), str)
        or not _SHA256_PATTERN.fullmatch(
            language_gate_report["receipt_sha256"]
        )
    ):
        failures.append("verified language gate report is required")
    version_reconciliation_report = verification.get(
        "version_reconciliation_report"
    )
    if (
        not isinstance(version_reconciliation_report, dict)
        or version_reconciliation_report.get("valid") is not True
        or version_reconciliation_report.get("status")
        not in {"not_required", "verified"}
        or not isinstance(
            version_reconciliation_report.get("receipt_sha256"), str
        )
        or not _SHA256_PATTERN.fullmatch(
            version_reconciliation_report["receipt_sha256"]
        )
    ):
        failures.append("verified version reconciliation report is required")
    if manifest.get("storage_mode") != "zotero-native":
        failures.append("storage_mode must be zotero-native")
    annotation_count = int(manifest.get("annotation_count", -1))
    native_keys = manifest.get("native_annotation_keys")
    if not isinstance(native_keys, list) or len(native_keys) != annotation_count:
        failures.append("native annotation key count does not match annotation_count")
    if manifest.get("editable_verified") is not True:
        failures.append("editable_verified must be true")
    if manifest.get("deletable_verified") is not True:
        failures.append("deletable_verified must be true")
    if int(manifest.get("locked_annotation_count", -1)) != 0:
        failures.append("locked_annotation_count must be zero")
    memory_layer = manifest.get("memory_layer")
    if not isinstance(memory_layer, dict):
        failures.append("memory_layer must be present and verified")
    else:
        for field in (
            "enabled",
            "note_memory_sentence_exact_match",
            "page_1_visual_render_verified",
        ):
            if memory_layer.get(field) is not True:
                failures.append(f"memory_layer.{field} must be true")
        if int(memory_layer.get("bridge_url_count", -1)) != 1:
            failures.append("memory_layer.bridge_url_count must equal one")
        if memory_layer.get("bridge_click_verified") is not True:
            failures.append("memory_layer.bridge_click_verified must be true")
        if int(memory_layer.get("direct_obsidian_uri_count", -1)) != 0:
            failures.append("memory_layer.direct_obsidian_uri_count must equal zero")
        if int(memory_layer.get("embedded_markup_count", -1)) != 0:
            failures.append("memory_layer.embedded_markup_count must be zero")
        if memory_layer.get("final_sha256") != manifest.get(
            "current_pdf_sha256"
        ):
            failures.append(
                "memory_layer.final_sha256 must match current_pdf_sha256"
            )
    if not manifest.get("verified_at"):
        failures.append("verified_at is required")
    if verification.get("note_completed") is not True:
        failures.append("Obsidian note is not complete")
    if verification.get("pdf_position_verified") is not True:
        failures.append("PDF positions are not verified")
    for field in (
        "note_contract_valid",
        "author_research_valid",
        "knowledge_links_valid",
        "pdf_memory_layer_verified",
        "memory_sentence_synced",
        "obsidian_uri_verified",
    ):
        if verification.get(field) is not True:
            failures.append(f"{field} must be true")
    if failures:
        raise CompletionError("; ".join(failures))
    return {
        "status": "已AI全文读",
        "complete": True,
        "ledger": ledger_report,
        "annotation_count": annotation_count,
        "workflow_scope": "full",
        "language_gate_receipt_sha256": language_gate_report[
            "receipt_sha256"
        ],
        "version_reconciliation_receipt_sha256": version_reconciliation_report[
            "receipt_sha256"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verification", required=True)
    parser.add_argument("--language-gate", type=Path)
    parser.add_argument("--version-reconciliation", type=Path)
    parser.add_argument("--status", required=True)
    args = parser.parse_args()
    ledger_raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    verification = json.loads(Path(args.verification).read_text(encoding="utf-8"))
    if args.status == "已AI全文读":
        verification["language_gate_report"] = (
            validate_language_gate(args.language_gate)
            if args.language_gate is not None
            else {
                "valid": False,
                "receipt_sha256": None,
                "failures": ["--language-gate is required"],
            }
        )
        verification["version_reconciliation_report"] = (
            validate_version_reconciliation(args.version_reconciliation)
            if args.version_reconciliation is not None
            else {
                "valid": False,
                "status": None,
                "receipt_sha256": None,
                "failures": ["--version-reconciliation is required"],
            }
        )
    result = validate_completion(
        ledger_raw, manifest, verification, args.status
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
