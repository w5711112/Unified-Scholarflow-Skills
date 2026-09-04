from __future__ import annotations

from dataclasses import dataclass
import ntpath
import re
from urllib.parse import urlsplit


REQUIRED_SECTIONS = ("核心结论", "搜索统计", "搜索轨迹", "冲突与缺失", "来源")
REQUIRED_STATS = (
    "纯搜索时间",
    "全局运行 ID",
    "运行类型",
    "范围指纹",
    "上一轮已验证对象数",
    "本轮新增已验证对象数",
    "本轮重叠对象数",
    "明确失效对象数",
    "累计已验证对象数",
    "停止证据",
    "原始结果数",
    "未去重 URL 数",
    "有效 URL 数",
    "规范化去重有效 URL 数",
    "未去重 URL/s",
    "规范化去重 URL/s",
    "成功正文页/s",
    "有效结构化记录/s",
    "搜索模式",
    "50 URL/s目标",
    "独立域名数",
    "来源类别",
    "最高并发",
    "停止原因",
)
CATALOG_REQUIRED_STATS = (
    "唯一商品候选数",
    "唯一有效记录数",
    "商品候选平均速度",
    "最近 30 秒商品候选速度",
    "最长零新增间隔",
    "各来源商品聚合",
    "阻塞次数",
    "10 商品候选/s目标",
    "确定性范围证据",
)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
ALLOWED_STOPS = {
    "quick_direct": {"search_saturated", "ten_minute_limit"},
    "open_web_research": {"search_saturated", "ten_minute_limit"},
    "catalog_enumeration": {
        "deterministic_scope_complete",
        "ten_minute_limit",
    },
    "bounded_dataset_extract": {
        "deterministic_scope_complete",
        "ten_minute_limit",
    },
}
STOP_LABELS = {
    "搜索饱和": "search_saturated",
    "达到10分钟": "ten_minute_limit",
    "确定范围完成": "deterministic_scope_complete",
}


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]


def _outside_fences(text: str) -> str:
    outside: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            suffix = match.group(2)
            if fence is None:
                fence = (marker[0], len(marker))
            elif (
                marker[0] == fence[0]
                and len(marker) >= fence[1]
                and not suffix.strip(" \t")
            ):
                fence = None
            continue
        if fence is None:
            outside.append(line)
    return "\n".join(outside)


