from __future__ import annotations

import ipaddress
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from annotation_comment_quality import comment_quality_failures


class SemanticSelectionError(ValueError):
    """Raised when an annotation does not carry enough verifiable information."""


LOW_INFORMATION_EXACT = {
    "we propose",
    "our approach",
    "formal safety guarantees",
    "success rate remains",
    "moving obstacles",
    "forward invariance",
    "trained in isaac lab",
}

REQUIRED_COMMON = {
    "id",
    "page",
    "annotation_type",
    "kind",
    "color",
    "note_question",
    "claim",
    "reason",
    "information_roles",
    "evidence",
    "confidence",
}

ALLOWED_ROLES = {
    "problem",
    "motivation",
    "cause",
    "method",
    "mechanism",
    "design_rationale",
    "definition",
    "assumption",
    "condition",
    "effect",
    "metric",
    "comparison",
    "result",
    "limitation",
    "failure",
    "reuse",
    "evidence_gap",
    "reproducibility",
    "author_context",
    "contribution",
    "interface",
    "implementation",
    "training_scale",
    "experiment_setting",
    "baseline",
    "reference_role",
    "support_link",
}

SELECTION_MODES = {
    "semantic-span",
    "key-term",
    "key-metric",
    "key-link",
    "author-name",
}
AUTHOR_COMMENT_PREFIX = "外部信息："
LEGACY_AUTHOR_COMMENT_PREFIX = "外部核验，不是论文正文事实："

RELATION_ROLES = {"entity", "predicate", "effect", "condition"}
RELATION_TYPES = {
    "causes",
    "constrains",
    "solves",
    "couples",
    "improves",
    "depends_on",
    "contrasts_with",
}
DISCOURSE_PREFIXES = (
    "despite these advantages",
    "however",
    "moreover",
    "therefore",
    "thus",
    "specifically",
    "in addition",
)
RELATION_REQUIRED_FIELDS = (
    "relation_group_id",
    "relation_role",
    "relation_type",
    "relation_summary",
)
INK_CAPABILITY_FIELDS = (
    "editable_verified",
    "deletable_verified",
    "position_verified",
    "refresh_verified",
)


def _normalise(text: str) -> str:
    return " ".join(str(text).split()).strip().casefold()


def _word_like_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9μ×%]+|[\u4e00-\u9fff]", text))


def _non_empty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _schema_version(item: dict[str, Any], failures: list[str]) -> int:
    raw = item.get("annotation_schema_version", 1)
    if isinstance(raw, bool):
        failures.append("annotation_schema_version must be a positive integer")
        return 1
    try:
        version = int(raw)
    except (TypeError, ValueError):
        failures.append("annotation_schema_version must be a positive integer")
        return 1
    if version < 1:
        failures.append("annotation_schema_version must be a positive integer")
        return 1
    return version


def _is_public_http_url(value: str) -> bool:
    if "\\" in value or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError):
        return False
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or (port is not None and not 1 <= port <= 65535)
    ):
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.rstrip(".").encode("idna").decode("ascii").casefold()
        except UnicodeError:
            return False
        if (
            "." not in ascii_host
            or ascii_host == "localhost"
            or ascii_host.endswith((".localhost", ".local", ".internal"))
            or len(ascii_host) > 253
        ):
            return False
        return all(
            re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                label,
            )
            for label in ascii_host.split(".")
        )
    return address.is_global


def _append_v3_comment_failures(
    item: dict[str, Any],
    schema_version: int,
    failures: list[str],
) -> None:
    if schema_version >= 3:
        failures.extend(comment_quality_failures(item))




def _has_relation_metadata(item: dict[str, Any]) -> bool:
    return any(
        field in item
        for field in (
            *RELATION_REQUIRED_FIELDS,
            "connector_mode",
            "ink_native_key",
            *INK_CAPABILITY_FIELDS,
            "text_overlap_verified",
        )
    )


