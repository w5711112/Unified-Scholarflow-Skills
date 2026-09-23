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
    spec = importlib.util.spec_from_file_location("audit_obsidian_media_fences", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ObsidianMediaFenceSafetyTests(unittest.TestCase):
    def make_vault(self) -> Path:
        root = Path(__file__).resolve().parent / (".media-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        (root / ".obsidian").mkdir()
        (root / "截图存放位置").mkdir()
        (root / "AI绘图存放位置").mkdir()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    @staticmethod
    def write_media(path: Path) -> None:
        path.write_bytes(b"media")

    def test_unclosed_fence_protects_raw_reference_and_blocks_deletion(self):
        auditor = load_auditor()
        root = self.make_vault()
        protected = root / "截图存放位置" / "仍在使用.png"
        orphan = root / "AI绘图存放位置" / "候选孤儿.svg"
        self.write_media(protected)
        self.write_media(orphan)
        (root / "note.md").write_text(
            "```cpp\n"
            "int main() {}\n"
            "正文中的图片：![[截图存放位置/仍在使用.png|700]]\n",
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertTrue(report["parse_warnings"])
        self.assertEqual(
            report["protected_by_raw_reference"],
            ["截图存放位置/仍在使用.png"],
        )
        self.assertEqual(report["unreferenced"], ["AI绘图存放位置/候选孤儿.svg"])
        with self.assertRaisesRegex(ValueError, "parse warning"):
            auditor.delete_unreferenced(report, apply=True)
        self.assertTrue(protected.exists())
        self.assertTrue(orphan.exists())

    def test_media_named_inside_closed_code_fence_is_conservatively_protected(self):
        auditor = load_auditor()
        root = self.make_vault()
        protected = root / "截图存放位置" / "示例图片.png"
        self.write_media(protected)
        (root / "note.md").write_text(
            "```markdown\n"
            "![[截图存放位置/示例图片.png|375]]\n"
            "```\n",
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertEqual(report["parse_warnings"], [])
        self.assertEqual(
            report["protected_by_raw_reference"],
            ["截图存放位置/示例图片.png"],
        )
        self.assertEqual(report["unreferenced"], [])

    def test_missing_raw_reference_is_reported_without_blocking_safe_deletion(self):
        auditor = load_auditor()
        root = self.make_vault()
        orphan = root / "AI绘图存放位置" / "候选孤儿.svg"
        self.write_media(orphan)
        (root / "note.md").write_text(
            "```text\n"
            "![[截图存放位置/已经丢失.png|500]]\n"
            "```\n",
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertEqual(
            report["raw_missing"],
            [{"source": "note.md", "target": "截图存放位置/已经丢失.png"}],
        )
        deleted = auditor.delete_unreferenced(report, apply=True)
        self.assertEqual(deleted, ["AI绘图存放位置/候选孤儿.svg"])
        self.assertFalse(orphan.exists())

    def test_semantic_missing_reference_blocks_deletion(self):
        auditor = load_auditor()
        root = self.make_vault()
        orphan = root / "AI绘图存放位置" / "候选孤儿.svg"
        self.write_media(orphan)
        (root / "note.md").write_text(
            "正文图片：![[截图存放位置/已经丢失.png|500]]\n",
            encoding="utf-8",
        )

        report = auditor.audit_vault_media(root)

        self.assertEqual(
            report["missing"],
            [{"source": "note.md", "target": "截图存放位置/已经丢失.png"}],
        )
        with self.assertRaisesRegex(ValueError, "unresolved media reference"):
            auditor.delete_unreferenced(report, apply=True)
        self.assertTrue(orphan.exists())



if __name__ == "__main__":
    unittest.main()
