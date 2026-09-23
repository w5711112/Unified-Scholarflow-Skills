import unittest
import json
from pathlib import Path


SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "drone-literature-scout"
    / "SKILL.md"
)
NOTE_STYLE_SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-note-style"
    / "SKILL.md"
)
CONFIG = Path(__file__).resolve().parents[1] / "config.example.json"
READ_PAPER_SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "read-paper-analysis-highlight"
    / "SKILL.md"
)


class SkillContractTests(unittest.TestCase):
    def test_skill_contains_first_cycle_gate_and_strict_source_contract(self):
        text = SKILL.read_text(encoding="utf-8")
        required = (
            "first corpus audit",
            "official publisher/proceedings/DOI page",
            "Isaac Lab/vectorized RL",
            "RTX 4090 single-digit hours",
            "RTX 5070 Ti within one day",
            "Jetson-class deployment",
            "generic single-UAV obstacle avoidance",
            "UTF-8",
            "固定 15 列",
            "verification_date",
            "?? 占位符",
            "Markdown",
            "中文",
        )
        for phrase in required:
            self.assertIn(phrase, text)

    def test_obsidian_note_style_skill_requires_evidence_layered_detailed_writing(self):
        self.assertTrue(NOTE_STYLE_SKILL.exists())
        text = NOTE_STYLE_SKILL.read_text(encoding="utf-8")
        for phrase in ("论文报告", "量化算力", "不把推荐写成论文事实", "明确缺口"):
            self.assertIn(phrase, text)

    def test_obsidian_note_style_requires_full_vault_link_consistency(self):
        text = NOTE_STYLE_SKILL.read_text(encoding="utf-8")
        required = (
            "入链",
            "出链",
            "改名影响面",
            "全 Vault",
            "失效块",
            "不得创建空白占位笔记",
        )
        missing = [phrase for phrase in required if phrase not in text]
        self.assertFalse(missing, f"missing link-consistency rules: {missing}")

    def test_obsidian_note_style_owns_link_repair_failure_prevention(self):
        text = NOTE_STYLE_SKILL.read_text(encoding="utf-8")
        required = (
            "Vault 外",
            "扫描范围",
            "PowerShell 双引号",
            "Markdown 反引号",
            "CRLF",
            "检查器返回非零",
            "依赖缺失",
            "中断恢复",
        )
        missing = [phrase for phrase in required if phrase not in text]
        self.assertFalse(missing, f"missing link-repair prevention rules: {missing}")

    def test_example_schedule_has_only_the_two_requested_daily_times(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["cycle"]["daily_times"], ["10:00", "20:00"])

    def test_read_paper_canonical_skill_keeps_its_acceptance_contract(self):
        skill_bytes = READ_PAPER_SKILL.read_bytes()
        text = skill_bytes.decode("utf-8")
        for phrase in (
            "关系型证据原子",
            "逐图结构化审计",
            "固定故障路由",
            "中途增量验证",
            "最终全量验证",
        ):
            self.assertIn(phrase, text)

    def test_read_paper_prefers_local_zotero_pdf_and_preserves_original_meaning(self):
        text = READ_PAPER_SKILL.read_text(encoding="utf-8")
        required = (
            "Zotero PDF 跳转",
            "本地 PDF",
            "本地 PDF 可用时，不先抓取网页",
            "定义、公式、符号、下标、数量、几何形状、更新顺序、条件和边界",
            "不能改写成更强的绝对结论",
            "未从原文确认",
            "PDF 页码、公式号、图号或原文定义",
            "不增加新的全文阅读轮次",
        )
        missing = [phrase for phrase in required if phrase not in text]
        self.assertFalse(missing, f"missing paper-accuracy rules: {missing}")


if __name__ == "__main__":
    unittest.main()
