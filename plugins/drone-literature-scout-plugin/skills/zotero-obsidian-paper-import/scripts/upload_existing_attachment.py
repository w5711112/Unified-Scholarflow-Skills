from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
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

    session_id = f"paper-import-attachment-{uuid.uuid4().hex}"
    session_status, session_body = zotero_connector_save_item(
        {"items": [], "uri": source_url, "sessionID": session_id},
        base_url=base_url,
    )
    if session_status not in (200, 201):
        return {
            "status": "session_failed",
            "session_status": session_status,
            "session_response": session_body.decode("utf-8", errors="replace"),
            "parent_key": parent_key,
        }

    upload_status, upload_body = zotero_connector_upload_attachment(
        session_id,
        parent_key,
        path,
        source_url,
        base_url=base_url,
    )
    time.sleep(0.8)
    children = fetch_json(f"{base_url}/api/users/0/items/{parent_key}/children?limit=100")
    pdfs = [
        child
        for child in children
        if child.get("data", {}).get("contentType") == "application/pdf"
    ]
    matching = [child for child in pdfs if child.get("data", {}).get("title") == path.name]
    attachment = matching[-1] if matching else (pdfs[-1] if pdfs else None)
    result: dict[str, object] = {
        "status": "imported_pdf" if upload_status in (200, 201) and attachment else "upload_failed",
        "parent_key": parent_key,
        "session_status": session_status,
        "upload_status": upload_status,
        "upload_response": upload_body.decode("utf-8", errors="replace"),
        "attachment_key": attachment.get("key") if attachment else None,
        "attachment_count": len(pdfs),
        "pdf_path": str(path.resolve()),
    }
    return result


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
