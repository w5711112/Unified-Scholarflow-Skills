from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from validate_paper_note import _extract_paper_block


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolved_path(value: Any, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        return candidate.resolve()
    except OSError:
        return None


def _personal_callout_hash(block: str) -> str | None:
    lines = block.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r" {0,3}>[ \t]*\[!personal\]\+[ \t]+个人理解[ \t]*", line)
        ),
        None,
    )
    if start is None:
        return None
    selected = [lines[start]]
    for line in lines[start + 1 :]:
        if re.match(r" {0,3}#{1,3}[ \t]+", line):
            break
        if line.startswith(">") or not line.strip():
            selected.append(line)
            continue
        break
    while selected and not selected[-1].strip():
        selected.pop()
    return hashlib.sha256("\n".join(selected).encode("utf-8")).hexdigest()


def _load_receipt(receipt_or_path: dict[str, Any] | Path) -> tuple[dict[str, Any], Path, str]:
    if isinstance(receipt_or_path, Path):
        receipt_path = receipt_or_path.resolve()
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("language gate receipt must contain an object")
        return payload, receipt_path.parent, _digest(receipt_path)
    if not isinstance(receipt_or_path, dict):
        raise TypeError("language gate must be a receipt object or Path")
    rendered = json.dumps(
        receipt_or_path,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return receipt_or_path, Path.cwd(), hashlib.sha256(rendered).hexdigest()


def validate_language_gate(receipt_or_path: dict[str, Any] | Path) -> dict[str, Any]:
    try:
        receipt, base_dir, receipt_sha256 = _load_receipt(receipt_or_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return {
            "valid": False,
            "scene": None,
            "receipt_sha256": None,
            "failures": [f"language gate receipt is unreadable: {exc}"],
        }

    failures: list[str] = []
    if receipt.get("schema_version") != 1:
        failures.append("schema_version must equal 1")
    if receipt.get("scene") != "paper-notes":
        failures.append("scene must be paper-notes")
    if not isinstance(receipt.get("target_reader"), str) or not receipt["target_reader"].strip():
        failures.append("target_reader is required")

    checked_paths: dict[str, str] = {}
    stage_paths: dict[str, Path] = {}
    final_block = ""
    for stage in ("semantic_draft", "renhua_output", "final_note"):
        payload = receipt.get(stage)
        if not isinstance(payload, dict):
            failures.append(f"{stage} must be an object")
            continue
        path = _resolved_path(payload.get("path"), base_dir)
        if path is None or not path.is_file():
            failures.append(f"{stage} path does not exist")
            continue
        expected = payload.get("sha256")
        actual = _digest(path)
        if not isinstance(expected, str) or not _SHA256_PATTERN.fullmatch(expected):
            failures.append(f"{stage} sha256 is invalid")
        elif expected != actual:
            failures.append(f"{stage} sha256 mismatch")
        checked_paths[stage] = str(path)
        stage_paths[stage] = path

        if stage == "final_note":
            block_id = payload.get("block_id")
            if not isinstance(block_id, str) or not block_id.strip():
                failures.append("final_note.block_id is required")
                continue
            text = path.read_text(encoding="utf-8")
            block, block_valid, block_failure = _extract_paper_block(text, block_id)
            if not block_valid:
                failures.append(
                    f"final_note block is invalid: {block_failure or block_id}"
                )
                continue
            final_block = block
            expected_block_hash = payload.get("block_sha256")
            actual_block_hash = hashlib.sha256(block.encode("utf-8")).hexdigest()
            if expected_block_hash != actual_block_hash:
                failures.append("final_note.block_sha256 mismatch")

    if len(stage_paths) == 3 and len(set(stage_paths.values())) != 3:
        failures.append("language stages must use three distinct files")

    protection = receipt.get("protection_ledger")
    if not isinstance(protection, dict):
        failures.append("protection_ledger must be an object")
    else:
        for field in (
            "numbers_and_units_preserved",
            "formulas_preserved",
            "citations_preserved",
            "claims_and_boundaries_preserved",
        ):
            if protection.get(field) is not True:
                failures.append(f"protection_ledger.{field} must be true")
        before = protection.get("personal_content_sha256_before")
        after = protection.get("personal_content_sha256_after")
        if (
            not isinstance(before, str)
            or not _SHA256_PATTERN.fullmatch(before)
            or not isinstance(after, str)
            or not _SHA256_PATTERN.fullmatch(after)
            or before != after
        ):
            failures.append("personal content changed")
        if final_block:
            current_personal_hash = _personal_callout_hash(final_block)
            if current_personal_hash is None:
                failures.append("final note is missing personal content callout")
            elif current_personal_hash != after:
                failures.append("personal content after hash does not match final note")

    terms = receipt.get("term_decision_ledger")
    if not isinstance(terms, list) or not terms:
        failures.append("term_decision_ledger must be a non-empty list")
    else:
        seen_terms: set[str] = set()
        for item in terms:
            term = item.get("term") if isinstance(item, dict) else None
            label = term if isinstance(term, str) and term.strip() else "<invalid>"
            if not isinstance(item, dict):
                failures.append("term decision must be an object")
                continue
            chosen_form = item.get("chosen_form")
            if not isinstance(term, str) or not term.strip():
                failures.append("term decision term is required")
            elif term in seen_terms:
                failures.append(f"duplicate term decision: {term}")
            else:
                seen_terms.add(term)
            for field in ("chosen_form", "reason", "first_occurrence"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    failures.append(f"term decision {field} is required: {label}")
            if item.get("meaning_preserved") is not True:
                failures.append(f"term meaning is not preserved: {label}")
            if item.get("explanation_present") is not True:
                failures.append(
                    f"term decision needs an in-context explanation: {label}"
                )
            if (
                final_block
                and isinstance(chosen_form, str)
                and chosen_form.strip()
                and chosen_form not in final_block
            ):
                failures.append(f"chosen term form is absent from final note: {label}")

    readthrough = receipt.get("readthrough_result")
    if not isinstance(readthrough, dict):
        failures.append("readthrough_result must be an object")
    else:
        for field in (
            "full_ai_block_read",
            "flow_continuity_verified",
            "section_transitions_verified",
            "density_expanded_when_needed",
        ):
            if readthrough.get(field) is not True:
                failures.append(f"readthrough_result.{field} must be true")

    acceptance = receipt.get("delivery_acceptance")
    if not isinstance(acceptance, dict):
        failures.append("delivery_acceptance must be an object")
    else:
        for field in (
            "fidelity_verified",
            "clarity_verified",
            "term_consistency_verified",
            "no_hard_translation_verified",
            "no_ai_residue_verified",
            "flow_continuity_verified",
            "personal_content_unchanged",
        ):
            if acceptance.get(field) is not True:
                failures.append(f"delivery_acceptance.{field} must be true")

    return {
        "valid": not failures,
        "scene": receipt.get("scene"),
        "receipt_sha256": receipt_sha256,
        "checked_paths": checked_paths,
        "term_decision_count": len(terms) if isinstance(terms, list) else 0,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    report = validate_language_gate(args.receipt)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

