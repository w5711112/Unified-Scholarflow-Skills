"""Pure, JSON-serializable continuation state for public JD search pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


JD_PROTOCOL_PAGE_MAX = 512
QUERY_SUFFIXES = ("", "自营", "品牌", "型号", "新品")
RECOVERY_STAGES = frozenset({"initial", "reproject", "reload"})
SOFT_JD_FAILURE_CATEGORIES = frozenset(
    {"pagination_page_transient_empty", "pagination_page_stalled"}
)
FAMILY_ROTATION_FAILURE_CATEGORIES = frozenset(
    {
        "browser_page_structure_changed",
        "pagination_session_missing",
        "page_exhausted",
    }
)
HARD_JD_FAILURE_CATEGORIES = frozenset(
    {
        "authentication_required",
        "browser_authentication_required",
        "captcha_required",
        "browser_captcha_required",
        "rate_limited",
        "browser_rate_limited",
    }
)


@dataclass(frozen=True)
class JdPageRequest:
    """The one page that a caller may materialize from a continuation plan."""

    topic: str
    query: str
    query_family: str
    family_index: int
    page_number: int
    session_action: str
    recovery_attempt: int


def deterministic_query_families(topic: str) -> tuple[str, ...]:
    """Return the fixed, normalized query family for one user topic."""
    base = " ".join(topic.split())
    if not base:
        raise ValueError("topic must not be empty")
    return tuple(
        dict.fromkeys(
            base if not suffix else f"{base} {suffix}" for suffix in QUERY_SUFFIXES
        )
    )


def new_continuation(topics: Sequence[str]) -> dict[str, object]:
    """Create a fresh plan without materializing any page request."""
    normalized_topics = [" ".join(topic.split()) for topic in topics]
    if not normalized_topics or any(not topic for topic in normalized_topics):
        raise ValueError("topics must contain at least one non-empty topic")
    families = list(deterministic_query_families(normalized_topics[0]))
    return {
        "topics": normalized_topics,
        "topic_index": 0,
        "families": families,
        "family_index": 0,
        "page_number": 1,
        "recovery_stage": "initial",
        "recovery_attempt": 0,
        "abandoned_families": [],
        "complete": False,
    }


def current_request(plan: Mapping[str, object]) -> JdPageRequest | None:
    """Return the current single-page request, or ``None`` after completion."""
    if plan["complete"] or int(plan["page_number"]) > JD_PROTOCOL_PAGE_MAX:
        return None
    topic_index = int(plan["topic_index"])
    family_index = int(plan["family_index"])
    topics = plan["topics"]
    families = plan["families"]
    if not isinstance(topics, list) or not isinstance(families, list):
        raise TypeError("continuation plan must use JSON lists for topics and families")
    topic = str(topics[topic_index])
    query = str(families[family_index])
    recovery_stage = str(plan["recovery_stage"])
    if recovery_stage not in RECOVERY_STAGES:
        raise ValueError(f"unsupported recovery stage: {recovery_stage}")
    return JdPageRequest(
        topic=topic,
        query=query,
        query_family=query,
        family_index=family_index,
        page_number=int(plan["page_number"]),
        session_action="recover"
        if recovery_stage in {"reproject", "reload"}
        else ("start" if int(plan["page_number"]) == 1 else "next"),
        recovery_attempt=int(plan["recovery_attempt"]),
    )


def page_verified(plan: dict[str, object]) -> None:
    """Advance exactly one verified page and clear its recovery state."""
    plan["recovery_stage"] = "initial"
    plan["recovery_attempt"] = 0
    if int(plan["page_number"]) >= JD_PROTOCOL_PAGE_MAX:
        plan["page_number"] = JD_PROTOCOL_PAGE_MAX
        plan["complete"] = True
        return
    plan["page_number"] = int(plan["page_number"]) + 1


def soft_failure(plan: dict[str, object], category: str) -> None:
    """Move the current family through its bounded recovery stages."""
    _require_allowed_category(category, SOFT_JD_FAILURE_CATEGORIES, "soft_failure")
    attempt = min(int(plan["recovery_attempt"]) + 1, 2)
    plan["recovery_attempt"] = attempt
    plan["recovery_stage"] = "reproject" if attempt == 1 else "reload"


def recovery_failed(plan: dict[str, object], category: str) -> None:
    """Abandon the current family and deterministically select the next one."""
    _require_allowed_category(
        category, FAMILY_ROTATION_FAILURE_CATEGORIES, "recovery_failed"
    )
    families = plan["families"]
    abandoned_families = plan["abandoned_families"]
    if not isinstance(families, list) or not isinstance(abandoned_families, list):
        raise TypeError("continuation plan must use JSON lists for families")
    family_index = int(plan["family_index"])
    abandoned_families.append(str(families[family_index]))
    plan["family_index"] = family_index + 1
    if int(plan["family_index"]) >= len(families):
        _advance_topic(plan)
    else:
        _reset_family_cursor(plan)


def advance_to_next_topic(plan: dict[str, object]) -> None:
    """Debug page cap reached: skip the remaining families of the current topic
    and select the first family of the next topic (or mark complete). This makes
    ``--max-pages-per-topic`` a per-topic total, so multi-topic runs rotate
    across topics instead of idling forever at the page cap."""
    _advance_topic(plan)


def _advance_topic(plan: dict[str, object]) -> None:
    """Select the first family of the next normalized topic, if any."""
    next_topic_index = int(plan["topic_index"]) + 1
    topics = plan["topics"]
    if not isinstance(topics, list):
        raise TypeError("continuation plan must use a JSON list for topics")
    if next_topic_index >= len(topics):
        plan["complete"] = True
        plan["recovery_stage"] = "initial"
        plan["recovery_attempt"] = 0
        return
    plan["topic_index"] = next_topic_index
    plan["families"] = list(deterministic_query_families(str(topics[next_topic_index])))
    plan["family_index"] = 0
    _reset_family_cursor(plan)


def _reset_family_cursor(plan: dict[str, object]) -> None:
    """Start a new family from page one with no pending recovery."""
    plan["page_number"] = 1
    plan["recovery_stage"] = "initial"
    plan["recovery_attempt"] = 0


def _require_allowed_category(
    category: str, allowed_categories: frozenset[str], transition: str
) -> None:
    """Reject hard and unknown categories before a continuation state mutation."""
    if category in HARD_JD_FAILURE_CATEGORIES:
        raise ValueError(f"{transition} rejects hard JD category: {category}")
    if category not in allowed_categories:
        raise ValueError(f"unsupported {transition} category: {category}")
