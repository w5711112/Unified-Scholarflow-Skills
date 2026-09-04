"""Merge the workspace CSV and legacy Markdown table into one CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from corpus_tools import CSV_FIELDS, audit_record, merge_records, parse_csv_rows, parse_markdown_rows


DEFAULT_WHITELIST = {
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


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--accepted-only", action="store_true")
    args = parser.parse_args()

    existing = parse_csv_rows(args.csv)
    incoming = parse_markdown_rows(args.markdown)
    audit = [audit_record(row, DEFAULT_WHITELIST) for row in incoming]
    if args.accepted_only:
        incoming = [row for row, decision in zip(incoming, audit) if decision["status"] == "accepted"]
    merged, decisions = merge_records(existing, incoming)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, merged)
    args.report.write_text(
        json.dumps(
            {
                "existing_rows": len(existing),
                "incoming_rows": len(parse_markdown_rows(args.markdown)),
                "merged_rows": len(merged),
                "audit": audit,
                "decisions": decisions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
