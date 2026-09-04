from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
from typing import Literal


MarketplacePlatform = Literal["jd", "taobao"]
DOMESTIC_DISCOVERY_ENGINES = ("360search", "baidu", "sogou", "quark")
_PLATFORMS = frozenset({"jd", "taobao"})
DEFAULT_EDGE_USER_DATA_DIR = str(
    Path(__file__).resolve().parents[5]
    / ".codex-runtime"
    / "searching-at-scale"
    / "edge-profile"
)
#: Env carrier the driver sets so the one-shot Node worker and its preflight
#: probe share one per-profile pipe, mirroring ``SAT_JD_PAGINATION_ROUTE``.
SAT_EDGE_PIPE_PATH_ENV = "SAT_EDGE_PIPE_PATH"
#: Default broker pipe held by the user's real Edge extension. Owned skill
#: profiles use a per-profile name so a fresh campaign coexists with Edge.
DEFAULT_BROKER_PIPE_NAME = "codex.searching_at_scale.v1"


def edge_pipe_name(user_data_dir: str | None) -> str | None:
    """Return the broker pipe name for an owned Edge profile.

    ``None`` keeps the shared default pipe, which belongs to the user's real
    Edge extension (legacy no-flag runs). Any explicit profile gets a
    deterministic per-profile name so a fresh campaign coexists with the real
    Edge instead of fighting it for one pipe.
    """
    if user_data_dir is None:
        return None
    token = sha256(user_data_dir.encode("utf-8")).hexdigest()[:12]
    return f"codex.searching_at_scale.{token}"


def edge_pipe_path(user_data_dir: str | None) -> str | None:
    """Return the ``\\\\.\\pipe\\<name>`` worker path, or None for the default."""
    name = edge_pipe_name(user_data_dir)
    if name is None:
        return None
    return rf"\\.\pipe\{name}"
_DIMENSION_NAMES = (
    "brands",
    "specifications",
    "uses",
    "categories",
    "price_bands",
)
EDGE_PAYLOAD_KEYS = frozenset(
    {
        "platform",
        "query",
        "query_family",
        "cursor",
        "user_data_dir",
        "deadline_seconds",
        "max_items",
        "session_action",
        "pagination_enabled",
    }
)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return " ".join(value.split())


def _normalized_values(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    normalized = tuple(_required_text(item, name) for item in value)
    if len({item.casefold() for item in normalized}) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class MarketplaceQueryDimensions:
    topic: str
    brands: tuple[str, ...] = ()
    specifications: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    price_bands: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "topic", _required_text(self.topic, "topic"))
        for name in (*_DIMENSION_NAMES, "exclusions"):
            object.__setattr__(
                self,
                name,
                _normalized_values(getattr(self, name), name),
            )


@dataclass(frozen=True)
class MarketplaceQueryCursor:
    cursor_id: str
    ordinal: int
    platform: MarketplacePlatform
    query_family: str
    query: str
    marketplace_query: str
    engines: tuple[str, ...]
    page_number: int
    sort: str
    category: str
    price_band: str


def _normalized_platforms(platforms: object) -> tuple[MarketplacePlatform, ...]:
    if not isinstance(platforms, tuple) or not platforms:
        raise ValueError("platforms must be a non-empty tuple")
    if any(platform not in _PLATFORMS for platform in platforms):
        raise ValueError("platforms contains an unsupported marketplace")
    if len(set(platforms)) != len(platforms):
        raise ValueError("platforms must be unique")
    return platforms


def _choices(values: tuple[str, ...]) -> tuple[str, ...]:
    return values if values else ("",)


def query_total(
    dimensions: MarketplaceQueryDimensions, *, platforms: tuple[str, ...]
) -> int:
    if not isinstance(dimensions, MarketplaceQueryDimensions):
        raise ValueError("dimensions must be MarketplaceQueryDimensions")
    normalized_platforms = _normalized_platforms(platforms)
    lengths = [len(normalized_platforms)]
    lengths.extend(len(_choices(getattr(dimensions, name))) for name in _DIMENSION_NAMES)
    return math.prod(lengths)


def _decode(
    dimensions: MarketplaceQueryDimensions,
    platforms: tuple[MarketplacePlatform, ...],
    ordinal: int,
) -> tuple[MarketplacePlatform, str, str, str, str, str]:
    axes: tuple[tuple[str, ...], ...] = (
        platforms,
        *tuple(_choices(getattr(dimensions, name)) for name in _DIMENSION_NAMES),
    )
    indexes = [0] * len(axes)
    remainder = ordinal
    for index in range(len(axes) - 1, -1, -1):
        remainder, indexes[index] = divmod(remainder, len(axes[index]))
    return tuple(axis[index] for axis, index in zip(axes, indexes, strict=True))


