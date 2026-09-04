"""Strictly clean and merge the workspace UAV literature corpus.

This script is intentionally offline and deterministic.  It only admits records
whose venue is on the whitelist and whose URL is a DOI, publisher record, or
official proceedings page.  Search/discovery sources are never written into the
main corpus.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from corpus_tools import (
    CSV_FIELDS,
    EXCLUDED_SOURCES,
    audit_record,
    deduplicate_records,
    has_complete_original_abstract,
    is_official_record_url,
    normalize_title,
    parse_csv_rows,
    parse_markdown_rows,
    validate_csv_file,
    validate_record_integrity,
)


WHITELIST = {
    "Nature",
    "Science",
    "Science Robotics",
    "NMI",
    "TPAMI",
    "TRO",
    "RAL",
    "TNNLS",
    "TMech",
    "TASE",
    "TITS",
    "IJRR",
    "ICRA",
    "IROS",
    "CoRL",
    "CVPR",
    "ICCV",
    "NeurIPS",
    "ICML",
    "ICLR",
    "AAAI",
    "RSS",
}

SOURCE_ALIASES = {
    "nature machine intelligence": "NMI",
    "tmech": "TMech",
    "t-mech": "TMech",
    "ral": "RAL",
    "tro": "TRO",
    "tase": "TASE",
    "tits": "TITS",
    "ijrr": "IJRR",
    "nips": "NeurIPS",
    "neurips": "NeurIPS",
}

# These are verified legacy records with an official record URL and a
# whitelist venue.  The legacy Markdown file used search/update dates in place
# of venue metadata, so these fields are deliberately explicit.
VERIFIED_LEGACY = {
    normalize_title("Vision-Based Hierarchical Reinforcement Learning for Quadrotor UAV Navigation"): {
        "source": "TMech",
        "venue_time": "2025",
        "url": "https://ieeexplore.ieee.org/abstract/document/11152372/",
    },
    normalize_title("Falcongym: A photorealistic simulation framework for zero-shot sim-to-real vision-based quadrotor navigation"): {
        "source": "IROS",
        "venue_time": "2025",
        "url": "https://ieeexplore.ieee.org/document/11247178",
    },
    normalize_title("Time-varying control barrier function for safe and precise landing of a uav on a moving target"): {
        "source": "IROS",
        "venue_time": "2024",
        "url": "https://ieeexplore.ieee.org/document/10802827",
    },
    normalize_title("Semantic-aware active perception for uavs using deep reinforcement learning"): {
        "source": "IROS",
        "venue_time": "2021",
        "url": "https://ieeexplore.ieee.org/document/9635893",
    },
    normalize_title("A sim-to-real deep learning-based framework for autonomous nano-drone racing"): {
        "source": "RAL",
        "venue_time": "2024",
        "url": "https://doi.org/10.1109/LRA.2024.3349814",
    },
    normalize_title("Skill transfer and discovery for sim-to-real learning: A representation-based viewpoint"): {
        "source": "IROS",
        "venue_time": "2024",
        "url": "https://ieeexplore.ieee.org/document/10801637",
    },
    normalize_title("UAST: Unified Active Search and Tracking for Arbitrary Targets with UAVs"): {
        "source": "CVPR",
        "venue_time": "2026",
        "url": "https://openaccess.thecvf.com/content/CVPR2026/html/Qin_UAST_Unified_Active_Search_and_Tracking_for_Arbitrary_Targets_with_CVPR_2026_paper.html",
    },
    normalize_title("Learning on the Fly: Rapid Policy Adaptation via Differentiable Simulation"): {
        "source": "RAL",
        "venue_time": "2026",
        "url": "https://doi.org/10.1109/LRA.2026.3655300",
    },
    normalize_title("Vision-Based Autonomous Drone Landing on Moving Platforms With Uncertain Motion via Deep Reinforcement Learning"): {
        "source": "RAL",
        "venue_time": "2026",
        "url": "https://doi.org/10.1109/LRA.2026.3674011",
    },
    normalize_title("Learning Agile Quadrotor Flight in the Real World"): {
        "source": "RSS",
        "venue_time": "2026",
        "url": "https://roboticsconference.org/program/papers/",
    },
}

CURRENT_URL_OVERRIDES = {
    normalize_title("FalconGym: A Photorealistic Simulation Framework for Zero-Shot Sim-to-Real Vision-Based Quadrotor Navigation"): "https://ieeexplore.ieee.org/document/11247178",
    normalize_title("Learning Agile Quadrotor Flight in the Real World"): "https://roboticsconference.org/program/papers/",
    normalize_title("Learning on the Fly: Rapid Policy Adaptation via Differentiable Simulation"): "https://doi.org/10.1109/LRA.2026.3655300",
}

HARD_GATE_PATTERNS = (
    (re.compile(r"\b(?:vla|vlm|llm)\b|vision[- ]language|large language model", re.I), "VLA/VLM/LLM or vision-language content"),
    (re.compile(r"event[- ]based|event camera", re.I), "event-camera content"),
    (re.compile(r"\bmulti[- ]?(?:uav|drone|robot)\b|\bswarm\b|marsupial|formation control of (?:drones|uavs)", re.I), "multi-UAV/swarm content"),
    (re.compile(r"\b(?:survey|literature review)\b", re.I), "survey/literature-review content"),
    (re.compile(r"gaussian splatting|3d gaussian", re.I), "large Gaussian-splatting content"),
)


def canonical_source(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    lowered = raw.casefold()
    if lowered in SOURCE_ALIASES:
        return SOURCE_ALIASES[lowered]
    for source in WHITELIST:
        if lowered == source.casefold():
            return source
    return raw


def apply_override(row: dict[str, str], overrides: dict[str, dict[str, str]] | None = None) -> dict[str, str]:
    result = {field: (row.get(field) or "").strip() for field in CSV_FIELDS}
    key = normalize_title(result["title"])
    if overrides and key in overrides:
        result.update(overrides[key])
    if key in CURRENT_URL_OVERRIDES and not overrides:
        result["url"] = CURRENT_URL_OVERRIDES[key]
    result["source"] = canonical_source(result["source"])
    return result


def hard_gate_reason(record: dict[str, str]) -> str | None:
    text = " ".join(record.get(field, "") for field in ("title", "abstract", "method_evidence", "compute_evidence", "experiment_evidence"))
    for pattern, reason in HARD_GATE_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def strict_audit(record: dict[str, str]) -> dict[str, str]:
    integrity_errors = validate_record_integrity(record)
    if integrity_errors:
        return {"status": "reject", "reason": "record integrity failure: " + "; ".join(integrity_errors)}
    source = canonical_source(record.get("source"))
    normalized = {**record, "source": source}
    basic = audit_record(normalized, WHITELIST)
    if basic["status"] != "accepted":
        return basic
    if not is_official_record_url(record.get("url")):
        return {"status": "reject", "reason": "URL is not a DOI, publisher, or official proceedings record"}
    if not has_complete_original_abstract(record):
        return {"status": "reject", "reason": "missing complete original abstract or official abstract source URL"}
    topic_reason = hard_gate_reason(record)
    if topic_reason:
        return {"status": "reject", "reason": topic_reason}
    return {"status": "accepted", "reason": "passes strict corpus audit"}


def prepare_candidates(csv_path: Path, markdown_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    current = [apply_override(row) for row in parse_csv_rows(csv_path)]
    legacy_rows = []
    if markdown_path.exists():
        for row in parse_markdown_rows(markdown_path):
            legacy_rows.append(apply_override(row, VERIFIED_LEGACY))
    return current + legacy_rows, legacy_rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)
    errors = validate_csv_file(path)
    if errors:
        raise ValueError("CSV integrity validation failed after write:\n" + "\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    candidates, legacy_rows = prepare_candidates(args.csv, args.markdown)
    audit = []
    accepted = []
    for row in candidates:
        decision = strict_audit(row)
        audit.append({"title": row["title"], "source": row["source"], "url": row["url"], **decision})
        if decision["status"] == "accepted":
            accepted.append(row)

    deduplicated, dedup_decisions = deduplicate_records(accepted)
    deduplicated.sort(key=lambda row: (row.get("venue_time", ""), normalize_title(row.get("title"))), reverse=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, deduplicated)
    args.report.write_text(
        json.dumps(
            {
                "input_csv_rows": len(parse_csv_rows(args.csv)),
                "legacy_rows_seen": len(legacy_rows),
                "candidates": len(candidates),
                "accepted_before_deduplication": len(accepted),
                "final_rows": len(deduplicated),
                "accepted_source_counts": {
                    source: sum(row["source"] == source for row in deduplicated)
                    for source in sorted(WHITELIST)
                    if any(row["source"] == source for row in deduplicated)
                },
                "audit": audit,
                "deduplication": dedup_decisions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