def _append_relation_item_failures(
    item: dict[str, Any],
    failures: list[str],
) -> None:
    if not _has_relation_metadata(item):
        return

    missing = [
        field
        for field in RELATION_REQUIRED_FIELDS
        if _non_empty_text(item.get(field)) is None
    ]
    if missing:
        if missing == ["relation_summary"]:
            failures.append(
                "partial relation metadata; requires non-empty relation_summary"
            )
        else:
            failures.append(
                "partial relation metadata; missing or blank: " + ", ".join(missing)
            )
        return

    relation_role = str(item["relation_role"])
    relation_type = str(item["relation_type"])
    if relation_role not in RELATION_ROLES:
        failures.append(
            "relation_role must be entity, predicate, effect, or condition"
        )
    if relation_type not in RELATION_TYPES:
        failures.append(
            "relation_type must be causes, constrains, solves, couples, "
            "improves, depends_on, or contrasts_with"
        )

    quote = _normalise(str(item.get("quote", "")))
    if any(quote.startswith(prefix) for prefix in DISCOURSE_PREFIXES):
        failures.append(
            "relation quote starts with discourse scaffolding instead of evidence"
        )

    connector_mode = item.get("connector_mode", "shared-id")
    if connector_mode not in {"shared-id", "native-ink"}:
        failures.append("connector_mode must be shared-id or native-ink")
        return

    if connector_mode == "shared-id":
        ink_fields = (
            "ink_native_key",
            *INK_CAPABILITY_FIELDS,
            "text_overlap_verified",
        )
        if any(field in item for field in ink_fields):
            failures.append(
                "shared-id connector must not claim native-ink capability proof"
            )
        return

    native_failures = []
    if _non_empty_text(item.get("ink_native_key")) is None:
        native_failures.append("ink_native_key")
    native_failures.extend(
        field for field in INK_CAPABILITY_FIELDS if item.get(field) is not True
    )
    if item.get("text_overlap_verified") is not False:
        native_failures.append("text_overlap_verified=false")
    if native_failures:
        failures.append(
            "native-ink requires verified editable, deletable, positioned, "
            "refreshed, non-overlapping native annotations; missing: "
            + ", ".join(native_failures)
        )


