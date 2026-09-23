import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "SKILL.md"
FIXTURE = ROOT / "tests" / "fixtures" / "SKILL.before-route-b.md"
AUTHORITY_MAP = ROOT / "references" / "authority-map.json"

DIRECT_REFERENCES = (
    "references/identity-state-and-capability-contract.md",
    "references/full-reading-protocol.md",
    "references/pdf-annotation-contract.md",
    "references/author-research-contract.md",
    "references/obsidian-callout-template.md",
    "references/zotero-memory-link-and-ui-contract.md",
    "references/runtime-validation-and-cleanup.md",
)

EVIDENCE_OBJECTS = (
    "PAPER_BASELINE",
    "READING_LEDGER",
    "CLAIM_EVIDENCE_MAP",
    "AUTHOR_EVIDENCE",
    "VERSION_RECONCILIATION",
    "LANGUAGE_GATE",
    "NOTE_PACKAGE",
    "ANNOTATION_PLAN",
    "NATIVE_READBACK",
    "PAPER_ACCEPTANCE",
)


class RouteBArchitectureTests(unittest.TestCase):
    def test_legacy_fixture_is_compact_and_exact(self):
        data = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
        self.assertTrue(FIXTURE.is_file())
        self.assertEqual(data["compact_fixture_sha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertLessEqual(FIXTURE.stat().st_size, 4096)
        self.assertTrue(FIXTURE.read_text(encoding="utf-8").startswith("---\nname:"))

    def test_entry_is_a_compact_one_level_router(self):
        text = ENTRY.read_text(encoding="utf-8")
        self.assertLessEqual(len(ENTRY.read_bytes()), 22000)
        for reference in DIRECT_REFERENCES:
            with self.subTest(reference=reference):
                self.assertEqual(1, text.count(f"`{reference}`"))
                self.assertTrue((ROOT / reference).is_file())
        for evidence in EVIDENCE_OBJECTS:
            with self.subTest(evidence=evidence):
                self.assertIn(f"`{evidence}`", text)
        self.assertIn("直接参考不得继续路由第二层参考", text)

    def test_hard_numeric_and_quality_guards_remain_at_entry(self):
        text = ENTRY.read_text(encoding="utf-8")
        for phrase in (
            "20 分钟",
            "schema_version: 4",
            "Zotero 9.0.6",
            "≤ 0.01 pt",
            "150–200 dpi",
            "bridge_url_count = 1",
            "direct_obsidian_uri_count = 0",
            "不设置字符上限",
            "每页恰好一条",
            "每篇论文只触发一次",
            "八项硬质量门槛",
            "最终全量验证",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_author_and_block_anchor_conflicts_follow_main_skill(self):
        author = (ROOT / "references" / "author-research-contract.md").read_text(
            encoding="utf-8"
        )
        template = (ROOT / "references" / "obsidian-callout-template.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不得创建独立作者/团队笔记", author)
        self.assertNotIn("完整作者履历写入唯一的作者/团队知识位置", author)
        self.assertIn("^BLOCK-ID\n> [!note]- **来源**", template)
        self.assertNotIn("状态：待精读 ^BLOCK-ID", template)

    def test_authority_map_is_record_only_and_complete(self):
        data = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
        self.assertEqual("record-only", data["authority"])
        self.assertEqual(
            "bfcb85a226d22149f76549d85d315f71be2683a2f7dc351a1efd033fe954eeb3",
            data["legacy_sha256"],
        )
        self.assertEqual(785, data["legacy_lines"])
        self.assertEqual(list(DIRECT_REFERENCES), data["direct_references"])
        self.assertEqual(list(EVIDENCE_OBJECTS), data["evidence_objects"])
        self.assertEqual([], data["missing_legacy_requirements"])

    def test_beginner_module_contract_and_language_handoffs_are_mandatory(self):
        manifest = json.loads(
            (ROOT.parents[1] / "architecture-manifest.json").read_text(encoding="utf-8")
        )["skills"]["read-paper-analysis-highlight"]
        self.assertEqual("modular-v2", manifest["migration_state"])
        self.assertEqual("1.2.0", manifest["interface_version"])
        self.assertEqual(8, manifest["numeric_guards"]["module_explanation_fields"])
        self.assertEqual(1, manifest["numeric_guards"]["language_gate_schema_version"])
        self.assertEqual(
            1,
            manifest["numeric_guards"]["version_reconciliation_schema_version"],
        )
        self.assertIn("global.renhua", manifest["calls"]["required_preprocess"])

        combined = ENTRY.read_text(encoding="utf-8") + "\n" + "\n".join(
            (ROOT / reference).read_text(encoding="utf-8")
            for reference in DIRECT_REFERENCES
        )
        for phrase in (
            "模块任务",
            "输入来源",
            "输入内容",
            "实际处理顺序",
            "输出的物理意义",
            "下游接口",
            "训练阶段与部署阶段",
            "条件与失效边界",
            "一眼记住这篇论文",
            "1–3 个完整句子",
            "不能用术语替代解释",
            "论文未报告",
            "专业语义草稿 → global.renhua → obsidian-note-style",
        ):
            self.assertIn(phrase, combined, phrase)

    def test_reader_facing_note_uses_canonical_claim_homes_without_page_labels(self):
        full_reading = (ROOT / "references" / "full-reading-protocol.md").read_text(
            encoding="utf-8"
        )
        template = (ROOT / "references" / "obsidian-callout-template.md").read_text(
            encoding="utf-8"
        )

        # Internal evidence keeps page coordinates, while the completed reader-facing
        # callout shows only stable document objects such as equations and figures.
        self.assertIn("内部证据台账继续保留 PDF 文件页码", full_reading)
        self.assertIn("完成态 `已AI全文读` Callout 不显示 `（PDF第 N 页）`", template)
        for anchor in ("公式", "图", "表", "算法"):
            self.assertIn(anchor, template)

        # The note contract assigns each conclusion one semantic home. Other fields
        # may point back to it, but may not paraphrase the conclusion as fresh text.
        for phrase in (
            "唯一语义归属",
            "不得用同义改写再次陈述",
            "Interesting 只回答",
            "Solvable 只回答",
            "Current level 只回答",
            "Impactful 只回答",
        ):
            self.assertIn(phrase, full_reading + "\n" + template, phrase)

    def test_completed_ai_callout_always_creates_or_preserves_personal_callout(self):
        template = (ROOT / "references" / "obsidian-callout-template.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "每次生成完成态 AI Callout 时同步生成",
            "新建时只写空的 `> [!personal]+ 个人理解`",
            "已有个人理解逐字保留",
            "不得出现只有 AI Callout、没有个人理解 Callout",
        ):
            self.assertIn(phrase, template, phrase)


if __name__ == "__main__":
    unittest.main()
