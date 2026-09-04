from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from authority_contract import validate_contract


def _render(errors: list[Any]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "errors": [
            {
                "code": getattr(item, "code", "VALIDATION_ERROR"),
                "message": getattr(item, "message", str(item)),
            }
            for item in errors
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a thin original-Skill authority contract.",
    )
    parser.add_argument("contract_json", type=Path)
    parser.add_argument(
        "--phase",
        choices=("work", "pre_artifact", "delivery"),
        default="work",
    )
    args = parser.parse_args(argv)
    try:
        contract_path = args.contract_json.resolve()
        data = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("contract JSON must contain an object")
        errors = validate_contract(data, contract_path, args.phase)
        result = _render(errors)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        result = {
            "ok": False,
            "errors": [
                {"code": "CONTRACT_JSON_INVALID", "message": str(exc)}
            ],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
