"""Audit every CSV row and emit a machine-readable report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clean_main_csv import strict_audit
from corpus_tools import audit_record, parse_csv_rows, validate_csv_file


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--strict-new-records", action="store_true")
    parser.add_argument("--strict", action="store_true", help="enforce official URL and hard-gate checks")
    args = parser.parse_args()

    schema_errors = validate_csv_file(args.csv)
    rows = parse_csv_rows(args.csv)
    decisions = []
    for index, row in enumerate(rows, start=2):
        decision = strict_audit(row) if args.strict else audit_record(row, DEFAULT_WHITELIST)
        decisions.append({"row": index, "title": row.get("title", ""), **decision})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {"rows": len(rows), "schema_errors": schema_errors, "decisions": decisions},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.strict and schema_errors:
        return 2
    if args.strict_new_records and any(item["status"] != "accepted" for item in decisions):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
