import shutil
import sys
import unittest
import uuid
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "skills" / "obsidian-note-style" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from check_obsidian_links import repair_links, scan_vault


class ObsidianLinkCheckerTests(unittest.TestCase):
    def make_vault(self):
        root = Path(__file__).resolve().parent / (".link-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        (root / ".obsidian").mkdir()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_scans_real_vault_when_started_from_nested_project(self):
        """Would fail if link validation is limited to the current project directory."""
        root = self.make_vault()
        (root / "target.md").write_text("# Existing\n", encoding="utf-8")
        project = root / "project"
        project.mkdir()
        (project / "source.md").write_text("[[target#Existing|target]]\n", encoding="utf-8")

        report = scan_vault(project)

        self.assertEqual(report.markdown_files, 2)
        self.assertEqual(report.issues, [])

    def test_reports_missing_file_heading_and_block_but_ignores_fenced_examples(self):
        root = self.make_vault()
        (root / "target.md").write_text("# Existing\n正文 ^known-block\n", encoding="utf-8")
        (root / "source.md").write_text(
            "[[target#Existing|有效标题]]\n"
            "[[target#^known-block|有效块]]\n"
            "[[missing|缺失文件]]\n"
            "[[target#Missing|缺失标题]]\n"
            "[[target#^missing-block|缺失块]]\n"
            "```markdown\n[[not-real|代码示例]]\n```\n",
            encoding="utf-8",
        )

        report = scan_vault(root)

        self.assertEqual(
            [(issue.kind, issue.target) for issue in report.issues],
            [
                ("missing-file", "missing"),
                ("missing-heading", "target#Missing"),
                ("missing-block", "target#^missing-block"),
            ],
        )

    def test_ignores_wiki_links_inside_inline_code(self):
        root = self.make_vault()
        (root / "source.md").write_text(
            "真实：[[missing|应报告]]\n"
            "示例：`[[example#Heading|不应报告]]`\n"
            "双反引号：``[[another#^block|也不应报告]]``\n",
            encoding="utf-8",
        )

        report = scan_vault(root)

        self.assertEqual([(issue.kind, issue.target) for issue in report.issues], [("missing-file", "missing")])

    def test_accepts_escaped_alias_separator_in_markdown_table_wikilink(self):
        r"""Obsidian tables require ``\|`` so the alias pipe does not split columns."""
        root = self.make_vault()
        (root / "target.md").write_text("# Existing\n", encoding="utf-8")
        (root / "source.md").write_text(
            "| 方法 | 说明 |\n"
            "| --- | --- |\n"
            "| [[target#Existing\\|简短别名]] | 有效链接 |\n",
            encoding="utf-8",
        )

        report = scan_vault(root)

        self.assertEqual(report.issues, [])

    def test_repairs_only_unique_moved_basename_and_preserves_anchor(self):
        root = self.make_vault()
        (root / "moved").mkdir()
        (root / "moved" / "note.md").write_text("# Methods\n", encoding="utf-8")
        source = root / "source.md"
        source.write_text("[[old-place/note#Methods|方法]]\n", encoding="utf-8")

        changes = repair_links(root)

        self.assertEqual(changes, 1)
        self.assertEqual(source.read_text(encoding="utf-8"), "[[moved/note#Methods|方法]]\n")

    def test_repair_preserves_existing_lf_line_endings(self):
        """Would fail if a Windows repair rewrites an LF note as CRLF."""
        root = self.make_vault()
        (root / "moved").mkdir()
        (root / "moved" / "note.md").write_bytes("# Methods\n".encode("utf-8"))
        source = root / "source.md"
        source.write_bytes("[[old-place/note#Methods|方法]]\n下一行\n".encode("utf-8"))

        changes = repair_links(root)

        self.assertEqual(changes, 1)
        self.assertEqual(
            source.read_bytes(),
            "[[moved/note#Methods|方法]]\n下一行\n".encode("utf-8"),
        )

    def test_skips_hidden_and_temporary_directories_before_recursing(self):
        root = self.make_vault()
        for folder in (".codex-test-tmp", "tmp_unreadable", "临时测试目录"):
            (root / folder).mkdir()
            (root / folder / "ignored.md").write_text("[[missing]]\n", encoding="utf-8")

        report = scan_vault(root)

        self.assertEqual(report.markdown_files, 0)
        self.assertEqual(report.issues, [])
    def test_does_not_scan_excluded_folders(self):
        root = self.make_vault()
        for folder in ("<NOTE_VAULT_NAME>", "无人机方向分析kimi"):
            (root / folder).mkdir()
            (root / folder / "ignored.md").write_text("[[missing]]\n", encoding="utf-8")

        report = scan_vault(root)

        self.assertEqual(report.markdown_files, 0)
        self.assertEqual(report.issues, [])


if __name__ == "__main__":
    unittest.main()
