from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_paper_note import validate_paper_note  # noqa: E402
from test_support import writable_test_directory  # noqa: E402


BLOCK_ID = "paper-fixture"
KNOWLEDGE_TARGET = "Sim2real与实机部署#^isaac-lab-definition"
MEMORY_SENTENCE = (
    "Dijkstra/ESDF 解决“往哪绕”，HOCBF-QP 负责“动作能不能执行”："
    "以“策略快飞 + 模型兜底”的双层结构实现高速避障。"
)
MEMORY_LINE = f"> - **一眼记住这篇论文**：=={MEMORY_SENTENCE}=="


def source_line(status: str = "待精读") -> str:
    return (
        "> [!note]- **来源**：[DOI](https://doi.org/10.0000/fixture)，"
        "[Zotero的PDF](zotero://open-pdf/library/items/ABC123)。"
        f"A，状态：{status}"
    )


def paper_block(status: str = "待精读") -> str:
    return f"""### Fixture Paper
^{BLOCK_ID}
{source_line(status)}
{MEMORY_LINE}
>   > [!info]- **作者与团队背景**
>   > - Alice Example：共同一作。
>   > - Bob Example：通讯作者。
>   >
>   > [!info]- **概念解释：为什么使用安全过滤器？**
>   > - 它在动作执行前检查约束。
> - **作者贡献**
>   - **训练期几何塑形**：把路径进展与安全趋势写入奖励，改变策略形成方式；它是训练设计，不是新的安全定理（PDF第 2、3 页）（公式 1）。
> - **研究问题审计：Interesting / Solvable / Current level / Impactful？**
>   - **Interesting（问题值得研究吗）**：值得。
>   - **Solvable（问题可解吗）**：条件可解。
>   - **Current level（当前研究水平）**：系统前沿。
>   - **Impactful（问题影响大吗）**：影响明确。
>   - **新旧问题/方法分类**：老问题、成熟方法的新组合。
> - **What / 研究的问题是什么？**
>   - 约束定义见（PDF第 3 页）（公式 1）。
> - **Why / 为什么要研究？**
>   - 现有系统存在可验证的缺口。
> - **How / 使用的方法是什么？**
>   - 约束定义见（PDF第 3 页）（公式 1）。
>   - 实验装置见（PDF第 4 页）（图 2）。
>   - 消融结果见（PDF第 5 页）（表 II）。
> - **Pros / Cons：优缺点是什么？**
>   - **Pros**：过滤器可检查。
>   - **Cons**：仍依赖模型。
> - **论文明确承认的局限**
>   - 只验证了单一平台。
> - **未报告与疑点**
>   - 未报告跨平台结果。
> - **支撑链接**
>   - [[{KNOWLEDGE_TARGET}|Isaac Lab]]
> - **PDF 原文标注**
>   - 第 3 页公式已标注。
> - **如何拓展与利用？**
>   - 复用接口并扩展到新平台。
"""


