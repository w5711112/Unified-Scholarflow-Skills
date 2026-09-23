import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


SCRIPT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-note-style"
    / "scripts"
)
sys.path.insert(0, str(SCRIPT_ROOT))

import build_obsidian_knowledge_index as knowledge_index


build_index = knowledge_index.build_index


class ObsidianKnowledgeIndexTests(unittest.TestCase):
    def make_vault(self):
        root = Path(__file__).resolve().parent / (".knowledge-index-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def write_fixture_vault(self):
        root = self.make_vault()
        (root / ".obsidian").mkdir()
        nested = root / "a资料"
        nested.mkdir()
        (root / "z-note.md").write_text(
            "# Zeta\ntext ^z-block\n# alpha\ntext ^a-block\n",
            encoding="utf-8",
        )
        (nested / "中文笔记.md").write_text(
            "# 安全   规划\n正文 ^block-cn\n",
            encoding="utf-8",
        )
        for folder in (".hidden", "backup", "tmp"):
            (root / folder).mkdir()
            (root / folder / "ignored.md").write_text(
                "# Ignored\n正文 ^ignored\n",
                encoding="utf-8",
            )
        plugin_docs = root / "skill-with-plugin" / "example-plugin"
        plugin_docs.mkdir(parents=True)
        (plugin_docs / "SKILL.md").write_text("# Internal skill\n", encoding="utf-8")
        return root

    def test_discovers_real_vault_root_from_nested_project_directory(self):
        """Would fail if a nested project is mistaken for the Obsidian vault root."""
        root = self.make_vault()
        (root / ".obsidian").mkdir()
        (root / "root-note.md").write_text("# Root\n", encoding="utf-8")
        project = root / "project" / "research"
        project.mkdir(parents=True)

        index = build_index(project)

        self.assertEqual(index["vault"], str(root.resolve()))
        self.assertEqual(
            [record["path"] for record in index["files"]],
            ["root-note.md"],
        )

    def test_rejects_directory_outside_an_obsidian_vault(self):
        """Would fail if an arbitrary folder can silently become a fake vault root."""
        with self.assertRaisesRegex(ValueError, r"\.obsidian"):
            build_index(Path(r"C:\tmp\not-an-obsidian-vault-root-test"))

    def test_finds_all_existing_notes_by_basename_across_the_real_vault(self):
        """Would fail if note creation checks only the current project directory."""
        root = self.make_vault()
        (root / ".obsidian").mkdir()
        project = root / "project"
        project.mkdir()
        (root / "\u6df1\u5ea6\u5f3a\u5316\u5b66\u4e60.md").write_text("# Root\n", encoding="utf-8")
        (project / "\u6df1\u5ea6\u5f3a\u5316\u5b66\u4e60.md").write_text("# Duplicate\n", encoding="utf-8")
        finder = getattr(knowledge_index, "find_notes_by_basename", None)
        self.assertIsNotNone(finder, "missing whole-vault note ownership check")

        matches = finder(project, "\u6df1\u5ea6\u5f3a\u5316\u5b66\u4e60")

        self.assertEqual(
            [path.relative_to(root).as_posix() for path in matches],
            ["project/\u6df1\u5ea6\u5f3a\u5316\u5b66\u4e60.md", "\u6df1\u5ea6\u5f3a\u5316\u5b66\u4e60.md"],
        )

    def test_build_index_records_sorted_wikilink_targets_and_excludes_working_artifacts(self):
        """Would fail if headings/blocks/terms lose normalization, sorting, or exclusions."""
        root = self.write_fixture_vault()

        index = build_index(root)

        self.assertEqual(index["vault"], str(root.resolve()))
        self.assertEqual(
            index["files"],
            [
                {
                    "path": "a资料/中文笔记.md",
                    "headings": ["安全 规划"],
                    "block_ids": ["block-cn"],
                    "term_hits": ["block-cn", "安全 规划"],
                },
                {
                    "path": "z-note.md",
                    "headings": ["alpha", "zeta"],
                    "block_ids": ["a-block", "z-block"],
                    "term_hits": ["a-block", "alpha", "z-block", "zeta"],
                },
            ],
        )

    def test_excludes_tmp_prefixed_runtime_directory_without_matching_embedded_tmp(self):
        """Would fail if tmp-prefix filtering misses runtime artifacts or overmatches names."""
        root = self.make_vault()
        (root / ".obsidian").mkdir()
        runtime_tmp = root / "\u8fd0\u884c\u6570\u636e" / "tmpshwg_j9f"
        runtime_tmp.mkdir(parents=True)
        (runtime_tmp / "ignored.md").write_text("# Ignored\n", encoding="utf-8")
        ordinary = root / "knowledge-tmp-notes"
        ordinary.mkdir()
        (ordinary / "included.md").write_text("# Included\n", encoding="utf-8")

        index = build_index(root)

        self.assertEqual(
            [record["path"] for record in index["files"]],
            ["knowledge-tmp-notes/included.md"],
        )

    def test_permission_error_during_traversal_preserves_files_already_found(self):
        """Would fail if one denied directory aborts the complete index build."""
        root = self.make_vault()
        (root / ".obsidian").mkdir()
        kept = root / "kept.md"
        kept.write_text("# Kept\n", encoding="utf-8")

        def paths_then_error(_vault):
            yield kept
            raise PermissionError("denied runtime directory")

        with mock.patch("build_obsidian_knowledge_index.iter_markdown_files", side_effect=paths_then_error):
            try:
                index = build_index(root)
            except PermissionError as error:
                self.fail(f"build_index did not degrade after PermissionError: {error}")

        self.assertEqual([record["path"] for record in index["files"]], ["kept.md"])

    def test_cli_writes_utf8_json_index(self):
        """Would fail if the CLI omits the required UTF-8 JSON artifact."""
        root = self.write_fixture_vault()
        output = root / "知识索引.json"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_ROOT / "build_obsidian_knowledge_index.py"),
                "--vault",
                str(root),
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["files"][0]["path"], "a资料/中文笔记.md")
        self.assertEqual(payload["files"][0]["term_hits"], ["block-cn", "安全 规划"])


if __name__ == "__main__":
    unittest.main()
