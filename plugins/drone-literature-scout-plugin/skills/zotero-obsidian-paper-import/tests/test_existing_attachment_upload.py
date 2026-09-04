import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from upload_existing_attachment import upload_existing_attachment


class ExistingAttachmentUploadTests(unittest.TestCase):
    def test_uploads_into_existing_parent_and_returns_real_attachment_key(self):
        state_dir = next(
            path for path in (ROOT / "skill-with-plugin").iterdir()
            if path.is_dir() and any(path.glob("*.json"))
        )
        pdf = state_dir / "test-existing-attachment-089.pdf"
        pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 300)
        try:
            children = [{"key": "ATTACH89", "data": {"contentType": "application/pdf", "title": "test-existing-attachment-089.pdf"}}]
            with patch(
                "upload_existing_attachment.zotero_connector_save_item",
                return_value=(201, b""),
            ) as save_item, patch(
                "upload_existing_attachment.zotero_connector_upload_attachment",
                return_value=(201, b""),
            ) as upload, patch(
                "upload_existing_attachment.fetch_json",
                return_value=children,
            ):
                result = upload_existing_attachment("PARENT89", pdf, "https://example.test/089.pdf")
        finally:
            if pdf.exists():
                pdf.unlink()

        self.assertEqual(result["status"], "imported_pdf")
        self.assertEqual(result["parent_key"], "PARENT89")
        self.assertEqual(result["attachment_key"], "ATTACH89")
        self.assertEqual(save_item.call_args.args[0]["items"], [])
        self.assertEqual(upload.call_args.args[1], "PARENT89")


if __name__ == "__main__":
    unittest.main()

