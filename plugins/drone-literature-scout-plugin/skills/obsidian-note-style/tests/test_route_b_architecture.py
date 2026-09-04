import hashlib
import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
ENTRY = SKILL_ROOT / "SKILL.md"
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "SKILL.before-route-b.md"
ENTRY_REFS = [
    "references/style-profile.md",
    "references/knowledge-architecture-and-links.md",
    "references/formatting-and-evidence-contract.md",
    "references/formula-explanation-patterns.md",
    "references/cross-course-concept-bridges.md",
    "references/visual-media-lifecycle.md",
    "references/workflow-and-acceptance.md",
]
MANIFEST_REFS = [f"skills/obsidian-note-style/{ref}" for ref in ENTRY_REFS]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ObsidianRouteBArchitectureTests(unittest.TestCase):
    def test_legacy_fixture_is_compact_and_exact(self):
        authority = json.loads((SKILL_ROOT / "references" / "authority-map.json").read_text(encoding="utf-8"))
        self.assertEqual(sha256(FIXTURE), authority["compact_fixture_sha256"])
        self.assertLessEqual(FIXTURE.stat().st_size, 4096)
        self.assertTrue(FIXTURE.read_text(encoding="utf-8").startswith("---\nname:"))

    def test_manifest_registers_modular_contract_and_numeric_guards(self):
        data = json.loads((PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
        item = data["skills"]["obsidian-note-style"]
        self.assertEqual(item["migration_state"], "modular-v2")
        self.assertEqual(item["interface_version"], "1.1.0")
        self.assertEqual(item["references"], MANIFEST_REFS)
        self.assertEqual(item["evidence_objects"], [
            "NOTE_BASELINE",
            "KNOWLEDGE_PLACEMENT",
            "LINK_GRAPH",
            "VISUAL_DECISION",
            "NOTE_ACCEPTANCE",
        ])
        guards = item["numeric_guards"]
        self.assertEqual(guards["term_first_appearance_questions"], 5)
        self.assertEqual(guards["frozen_paper_hubs"], 2)
        self.assertEqual(guards["link_issue_categories"], 5)
        self.assertEqual(guards["images_per_knowledge_min"], 0)
        self.assertEqual(guards["images_per_knowledge_max"], 1)
        self.assertEqual(guards["paper_visual_audit_runs"], 1)
        self.assertEqual(guards["formula_long_sequence_steps"], 12)
        self.assertIn("global.renhua", item["calls"]["required_preprocess"])

    def test_entry_routes_each_reference_once_and_reuses_evidence(self):
        text = ENTRY.read_text(encoding="utf-8")
        for ref in ENTRY_REFS:
            self.assertEqual(text.count(ref), 1, ref)
            self.assertTrue((SKILL_ROOT / ref).is_file(), ref)
        for evidence_id in ("NOTE_BASELINE", "KNOWLEDGE_PLACEMENT", "LINK_GRAPH", "VISUAL_DECISION", "NOTE_ACCEPTANCE"):
            self.assertIn(evidence_id, text)
        self.assertIn("同一证据边界", text)
        self.assertIn("只生成并验证一次", text)

    def test_lossless_contract_and_authority_map(self):
        authority = json.loads((SKILL_ROOT / "references" / "authority-map.json").read_text(encoding="utf-8"))
        self.assertEqual(authority["compact_fixture_sha256"], sha256(FIXTURE))
        self.assertEqual(authority["unmapped_removed_blocks"], [])
        combined = ENTRY.read_text(encoding="utf-8") + "\n" + "\n".join(
            (SKILL_ROOT / ref).read_text(encoding="utf-8") for ref in ENTRY_REFS
        )
        required = [
            "使用我的 Obsidian 语言风格",
            "必须调用",
            "是什么 → 为什么 → 怎么做 → 适用条件/局限 → 延伸链接",
            "当前无人机论文项目的知识文件冻结",
            "安全控制与<YOUR_METHOD>.md",
            "路径规划与环境表示.md",
            "missing-file",
            "missing-heading",
            "missing-block",
            "ambiguous-file",
            "relocatable-file",
            "未确认不得写入",
            "每个本轮新增或扩充的正式知识点",
            "0` 或 `1` 张",
            "每篇论文只触发一次",
            "八项硬质量门槛",
            "论文报告",
            "可以推断",
            "尚不能证明",
            "canonical 与聚合说明",
        ]
        for phrase in required:
            self.assertIn(phrase, combined, phrase)
        for retired in ("互为字节级镜像", "修改任一侧"):
            self.assertNotIn(retired, combined, retired)

    def test_chinese_note_generation_uses_language_gate_and_beginner_data_flow(self):
        combined = ENTRY.read_text(encoding="utf-8") + "\n" + "\n".join(
            (SKILL_ROOT / ref).read_text(encoding="utf-8") for ref in ENTRY_REFS
        )
        required = (
            "专业语义草稿 → global.renhua → Obsidian 格式化",
            "格式化阶段新增实质性正文",
            "输入来源",
            "输入内容",
            "处理顺序",
            "输出的物理意义",
            "下游模块",
            "训练阶段与部署阶段",
            "论文未报告",
            "用于比较的基准方法（baseline）",
        )
        for phrase in required:
            self.assertIn(phrase, combined, phrase)

    def test_cross_section_dedup_preserves_information_at_one_semantic_home(self):
        contract = (SKILL_ROOT / "references" / "formatting-and-evidence-contract.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "唯一语义归属",
            "不减少事实、条件、数字、局限或复现缺口",
            "不得用同义句在相邻栏目重新陈述",
            "其他栏目只补充新的机制、条件、证据或边界",
        ):
            self.assertIn(phrase, contract, phrase)


if __name__ == "__main__":
    unittest.main()