def _section(text: str, name: str) -> str | None:
    match = re.search(
        rf"^##[ \t]+{re.escape(name)}[ \t]*$\n?(.*?)(?=^##[ \t]+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return None if match is None else match.group(1)


def _raw_visible_section(text: str, name: str) -> str | None:
    """Return one visible level-two section while retaining its fence bodies."""
    content: list[str] = []
    fence: tuple[str, int] | None = None
    found = False
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            suffix = match.group(2)
            if found:
                content.append(line)
            if fence is None:
                fence = (marker[0], len(marker))
            elif (
                marker[0] == fence[0]
                and len(marker) >= fence[1]
                and not suffix.strip(" \t")
            ):
                fence = None
            continue
        if fence is None:
            heading = re.fullmatch(r"##[ \t]+(.+?)[ \t]*", line)
            if heading:
                if found:
                    return "\n".join(content)
                if heading.group(1) == name:
                    found = True
                continue
        if found:
            content.append(line)
    return "\n".join(content) if found else None


def _has_search_timeline(section: str) -> bool:
    visible = _outside_fences(section)
    svg = re.search(r"<svg\b[^>]*>.*?</svg>", visible, re.IGNORECASE | re.DOTALL)
    if svg and (
        "搜索时间—累计未去重 URL" in svg.group(0)
        and re.search(r"<polyline\b[^>]*\bpoints=", svg.group(0), re.IGNORECASE)
    ):
        return True
    if re.search(
        r"(?m)^字符折线：[^\r\n]*[▁▂▃▄▅▆▇█][^\r\n]*URL[ \t]*→[^\r\n]*URL[ \t]*$",
        visible,
    ):
        return True

    fence: tuple[str, int] | None = None
    mermaid = False
    body: list[str] = []
    for line in section.splitlines():
        match = _FENCE.match(line)
        if fence is None:
            if match:
                marker = match.group(1)
                language = match.group(2).strip().split(maxsplit=1)
                fence = (marker[0], len(marker))
                mermaid = bool(language) and language[0].casefold() == "mermaid"
                body = []
            continue
        if match:
            marker = match.group(1)
            suffix = match.group(2)
            if (
                marker[0] == fence[0]
                and len(marker) >= fence[1]
                and not suffix.strip(" \t")
            ):
                chart = "\n".join(body)
                if mermaid and all(
                    token in chart
                    for token in ("xychart-beta", "x-axis", "y-axis", "line [")
                ):
                    return True
                fence = None
                mermaid = False
                body = []
                continue
        if mermaid:
            body.append(line)
    return False


def _stat_value(statistics: str | None, field: str) -> str | None:
    if statistics is None:
        return None
    match = re.search(
        rf"^-[ \t]+{re.escape(field)}：[ \t]*(\S(?:[^\r\n]*\S)?)[ \t]*$",
        statistics,
        re.MULTILINE,
    )
    return None if match is None else match.group(1)


def _valid_http_url(url: str) -> bool:
    if (
        "\\" in url
        or re.search(r"%(?![0-9A-Fa-f]{2})", url)
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)
    ):
        return False
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _parse_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)[ \t]*秒", value)
    if match is None:
        return None
    return float(match.group(1))


def _parse_count(value: str | None) -> int | None:
    if value is None or re.fullmatch(r"[0-9]+", value) is None:
        return None
    return int(value)


def _parse_candidate_rate(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)[ \t]*候选/s", value)
    return None if match is None else float(match.group(1))


def _valid_marketplace_source_aggregate(value: str | None) -> bool:
    if value is None:
        return False
    entries = [entry.strip() for entry in value.split(";") if entry.strip()]
    return bool(entries) and all(
        re.fullmatch(
            r"[^();\r\n]+\(raw=[0-9]+,unique=[0-9]+,duplicate=[0-9]+\)",
            entry,
        )
        is not None
        for entry in entries
    )


def _trajectory_run_id(trajectory: str | None) -> str | None:
    if trajectory is None:
        return None
    visible = _outside_fences(trajectory)
    match = re.search(
        r"^轨迹运行 ID：[ \t]*(\S(?:[^\r\n]*\S)?)[ \t]*$",
        visible,
        re.MULTILINE,
    )
    return None if match is None else match.group(1)


def _valid_saturation_evidence(value: str | None) -> bool:
    if value is None:
        return False
    return all(
        token in value
        for token in (
            "source_classes=complete",
            "query_dimensions=complete",
            "zero_yield_rounds=3",
            "coverage_gaps=closed",
            "domains=diverse",
            "candidate_set=stable",
        )
    )


def _valid_deterministic_scope(value: str | None) -> bool:
    if value is None:
        return False
    boundary = re.search(r"(?:^|;)[ \t]*boundary=([^;\r\n]+)", value)
    counts: dict[str, int] = {}
    for name in ("expected_pages", "completed_pages", "failed_pages"):
        match = re.search(rf"(?:^|;)[ \t]*{name}=([0-9]+)(?:;|$)", value)
        if match is None:
            return False
        counts[name] = int(match.group(1))
    return (
        boundary is not None
        and bool(boundary.group(1).strip())
        and counts["expected_pages"] > 0
        and counts["completed_pages"] == counts["expected_pages"]
        and counts["failed_pages"] == 0
        and "scheduler_status=deterministic_scope_complete" in value
    )


