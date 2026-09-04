from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractV3Tests(unittest.TestCase):
    def test_skill_declares_v3_evidence_and_zotero_coordinate_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "Zotero 9",
            "PDF /Square",
            "PDF /Ink",
            "证据原子",
            "第一行必须先给结论",
            "不设置字符上限",
            "方法名",
            "baseline",
            "参考文献角色",
            "key-link",
            "pymupdf-page-top-left",
            "pdf-page-bottom-left",
            "zotero_rect",
            "外部信息：",
            "中间文件",
            "自动翻译后缀",
            "逐字相等",
            "分别计数",
            "干净 backup",
            "一眼记住这篇论文",
            "通过什么原理",
            "构建什么结构",
            "实现什么效果",
            "Obsidian URI",
            "PDF 首页左上角",
            "返回 Obsidian的对应精读位置",
            "obsidian-link.invalid",
            "Zotero 内置阅读器",
            "协议能力预检",
            "权限预检",
            "obsidian-note-style",
            "0x80070005",
            "20 分钟",
            "默认不限制完成时间",
            "Python -X utf8",
            "PowerShell",
            "旧批注",
            "坐标往返",
            "Interesting（问题值得研究吗）",
            "Solvable（问题可解吗）",
            "Current level（当前研究水平）",
            "Impactful（问题影响大吗）",
            "新旧问题/方法分类",
            "What / Why / How",
            "Pros / Cons",
            "如何拓展与利用",
            "python -m pip install",
            "安装后重新 import",
            "launchWithURI",
            "Zotero.launchURL",
            "不可见会话",
            "离线原位升级",
            "plugin_installation_normalized",
            "行为门槛",
            "默认无界面",
            "ui_gate_pending",
            "不得抢占鼠标",
        )
        missing = [term for term in required if term not in text]
        self.assertFalse(missing, f"missing V3 skill terms: {missing}")

    def test_source_line_and_block_anchor_rules_do_not_conflict(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "来源第一行的下载链接、DOI、Zotero key、等级与标点原样保留；"
            "唯一 `^block-id` 必须单独放在论文标题下方、主 Callout 之前",
            text,
        )
        self.assertNotIn("标点与 block ID 原样保留", text)

    def test_pdf_contract_declares_both_coordinate_spaces_and_comment_depth(self):
        text = (ROOT / "references" / "pdf-annotation-contract.md").read_text(
            encoding="utf-8"
        )
        required = (
            "schema_version",
            "PDF /Square",
            "PDF /Ink",
            "pymupdf-page-top-left",
            "pdf-page-bottom-left",
            "zotero_rect",
            "结论：",
            "外部信息：",
            "不设置字符上限",
            "URL 可达性",
        )
        missing = [term for term in required if term not in text]
        self.assertFalse(missing, f"missing V3 PDF contract terms: {missing}")

    def test_v3_helper_scripts_are_part_of_the_skill(self):
        required = (
            "pdf_coordinate_spaces.py",
            "annotation_comment_quality.py",
            "check_evidence_urls.py",
            "augment_pdf_memory_layer.py",
            "build_zotero_native_annotation_plan.py",
            "zotero_local_bridge_client.py",
            "validation_gate_cache.py",
        )
        for name in required:
            with self.subTest(name=name):
                self.assertTrue((ROOT / "scripts" / name).is_file())

    def test_zotero_local_bridge_integration_is_packaged(self):
        integration = ROOT.parents[1] / "integrations" / "zotero-local-bridge"
        for name in (
            "manifest.json",
            "bootstrap.js",
            "link_bridge.js",
            "annotation_bridge.js",
            "README.md",
        ):
            with self.subTest(name=name):
                self.assertTrue((integration / name).is_file())

    def test_skill_assigns_unique_responsibilities_and_no_console_fallback(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "`read-paper-analysis-highlight` 唯一负责批注选择、评论、颜色、坐标转换",
            "`zotero-local-bridge` 只负责",
            "`global.collect-bug-update-accelerate` 只记录并路由",
            "preflight",
            "apply",
            "原生读回",
        ):
            self.assertIn(phrase, text)
        for phrase in (
            "build_zotero_native_area_script.py",
            "执行 JavaScript",
            "Zotero.Annotations.saveFromJSON",
        ):
            self.assertNotIn(phrase, text)

    def test_pdf_and_reading_contracts_require_relations_and_figure_audits(self):
        pdf_text = (
            ROOT / "references" / "pdf-annotation-contract.md"
        ).read_text(encoding="utf-8")
        for term in (
            "relation_group_id",
            "relation_role",
            "relation_type",
            "relation_summary",
            "connector_mode",
            "native-ink",
            "shared-id",
            "discourse scaffolding",
        ):
            self.assertIn(term, pdf_text)

        reading_text = (
            ROOT / "references" / "full-reading-protocol.md"
        ).read_text(encoding="utf-8")
        for term in (
            "schema_version: 4",
            "figure_audits",
            "observed_claims",
            "text_formula_table_consistency",
            "limitations_or_anomalies",
            "annotation_regions",
        ):
            self.assertIn(term, reading_text)

    def test_skill_declares_incremental_and_final_gate_policy(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for term in (
            "validation_gate_cache.py",
            "输入指纹",
            "已通过且输入未变",
            "失败门槛",
            "受影响的下游门槛",
            "最终交付前",
            "从新鲜输入完整运行",
        ):
            self.assertIn(term, text)

if __name__ == "__main__":
    unittest.main()