def validate_relation_groups(items: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    relation_annotation_count = 0
    failures: list[str] = []

    for index, item in enumerate(items):
        if not _has_relation_metadata(item):
            continue
        item_failures: list[str] = []
        _append_relation_item_failures(item, item_failures)
        failures.extend(
            f"item {index}: {failure}" for failure in item_failures
        )
        group_id = _non_empty_text(item.get("relation_group_id"))
        if group_id:
            groups.setdefault(group_id, []).append(item)
            relation_annotation_count += 1

    for group_id, group_items in groups.items():
        roles = {
            str(item.get("relation_role"))
            for item in group_items
            if item.get("relation_role") is not None
        }
        relation_types = {
            str(item.get("relation_type"))
            for item in group_items
            if item.get("relation_type") is not None
        }
        if "predicate" not in roles:
            failures.append(
                f"group {group_id}: requires at least one predicate"
            )
        if not roles.intersection({"entity", "effect", "condition"}):
            failures.append(
                f"group {group_id}: requires at least one entity, effect, or condition"
            )
        if len(relation_types) != 1:
            failures.append(
                f"group {group_id}: inconsistent relation_type values"
            )

    if failures:
        raise SemanticSelectionError("; ".join(failures))
    return {
        "valid": True,
        "relation_group_count": len(groups),
        "relation_annotation_count": relation_annotation_count,
    }


def information_failures(item: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    missing = sorted(
        field
        for field in REQUIRED_COMMON
        if field not in item or item[field] in (None, "", [])
    )
    if missing:
        failures.append("missing required fields: " + ", ".join(missing))
        return failures

    schema_version = _schema_version(item, failures)
    _append_relation_item_failures(item, failures)
    roles = set(item.get("information_roles", []))
    unknown_roles = sorted(roles - ALLOWED_ROLES)
    if unknown_roles:
        failures.append("unknown information roles: " + ", ".join(unknown_roles))

    selection_mode = str(item.get("selection_mode") or "semantic-span")
    annotation_type = item.get("annotation_type")
    if selection_mode not in SELECTION_MODES:
        failures.append(
            "selection_mode must be semantic-span, key-term, key-metric, "
            "key-link, or author-name"
        )
    if annotation_type != "highlight" and selection_mode != "semantic-span":
        failures.append(
            "non-semantic selection_mode requires annotation_type=highlight"
        )

    if annotation_type == "highlight" and selection_mode == "semantic-span":
        for field in ("quote", "claim", "reason"):
            if _non_empty_text(item.get(field)) is None:
                failures.append(f"semantic-span requires non-empty {field}")

    if annotation_type == "highlight" and selection_mode != "semantic-span":
        quote = _non_empty_text(item.get("quote"))
        if quote is None:
            failures.append(f"{selection_mode} requires non-empty quote")
        quote = quote or ""

        if selection_mode == "key-term":
            if _word_like_count(quote) < 1:
                failures.append(
                    "key-term quote requires at least one word-like token"
                )
            if _non_empty_text(item.get("context_summary")) is None:
                failures.append("key-term requires non-empty context_summary")
            if _non_empty_text(item.get("annotation_comment")) is None:
                failures.append("key-term requires non-empty annotation_comment")
        elif selection_mode == "key-metric":
            if not re.search(r"\d", quote):
                failures.append("key-metric quote must contain a number")
            if _non_empty_text(item.get("metric_context")) is None:
                failures.append("key-metric requires non-empty metric_context")
            if _non_empty_text(item.get("condition")) is None:
                failures.append("key-metric requires non-empty condition")
            if _non_empty_text(item.get("annotation_comment")) is None:
                failures.append("key-metric requires non-empty annotation_comment")
        elif selection_mode == "key-link":
            if not quote or not _is_public_http_url(quote):
                failures.append(
                    "key-link quote must be a public HTTP(S) URL"
                )
            if _non_empty_text(item.get("link_context")) is None:
                failures.append("key-link requires non-empty link_context")
            if _non_empty_text(item.get("annotation_comment")) is None:
                failures.append("key-link requires non-empty annotation_comment")
            if "support_link" not in roles:
                failures.append("key-link requires support_link role")
        elif selection_mode == "author-name":
            if item.get("kind") != "author-background":
                failures.append("author-name requires kind=author-background")
            if "author_context" not in roles:
                failures.append("author-name requires author_context role")
            if _non_empty_text(item.get("author_context")) is None:
                failures.append("author-name requires non-empty author_context")
            external_evidence = _non_empty_text(item.get("external_evidence"))
            if not external_evidence:
                failures.append(
                    "author-name requires non-empty external_evidence"
                )
            elif not _is_public_http_url(external_evidence):
                failures.append(
                    "author-name external_evidence must be a public HTTP(S) URL"
                )
            external_sources = item.get("external_sources")
            if external_sources is not None:
                if (
                    not isinstance(external_sources, list)
                    or not external_sources
                    or not all(
                        isinstance(source, str)
                        and _is_public_http_url(source)
                        for source in external_sources
                    )
                ):
                    failures.append(
                        "author-name external_sources must be a non-empty "
                        "list of public HTTP(S) URLs"
                    )
            verified_at = _non_empty_text(item.get("verified_at"))
            if not verified_at:
                failures.append("author-name requires non-empty verified_at")
            else:
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_at):
                        raise ValueError
                    date.fromisoformat(verified_at)
                except ValueError:
                    failures.append(
                        "author-name verified_at must be an ISO date"
                    )
            annotation_comment = _non_empty_text(
                item.get("annotation_comment")
            )
            if not annotation_comment:
                failures.append(
                    "author-name requires non-empty annotation_comment"
                )
            else:
                required_prefix = (
                    AUTHOR_COMMENT_PREFIX
                    if schema_version >= 3
                    else LEGACY_AUTHOR_COMMENT_PREFIX
                )
                if not annotation_comment.startswith(required_prefix):
                    failures.append(
                        "author-name annotation_comment must start with "
                        f"'{required_prefix}'"
                    )

        if _word_like_count(str(item.get("claim", ""))) < 6:
            failures.append(
                "claim does not explain what the evidence establishes"
            )
        if _word_like_count(str(item.get("reason", ""))) < 6:
            failures.append(
                "reason does not justify the selected span"
            )
        _append_v3_comment_failures(item, schema_version, failures)
        return failures

    if annotation_type == "highlight":
        quote = str(item.get("quote", "")).strip()
        normalised = _normalise(quote)
        if not quote:
            failures.append("text highlight requires quote")
        if normalised in LOW_INFORMATION_EXACT:
            failures.append("quote is a low-information fragment")
        if re.fullmatch(r"[\d\s.,%μ-]+", quote) and not re.search(
            r"\b(?:average|maximum|minimum|time|rate|latency|frequency|"
            r"success|computation|trigger|velocity|distance|trials?|"
            r"images?|depth)\b",
            quote,
            flags=re.IGNORECASE,
        ):
            failures.append("number or noun fragment lacks metric context")
        if _word_like_count(quote) < 6 and not _has_relation_metadata(item):
            failures.append(
                "quote is too short to carry a complete technical relation"
            )
        if "method" in roles and not roles.intersection(
            {
                "mechanism",
                "design_rationale",
                "condition",
                "result",
                "definition",
                "interface",
                "implementation",
            }
        ):
            failures.append(
                "method highlight lacks mechanism, rationale, condition, "
                "result, definition, interface, or implementation"
            )
    elif annotation_type == "area":
        if not item.get("visual_object"):
            failures.append("area annotation requires visual_object")
        rect = item.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            failures.append("area annotation requires a four-value rect")
        if not roles.intersection(
            {
                "metric",
                "comparison",
                "result",
                "mechanism",
                "failure",
                "implementation",
            }
        ):
            failures.append("area annotation lacks a visual evidence role")
    else:
        failures.append("annotation_type must be highlight or area")

    if _word_like_count(str(item.get("claim", ""))) < 6:
        failures.append(
            "claim does not explain what the evidence establishes"
        )
    if _word_like_count(str(item.get("reason", ""))) < 6:
        failures.append("reason does not justify the selected span")
    _append_v3_comment_failures(item, schema_version, failures)
    return failures


def validate_semantic_annotation(item: dict[str, Any]) -> dict[str, Any]:
    validated = {
        **item,
        "selection_mode": item.get("selection_mode") or "semantic-span",
    }
    failures = information_failures(validated)
    if failures:
        raise SemanticSelectionError("; ".join(failures))
    return validated