def _query_text(
    dimensions: MarketplaceQueryDimensions,
    platform: MarketplacePlatform,
    brand: str,
    specification: str,
    use: str,
    category: str,
    price_band: str,
) -> str:
    if platform == "jd":
        site = "site:item.jd.com"
    else:
        site = "(site:item.taobao.com OR site:detail.tmall.com OR site:detail.tmall.hk)"
    parts = [site, dimensions.topic]
    for label, value in (
        ("品牌", brand),
        ("规格", specification),
        ("用途", use),
        ("分类", category),
        ("价格", price_band),
    ):
        if value:
            parts.extend((label, value))
    parts.extend(f"-{value}" for value in dimensions.exclusions)
    return " ".join(parts)


def _marketplace_query_text(
    dimensions: MarketplaceQueryDimensions,
    brand: str,
    specification: str,
    use: str,
    category: str,
    price_band: str,
) -> str:
    parts = [dimensions.topic]
    parts.extend(
        value for value in (brand, specification, use, category, price_band) if value
    )
    parts.extend(f"-{value}" for value in dimensions.exclusions)
    return " ".join(parts)


def query_batch(
    dimensions: MarketplaceQueryDimensions,
    *,
    offset: int,
    limit: int,
    platforms: tuple[str, ...],
) -> tuple[MarketplaceQueryCursor, ...]:
    """Materialize at most ``limit`` deterministic cursors."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
        raise ValueError("limit must be an integer from 1 to 64")
    normalized_platforms = _normalized_platforms(platforms)
    total = query_total(dimensions, platforms=normalized_platforms)
    cursors: list[MarketplaceQueryCursor] = []
    for ordinal in range(offset, min(total, offset + limit)):
        platform, brand, specification, use, category, price_band = _decode(
            dimensions, normalized_platforms, ordinal
        )
        query = _query_text(
            dimensions,
            platform,
            brand,
            specification,
            use,
            category,
            price_band,
        )
        marketplace_query = _marketplace_query_text(
            dimensions,
            brand,
            specification,
            use,
            category,
            price_band,
        )
        identity = f"{platform}\0{ordinal}\0{query}"
        cursor_id = f"{platform}:{sha256(identity.encode('utf-8')).hexdigest()[:20]}"
        cursors.append(
            MarketplaceQueryCursor(
                cursor_id=cursor_id,
                ordinal=ordinal,
                platform=platform,
                query_family=f"{dimensions.topic}:default",
                query=query,
                marketplace_query=marketplace_query,
                engines=DOMESTIC_DISCOVERY_ENGINES,
                page_number=1,
                sort="default",
                category=category,
                price_band=price_band,
            )
        )
    return tuple(cursors)


def edge_task_batch(
    dimensions: MarketplaceQueryDimensions,
    *,
    offset: int,
    limit: int,
    platforms: tuple[str, ...],
    page_numbers: tuple[int, ...] = (1,),
    pagination_enabled: bool = False,
    user_data_dir: str | None = None,
) -> tuple[dict[str, object], ...]:
    """Build a bounded batch of transient Edge marketplace tasks.

    ``user_data_dir`` selects which owned Edge profile the session adapter
    launches (the path must end in ``edge-profile``). Defaults to the shared
    ``DEFAULT_EDGE_USER_DATA_DIR``; alternating profiles across spaced runs
    spreads JD's behavioral risk budget instead of accumulating it on one
    profile.
    """
    if not page_numbers or any(
        isinstance(page, bool) or not isinstance(page, int) or page < 1 or page > 512
        for page in page_numbers
    ):
        raise ValueError("page_numbers must contain integers from 1 to 512")
    if tuple(sorted(set(page_numbers))) != page_numbers:
        raise ValueError("page_numbers must be unique and numerically sorted")
    if not pagination_enabled and page_numbers != (1,):
        raise ValueError("pagination must be explicitly enabled beyond page 1")
    cursors = query_batch(
        dimensions,
        offset=offset,
        limit=limit,
        platforms=platforms,
    )
    tasks: list[dict[str, object]] = []
    for page_number in page_numbers:
        for cursor in cursors:
            tasks.append(
            {
                "task_id": f"edge-marketplace:{cursor.cursor_id}:page-{page_number}",
                "source_class": "marketplace_list",
                "backend": f"edge:{cursor.platform}",
                "query_family": cursor.query_family,
                "query_dimensions": [
                    "platform",
                    "brand",
                    "specification",
                    "use",
                    "category",
                    "price_band",
                ],
                "coverage_targets": [f"platform:{cursor.platform}"],
                "adapter": "edge_marketplace",
                "payload": {
                    "platform": cursor.platform,
                    "query": cursor.marketplace_query,
                    "query_family": cursor.query_family,
                    "cursor": {
                        "cursor_id": cursor.cursor_id,
                        "ordinal": cursor.ordinal,
                        "page_number": page_number,
                    },
                    "user_data_dir": user_data_dir or DEFAULT_EDGE_USER_DATA_DIR,
                    "deadline_seconds": 600.0,
                    "max_items": 1000,
                    "session_action": "start" if page_number == 1 else "next",
                    "pagination_enabled": pagination_enabled,
                },
                "status": "pending",
                "score_inputs": {},
                "concurrency": {"tier": 1, "tool_limit": 1, "host_limit": 1},
            }
        )
    return tuple(tasks)
