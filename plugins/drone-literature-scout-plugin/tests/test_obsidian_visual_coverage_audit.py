from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PLUGIN_ROOT
    / "skills"
    / "obsidian-note-style"
    / "scripts"
    / "audit_obsidian_visual_coverage.py"
)


def load_auditor():
    if not SCRIPT.is_file():
        raise AssertionError(f"visual coverage auditor is missing: {SCRIPT}")
    spec = importlib.util.spec_from_file_location(
        "audit_obsidian_visual_coverage", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ObsidianVisualCoverageAuditTests(unittest.TestCase):
    def make_vault(self) -> Path:
        root = Path(__file__).resolve().parent / (".visual-audit-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        (root / ".obsidian").mkdir()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_records_heading_sections_and_ignores_fenced_or_internal_artifacts(self):
        auditor = load_auditor()
        root = self.make_vault()
        (root / "知识.md").write_text(
            "# PPO\n"
            "正文\n"
            "![[AI绘图存放位置/PPO原理.png|800]]\n"
            "## Clip\n"
            "正文\n"
            "```markdown\n"
            "# 伪标题\n"
            "![[AI绘图存放位置/伪图片.png]]\n"
            "```\n"
            "# SDCQ\n"
            "正文\n",
            encoding="utf-8",
        )
        internal = root / "docs" / "superpowers"
        internal.mkdir(parents=True)
        (internal / "plan.md").write_text("# 内部计划\n", encoding="utf-8")
        plugin = root / "skill-with-plugin" / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "SKILL.md").write_text("# 内部 Skill\n", encoding="utf-8")

        report = auditor.audit_visual_coverage(root)

        self.assertEqual(report["scanned_markdown"], 1)
        self.assertEqual(
            report["sections"],
            [
                {
                    "path": "知识.md",
                    "heading": "PPO",
                    "level": 1,
                    "line": 1,
                    "managed_images": ["AI绘图存放位置/PPO原理.png"],
                    "has_managed_image": True,
                },
                {
                    "path": "知识.md",
                    "heading": "Clip",
                    "level": 2,
                    "line": 4,
                    "managed_images": [],
                    "has_managed_image": False,
                },
                {
                    "path": "知识.md",
                    "heading": "SDCQ",
                    "level": 1,
                    "line": 10,
                    "managed_images": [],
                    "has_managed_image": False,
                },
            ],
        )

    def test_cli_prints_utf8_json_without_creating_a_persistent_report(self):
        root = self.make_vault()
        (root / "知识.md").write_text("# B-spline\n正文\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(root), "--json"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["sections"][0]["heading"], "B-spline")
        self.assertEqual(list(root.glob("*visual*json")), [])


if __name__ == "__main__":
    unittest.main()
