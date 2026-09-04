import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_contract_files_exist(self):
        required = [
            ROOT / "SKILL.md",
            ROOT / "agents" / "openai.yaml",
            ROOT / "references" / "full-reading-protocol.md",
            ROOT / "references" / "obsidian-callout-template.md",
            ROOT / "references" / "pdf-annotation-contract.md",
            ROOT / "scripts" / "annotate_pdf.py",
            ROOT / "scripts" / "verify_annotation_manifest.py",
            ROOT / "scripts" / "semantic_selection.py",
            ROOT / "scripts" / "validate_reading_ledger.py",
            ROOT / "scripts" / "validate_completion.py",
            ROOT / "scripts" / "validation_gate_cache.py",
            ROOT / "scripts" / "build_zotero_native_annotation_plan.py",
            ROOT / "scripts" / "zotero_local_bridge_client.py",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        self.assertFalse(missing, f"missing skill contract files: {missing}")

    def test_skill_contract_requires_evidence_first_callout_and_overwrite_safety(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8").lower()
        required_terms = [
            "zotero-obsidian-paper-import",
            "application/pdf",
            "full-text",
            "callout",
            "supporting links",
            "sha-256",
            "backup",
            "overwrite",
            "annotation manifest",
            "do not invent",
        ]
        missing = [term for term in required_terms if term not in text]
        self.assertFalse(missing, f"missing contract terms: {missing}")

    def test_skill_contract_requires_question_led_note_and_explicit_unknowns(self):
        template = (ROOT / "references" / "obsidian-callout-template.md").read_text(
            encoding="utf-8"
        ).lower()
        for term in (
            "what did the authors try to accomplish",
            "what were the key elements",
            "what can you use yourself",
            "what other references",
            "尚不能证明",
            "支撑链接",
        ):
            self.assertIn(term.lower(), template)

    def test_skill_requires_semantic_spans_native_zotero_and_no_quota(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "独立信息价值", "不设置", "数量", "quote", "quads", "逐页台账",
            "图表", "preflight", "apply", "zotero-native", "可编辑", "可删除",
            "已AI全文读", "we propose", "success rate remains",
        )
        for term in required:
            self.assertIn(term, text)

    def test_skill_requires_authors_exact_pages_knowledge_links_and_open_selection(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "不设死板名单",
            "（PDF第 N 页）",
            "共同一作和通讯作者",
            "作者与团队背景",
            "Google Scholar",
            "QS",
            "外部核验，不是论文正文事实",
            "知识索引",
            "[[笔记#标题|别名]]",
            "[[笔记#^block-id|别名]]",
            "论文明确承认的局限",
            "未报告与疑点",
            "嵌套折叠",
        )
        for term in required:
            self.assertIn(term, text)

    def test_skill_requires_first_author_student_stage_and_year_without_guessing(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for term in (
            "一作/共同一作",
            "硕士生还是博士生",
            "具体年级",
            "已毕业/当前非在读",
            "未公开核验",
            "不得根据入学年份自行推算",
        ):
            self.assertIn(term, text)

    def test_skill_requires_specialized_native_bridge_execution(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "zotero-local-bridge",
            "build_zotero_native_annotation_plan.py",
            "zotero_local_bridge_client.py",
            "health",
            "preflight",
            "apply",
            "原子执行",
            "原生读回",
            "禁止直接写 SQLite",
        )
        for term in required:
            self.assertIn(term, text)
        forbidden = (
            "build_zotero_native_area_script.py",
            "zotero-obsidian-link-bridge",
            "执行 JavaScript",
            "Zotero.Annotations.saveFromJSON",
            'new Zotero.Item("annotation")',
        )
        for term in forbidden:
            self.assertNotIn(term, text)

    def test_skill_requires_relational_evidence_visual_audits_and_fixed_routing(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "关系型证据原子",
            "技术实体 → 谓词/动作 → 作用对象/效果 → 条件/边界",
            "连接词只用于定位候选",
            "保留否定、范围、模态、数值限定",
            "incurs cumulative latency",
            "lack theoretical safety guarantees",
            "out-of-distribution generalization failures",
            "tightly couples reinforcement learning with model-based safety mechanisms",
            "alleviates local minima in Euclidean distance objectives",
            "逐图结构化审计",
            "Zotero 原生 Ink",
            "失败闭合",
            "固定故障路由",
            "中途增量验证",
            "最终全量验证",
            "不重复运行",
            "Computer Use",
        )
        missing = [term for term in required if term not in text]
        self.assertFalse(missing, f"missing relational/visual/runtime terms: {missing}")

    def test_knowledge_points_require_intuition_then_mathematical_principle(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        template = (
            ROOT / "references" / "obsidian-callout-template.md"
        ).read_text(encoding="utf-8")
        required_skill_terms = (
            "知识点递进解释合同",
            "第一层：直觉理解",
            "第二层：公式与原理",
            "先直觉、后数学",
            "不得只用图代替公式",
            "最小推导",
            "数值代入或极端情形",
            "够用即止",
            "同一结论只说一次",
            "正文说明 → 现有图 → 读图与图例 → 公式与原理",
            "论文 Callout 只保留本文用途",
        )
        required_template_terms = (
            "第一层｜直觉理解",
            "第二层｜公式与原理",
            "公式原文",
            "逐符号解释",
            "最小推导",
            "回扣直觉",
            "现有合格图不修改",
            "只保留理解下一层所需的内容",
            "同一结论不换句话重复",
            "知识点总标题只写标准名称",
            "第一层｜直觉理解 | 一句话本质",
            "只用同领域的最简概念作比较",
            "不用生活类比",
        )
        self.assertFalse(
            [term for term in required_skill_terms if term not in skill],
            "skill must require progressive knowledge-point explanations",
        )
        self.assertFalse(
            [term for term in required_template_terms if term not in template],
            "template must expose both intuition and mathematical layers",
        )

if __name__ == "__main__":
    unittest.main()