class PaperNoteTests(unittest.TestCase):
    def validate(
        self,
        block: str,
        *,
        prefix: str = "",
        suffix: str = "",
        links: list[dict] | None = None,
        author_source_line: str | None = source_line(),
        knowledge_source_line: str | None = None,
    ) -> dict:
        with writable_test_directory() as tmp:
            root = Path(tmp)
            note_path = root / "note.md"
            author_path = root / "authors.json"
            knowledge_path = root / "knowledge.json"
            note_path.write_text(prefix + block + suffix, encoding="utf-8")
            author_payload = {
                "designated_authors": [
                    {"name": "Alice Example", "roles": ["co-first"]},
                    {"name": "Bob Example", "roles": ["corresponding"]},
                ]
            }
            if author_source_line is not None:
                author_payload["source_line"] = author_source_line
            author_path.write_text(json.dumps(author_payload), encoding="utf-8")

            knowledge_payload = {
                "links": links
                if links is not None
                else [
                    {
                        "target": f"[[{KNOWLEDGE_TARGET}|Isaac Lab]]",
                        "target_exists": True,
                    }
                ]
            }
            if knowledge_source_line is not None:
                knowledge_payload["source_line"] = knowledge_source_line
            knowledge_path.write_text(
                json.dumps(knowledge_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            return validate_paper_note(
                note_path, BLOCK_ID, author_path, knowledge_path
            )

    def test_valid_target_block_returns_detailed_boolean_report(self):
        prefix = """### Other Paper
This unrelated block contains forbidden p. 9559.

"""
        report = self.validate(paper_block(), prefix=prefix)
        self.assertTrue(report["valid"], report["failures"])
        for field in (
            "block_id_valid",
            "printed_page_references_valid",
            "pdf_page_reference_valid",
            "main_callout_valid",
            "author_section_valid",
            "nested_concepts_valid",
            "author_contributions_valid",
            "author_contribution_emphasis_valid",
            "author_contribution_evidence_valid",
            "limitations_valid",
            "unreported_questions_valid",
            "support_links_valid",
            "pdf_annotations_valid",
            "designated_authors_valid",
            "knowledge_links_valid",
            "source_line_baseline_valid",
            "source_line_preserved",
            "memory_sentence_valid",
            "memory_sentence_position_valid",
            "compact_pdf_page_references_valid",
            "problem_interest_valid",
            "problem_solvability_valid",
            "research_level_valid",
            "problem_impact_valid",
            "novelty_classification_valid",
            "what_valid",
            "why_valid",
            "how_valid",
            "pros_cons_valid",
            "extension_reuse_valid",
        ):
            self.assertIs(report.get(field), True, field)
        self.assertEqual(report["failures"], [])
        self.assertIn("### Fixture Paper", report["block"])
        self.assertNotIn("Other Paper", report["block"])

    def test_author_contribution_field_is_required(self):
        contribution = (
            "> - **作者贡献**\n"
            ">   - **训练期几何塑形**：把路径进展与安全趋势写入奖励，"
            "改变策略形成方式；它是训练设计，不是新的安全定理"
            "（PDF第 2、3 页）（公式 1）。\n"
        )
        report = self.validate(paper_block().replace(contribution, ""))
        self.assertFalse(report["valid"])
        self.assertIs(report.get("author_contributions_valid"), False)
        self.assertIn("missing author contributions", report["failures"])

    def test_author_contribution_requires_a_bold_core_phrase_beyond_label(self):
        report = self.validate(
            paper_block().replace(
                "**训练期几何塑形**",
                "训练期几何塑形",
            )
        )
        self.assertFalse(report["valid"])
        self.assertIs(report.get("author_contributions_valid"), True)
        self.assertIs(report.get("author_contribution_emphasis_valid"), False)
        self.assertIn(
            "author contribution needs a bold core phrase beyond the field label",
            report["failures"],
        )

    def test_author_contribution_requires_paper_evidence(self):
        report = self.validate(
            paper_block().replace(
                "（PDF第 2、3 页）（公式 1）",
                "",
            )
        )
        self.assertFalse(report["valid"])
        self.assertIs(report.get("author_contributions_valid"), True)
        self.assertIs(report.get("author_contribution_evidence_valid"), False)
        self.assertIn(
            "author contribution needs a PDF, formula, figure, or table locator",
            report["failures"],
        )

    def test_research_problem_audit_and_what_why_how_contract_is_required(self):
        required_markers = {
            "problem_interest_valid": "**Interesting（问题值得研究吗）**",
            "problem_solvability_valid": "**Solvable（问题可解吗）**",
            "research_level_valid": "**Current level（当前研究水平）**",
            "problem_impact_valid": "**Impactful（问题影响大吗）**",
            "novelty_classification_valid": "**新旧问题/方法分类**",
            "what_valid": "**What / 研究的问题是什么？**",
            "why_valid": "**Why / 为什么要研究？**",
            "how_valid": "**How / 使用的方法是什么？**",
            "pros_cons_valid": "**Pros / Cons：优缺点是什么？**",
            "extension_reuse_valid": "**如何拓展与利用？**",
        }
        for field, marker in required_markers.items():
            with self.subTest(field=field):
                report = self.validate(paper_block().replace(marker, "**缺失栏目**"))
                self.assertFalse(report["valid"])
                self.assertIs(report.get(field), False)

    def test_missing_memory_sentence_is_rejected(self):
        report = self.validate(paper_block().replace(MEMORY_LINE + "\n", ""))
        self.assertFalse(report["valid"])
        self.assertIs(report.get("memory_sentence_valid"), False)
        self.assertIn("missing paper memory sentence", report["failures"])

    def test_memory_sentence_must_follow_source_before_analysis(self):
        block = paper_block().replace(MEMORY_LINE + "\n", "")
        block = block.replace(
            "> - **方法证据**\n",
            f"> - **方法证据**\n{MEMORY_LINE}\n",
        )
        report = self.validate(block)
        self.assertFalse(report["valid"])
        self.assertIs(report.get("memory_sentence_position_valid"), False)
        self.assertIn(
            "paper memory sentence must immediately follow source",
            report["failures"],
        )

    def test_adjacent_single_page_locators_must_be_compacted(self):
        block = paper_block().replace(
            "约束定义见（PDF第 3 页）（公式 1）。",
            "约束定义见（PDF第 1 页）（PDF第 2 页）（公式 1）。",
        )
        report = self.validate(block)
        self.assertFalse(report["valid"])
        self.assertIs(report.get("compact_pdf_page_references_valid"), False)
        self.assertIn(
            "adjacent PDF page locators must be compacted",
            report["failures"],
        )

    def test_compact_multi_page_locator_is_allowed(self):
        block = paper_block().replace(
            "约束定义见（PDF第 3 页）（公式 1）。",
            "约束定义见（PDF第 1、2 页）（公式 1）。",
        )
        report = self.validate(block)
        self.assertTrue(report["valid"], report["failures"])
        self.assertIs(report.get("compact_pdf_page_references_valid"), True)

    def test_source_line_baseline_is_required_from_at_least_one_input(self):
        report = self.validate(
            paper_block(),
            author_source_line=None,
            knowledge_source_line=None,
        )
        self.assertFalse(report["valid"])
        self.assertIs(report.get("source_line_baseline_valid"), False)
        self.assertIn("source line baseline is required", report["failures"])

    def test_author_and_knowledge_source_line_baselines_must_agree(self):
        report = self.validate(
            paper_block(),
            knowledge_source_line=source_line().replace("。A，", "。A-，"),
        )
        self.assertFalse(report["valid"])
        self.assertIs(report.get("source_line_baseline_valid"), False)
        self.assertIn(
            "author and knowledge source_line baselines disagree",
            report["failures"],
        )

    def test_source_line_doi_mutation_is_rejected(self):
        report = self.validate(
            paper_block().replace("10.0000/fixture", "10.0000/mutated")
        )
        self.assertFalse(report["valid"])
        self.assertFalse(report["source_line_preserved"])
        self.assertIn(
            "source line changed or has an unsupported status",
            report["failures"],
        )

    def test_only_source_status_may_change(self):
        report = self.validate(
            paper_block("已AI全文读"),
            author_source_line=source_line("待精读"),
            knowledge_source_line=source_line("已AI全文读"),
        )
        self.assertTrue(report["valid"], report["failures"])
        self.assertTrue(report.get("source_line_baseline_valid"))
        self.assertTrue(report["source_line_preserved"])

    def test_printed_journal_pages_are_rejected_but_pdf_locators_are_allowed(self):
        for forbidden in (
            "（p. 9559–9560）",
            "p. 9559",
            "pp. 9559–9560",
            "PP. 9559-9560",
            "P. 9559",
        ):
            with self.subTest(forbidden=forbidden):
                report = self.validate(
                    paper_block().replace(
                        "约束定义见（PDF第 3 页）（公式 1）。",
                        f"约束定义见（PDF第 3 页）（公式 1）{forbidden}。",
                    )
                )
                self.assertFalse(report["valid"])
                self.assertFalse(report["printed_page_references_valid"])
                self.assertIn(
                    "printed journal page reference is forbidden",
                    report["failures"],
                )

    def test_missing_structure_author_and_target_are_reported(self):
        block = (
            paper_block()
            .replace(">   > [!info]- **作者与团队背景**", "**作者与团队背景**")
            .replace(">   > [!info]- **概念解释：为什么使用安全过滤器？**", "")
            .replace("Bob Example", "Missing Corresponding Author")
            .replace(f"[[{KNOWLEDGE_TARGET}|Isaac Lab]]", "[[Wrong Target]]")
            .replace("**论文明确承认的局限**", "**局限**")
            .replace("**未报告与疑点**", "**疑点**")
        )
        report = self.validate(block)
        self.assertFalse(report["valid"])
        self.assertFalse(report["author_section_valid"])
        self.assertFalse(report["nested_concepts_valid"])
        self.assertFalse(report["limitations_valid"])
        self.assertFalse(report["unreported_questions_valid"])
        self.assertFalse(report["designated_authors_valid"])
        self.assertFalse(report["knowledge_links_valid"])
        self.assertIn("missing designated author: Bob Example", report["failures"])

    def test_missing_pdf_page_reference_is_reported(self):
        block = (
            paper_block()
            .replace("（PDF第 2、3 页）（公式 1）", "（公式 1）")
            .replace("（PDF第 3 页）（公式 1）", "（公式 1）")
            .replace("（PDF第 4 页）（图 2）", "（图 2）")
            .replace("（PDF第 5 页）（表 II）", "（表 II）")
        )
        report = self.validate(block)
        self.assertFalse(report["valid"])
        self.assertFalse(report["pdf_page_reference_valid"])
        self.assertIn("PDF page reference is required", report["failures"])

    def test_unknown_source_status_fails_the_overall_contract(self):
        report = self.validate(paper_block("人工改写状态"))
        self.assertFalse(report["valid"])
        self.assertFalse(report["source_line_preserved"])
        self.assertIn(
            "source line changed or has an unsupported status",
            report["failures"],
        )

    def test_plain_text_does_not_satisfy_a_knowledge_target(self):
        report = self.validate(
            paper_block().replace(
                f"[[{KNOWLEDGE_TARGET}|Isaac Lab]]",
                KNOWLEDGE_TARGET,
            ),
            links=[{"target": KNOWLEDGE_TARGET, "target_exists": True}],
        )
        self.assertFalse(report["valid"])
        self.assertFalse(report["knowledge_links_valid"])

    def test_target_does_not_match_a_target_extra_wikilink(self):
        report = self.validate(
            paper_block().replace(
                f"[[{KNOWLEDGE_TARGET}|Isaac Lab]]",
                f"[[{KNOWLEDGE_TARGET}-extra|Isaac Lab]]",
            ),
            links=[{"target": KNOWLEDGE_TARGET, "target_exists": True}],
        )
        self.assertFalse(report["valid"])
        self.assertFalse(report["knowledge_links_valid"])

    def test_alias_differences_do_not_override_the_exact_wikilink_target(self):
        report = self.validate(
            paper_block().replace("|Isaac Lab]]", "|Display Alias Changed]]"),
            links=[
                {
                    "target": f"[[{KNOWLEDGE_TARGET}|Stale Map Alias]]",
                    "target_exists": True,
                }
            ],
        )
        self.assertTrue(report["valid"], report["failures"])
        self.assertTrue(report["knowledge_links_valid"])

    def test_unconfirmed_knowledge_target_fails_even_when_used(self):
        report = self.validate(
            paper_block(),
            links=[
                {
                    "target": f"[[{KNOWLEDGE_TARGET}|Isaac Lab]]",
                    "target_exists": False,
                }
            ],
        )
        self.assertFalse(report["valid"])
        self.assertFalse(report["knowledge_links_valid"])

    def test_paper_block_stops_at_next_h1_h2_or_h3_heading(self):
        for heading in ("# Root Section", "## Parent Section", "### Next Paper"):
            with self.subTest(heading=heading):
                report = self.validate(
                    paper_block(),
                    suffix=f"\n{heading}\nOutside p. 9559.\n",
                )
                self.assertTrue(report["valid"], report["failures"])
                self.assertNotIn("Outside p. 9559", report["block"])

    def test_paper_block_stops_at_commonmark_heading_indented_up_to_three_spaces(
        self,
    ):
        for indent in range(4):
            for heading in ("# Root Section", "## Parent Section", "### Next Paper"):
                with self.subTest(indent=indent, heading=heading):
                    report = self.validate(
                        paper_block(),
                        suffix=(
                            f"\n{' ' * indent}{heading}\n"
                            "Outside p. 9559.\n"
                        ),
                    )
                    self.assertTrue(report["valid"], report["failures"])
                    self.assertNotIn("Outside p. 9559", report["block"])

    def test_fenced_code_pseudo_heading_remains_inside_the_paper_block(self):
        report = self.validate(
            paper_block(),
            suffix=(
                "\n```markdown\n"
                "### Not A Paper Heading\n"
                "Inside p. 9559.\n"
                "```\n"
            ),
        )
        self.assertFalse(report["valid"])
        self.assertIn("### Not A Paper Heading", report["block"])
        self.assertFalse(report["printed_page_references_valid"])

    def test_h4_heading_remains_inside_the_paper_block(self):
        report = self.validate(
            paper_block(),
            suffix="\n#### Internal Detail\nInside p. 9559.\n",
        )
        self.assertFalse(report["valid"])
        self.assertIn("#### Internal Detail", report["block"])
        self.assertFalse(report["printed_page_references_valid"])

    def test_block_id_after_h2_is_not_attributed_to_an_earlier_h3(self):
        note_fragment = paper_block().removeprefix("### Fixture Paper\n")
        report = self.validate(
            note_fragment,
            prefix="### Stale Paper\nOld text.\n\n## New Section\n",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(report["block_id_valid"])
        self.assertIn(
            f"block ID is not inside a ### paper block: {BLOCK_ID}",
            report["failures"],
        )

    def test_block_id_must_be_a_standalone_line_immediately_after_heading(self):
        inline = paper_block().replace(
            f"^{BLOCK_ID}\n{source_line()}",
            f"{source_line()} ^{BLOCK_ID}",
        )
        report = self.validate(inline)
        self.assertFalse(report["valid"])
        self.assertFalse(report["block_id_valid"])
        self.assertIn(
            f"block ID must be a standalone line immediately after its ### heading: {BLOCK_ID}",
            report["failures"],
        )

        displaced = paper_block().replace(
            f"^{BLOCK_ID}\n{source_line()}",
            f"{source_line()}\n^{BLOCK_ID}",
        )
        report = self.validate(displaced)
        self.assertFalse(report["valid"])
        self.assertFalse(report["block_id_valid"])

    def test_indented_second_main_callout_is_rejected(self):
        canonical = source_line()
        duplicate_without_block_id = canonical
        for indent in range(1, 4):
            with self.subTest(indent=indent):
                block = paper_block().replace(
                    canonical + "\n",
                    (
                        canonical
                        + "\n"
                        + (" " * indent)
                        + duplicate_without_block_id
                        + "\n"
                    ),
                    1,
                )
                report = self.validate(block)
                self.assertFalse(report["valid"])
                self.assertFalse(report["main_callout_valid"])

    def test_one_info_callout_cannot_satisfy_author_and_concept_sections(self):
        lines = paper_block().splitlines()
        info_indices = [
            index for index, line in enumerate(lines) if "[!info]-" in line
        ]
        lines[info_indices[0]] += " " + lines[info_indices[1]].split(
            "[!info]-", 1
        )[1].strip()
        del lines[info_indices[1]]
        report = self.validate("\n".join(lines) + "\n")
        self.assertFalse(report["valid"])
        self.assertFalse(
            report["author_section_valid"]
            and report["nested_concepts_valid"]
        )

    def test_fixture_does_not_require_a_writable_source_tree(self):
        real_temporary_directory = tempfile.TemporaryDirectory

        def system_temporary_directory(*args, **kwargs):
            self.assertIsNone(
                kwargs.get("dir"),
                "test fixtures must not create temporary files in the source tree",
            )
            return real_temporary_directory(*args, **kwargs)

        with patch.object(
            tempfile,
            "TemporaryDirectory",
            side_effect=system_temporary_directory,
        ):
            report = self.validate(paper_block())
        self.assertTrue(report["valid"], report["failures"])


if __name__ == "__main__":
    unittest.main()