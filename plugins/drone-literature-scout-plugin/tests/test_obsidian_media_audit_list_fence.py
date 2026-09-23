from __future__ import annotations

import importlib.util
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
    spec = importlib.util.spec_from_file_location("audit_obsidian_media_lists", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ObsidianMediaListFenceTests(unittest.TestCase):
    def test_list_prefixed_fence_does_not_hide_following_image(self):
        auditor = load_auditor()
        root = Path(__file__).resolve().parent / (".media-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root, True)
        (root / ".obsidian").mkdir()
        media_dir = root / "截图存放位置"
        media_dir.mkdir()
        (root / "AI绘图存放位置").mkdir()
        image = media_dir / "正文图片.png"
        image.write_bytes(b"media")
        (root / "note.md").write_text(
            "- ```python\n"
            "  print('inside list')\n"
            "  ```\n"
            "正文图片：![[截图存放位置/正文图片.png|600]]\n",
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertEqual(report["parse_warnings"], [])
        self.assertEqual(report["referenced"], ["截图存放位置/正文图片.png"])
        self.assertEqual(report["protected_by_raw_reference"], [])
        self.assertEqual(report["unreferenced"], [])


if __name__ == "__main__":
    unittest.main()
