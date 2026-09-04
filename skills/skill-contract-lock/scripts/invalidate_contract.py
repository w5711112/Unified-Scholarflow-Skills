from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from authority_contract import invalidate_contract, validate_contract


def _read_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("contract JSON must contain an object")
    return value


def _render_errors(errors: list[Any]) -> str:
    return json.dumps(
        [
            {
                "code": getattr(item, "code", "VALIDATION_ERROR"),
                "message": getattr(item, "message", str(item)),
            }
            for item in errors
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Invalidate receipts affected by changed current-task paths.",
    )
    parser.add_argument("contract_json", type=Path)
    parser.add_argument("--changed", action="append", required=True)
    args = parser.parse_args(argv)

    contract_path = args.contract_json.resolve()
    temporary_path = contract_path.with_name(contract_path.name + ".tmp")
    try:
        data = _read_contract(contract_path)
        changed_paths = set(args.changed)
        updated, affected = invalidate_contract(data, changed_paths)
        temporary_path.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        reparsed = _read_contract(temporary_path)
        errors = validate_contract(reparsed, contract_path, "work")
        if errors:
            task_root = Path(data["task"]["task_root"]).resolve()
            source_paths = {
                str(
                    (Path(item["path"]) if Path(item["path"]).is_absolute() else task_root / item["path"])
                    .resolve()
                )
                for item in data.get("sources", [])
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            expected_source_errors = {
                "SOURCE_MISSING",
                "SOURCE_HASH_MISMATCH",
                "REQUIREMENT_ANCHOR_INVALID",
            }
            codes = {getattr(item, "code", "") for item in errors}
            resolved_changes = {
                str(
                    (Path(item) if Path(item).is_absolute() else task_root / item)
                    .resolve()
                )
                for item in changed_paths
            }
            if resolved_changes.intersection(source_paths) and codes <= expected_source_errors:
                temporary_path.replace(contract_path)
            print(_render_errors(errors), file=sys.stderr)
            return 1
        temporary_path.replace(contract_path)
        print(json.dumps(sorted(affected), ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(
            json.dumps(
                [{"code": "INVALIDATION_FAILED", "message": str(exc)}],
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