def _valid_marketplace_deterministic_scope(value: str | None) -> bool:
    if value is None:
        return False
    required = (
        "query_generation_exhausted=true",
        "healthy_cursors_open=0",
        "healthy_cursors_blocked=0",
        "edge_plan_completed=true",
        "untried_high_yield_families=0",
        "scheduler_status=deterministic_scope_complete",
    )
    if not all(token in value for token in required):
        return False
    additions = re.search(
        r"recent_candidate_additions=([0-9]+),([0-9]+),([0-9]+)", value
    )
    if additions is None or sum(int(number) for number in additions.groups()) > 1:
        return False
    for blocker in ("captcha_required", "authentication_required"):
        match = re.search(rf"(?:^|;)[ \t]*{blocker}=([0-9]+)(?:;|$)", value)
        if match is None or int(match.group(1)) != 0:
            return False
    return True


def _invalidation_lines(section: str | None) -> tuple[tuple[str, str, str], ...]:
    if section is None:
        return ()
    entries: list[tuple[str, str, str]] = []
    for match in re.finditer(
        r"^失效项：([^｜\r\n]+)｜([^｜\r\n]+)｜(\S+)[ \t]*$",
        section,
        re.MULTILINE,
    ):
        object_id, reason, url = (part.strip() for part in match.groups())
        if object_id and reason and _valid_http_url(url):
            entries.append((object_id, reason, url))
    return tuple(entries)


