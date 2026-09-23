from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_STATUS_PATTERN = re.compile(r"状态：(待精读|已AI全文读)")
_PRINTED_PAGE_PATTERN = re.compile(
    r"(?<![\w])p{1,2}\.\s*\d+(?:\s*[-–—]\s*\d+)?",
    re.IGNORECASE,
)
_PDF_PAGE_PATTERN = re.compile(
    r"（PDF第\s*[1-9]\d*(?:\s*、\s*[1-9]\d*)*\s*页）"
)
_ADJACENT_PDF_PAGE_PATTERN = re.compile(
    r"（PDF第\s*[1-9]\d*\s*页）\s*（PDF第\s*[1-9]\d*\s*页）"
)
_MEMORY_LINE_PATTERN = re.compile(
    r"^> - \*\*一眼记住这篇论文\*\*：==(?P<sentence>\S(?:.*\S)?)==\s*$"
)
_ATX_HEADING_PATTERN = re.compile(r"^ {0,3}(#{1,3})(?!#)[ \t]+.+$")
_FENCE_OPEN_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_MAIN_CALLOUT_PATTERN = re.compile(r"^ {0,3}>[ \t]*\[!note\]-[ \t]+\*\*\u6765\u6e90\*\*")
_INFO_CALLOUT_PATTERN = re.compile(r"^ {0,3}(?:>[ \t]*){2,}\[!info\]-[^\r\n]*$")
_WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]\r\n]+)\]\]")
_AUTHOR_CONTRIBUTION_MARKER = "**作者贡献**"
_PAPER_EVIDENCE_PATTERN = re.compile(
    r"（(?:PDF第\s*[1-9]\d*(?:\s*、\s*[1-9]\d*)*\s*页|公式\s*[^）]+|图\s*[^）]+|表\s*[^）]+)）"
)


def _markdown_headings(text: str) -> list[tuple[int, int]]:
    headings: list[tuple[int, int]] = []
    offset = 0
    fence_marker: str | None = None
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if fence_marker is not None:
            closing_pattern = rf" {{0,3}}{re.escape(fence_marker[0])}{{{len(fence_marker)},}}[ \t]*"
            if re.fullmatch(closing_pattern, line):
                fence_marker = None
        else:
            fence = _FENCE_OPEN_PATTERN.fullmatch(line)
            if fence is not None:
                fence_marker = fence.group(1)
            else:
                heading = _ATX_HEADING_PATTERN.fullmatch(line)
                if heading is not None:
                    headings.append((offset, len(heading.group(1))))
        offset += len(raw_line)
    return headings


def _extract_paper_block(text: str, block_id: str) -> tuple[str, bool, str | None]:
    marker_pattern = re.compile(
        rf"(?<![\w-])\^{re.escape(block_id)}(?=$|\s)",
        re.MULTILINE,
    )
    markers = list(marker_pattern.finditer(text))
    if len(markers) != 1:
        return "", False, f"expected exactly one block ID: {block_id}"

    marker = markers[0]
    headings = _markdown_headings(text)
    preceding_headings = [
        heading for heading in headings if heading[0] < marker.start()
    ]
    if not preceding_headings or preceding_headings[-1][1] != 3:
        return "", False, f"block ID is not inside a ### paper block: {block_id}"

    heading_start = preceding_headings[-1][0]
    marker_line_start = text.rfind("\n", 0, marker.start()) + 1
    marker_line_end = text.find("\n", marker.end())
    if marker_line_end == -1:
        marker_line_end = len(text)
    marker_line = text[marker_line_start:marker_line_end].rstrip("\r")
    heading_line_end = text.find("\n", heading_start)
    if heading_line_end == -1:
        heading_line_end = len(text)
    if (
        marker_line != f"^{block_id}"
        or marker_line_start != heading_line_end + 1
    ):
        return (
            "",
            False,
            f"block ID must be a standalone line immediately after its ### heading: {block_id}",
        )
    next_heading_start = next(
        (start for start, _level in headings if start > marker.end()),
        None,
    )
    block_end = next_heading_start if next_heading_start is not None else len(text)
    return text[heading_start:block_end], True, None


