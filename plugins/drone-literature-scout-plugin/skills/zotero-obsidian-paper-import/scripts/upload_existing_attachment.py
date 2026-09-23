from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from paper_import import (
    fetch_json,
    is_valid_pdf_bytes,
    zotero_connector_save_item,
    zotero_connector_upload_attachment,
)


def upload_existing_attachment(
    parent_key: str,
    pdf_path: str | Path,
    source_url: str = "",
    base_url: str = "http://localhost:23119",
) -> dict[str, object]:
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if not is_valid_pdf_bytes(path.read_bytes()[:1024]):
        raise ValueError(f"not a valid PDF: {path}")

    # Connector saveAttachment does not accept an existing Zotero item key as
    # parentItemID. It accepts only the connector item id emitted by saveItems
    # in the same session. Failing closed here prevents the previous behaviour:
    # an empty session followed by an invalid upload that looked automatable.
    return {
        "status": "existing_parent_attachment_requires_supported_ui_or_bridge",
        "parent_key": parent_key,
        "attachment_key": None,
        "pdf_path": str(path.resolve()),
        "source_url": source_url,
        "reason": (
            "Connector saveAttachment requires the connector item id created "
            "by saveItems in the same session; a Zotero parent key cannot be "
            "used as parentItemID. Use a verified Zotero UI or supported bridge."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-key", required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--source-url", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = upload_existing_attachment(args.parent_key, args.pdf, args.source_url)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "imported_pdf" else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