def validate_report(text: str) -> ValidationResult:
    errors: list[str] = []
    report = _outside_fences(text)
    sections = {name: _section(report, name) for name in REQUIRED_SECTIONS}
    for name, content in sections.items():
        if content is None:
            errors.append(f"missing-section:{name}")

    trajectory = _raw_visible_section(text, "搜索轨迹")
    if sections["搜索轨迹"] is not None and (
        trajectory is None or not _has_search_timeline(trajectory)
    ):
        errors.append("missing-search-timeline")

    statistics = sections["搜索统计"]
    values = {field: _stat_value(statistics, field) for field in REQUIRED_STATS}
    for field, value in values.items():
        if value is None:
            errors.append(f"missing-stat:{field}")
    stop_status = STOP_LABELS.get(values["停止原因"])
    if stop_status is None:
        errors.append("invalid-stop-reason")

    run_type = values["运行类型"]
    catalog_values = {
        field: _stat_value(statistics, field) for field in CATALOG_REQUIRED_STATS
    }
    if run_type == "catalog_enumeration":
        for field, value in catalog_values.items():
            if value is None:
                errors.append(f"missing-catalog-stat:{field}")
    if run_type is not None and run_type not in ALLOWED_STOPS:
        errors.append("not-global-market-run")
    elif run_type is not None and stop_status is not None and stop_status not in ALLOWED_STOPS[run_type]:
        errors.append("invalid-stop-for-run-type")

    seconds = _parse_seconds(values["纯搜索时间"])
    if values["纯搜索时间"] is not None and seconds is None:
        errors.append("invalid-pure-search-time")
    if values["停止原因"] == "达到10分钟" and (
        seconds is None or seconds < 600
    ):
        errors.append("ten-minute-stop-before-limit")
    if values["停止原因"] == "搜索饱和" and not _valid_saturation_evidence(
        values["停止证据"]
    ):
        errors.append("incomplete-saturation-evidence")
    if values["停止原因"] == "确定范围完成":
        if run_type == "catalog_enumeration":
            combined_scope = "; ".join(
                value
                for value in (
                    values["停止证据"],
                    catalog_values["确定性范围证据"],
                )
                if value is not None
            )
            if not _valid_marketplace_deterministic_scope(combined_scope):
                errors.append("blocked-deterministic-marketplace-scope")
        elif not _valid_deterministic_scope(values["停止证据"]):
            errors.append("incomplete-deterministic-scope")

    if run_type == "catalog_enumeration":
        candidate_count = _parse_count(catalog_values["唯一商品候选数"])
        record_count = _parse_count(catalog_values["唯一有效记录数"])
        average_rate = _parse_candidate_rate(
            catalog_values["商品候选平均速度"]
        )
        recent_rate = _parse_candidate_rate(
            catalog_values["最近 30 秒商品候选速度"]
        )
        zero_gap = _parse_seconds(catalog_values["最长零新增间隔"])
        blocked_count = _parse_count(catalog_values["阻塞次数"])
        parsed_catalog = {
            "唯一商品候选数": candidate_count,
            "唯一有效记录数": record_count,
            "商品候选平均速度": average_rate,
            "最近 30 秒商品候选速度": recent_rate,
            "最长零新增间隔": zero_gap,
            "阻塞次数": blocked_count,
        }
        for field, parsed in parsed_catalog.items():
            if catalog_values[field] is not None and parsed is None:
                errors.append(f"invalid-catalog-stat:{field}")
        if not _valid_marketplace_source_aggregate(
            catalog_values["各来源商品聚合"]
        ) and catalog_values["各来源商品聚合"] is not None:
            errors.append("invalid-catalog-source-aggregate")
        if (
            candidate_count is not None
            and seconds not in (None, 0)
            and average_rate is not None
            and abs(average_rate - candidate_count / seconds) > 0.01
        ):
            errors.append("marketplace-candidate-rate-mismatch")
        target = catalog_values["10 商品候选/s目标"]
        if target is not None and target not in {"达到", "未达到"}:
            errors.append("invalid-marketplace-target-status")
        if target == "达到" and not (
            seconds is not None
            and seconds >= 600
            and candidate_count is not None
            and candidate_count >= 6000
            and average_rate is not None
            and average_rate >= 10.0
            and zero_gap is not None
            and zero_gap < 30.0
        ):
            errors.append("marketplace-throughput-target-misreported")
        if values["停止原因"] == "达到10分钟" and (
            zero_gap is None or zero_gap >= 30.0
        ):
            errors.append("marketplace-zero-window-violation")

    trajectory_id = _trajectory_run_id(trajectory)
    if values["全局运行 ID"] is not None and trajectory_id != values["全局运行 ID"]:
        errors.append("trajectory-run-mismatch")

    lineage_fields = (
        "上一轮已验证对象数",
        "本轮新增已验证对象数",
        "本轮重叠对象数",
        "明确失效对象数",
        "累计已验证对象数",
    )
    lineage = {field: _parse_count(values[field]) for field in lineage_fields}
    for field, count in lineage.items():
        if values[field] is not None and count is None:
            errors.append(f"invalid-lineage-stat:{field}")
    if all(count is not None for count in lineage.values()):
        expected = (
            lineage["上一轮已验证对象数"]
            + lineage["本轮新增已验证对象数"]
            - lineage["明确失效对象数"]
        )
        if lineage["累计已验证对象数"] != expected:
            errors.append("invalid-cumulative-union")
        invalidation_count = lineage["明确失效对象数"]
        if invalidation_count and len(_invalidation_lines(sections["冲突与缺失"])) < invalidation_count:
            errors.append("missing-invalidation-evidence")

    sources = sections["来源"]
    links = () if sources is None else re.findall(r"\[[^\]]+\]\(([^)]+)\)", sources)
    if not any(_valid_http_url(link) for link in links):
        errors.append("missing-http-source")
    return ValidationResult(tuple(errors))


def _normalize_path(path: str) -> str:
    return ntpath.normpath(path.replace("/", "\\")).casefold()


def unexpected_artifacts(
    before: set[str], after: set[str], allowed: set[str]
) -> set[str]:
    normalized_before = {_normalize_path(path) for path in before}
    normalized_after = {_normalize_path(path) for path in after}
    normalized_allowed = {_normalize_path(path) for path in allowed}
    return (normalized_after - normalized_before) - normalized_allowed