def _folded_info_callout_positions(block: str, title: str) -> set[int]:
    return {
        index
        for index, line in enumerate(block.splitlines())
        if _INFO_CALLOUT_PATTERN.fullmatch(line) and title in line
    }

def _folded_info_callout(block: str, title: str) -> bool:
    positions = _folded_info_callout_positions(block, title)
    if title == "\u6982\u5ff5\u89e3\u91ca":
        author_positions = _folded_info_callout_positions(
            block, "\u4f5c\u8005\u4e0e\u56e2\u961f\u80cc\u666f"
        )
        return bool(positions) and (
            not author_positions
            or any(author != concept for author in author_positions for concept in positions)
        )
    return bool(positions)

def _normalized_source_line(line: str) -> str | None:
    statuses = list(_STATUS_PATTERN.finditer(line))
    if len(statuses) != 1:
        return None
    status = statuses[0]
    return line[: status.start()] + "状态：<STATUS>" + line[status.end() :]


def _source_line_baseline(
    author_payload: dict[str, Any],
    knowledge_map: dict[str, Any],
) -> tuple[bool, str | None, list[str]]:
    normalized_lines: list[str] = []
    for label, payload in (
        ("author", author_payload),
        ("knowledge", knowledge_map),
    ):
        if "source_line" not in payload:
            continue
        source_line = payload["source_line"]
        if not isinstance(source_line, str) or not source_line.strip():
            return False, None, [f"{label} source_line baseline is invalid"]
        normalized = _normalized_source_line(source_line)
        if normalized is None:
            return False, None, [f"{label} source_line baseline has unsupported status"]
        normalized_lines.append(normalized)

    if not normalized_lines:
        return False, None, ["source line baseline is required"]
    if len(normalized_lines) == 2 and normalized_lines[0] != normalized_lines[1]:
        return False, None, ["author and knowledge source_line baselines disagree"]
    return True, normalized_lines[0], []


def _wikilink_target(value: str) -> str | None:
    candidate = value.strip()
    full_link = _WIKILINK_PATTERN.fullmatch(candidate)
    if candidate.startswith("[[") or candidate.endswith("]]" ):
        if full_link is None:
            return None
        candidate = full_link.group(1)
    target = candidate.split("|", 1)[0].strip()
    return target or None


def _wikilink_targets_in(block: str) -> set[str]:
    targets: set[str] = set()
    for match in _WIKILINK_PATTERN.finditer(block):
        target = match.group(1).split("|", 1)[0].strip()
        if target:
            targets.add(target)
    return targets


def _callout_list_item(line: str) -> tuple[int, int, str] | None:
    stripped = line.lstrip(" ")
    quote_depth = 0
    while stripped.startswith(">"):
        quote_depth += 1
        stripped = stripped[1:]
        if stripped.startswith(" "):
            stripped = stripped[1:]
    if quote_depth == 0:
        return None
    item = re.fullmatch(r"(?P<indent>[ \t]*)-[ \t]+(?P<body>.*)", stripped)
    if item is None:
        return None
    indent = len(item.group("indent").expandtabs(4))
    return quote_depth, indent, item.group("body")


def _author_contribution_section(block: str) -> str | None:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        item = _callout_list_item(line)
        if item is None or _AUTHOR_CONTRIBUTION_MARKER not in item[2]:
            continue
        start_quote_depth, start_indent, _body = item
        section = [line]
        for following in lines[index + 1 :]:
            following_item = _callout_list_item(following)
            if following_item is not None:
                quote_depth, indent, body = following_item
                is_next_field = (
                    quote_depth <= start_quote_depth
                    and indent <= start_indent
                    and body.startswith("**")
                )
                if is_next_field:
                    break
            section.append(following)
        return "\n".join(section)
    return None


def _author_contribution_contract(block: str) -> tuple[bool, bool, bool]:
    section = _author_contribution_section(block)
    if section is None:
        return False, False, False
    content = section.replace(_AUTHOR_CONTRIBUTION_MARKER, "", 1)
    has_content = bool(content.strip(" >-\t:：\r\n"))
    has_core_emphasis = bool(re.search(r"\*\*[^*\r\n]+\*\*", content))
    has_evidence = bool(_PAPER_EVIDENCE_PATTERN.search(content))
    return has_content, has_core_emphasis, has_evidence


