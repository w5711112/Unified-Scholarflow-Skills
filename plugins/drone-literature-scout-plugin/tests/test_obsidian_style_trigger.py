from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class ObsidianStyleTriggerTests(unittest.TestCase):
    def test_surface_metadata_uses_canonical_skill_name(self):
        metadata_path = (
            PLUGIN_ROOT
            / "skills"
            / "obsidian-note-style"
            / "agents"
            / "openai.yaml"
        )
        self.assertTrue(metadata_path.is_file())
        metadata = metadata_path.read_text(encoding="utf-8")
        self.assertIn('display_name: "Obsidian Note Style"', metadata)
        self.assertIn("$obsidian-note-style", metadata)
        self.assertNotIn("obsidian-" + "research-voice", metadata)
        self.assertNotIn("Obsidian " + "Research Voice", metadata)
    def test_user_style_phrase_is_bound_to_style_skill(self):
        style = (PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md").read_text(encoding="utf-8")
        drone = (PLUGIN_ROOT / "skills" / "drone-literature-scout" / "SKILL.md").read_text(encoding="utf-8")
        required = ("使用我的 Obsidian 语言风格", "obsidian-note-style", "必须调用")
        for phrase in required:
            self.assertIn(phrase, style)
            self.assertIn(phrase, drone)

    def test_unordered_list_items_have_no_terminal_punctuation_rule(self):
        style = (
            PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md"
        ).read_text(encoding="utf-8")
        required = (
            "无序列表项的最后一个可见内容字符通常不保留任何收尾标点",
            "`。`、`．`、`.`、`；`、`;`、`：`、`:`、`，`、`,`、`、`",
            "问号、感叹号",
            "代码块、Frontmatter、原始引用、URL 和公式",
            "canonical",
        )
        for phrase in required:
            self.assertIn(phrase, style)

    def test_canonical_domain_skills_declare_the_same_trigger(self):
        skill_files = (
            PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md",
            PLUGIN_ROOT / "skills" / "zotero-obsidian-paper-import" / "SKILL.md",
            PLUGIN_ROOT / "skills" / "drone-literature-scout" / "SKILL.md",
            PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "SKILL.md",
        )
        for path in skill_files:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(any(trigger in text for trigger in ("使用我的 Obsidian 语言风格", "用户要求自己的 Obsidian 风格")), str(path))
            self.assertIn("obsidian-note-style", text, path.name)


if __name__ == "__main__":
    unittest.main()


