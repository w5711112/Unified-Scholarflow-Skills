"""Validate and render pure-search-time URL discovery telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
import json
import math
import sys
from typing import Iterable, Mapping, Sequence


CUMULATIVE_FIELDS = (
    "raw_url_observations",
    "valid_url_observations",
    "normalized_unique_urls",
    "unique_objects",
    "unique_marketplace_candidates",
)
BLOCKS = "▁▂▃▄▅▆▇█"
FUNNEL_STAGE_NAMES = (
    "raw_url_observations",
    "literal_unique_urls",
    "normalized_unique_urls",
    "content_unique_pages",
    "topic_relevant_pages",
    "product_page_candidates",
    "unique_valid_structured_records",
)
MARKETPLACE_FUNNEL_STAGE_NAMES = (
    "raw_url_observations",
    "normalized_unique_urls",
    "unique_marketplace_candidates",
    "unique_valid_structured_records",
)
FUNNEL_STAGE_LABELS = {
    "raw_url_observations": "原始 URL",
    "literal_unique_urls": "字面去重",
    "normalized_unique_urls": "规范 URL",
    "content_unique_pages": "内容唯一页",
    "topic_relevant_pages": "主题相关页",
    "product_page_candidates": "商品候选",
    "unique_valid_structured_records": "有效记录",
    "unique_marketplace_candidates": "去重商品候选",
}


def _finite_nonnegative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class SearchCheckpoint:
    pure_discovery_seconds: float
    raw_url_observations: int
    valid_url_observations: int
    normalized_unique_urls: int
    unique_objects: int
    backend: str
    backend_kind: str
    actual_in_flight: int
    unique_marketplace_candidates: int = 0

    def __post_init__(self) -> None:
        seconds = _finite_nonnegative(
            self.pure_discovery_seconds, "pure_discovery_seconds"
        )
        raw = _count(self.raw_url_observations, "raw_url_observations")
        valid = _count(self.valid_url_observations, "valid_url_observations")
        normalized = _count(
            self.normalized_unique_urls, "normalized_unique_urls"
        )
        objects = _count(self.unique_objects, "unique_objects")
        candidates = _count(
            self.unique_marketplace_candidates, "unique_marketplace_candidates"
        )
        in_flight = _count(self.actual_in_flight, "actual_in_flight")
        backend = _label(self.backend, "backend")
        backend_kind = _label(self.backend_kind, "backend_kind")
        if not raw >= valid >= normalized:
            raise ValueError(
                "counts must satisfy raw >= valid >= normalized_unique"
            )
        if candidates > normalized:
            raise ValueError(
                "unique_marketplace_candidates cannot exceed normalized URLs"
            )
        object.__setattr__(self, "pure_discovery_seconds", seconds)
        object.__setattr__(self, "raw_url_observations", raw)
        object.__setattr__(self, "valid_url_observations", valid)
        object.__setattr__(self, "normalized_unique_urls", normalized)
        object.__setattr__(self, "unique_objects", objects)
        object.__setattr__(self, "unique_marketplace_candidates", candidates)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "backend_kind", backend_kind)
        object.__setattr__(self, "actual_in_flight", in_flight)


@dataclass(frozen=True)
class FunnelStage:
    name: str
    retained_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "funnel stage name"))
        object.__setattr__(
            self,
            "retained_count",
            _count(self.retained_count, "funnel retained_count"),
        )


@dataclass(frozen=True)
class ThroughputSummary:
    raw_url_observations_per_second: float
    url_discovery_per_second: float
    duplicate_rate: float
    successful_page_bodies_per_second: float | None
    unique_valid_structured_records_per_second: float | None
    unique_marketplace_candidates_per_second: float | None
    recent_unique_marketplace_candidates_per_second: float | None


def validate_funnel(
    checkpoints: Sequence[SearchCheckpoint],
    stages: Sequence[FunnelStage],
) -> tuple[FunnelStage, ...]:
    series = _validated_series(checkpoints)
    funnel = tuple(stages)
    names = tuple(stage.name for stage in funnel)
    if names not in {FUNNEL_STAGE_NAMES, MARKETPLACE_FUNNEL_STAGE_NAMES}:
        raise ValueError(
            "funnel must contain a canonical stage sequence"
        )
    if funnel[0].retained_count != series[-1].raw_url_observations:
        raise ValueError(
            "funnel origin must equal final raw_url_observations for the same cohort"
        )
    for previous, current in zip(funnel, funnel[1:]):
        if current.retained_count > previous.retained_count:
            raise ValueError("funnel retained counts must be non-increasing")
    return funnel


def active_discovery_seconds(
    intervals: Iterable[tuple[float, float]],
) -> float:
    """Return wall-clock union length for URL-discovery request intervals."""
    validated: list[tuple[float, float]] = []
    for item in intervals:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("each interval must contain start and end")
        start = _finite_nonnegative(item[0], "interval start")
        end = _finite_nonnegative(item[1], "interval end")
        if end < start:
            raise ValueError("interval end must not precede start")
        validated.append((start, end))
    if not validated:
        return 0.0

    validated.sort()
    total = 0.0
    current_start, current_end = validated[0]
    for start, end in validated[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    total += current_end - current_start
    return total


def _validated_series(
    checkpoints: Sequence[SearchCheckpoint],
) -> tuple[SearchCheckpoint, ...]:
    series = tuple(checkpoints)
    if not series:
        raise ValueError("at least one checkpoint is required")
    for checkpoint in series:
        if not isinstance(checkpoint, SearchCheckpoint):
            raise ValueError("checkpoints must be SearchCheckpoint instances")
    first = series[0]
    if first.pure_discovery_seconds != 0 or first.raw_url_observations != 0:
        raise ValueError("the first checkpoint must be the 0-second/0-URL origin")
    for previous, current in zip(series, series[1:]):
        if current.pure_discovery_seconds < previous.pure_discovery_seconds:
            raise ValueError("checkpoint time must be monotonic")
        for field in CUMULATIVE_FIELDS:
            if getattr(current, field) < getattr(previous, field):
                raise ValueError(f"{field} must be cumulative")
    return series


def _rate(count: int, seconds: float, name: str) -> float:
    count = _count(count, name)
    seconds = _finite_nonnegative(seconds, f"{name}_seconds")
    if seconds == 0:
        if count:
            raise ValueError(f"{name} cannot be positive at zero seconds")
        return 0.0
    return count / seconds


def _optional_rate(
    count: int | None,
    seconds: float | None,
    name: str,
) -> float | None:
    if count is None and seconds is None:
        return None
    if count is None or seconds is None:
        raise ValueError(f"{name} count and seconds must be provided together")
    return _rate(count, seconds, name)


def summarize_throughput(
    checkpoints: Sequence[SearchCheckpoint],
    *,
    successful_page_bodies: int | None = None,
    page_read_seconds: float | None = None,
    unique_valid_structured_records: int | None = None,
    structured_request_seconds: float | None = None,
    marketplace: bool = False,
) -> ThroughputSummary:
    series = _validated_series(checkpoints)
    final = series[-1]
    elapsed = final.pure_discovery_seconds
    raw_rate = _rate(
        final.raw_url_observations, elapsed, "raw_url_observations"
    )
    unique_rate = _rate(
        final.normalized_unique_urls, elapsed, "normalized_unique_urls"
    )
    duplicate_rate = (
        (final.raw_url_observations - final.normalized_unique_urls)
        / final.raw_url_observations
        if final.raw_url_observations
        else 0.0
    )
    marketplace_rate: float | None = None
    recent_marketplace_rate: float | None = None
    if marketplace:
        marketplace_rate = _rate(
            final.unique_marketplace_candidates,
            elapsed,
            "unique_marketplace_candidates",
        )
        cutoff = max(0.0, elapsed - 30.0)
        anchor = max(
            (point for point in series if point.pure_discovery_seconds <= cutoff),
            key=lambda point: point.pure_discovery_seconds,
        )
        recent_seconds = elapsed - anchor.pure_discovery_seconds
        recent_count = (
            final.unique_marketplace_candidates
            - anchor.unique_marketplace_candidates
        )
        recent_marketplace_rate = _rate(
            recent_count,
            recent_seconds,
            "recent_unique_marketplace_candidates",
        )
    return ThroughputSummary(
        raw_url_observations_per_second=raw_rate,
        url_discovery_per_second=unique_rate,
        duplicate_rate=duplicate_rate,
        successful_page_bodies_per_second=_optional_rate(
            successful_page_bodies,
            page_read_seconds,
            "successful_page_bodies",
        ),
        unique_valid_structured_records_per_second=_optional_rate(
            unique_valid_structured_records,
            structured_request_seconds,
            "unique_valid_structured_records",
        ),
        unique_marketplace_candidates_per_second=marketplace_rate,
        recent_unique_marketplace_candidates_per_second=recent_marketplace_rate,
    )


def downsample_checkpoints(
    checkpoints: Sequence[SearchCheckpoint],
    limit: int = 24,
) -> tuple[SearchCheckpoint, ...]:
    series = _validated_series(checkpoints)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2:
        raise ValueError("limit must be an integer of at least two")
    if len(series) <= limit:
        return series

    required = {0, len(series) - 1}
    for index in range(1, len(series)):
        previous = series[index - 1]
        current = series[index]
        if (
            current.backend != previous.backend
            or current.backend_kind != previous.backend_kind
        ):
            required.add(index)
    if len(required) > limit:
        return tuple(series[index] for index in sorted(required))

    optional = [index for index in range(1, len(series) - 1) if index not in required]
    slots = min(limit - len(required), len(optional))
    selected = set(required)
    for position in range(slots):
        optional_index = ((position + 1) * len(optional)) // (slots + 1)
        selected.add(optional[optional_index])
    return tuple(series[index] for index in sorted(selected))


def _format_number(value: float | int) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return format(number, ".6g")


def render_mermaid(
    checkpoints: Sequence[SearchCheckpoint],
    *,
    limit: int = 24,
    marketplace: bool = False,
) -> str:
    series = downsample_checkpoints(checkpoints, limit=limit)
    x_values = ", ".join(
        _format_number(point.pure_discovery_seconds) for point in series
    )
    counts = [
        point.unique_marketplace_candidates if marketplace else point.raw_url_observations
        for point in series
    ]
    y_values = ", ".join(str(value) for value in counts)
    y_max = max(1, max(counts))
    title = "搜索时间—累计去重商品候选" if marketplace else "搜索时间—累计未去重 URL"
    axis = "累计去重商品候选数" if marketplace else "累计未去重 URL 数"
    return (
        "```mermaid\n"
        "xychart-beta\n"
        f'    title "{title}"\n'
        f'    x-axis "纯搜索时间（秒）" [{x_values}]\n'
        f'    y-axis "{axis}" 0 --> {y_max}\n'
        f"    line [{y_values}]\n"
        "```"
    )


def _nice_ceiling(value: int) -> int:
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 4, 5, 8, 10):
        candidate = factor * magnitude
        if candidate >= value:
            return int(candidate)
    raise AssertionError("unreachable")


def _render_discovery_svg(
    checkpoints: Sequence[SearchCheckpoint],
    *,
    limit: int = 24,
    marketplace: bool = False,
) -> str:
    """Render a dependency-free inline SVG for fast chat display."""
    series = (
        _validated_series(checkpoints)
        if marketplace
        else downsample_checkpoints(checkpoints, limit=limit)
    )
    width, height = 720, 360
    left, right, top, bottom = 64, 24, 40, 60
    plot_width = width - left - right
    plot_height = height - top - bottom
    final = series[-1]
    x_max = max(1.0, final.pure_discovery_seconds)
    def count(point: SearchCheckpoint) -> int:
        return (
            point.unique_marketplace_candidates
            if marketplace
            else point.raw_url_observations
        )

    y_max = _nice_ceiling(max(count(point) for point in series))
    chart_title = (
        "搜索时间—累计去重商品候选"
        if marketplace
        else "搜索时间—累计未去重 URL"
    )
    y_axis_label = "累计去重商品候选" if marketplace else "累计未去重 URL"
    rate_unit = "去重候选/秒" if marketplace else "URL/s"
    discovery_color = "#2e7d32" if marketplace else "#c62828"

    def x_position(seconds: float) -> float:
        return left + (seconds / x_max) * plot_width

    def y_position(count: int) -> float:
        return top + plot_height - (count / y_max) * plot_height

    points = " ".join(
        f"{_format_number(x_position(point.pure_discovery_seconds))},"
        f"{_format_number(y_position(count(point)))}"
        for point in series
    )
    average = (
        count(final) / final.pure_discovery_seconds
        if final.pure_discovery_seconds
        else 0.0
    )
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 720 360" role="img" '
        f'aria-label="{chart_title}" '
        'style="width:100%;max-width:720px;height:auto;background:#fff">',
        '  <rect width="720" height="360" fill="#fff" />',
        '  <text x="360" y="26" text-anchor="middle" font-size="24" '
        f'font-weight="600" fill="#111111">{chart_title}</text>',
    ]
    for step in range(5):
        fraction = step / 4
        x = left + fraction * plot_width
        y = top + plot_height - fraction * plot_height
        elements.extend(
            [
                f'  <line x1="{_format_number(left)}" y1="{_format_number(y)}" '
                f'x2="{_format_number(width - right)}" y2="{_format_number(y)}" '
                'stroke="#d0d0d0" stroke-width="1.25" />',
                f'  <line x1="{_format_number(x)}" y1="{_format_number(top)}" '
                f'x2="{_format_number(x)}" y2="{_format_number(top + plot_height)}" '
                'stroke="#d0d0d0" stroke-width="1.25" />',
                f'  <text x="{_format_number(left - 10)}" y="{_format_number(y + 4)}" '
                'text-anchor="end" font-size="16" fill="#111111">'
                f'{_format_number(y_max * fraction)}</text>',
                f'  <text x="{_format_number(x)}" y="320" text-anchor="middle" '
                'font-size="16" fill="#111111">'
                f'{_format_number(x_max * fraction)}</text>',
            ]
        )
    elements.extend(
        [
            '  <line x1="64" y1="40" x2="64" y2="300" '
            'stroke="#111111" stroke-width="2.5" />',
            '  <line x1="64" y1="300" x2="696" y2="300" '
            'stroke="#111111" stroke-width="2.5" />',
            '  <text x="380" y="345" text-anchor="middle" font-size="18" '
            'fill="#111111">纯搜索时间（秒）</text>',
            '  <text transform="translate(18 170) rotate(-90)" '
            'text-anchor="middle" font-size="18" fill="#111111">'
            f'{y_axis_label}</text>',
            f'  <polyline data-series="discovery" points="{points}" fill="none" '
            f'stroke="{discovery_color}" stroke-width="4" stroke-linecap="round" '
            'stroke-linejoin="round" />',
        ]
    )
    for point in series:
        x = x_position(point.pure_discovery_seconds)
        y = y_position(count(point))
        elements.append(
            f'  <circle data-discovery-marker="true" cx="{_format_number(x)}" '
            f'cy="{_format_number(y)}" r="5" fill="{discovery_color}" '
            'stroke="#ffffff" stroke-width="2" />'
        )
    elements.extend(
        [
            '  <rect x="82" y="48" width="235" height="33" rx="4" '
            'fill="#fff" stroke="#111111" stroke-width="1.5" />',
            '  <line x1="92" y1="61" x2="119" y2="61" '
            f'stroke="{discovery_color}" stroke-width="4" />',
            '  <text x="128" y="70" font-size="18" font-weight="600" '
            f'fill="#111111">平均速度 {_format_number(average)} {rate_unit}</text>',
            '</svg>',
        ]
    )
    return "\n".join(elements)


def _render_funnel_svg(
    checkpoints: Sequence[SearchCheckpoint],
    funnel: Sequence[FunnelStage],
    *,
    limit: int,
    marketplace: bool = False,
) -> str:
    series = (
        _validated_series(checkpoints)
        if marketplace
        else downsample_checkpoints(checkpoints, limit=limit)
    )
    stages = validate_funnel(series, funnel)
    width, height = 1100, 540
    left, split, right = 82.0, 600.0, 1015.0
    top, bottom = 76.0, 448.0
    plot_height = bottom - top
    final = series[-1]
    x_max = max(1.0, final.pure_discovery_seconds)
    y_max = _nice_ceiling(stages[0].retained_count)

    def y_position(count: int) -> float:
        return bottom - (count / y_max) * plot_height

    def discovery_x(seconds: float) -> float:
        return left + (seconds / x_max) * (split - left)

    def funnel_x(index: int) -> float:
        return split + (index / (len(stages) - 1)) * (right - split)

    def discovery_count(point: SearchCheckpoint) -> int:
        return (
            point.unique_marketplace_candidates
            if marketplace
            else point.raw_url_observations
        )

    discovery_points = " ".join(
        f"{_format_number(discovery_x(point.pure_discovery_seconds))},"
        f"{_format_number(y_position(discovery_count(point)))}"
        for point in series
    )
    funnel_points = " ".join(
        f"{_format_number(funnel_x(index))},"
        f"{_format_number(y_position(stage.retained_count))}"
        for index, stage in enumerate(stages)
    )
    average = (
        discovery_count(final) / final.pure_discovery_seconds
        if final.pure_discovery_seconds
        else 0.0
    )
    record_yield = (
        stages[-1].retained_count / stages[0].retained_count * 100
        if stages[0].retained_count
        else 0.0
    )
    chart_title = (
        "商品候选发现与 L0–L3 漏斗"
        if marketplace
        else "URL 发现与商品筛选完整漏斗"
    )
    left_axis = "累计去重商品候选" if marketplace else "累计未去重 URL"
    rate_unit = "去重候选/秒" if marketplace else "URL/s"
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 1100 540" role="img" '
        f'aria-label="{chart_title}" '
        'style="width:100%;max-width:1100px;height:auto;background:#fff">',
        '  <rect width="1100" height="540" fill="#fff" />',
        '  <text x="550" y="30" text-anchor="middle" font-size="24" '
        f'font-weight="700" fill="#111111">{chart_title}</text>',
    ]
    for step in range(5):
        fraction = step / 4
        y = bottom - fraction * plot_height
        value = y_max * fraction
        elements.extend(
            [
                f'  <line x1="{left}" y1="{_format_number(y)}" x2="{right}" '
                f'y2="{_format_number(y)}" stroke="#d0d0d0" stroke-width="1.1" />',
                f'  <text x="{left - 10}" y="{_format_number(y + 4)}" '
                'text-anchor="end" font-size="16" fill="#111111">'
                f'{_format_number(value)}</text>',
                f'  <text x="{right + 10}" y="{_format_number(y + 4)}" '
                'font-size="16" fill="#111111">'
                f'{_format_number(value)}</text>',
            ]
        )
    for step in range(5):
        fraction = step / 4
        x = left + fraction * (split - left)
        elements.extend(
            [
                f'  <line x1="{_format_number(x)}" y1="{top}" '
                f'x2="{_format_number(x)}" y2="{bottom}" '
                'stroke="#e1e1e1" stroke-width="1" />',
                f'  <text x="{_format_number(x)}" y="474" text-anchor="middle" '
                'font-size="16" fill="#111111">'
                f'{_format_number(x_max * fraction)}</text>',
            ]
        )
    elements.extend(
        [
            f'  <line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" '
            'stroke="#111111" stroke-width="2.5" />',
            f'  <line x1="{left}" y1="{bottom}" x2="{split}" y2="{bottom}" '
            'stroke="#111111" stroke-width="2.5" />',
            f'  <line x1="{split}" y1="{top}" x2="{right}" y2="{top}" '
            'stroke="#111111" stroke-width="2.5" />',
            f'  <line x1="{right}" y1="{top}" x2="{right}" y2="{bottom}" '
            'stroke="#111111" stroke-width="2.5" />',
            '  <text x="341" y="522" text-anchor="middle" font-size="18" '
            'font-weight="600" fill="#111111">纯搜索时间（秒）</text>',
            '  <text x="808" y="60" text-anchor="middle" font-size="18" '
            'font-weight="600" fill="#111111">筛选阶段</text>',
            '  <text transform="translate(18 241) rotate(-90)" '
            'text-anchor="middle" font-size="18" font-weight="600" '
            f'fill="#111111">{left_axis}</text>',
            '  <text transform="translate(1082 241) rotate(90)" '
            'text-anchor="middle" font-size="18" font-weight="600" '
            'fill="#111111">筛选后保留 URL / 商品记录</text>',
            f'  <polyline data-series="discovery" points="{discovery_points}" '
            'fill="none" stroke="#2e7d32" stroke-width="4" '
            'stroke-linecap="round" stroke-linejoin="round" />',
            f'  <polyline data-series="funnel" points="{funnel_points}" fill="none" '
            'stroke="#c62828" stroke-width="4" stroke-linecap="round" '
            'stroke-linejoin="round" />',
            '  <rect x="100" y="88" width="390" height="70" rx="5" '
            'fill="#fff" stroke="#111111" stroke-width="1.5" />',
            '  <line x1="114" y1="109" x2="148" y2="109" '
            'stroke="#2e7d32" stroke-width="4" />',
            f'  <text x="160" y="115" font-size="18" font-weight="600" '
            f'fill="#111111">平均速度 {_format_number(average)} {rate_unit}</text>',
            '  <line x1="114" y1="137" x2="148" y2="137" '
            'stroke="#c62828" stroke-width="4" />',
            f'  <text x="160" y="143" font-size="18" font-weight="600" '
            f'fill="#111111">商品命中率 {_format_number(record_yield)}%</text>',
        ]
    )
    for index, stage in enumerate(stages):
        x = funnel_x(index)
        y = y_position(stage.retained_count)
        retention = (
            stage.retained_count / stages[0].retained_count * 100
            if stages[0].retained_count
            else 0.0
        )
        if y <= top + 60:
            label_y = y + 24 + (index % 2) * 18
        elif y >= bottom - 80:
            label_y = y - 28 - (index % 3) * 20
        else:
            direction = -1 if index % 2 == 0 else 1
            label_y = y + direction * (28 + (index % 2) * 14)
        label_y = min(bottom - 18, max(top + 18, label_y))
        connector_y = label_y + 22 if label_y < y else label_y - 18
        short_label = FUNNEL_STAGE_LABELS[stage.name]
        elements.extend(
            [
                f'  <circle cx="{_format_number(x)}" cy="{_format_number(y)}" '
                'r="4" fill="#c62828" />',
                f'  <title>{escape(stage.name)}: {stage.retained_count}</title>',
                f'  <line x1="{_format_number(x)}" y1="{_format_number(y)}" '
                f'x2="{_format_number(x)}" y2="{_format_number(connector_y)}" '
                'stroke="#c62828" stroke-width="1.5" '
                'data-label-connector="true" />',
                f'  <text x="{_format_number(x)}" y="{_format_number(label_y)}" '
                'text-anchor="middle" font-size="16" fill="#111111">'
                f'{escape(short_label)}</text>',
                f'  <text x="{_format_number(x)}" '
                f'y="{_format_number(label_y + 16)}" '
                'text-anchor="middle" font-size="16" font-weight="600" '
                f'fill="#111111">{stage.retained_count} '
                f'({_format_number(retention)}%)</text>',
            ]
        )
    for point in series:
        x = discovery_x(point.pure_discovery_seconds)
        y = y_position(discovery_count(point))
        elements.append(
            f'  <circle data-discovery-marker="true" cx="{_format_number(x)}" '
            f'cy="{_format_number(y)}" r="6" fill="none" '
            'stroke="#2e7d32" stroke-width="3" />'
        )
    elements.append("</svg>")
    return "\n".join(elements)


def render_svg(
    checkpoints: Sequence[SearchCheckpoint],
    *,
    funnel: Sequence[FunnelStage] | None = None,
    limit: int = 24,
    marketplace: bool = False,
) -> str:
    if funnel is None:
        return _render_discovery_svg(
            checkpoints, limit=limit, marketplace=marketplace
        )
    return _render_funnel_svg(
        checkpoints, funnel, limit=limit, marketplace=marketplace
    )


def render_codex_fragment(
    checkpoints: Sequence[SearchCheckpoint],
    *,
    funnel: Sequence[FunnelStage] | None = None,
    limit: int = 24,
    marketplace: bool = False,
) -> str:
    """Wrap the SVG in a dependency-free Codex inline zoom/pan surface."""
    series = _validated_series(checkpoints)
    final = series[-1]
    terminal = funnel[-1].retained_count if funnel else final.unique_objects
    root_id = (
        f"search-timeline-{final.raw_url_observations}-"
        f"{round(final.pure_discovery_seconds * 1000)}-{terminal}"
    )
    svg = render_svg(
        checkpoints, funnel=funnel, limit=limit, marketplace=marketplace
    )
    fragment = """<div id="__ROOT_ID__" data-search-timeline-root>
  <div class="viz-controls" role="group" aria-label="搜索轨迹缩放控制">
    <button type="button" class="btn" data-action="zoom-in">放大</button>
    <button type="button" class="btn" data-action="zoom-out">缩小</button>
    <button type="button" class="btn" data-action="reset">重置</button>
    <span data-zoom-value aria-live="polite">1.00×</span>
    <span class="text-small">图内滚轮缩放，放大后拖动平移</span>
  </div>
  <div data-zoom-viewport aria-label="可缩放搜索轨迹图">__SVG__</div>
  <style>
    #__ROOT_ID__ [data-zoom-viewport] { overflow: hidden; touch-action: none; cursor: grab; }
    #__ROOT_ID__ [data-zoom-viewport].is-dragging { cursor: grabbing; }
    #__ROOT_ID__ [data-zoom-viewport] svg { display: block; width: 100%; max-width: none; height: auto; }
  </style>
  <script>
    (() => {
      const root = document.getElementById("__ROOT_ID__");
      if (!root || root.dataset.zoomReady === "true") return;
      root.dataset.zoomReady = "true";
      const viewport = root.querySelector("[data-zoom-viewport]");
      const svg = viewport.querySelector("svg");
      const zoomValue = root.querySelector("[data-zoom-value]");
      const zoomIn = root.querySelector('[data-action="zoom-in"]');
      const zoomOut = root.querySelector('[data-action="zoom-out"]');
      const reset = root.querySelector('[data-action="reset"]');
      const MIN_SCALE = 1;
      const MAX_SCALE = 4;
      const initial = svg.viewBox.baseVal;
      const original = {
        x: initial.x,
        y: initial.y,
        width: initial.width,
        height: initial.height
      };
      const view = { ...original };
      let dragging = false;
      let dragStart = null;

      const currentScale = () => original.width / view.width;
      const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
      const clampView = () => {
        view.x = clamp(view.x, original.x, original.x + original.width - view.width);
        view.y = clamp(view.y, original.y, original.y + original.height - view.height);
      };
      const applyView = () => {
        clampView();
        svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.width} ${view.height}`);
        zoomValue.textContent = `${currentScale().toFixed(2)}×`;
      };
      const zoomAt = (clientX, clientY, multiplier) => {
        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const oldScale = currentScale();
        const nextScale = clamp(oldScale * multiplier, MIN_SCALE, MAX_SCALE);
        if (Math.abs(nextScale - oldScale) < 1e-9) return;
        const ratioX = clamp((clientX - rect.left) / rect.width, 0, 1);
        const ratioY = clamp((clientY - rect.top) / rect.height, 0, 1);
        const anchorX = view.x + ratioX * view.width;
        const anchorY = view.y + ratioY * view.height;
        view.width = original.width / nextScale;
        view.height = original.height / nextScale;
        view.x = anchorX - ratioX * view.width;
        view.y = anchorY - ratioY * view.height;
        applyView();
      };
      const zoomFromCenter = (multiplier) => {
        const rect = svg.getBoundingClientRect();
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, multiplier);
      };

      viewport.addEventListener("wheel", (event) => {
        const scale = currentScale();
        const atLowerBound = scale <= MIN_SCALE + 1e-9 && event.deltaY > 0;
        const atUpperBound = scale >= MAX_SCALE - 1e-9 && event.deltaY < 0;
        if (atLowerBound || atUpperBound) return;
        event.preventDefault();
        zoomAt(event.clientX, event.clientY, event.deltaY < 0 ? 1.18 : 1 / 1.18);
      }, { passive: false });

      viewport.addEventListener("pointerdown", (event) => {
        if (currentScale() <= MIN_SCALE) return;
        dragging = true;
        dragStart = {
          clientX: event.clientX,
          clientY: event.clientY,
          x: view.x,
          y: view.y,
          width: view.width,
          height: view.height
        };
        viewport.classList.add("is-dragging");
        viewport.setPointerCapture(event.pointerId);
      });
      viewport.addEventListener("pointermove", (event) => {
        if (!dragging || !dragStart) return;
        const rect = svg.getBoundingClientRect();
        view.x = dragStart.x - (event.clientX - dragStart.clientX) / rect.width * dragStart.width;
        view.y = dragStart.y - (event.clientY - dragStart.clientY) / rect.height * dragStart.height;
        applyView();
      });
      const stopDragging = (event) => {
        if (!dragging) return;
        dragging = false;
        dragStart = null;
        viewport.classList.remove("is-dragging");
        if (viewport.hasPointerCapture(event.pointerId)) {
          viewport.releasePointerCapture(event.pointerId);
        }
      };
      viewport.addEventListener("pointerup", stopDragging);
      viewport.addEventListener("pointercancel", stopDragging);
      zoomIn.addEventListener("click", () => zoomFromCenter(1.25));
      zoomOut.addEventListener("click", () => zoomFromCenter(1 / 1.25));
      reset.addEventListener("click", () => {
        Object.assign(view, original);
        applyView();
      });
      applyView();
    })();
  </script>
</div>"""
    return fragment.replace("__ROOT_ID__", root_id).replace("__SVG__", svg)


def render_ascii(
    checkpoints: Sequence[SearchCheckpoint],
    *,
    funnel: Sequence[FunnelStage] | None = None,
    limit: int = 24,
    marketplace: bool = False,
) -> str:
    series = (
        _validated_series(checkpoints)
        if marketplace
        else downsample_checkpoints(checkpoints, limit=limit)
    )
    def count(point: SearchCheckpoint) -> int:
        return point.unique_marketplace_candidates if marketplace else point.raw_url_observations

    maximum = max(count(point) for point in series)
    if maximum == 0:
        sparkline = BLOCKS[0] * len(series)
    else:
        sparkline = "".join(
            BLOCKS[round((count(point) / maximum) * (len(BLOCKS) - 1))]
            for point in series
        )
    final = series[-1]
    unit = "候选" if marketplace else "URL"
    chart = (
        f"字符折线：{sparkline}  "
        f"0s/0 {unit} → {_format_number(final.pure_discovery_seconds)}s/"
        f"{count(final)} {unit}"
    )
    if funnel is None:
        return chart
    stages = validate_funnel(series, funnel)
    return chart + "；漏斗：" + " → ".join(
        f"{FUNNEL_STAGE_LABELS[stage.name]}={stage.retained_count}"
        for stage in stages
    )


def _checkpoint_from_mapping(value: Mapping[str, object]) -> SearchCheckpoint:
    if not isinstance(value, Mapping):
        raise ValueError("each checkpoint must be a JSON object")
    try:
        return SearchCheckpoint(
            pure_discovery_seconds=value["pure_discovery_seconds"],
            raw_url_observations=value["raw_url_observations"],
            valid_url_observations=value["valid_url_observations"],
            normalized_unique_urls=value["normalized_unique_urls"],
            unique_objects=value["unique_objects"],
            backend=value["backend"],
            backend_kind=value["backend_kind"],
            actual_in_flight=value["actual_in_flight"],
            unique_marketplace_candidates=value.get(
                "unique_marketplace_candidates", 0
            ),
        )
    except KeyError as error:
        raise ValueError(f"missing checkpoint field: {error.args[0]}") from error


def _funnel_stage_from_mapping(value: Mapping[str, object]) -> FunnelStage:
    if not isinstance(value, Mapping):
        raise ValueError("each funnel stage must be a JSON object")
    try:
        return FunnelStage(
            name=value["name"],
            retained_count=value["retained_count"],
        )
    except KeyError as error:
        raise ValueError(f"missing funnel field: {error.args[0]}") from error


def _optional_pair(
    payload: Mapping[str, object],
    count_key: str,
    seconds_key: str,
) -> tuple[object | None, object | None]:
    count_present = count_key in payload
    seconds_present = seconds_key in payload
    if count_present != seconds_present:
        raise ValueError(f"{count_key} and {seconds_key} must appear together")
    if not count_present:
        return None, None
    return payload[count_key], payload[seconds_key]


def run_cli(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("input must be a JSON object")
    raw_checkpoints = payload.get("checkpoints")
    if not isinstance(raw_checkpoints, list):
        raise ValueError("checkpoints must be a JSON array")
    checkpoints = tuple(
        _checkpoint_from_mapping(value) for value in raw_checkpoints
    )
    marketplace = payload.get("run_type") == "catalog_enumeration"
    raw_funnel = payload.get("funnel")
    funnel: tuple[FunnelStage, ...] | None = None
    if raw_funnel is not None:
        if not isinstance(raw_funnel, list):
            raise ValueError("funnel must be a JSON array")
        funnel = tuple(_funnel_stage_from_mapping(value) for value in raw_funnel)
        validate_funnel(checkpoints, funnel)
    page_count, page_seconds = _optional_pair(
        payload, "successful_page_bodies", "page_read_seconds"
    )
    record_count, record_seconds = _optional_pair(
        payload,
        "unique_valid_structured_records",
        "structured_request_seconds",
    )
    summary = summarize_throughput(
        checkpoints,
        successful_page_bodies=page_count,
        page_read_seconds=page_seconds,
        unique_valid_structured_records=record_count,
        structured_request_seconds=record_seconds,
        marketplace=marketplace,
    )
    chart_format = payload.get("format", "svg")
    if chart_format == "svg":
        chart = render_svg(checkpoints, funnel=funnel, marketplace=marketplace)
    elif chart_format == "html":
        chart = render_codex_fragment(
            checkpoints, funnel=funnel, marketplace=marketplace
        )
    elif chart_format == "mermaid":
        chart = render_mermaid(checkpoints, marketplace=marketplace)
    elif chart_format == "ascii":
        chart = render_ascii(
            checkpoints, funnel=funnel, marketplace=marketplace
        )
    else:
        raise ValueError("format must be svg, html, mermaid, or ascii")
    metrics = asdict(summary)
    if funnel is not None:
        origin = funnel[0].retained_count
        metrics["product_candidate_yield"] = (
            funnel[-2].retained_count / origin if origin else 0.0
        )
        metrics["final_record_yield"] = (
            funnel[-1].retained_count / origin if origin else 0.0
        )
    return {
        "format": chart_format,
        "chart": chart,
        "metrics": metrics,
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = run_cli(payload)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
