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
    spec = importlib.util.spec_from_file_location("audit_obsidian_media_forms", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ObsidianMediaReferenceFormTests(unittest.TestCase):
    def make_vault(self) -> Path:
        root = Path(__file__).resolve().parent / (".media-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        (root / ".obsidian").mkdir()
        (root / "截图存放位置").mkdir()
        (root / "AI绘图存放位置").mkdir()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_plain_wikilink_markdown_link_and_html_img_protect_media(self):
        auditor = load_auditor()
        root = self.make_vault()
        paths = (
            root / "截图存放位置" / "plain-wiki.png",
            root / "AI绘图存放位置" / "markdown-link.svg",
            root / "截图存放位置" / "html-image.png",
        )
        for path in paths:
            path.write_text("<svg/>" if path.suffix == ".svg" else "image", encoding="utf-8")
        (root / "note.md").write_text(
            "[[截图存放位置/plain-wiki.png|查看原图]]\n"
            "[方法图](AI绘图存放位置/markdown-link.svg)\n"
            '<img src="截图存放位置/html-image.png" width="300">\n',
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertEqual(
            report["referenced"],
            [
                "AI绘图存放位置/markdown-link.svg",
                "截图存放位置/html-image.png",
                "截图存放位置/plain-wiki.png",
            ],
        )
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["unreferenced"], [])


if __name__ == "__main__":
    unittest.main()
