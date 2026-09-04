from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class LedgerError(ValueError):
    """Raised when a full-text page ledger is incomplete."""


VISUAL_CHECK_FIELDS = (
    "equations_checked",
    "figures_checked",
    "tables_checked",
    "captions_checked",
)

LIST_FIELDS = (
    "sections",
    "key_questions",
    "candidate_evidence",
    "selected_annotations",
    "rejected_fragments",
    "unresolved",
)

FIGURE_AUDIT_COMPONENT_FIELDS = (
    "body_references",
    "panels",
    "visual_encodings",
    "axes",
    "legends",
    "modules",
    "arrows_and_flow",
    "inputs",
    "outputs",
    "limitations_or_anomalies",
    "annotation_regions",
)

FIGURE_AUDIT_REQUIRED_LIST_FIELDS = (
    "observed_claims",
    "text_formula_table_consistency",
)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_empty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_is_non_empty_string(item) for item in value)
    )


def validate_figure_audit(audit: dict[str, Any], page: int) -> list[str]:
    failures: list[str] = []
    if not isinstance(audit, dict):
        return ["figure audit must be an object"]
    if not _is_non_empty_string(audit.get("figure_id")):
        failures.append("figure_id must be non-empty text")
    if audit.get("pdf_page") != page:
        failures.append(f"pdf_page must equal ledger page {page}")
    if audit.get("caption_read") is not True:
        failures.append("caption_read must be true")

    for field in FIGURE_AUDIT_COMPONENT_FIELDS:
        value = audit.get(field)
        if value != "not_present" and not _is_non_empty_string_list(value):
            failures.append(
                f"{field} must be a non-empty text list or not_present"
            )

    for field in FIGURE_AUDIT_REQUIRED_LIST_FIELDS:
        if not _is_non_empty_string_list(audit.get(field)):
            failures.append(f"{field} must be a non-empty text list")

    unresolved = audit.get("unresolved")
    if not isinstance(unresolved, list):
        failures.append("unresolved must be a list")
    elif unresolved:
        failures.append(f"unresolved={unresolved}")
    return failures


def validate_ledger(
    pages: list[dict[str, Any]],
    expected_pages: int,
    schema_version: int = 3,
) -> dict[str, Any]:
    if expected_pages <= 0:
        raise LedgerError("expected_pages must be positive")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise LedgerError("schema_version must be an integer")
    if schema_version < 3:
        raise LedgerError("schema_version must be at least 3")

    page_numbers = [int(entry.get("page", 0)) for entry in pages]
    expected = list(range(1, expected_pages + 1))
    if sorted(page_numbers) != expected or len(page_numbers) != len(set(page_numbers)):
        raise LedgerError(
            f"ledger pages must contain each page exactly once: expected={expected} "
            f"actual={sorted(page_numbers)}"
        )

    failures: list[str] = []
    selected_count = 0
    figure_audit_count = 0
    for entry in pages:
        page = int(entry["page"])
        if entry.get("text_read") is not True:
            failures.append(f"page {page}: text_read is not true")
        for field in VISUAL_CHECK_FIELDS:
            if entry.get(field) not in {"checked", "not_present"}:
                failures.append(
                    f"page {page}: {field} must be checked or not_present"
                )
        for field in LIST_FIELDS:
            if not isinstance(entry.get(field), list):
                failures.append(f"page {page}: {field} must be a list")
        unresolved = entry.get("unresolved", [])
        if unresolved:
            failures.append(f"page {page}: unresolved={unresolved}")
        selected_count += len(entry.get("selected_annotations", []))

        if schema_version >= 4:
            figure_audits = entry.get("figure_audits")
            if not isinstance(figure_audits, list):
                failures.append(f"page {page}: figure_audits must be a list")
                figure_audits = []
            if entry.get("figures_checked") == "checked":
                if not figure_audits:
                    failures.append(
                        f"page {page}: checked figures require figure_audits"
                    )
                if entry.get("captions_checked") != "checked":
                    failures.append(
                        f"page {page}: figures require captions_checked=checked"
                    )
                for index, audit in enumerate(figure_audits):
                    audit_failures = validate_figure_audit(audit, page)
                    failures.extend(
                        f"page {page} figure_audits[{index}]: {failure}"
                        for failure in audit_failures
                    )
                figure_audit_count += len(figure_audits)
            elif figure_audits:
                failures.append(
                    f"page {page}: figure_audits must be empty when figures are not_present"
                )

    if failures:
        raise LedgerError("; ".join(failures))
    return {
        "valid": True,
        "schema_version": schema_version,
        "page_count": expected_pages,
        "selected_annotation_count": selected_count,
        "figure_audit_count": figure_audit_count,
        "quota_enforced": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    parser.add_argument("--expected-pages", required=True, type=int)
    args = parser.parse_args()
    raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        pages = raw["pages"]
        schema_version = raw.get("schema_version", 3)
    else:
        pages = raw
        schema_version = 3
    print(
        json.dumps(
            validate_ledger(
                pages,
                args.expected_pages,
                schema_version=schema_version,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
