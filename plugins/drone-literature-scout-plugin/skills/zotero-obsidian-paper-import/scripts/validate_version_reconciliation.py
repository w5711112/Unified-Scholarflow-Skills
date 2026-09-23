from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _load(
    receipt_or_path: dict[str, Any] | Path,
) -> tuple[dict[str, Any], str, Path]:
    if isinstance(receipt_or_path, Path):
        path = receipt_or_path.resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("version reconciliation receipt must contain an object")
        return payload, hashlib.sha256(path.read_bytes()).hexdigest(), path.parent
    if not isinstance(receipt_or_path, dict):
        raise TypeError("version reconciliation must be a receipt object or Path")
    rendered = json.dumps(
        receipt_or_path,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return receipt_or_path, hashlib.sha256(rendered).hexdigest(), Path.cwd()


def _required_true(
    payload: dict[str, Any],
    fields: tuple[str, ...],
    prefix: str,
    failures: list[str],
) -> None:
    for field in fields:
        if payload.get(field) is not True:
            failures.append(f"{prefix}.{field} must be true")


def validate_version_reconciliation(
    receipt_or_path: dict[str, Any] | Path,
) -> dict[str, Any]:
    try:
        receipt, receipt_sha256, base_dir = _load(receipt_or_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return {
            "valid": False,
            "status": None,
            "receipt_sha256": None,
            "failures": [f"version reconciliation receipt is unreadable: {exc}"],
        }

    failures: list[str] = []
    if receipt.get("schema_version") != 1:
        failures.append("schema_version must equal 1")
    status = receipt.get("status")
    conflict = receipt.get("conflict_detected")
    if status == "not_required":
        if conflict is not False:
            failures.append("version conflict cannot use not_required")
        if receipt.get("formal_identity_verified") is not True:
            failures.append("formal_identity_verified must be true")
    elif status in {"verified", "pending_manual_retirement"}:
        if conflict is not True:
            failures.append("version reconciliation requires conflict_detected true")
        old = receipt.get("old_identity")
        formal = receipt.get("formal_identity")
        if not isinstance(old, dict):
            failures.append("old_identity must be an object")
            old = {}
        if not isinstance(formal, dict):
            failures.append("formal_identity must be an object")
            formal = {}
        for prefix, payload in (("old_identity", old), ("formal_identity", formal)):
            for field in ("parent_key", "attachment_key", "pdf_sha256"):
                value = payload.get(field)
                if not isinstance(value, str) or not value.strip():
                    failures.append(f"{prefix}.{field} is required")
            digest = payload.get("pdf_sha256")
            if isinstance(digest, str) and not _SHA256_PATTERN.fullmatch(digest):
                failures.append(f"{prefix}.pdf_sha256 is invalid")
        if old.get("preserved_recoverably") is not True:
            failures.append("old attachment evidence must remain recoverable")
        if status == "verified" and old.get("retired_from_active_library") is not True:
            failures.append(
                "old_identity.retired_from_active_library must be true"
            )
        if status == "pending_manual_retirement":
            if old.get("retired_from_active_library") is not False:
                failures.append(
                    "pending retirement requires old parent to remain active"
                )
            manual_review = receipt.get("manual_review")
            if not isinstance(manual_review, dict):
                failures.append("manual_review must be an object")
            else:
                for field in ("old_parent_key", "required_action", "reason"):
                    value = manual_review.get(field)
                    if not isinstance(value, str) or not value.strip():
                        failures.append(f"manual_review.{field} is required")
        if (
            old.get("attachment_key")
            and old.get("attachment_key") == formal.get("attachment_key")
        ):
            failures.append("formal attachment must be distinct from old attachment")
        if formal.get("mime_type") != "application/pdf":
            failures.append("formal_identity.mime_type must be application/pdf")
        if not isinstance(formal.get("page_count"), int) or formal["page_count"] < 1:
            failures.append("formal_identity.page_count must be positive")
        if not isinstance(formal.get("source_url"), str) or not formal["source_url"].strip():
            failures.append("formal_identity.source_url is required")

        metadata = receipt.get("metadata_readback")
        if not isinstance(metadata, dict):
            failures.append("metadata_readback must be an object")
        else:
            _required_true(
                metadata,
                (
                    "title_verified",
                    "authors_verified",
                    "venue_verified",
                    "year_verified",
                    "doi_verified_or_not_available",
                    "url_verified",
                    "parent_readback_verified",
                    "children_readback_verified",
                    "active_attachment_verified",
                ),
                "metadata_readback",
                failures,
            )
            if not isinstance(metadata.get("author_count"), int) or metadata["author_count"] < 1:
                failures.append("metadata_readback.author_count must be positive")

        backup = receipt.get("annotation_free_backup")
        if not isinstance(backup, dict):
            failures.append("annotation_free_backup must be an object")
        else:
            if not isinstance(backup.get("path"), str) or not backup["path"].strip():
                failures.append("annotation_free_backup.path is required")
            if not isinstance(backup.get("sha256"), str) or not _SHA256_PATTERN.fullmatch(backup["sha256"]):
                failures.append("annotation_free_backup.sha256 is invalid")
            if backup.get("verified") is not True:
                failures.append("annotation_free_backup.verified must be true")
            if backup.get("sha256") != formal.get("pdf_sha256"):
                failures.append("annotation-free backup must match formal PDF hash")
            backup_path_value = backup.get("path")
            backup_path = (
                Path(backup_path_value)
                if isinstance(backup_path_value, str) and backup_path_value.strip()
                else None
            )
            if backup_path is not None and not backup_path.is_absolute():
                backup_path = base_dir / backup_path
            if backup_path is None or not backup_path.is_file():
                failures.append("annotation_free_backup path does not exist")
            elif backup.get("sha256") != hashlib.sha256(
                backup_path.read_bytes()
            ).hexdigest():
                failures.append("annotation_free_backup sha256 mismatch")

        rebuild = receipt.get("evidence_rebuild")
        if not isinstance(rebuild, dict):
            failures.append("evidence_rebuild must be an object")
        else:
            _required_true(
                rebuild,
                (
                    "old_page_coordinates_invalidated",
                    "reading_ledger_rebound",
                    "annotations_rebuilt",
                    "backlink_rebuilt",
                ),
                "evidence_rebuild",
                failures,
            )
        if not receipt.get("verified_at"):
            failures.append("verified_at is required")
    else:
        failures.append(
            "status must be not_required, pending_manual_retirement or verified"
        )

    return {
        "valid": not failures,
        "status": status,
        "conflict_detected": conflict,
        "completion_ready": status in {"not_required", "verified"} and not failures,
        "receipt_sha256": receipt_sha256,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    report = validate_version_reconciliation(args.receipt)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
