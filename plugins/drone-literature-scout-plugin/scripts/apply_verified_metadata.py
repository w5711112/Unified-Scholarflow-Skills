"""Apply a small, manually reviewed official-source evidence manifest to the CSV."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from corpus_tools import CSV_FIELDS, normalize_title, parse_csv_rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)


def apply_manifest(rows: list[dict[str, str]], manifest: list[dict[str, str]]) -> tuple[int, list[str]]:
    by_title = {normalize_title(row.get("title")): row for row in rows}
    applied = 0
    missing: list[str] = []
    for item in manifest:
        title = normalize_title(item.get("title"))
        row = by_title.get(title)
        if row is None:
            missing.append(item.get("title", ""))
            continue
        for field in CSV_FIELDS:
            if field in item:
                row[field] = str(item[field]).strip()
        row["verification_date"] = item.get("verification_date", date.today().isoformat())
        applied += 1
    return applied, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    rows = parse_csv_rows(args.csv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    applied, missing = apply_manifest(rows, manifest)
    if missing:
        raise SystemExit(f"Manifest titles not found: {missing}")
    write_csv(args.csv, rows)
    print(json.dumps({"applied": applied, "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

