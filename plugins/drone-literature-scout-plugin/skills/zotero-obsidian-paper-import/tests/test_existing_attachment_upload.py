import sys
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from upload_existing_attachment import upload_existing_attachment


class ExistingAttachmentUploadTests(unittest.TestCase):
    def test_existing_parent_key_fails_closed_without_connector_calls(self):
        temporary = tempfile.TemporaryDirectory()
        state_dir = Path(temporary.name)
        pdf = state_dir / "test-existing-attachment-089.pdf"
        pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 300)
        try:
            with patch(
                "upload_existing_attachment.zotero_connector_save_item",
                side_effect=AssertionError("must not create an empty Connector session"),
            ) as save_item, patch(
                "upload_existing_attachment.zotero_connector_upload_attachment",
                side_effect=AssertionError("must not pass a Zotero key as parentItemID"),
            ) as upload, patch(
                "upload_existing_attachment.fetch_json",
                side_effect=AssertionError("no write was attempted, so no readback is due"),
            ) as fetch:
                result = upload_existing_attachment("PARENT89", pdf, "https://example.test/089.pdf")
        finally:
            if pdf.exists():
                pdf.unlink()
            temporary.cleanup()

        self.assertEqual(
            result["status"],
            "existing_parent_attachment_requires_supported_ui_or_bridge",
        )
        self.assertEqual(result["parent_key"], "PARENT89")
        self.assertEqual(result["attachment_key"], None)
        self.assertIn("connector item id", result["reason"])
        save_item.assert_not_called()
        upload.assert_not_called()
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

