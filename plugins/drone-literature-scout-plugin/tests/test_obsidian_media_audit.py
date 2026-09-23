from __future__ import annotations

import importlib.util
import json
import shutil
import unittest
import uuid
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "scripts"
    / "audit_obsidian_media.py"
)


def load_auditor():
    if not SCRIPT.is_file():
        raise AssertionError(f"media auditor is missing: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("audit_obsidian_media", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ObsidianMediaAuditTests(unittest.TestCase):
    def make_vault(self) -> Path:
        root = Path(__file__).resolve().parent / (".media-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        (root / ".obsidian").mkdir()
        (root / "截图存放位置").mkdir()
        (root / "AI绘图存放位置").mkdir()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    @staticmethod
    def write_media(path: Path, content: bytes = b"media") -> None:
        path.write_bytes(content)

    def test_audits_markdown_canvas_missing_ambiguous_and_orphan_media(self):
        auditor = load_auditor()
        root = self.make_vault()
        self.write_media(root / "截图存放位置" / "used.png")
        self.write_media(root / "截图存放位置" / "shared.png")
        self.write_media(root / "AI绘图存放位置" / "shared.png")
        self.write_media(root / "AI绘图存放位置" / "canvas.svg", b"<svg/>")
        self.write_media(root / "AI绘图存放位置" / "orphan.svg", b"<svg/>")

        (root / "note.md").write_text(
            "![[截图存放位置/used.png|375]]\n"
            "![[shared.png|225]]\n"
            "![[missing.png|300]]\n",
            encoding="utf-8",
        )
        (root / "board.canvas").write_text(
            json.dumps(
                {
                    "nodes": [
                        {
                            "id": "file-node",
                            "type": "file",
                            "file": "AI绘图存放位置/canvas.svg",
                        }
                    ],
                    "edges": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertEqual(report["scanned_markdown"], 1)
        self.assertEqual(report["scanned_canvas"], 1)
        self.assertEqual(
            report["referenced"],
            [
                "AI绘图存放位置/canvas.svg",
                "截图存放位置/used.png",
            ],
        )
        self.assertEqual(
            [item["target"] for item in report["missing"]],
            ["missing.png"],
        )
        self.assertEqual(
            report["ambiguous"],
            [
                {
                    "source": "note.md",
                    "target": "shared.png",
                    "candidates": [
                        "AI绘图存放位置/shared.png",
                        "截图存放位置/shared.png",
                    ],
                }
            ],
        )
        self.assertEqual(report["unreferenced"], ["AI绘图存放位置/orphan.svg"])

    def test_dry_run_never_deletes_and_apply_deletes_only_reported_managed_files(self):
        auditor = load_auditor()
        root = self.make_vault()
        orphan = root / "AI绘图存放位置" / "orphan.svg"
        self.write_media(orphan, b"<svg/>")
        report = auditor.audit_vault_media(root)

        self.assertEqual(auditor.delete_unreferenced(report, apply=False), [])
        self.assertTrue(orphan.exists())

        deleted = auditor.delete_unreferenced(report, apply=True)

        self.assertEqual(deleted, ["AI绘图存放位置/orphan.svg"])
        self.assertFalse(orphan.exists())

    def test_delete_refuses_tampered_path_outside_managed_directories(self):
        auditor = load_auditor()
        root = self.make_vault()
        protected = root / "keep.png"
        self.write_media(protected)
        report = auditor.audit_vault_media(root)
        report["unreferenced"] = ["keep.png"]

        with self.assertRaisesRegex(ValueError, "managed media directories"):
            auditor.delete_unreferenced(report, apply=True)

        self.assertTrue(protected.exists())


if __name__ == "__main__":
    unittest.main()
