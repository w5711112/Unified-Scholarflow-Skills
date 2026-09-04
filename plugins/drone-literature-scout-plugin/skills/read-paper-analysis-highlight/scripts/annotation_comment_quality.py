from __future__ import annotations

from typing import Any


FIRST_LINE_PREFIXES = ("结论：", "外部信息：")
ANALYSIS_PREFIXES = (
    "机制：",
    "意义：",
    "复现：",
    "边界：",
    "疑点：",
    "定位：",
    "来源：",
    "论文报告：",
    "可以推断：",
    "尚不能证明：",
)
BOUNDARY_TERMS = (
    "未报告",
    "没有报告",
    "未给出",
    "不能证明",
    "尚不能证明",
    "无法判断",
    "无法核验",
    "证据不足",
    "不等于",
    "不能外推",
)
TRANSLATION_ONLY_MARKERS = ("翻译为", "翻译成", "意思是")
GENERIC_EXACT = {
    "这是一个重要的方法。",
    "这是重要数据。",
    "该方法很重要。",
    "该结果很好。",
}


def _clean_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def comment_quality_failures(item: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    comment = item.get("annotation_comment")
    if not isinstance(comment, str) or not comment.strip():
        return ["annotation_comment must be a non-empty string"]

    lines = _clean_lines(comment)
    if not lines or not lines[0].startswith(FIRST_LINE_PREFIXES):
        failures.append(
            "annotation_comment first line must start with 结论： or 外部信息："
        )
    if len(lines) < 2:
        failures.append(
            "V3 annotation_comment needs a conclusion plus contextual analysis"
        )
    elif not any(
        line.startswith(ANALYSIS_PREFIXES)
        for line in lines[1:]
    ):
        failures.append(
            "annotation_comment needs a labeled mechanism, meaning, "
            "reproduction, boundary, location, or source line"
        )

    normalised = " ".join(comment.split())
    if normalised in GENERIC_EXACT:
        failures.append("annotation_comment is generic and evidence-free")
    if any(marker in normalised for marker in TRANSLATION_ONLY_MARKERS) and not any(
        line.startswith(("机制：", "意义：", "复现：", "边界：", "疑点："))
        for line in lines[1:]
    ):
        failures.append(
            "annotation_comment is translation-only and lacks interpretation"
        )

    roles = item.get("information_roles")
    if not isinstance(roles, list) or not roles:
        failures.append("annotation_comment requires information_roles")
        roles = []
    if "evidence_gap" in roles and not any(
        term in comment for term in BOUNDARY_TERMS
    ):
        failures.append(
            "evidence_gap annotation_comment must state the missing evidence "
            "or unsupported boundary explicitly"
        )
    return failures