def validate_paper_note(
    note_path: Path,
    block_id: str,
    author_research_path: Path,
    knowledge_map_path: Path,
) -> dict[str, Any]:
    text = note_path.read_text(encoding="utf-8")
    block, block_id_valid, block_failure = _extract_paper_block(text, block_id)
    failures: list[str] = []
    if block_failure:
        failures.append(block_failure)

    author_payload = json.loads(author_research_path.read_text(encoding="utf-8"))
    knowledge_map = json.loads(knowledge_map_path.read_text(encoding="utf-8"))

    printed_page_references_valid = not bool(_PRINTED_PAGE_PATTERN.search(block))
    if not printed_page_references_valid:
        failures.append("printed journal page reference is forbidden")

    pdf_page_reference_valid = bool(_PDF_PAGE_PATTERN.search(block))
    if not pdf_page_reference_valid:
        failures.append("PDF page reference is required")

    compact_pdf_page_references_valid = not bool(
        _ADJACENT_PDF_PAGE_PATTERN.search(block)
    )
    if not compact_pdf_page_references_valid:
        failures.append("adjacent PDF page locators must be compacted")

    source_lines = [
        line
        for line in block.splitlines()
        if _MAIN_CALLOUT_PATTERN.match(line)
    ]
    main_callout_valid = len(source_lines) == 1
    if not main_callout_valid:
        failures.append("missing or duplicate folded main source callout")

    block_lines = block.splitlines()
    source_line_positions = [
        index
        for index, line in enumerate(block_lines)
        if _MAIN_CALLOUT_PATTERN.match(line)
    ]
    memory_line_positions = [
        index
        for index, line in enumerate(block_lines)
        if _MEMORY_LINE_PATTERN.fullmatch(line)
    ]
    memory_sentence_valid = len(memory_line_positions) == 1
    if not memory_sentence_valid:
        failures.append("missing paper memory sentence")
    memory_sentence_position_valid = (
        memory_sentence_valid
        and main_callout_valid
        and memory_line_positions[0] == source_line_positions[0] + 1
    )
    if not memory_sentence_position_valid:
        failures.append("paper memory sentence must immediately follow source")

    author_section_valid = _folded_info_callout(block, "作者与团队背景")
    if not author_section_valid:
        failures.append("missing note section: folded 作者与团队背景")

    nested_concepts_valid = _folded_info_callout(block, "概念解释")
    if not nested_concepts_valid:
        failures.append("missing note section: nested folded concept explanation")

    (
        author_contributions_valid,
        author_contribution_emphasis_valid,
        author_contribution_evidence_valid,
    ) = _author_contribution_contract(block)
    if not author_contributions_valid:
        failures.append("missing author contributions")
    else:
        if not author_contribution_emphasis_valid:
            failures.append(
                "author contribution needs a bold core phrase beyond the field label"
            )
        if not author_contribution_evidence_valid:
            failures.append(
                "author contribution needs a PDF, formula, figure, or table locator"
            )

    required_sections = {
        "limitations_valid": "论文明确承认的局限",
        "unreported_questions_valid": "未报告与疑点",
        "support_links_valid": "支撑链接",
        "pdf_annotations_valid": "PDF 原文标注",
    }
    section_results: dict[str, bool] = {}
    for field, label in required_sections.items():
        section_results[field] = label in block
        if not section_results[field]:
            failures.append(f"missing note section: {label}")

    required_audit_sections = {
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
    audit_results: dict[str, bool] = {}
    for field, marker in required_audit_sections.items():
        audit_results[field] = marker in block
        if not audit_results[field]:
            failures.append(f"missing research audit slot: {marker}")

    claimed_problem_marker = "**作者声称解决了什么当下的问题？**"
    research_audit_marker = "**研究问题审计："
    claimed_problem_count = block.count(claimed_problem_marker)
    author_claimed_current_problem_valid = claimed_problem_count == 1
    if not author_claimed_current_problem_valid:
        failures.append("missing author-claimed current problem section")
    claimed_problem_position = block.find(claimed_problem_marker)
    research_audit_position = block.find(research_audit_marker)
    author_claimed_current_problem_order_valid = (
        author_claimed_current_problem_valid
        and research_audit_position >= 0
        and claimed_problem_position < research_audit_position
    )
    if not author_claimed_current_problem_order_valid:
        failures.append(
            "author-claimed current problem must precede research audit"
        )

    designated_authors_valid = True
    designated_authors = author_payload.get("designated_authors")
    if not isinstance(designated_authors, list):
        designated_authors_valid = False
        failures.append("author research designated_authors must be a list")
    else:
        for author in designated_authors:
            name = author.get("name") if isinstance(author, dict) else None
            if not isinstance(name, str) or not name or name not in block:
                designated_authors_valid = False
                failures.append(f"missing designated author: {name or '<invalid>'}")

    knowledge_links_valid = True
    block_targets = _wikilink_targets_in(block)
    links = knowledge_map.get("links")
    if not isinstance(links, list):
        knowledge_links_valid = False
        failures.append("knowledge map links must be a list")
    else:
        for link in links:
            target_value = link.get("target") if isinstance(link, dict) else None
            target_label = (
                target_value
                if isinstance(target_value, str) and target_value
                else "<invalid>"
            )
            target = (
                _wikilink_target(target_value)
                if isinstance(target_value, str)
                else None
            )
            if (
                not isinstance(link, dict)
                or link.get("target_exists") is not True
                or target is None
                or target not in block_targets
            ):
                knowledge_links_valid = False
                failures.append(f"invalid or unused knowledge target: {target_label}")

    (
        source_line_baseline_valid,
        expected_source_line,
        baseline_failures,
    ) = _source_line_baseline(author_payload, knowledge_map)
    failures.extend(baseline_failures)

    source_line_preserved = False
    if main_callout_valid and source_line_baseline_valid:
        source_line = source_lines[0]
        normalized_source_line = _normalized_source_line(source_line)
        source_line_preserved = (
            normalized_source_line is not None
            and normalized_source_line == expected_source_line
        )
        if not source_line_preserved:
            failures.append("source line changed or has an unsupported status")

    report = {
        "block_id_valid": block_id_valid,
        "printed_page_references_valid": printed_page_references_valid,
        "pdf_page_reference_valid": pdf_page_reference_valid,
        "compact_pdf_page_references_valid": compact_pdf_page_references_valid,
        "main_callout_valid": main_callout_valid,
        "memory_sentence_valid": memory_sentence_valid,
        "memory_sentence_position_valid": memory_sentence_position_valid,
        "author_section_valid": author_section_valid,
        "nested_concepts_valid": nested_concepts_valid,
        "author_contributions_valid": author_contributions_valid,
        "author_contribution_emphasis_valid": author_contribution_emphasis_valid,
        "author_contribution_evidence_valid": author_contribution_evidence_valid,
        "author_claimed_current_problem_valid": author_claimed_current_problem_valid,
        "author_claimed_current_problem_order_valid": author_claimed_current_problem_order_valid,
        "limitations_valid": section_results["limitations_valid"],
        "unreported_questions_valid": section_results[
            "unreported_questions_valid"
        ],
        "support_links_valid": section_results["support_links_valid"],
        "pdf_annotations_valid": section_results["pdf_annotations_valid"],
        "designated_authors_valid": designated_authors_valid,
        "knowledge_links_valid": knowledge_links_valid,
        "source_line_baseline_valid": source_line_baseline_valid,
        "source_line_preserved": source_line_preserved,
        "failures": failures,
        "block": block,
    }
    report.update(audit_results)
    report["valid"] = not failures
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", required=True, type=Path)
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--author-research", required=True, type=Path)
    parser.add_argument("--knowledge-map", required=True, type=Path)
    args = parser.parse_args()
    report = validate_paper_note(
        args.note,
        args.block_id,
        args.author_research,
        args.knowledge_map,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
