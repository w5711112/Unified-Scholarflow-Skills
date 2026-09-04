from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pdf_coordinate_spaces import fitz_rect_to_zotero  # noqa: E402


COLOR_MAP = {
    "yellow": "#ffd900",
    "red": "#f23333",
    "green": "#33bf33",
    "blue": "#3380ff",
    "purple": "#994ccc",
    "orange": "#ff8c1a",
    "gray": "#aaaaaa",
}
KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _annotations(plan: Any) -> list[dict[str, Any]]:
    if isinstance(plan, list):
        return plan
    if isinstance(plan, dict) and isinstance(plan.get("annotations"), list):
        return plan["annotations"]
    raise ValueError("annotation plan must contain an annotations list")


def _stable_id(source: dict[str, Any]) -> str:
    value = source.get("stable_id", source.get("id"))
    if not isinstance(value, str) or not STABLE_ID_PATTERN.fullmatch(value):
        raise ValueError("every annotation requires a valid stable ID")
    return value


def _page(source: dict[str, Any]) -> tuple[int, int]:
    try:
        page = int(source["page"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("annotation page must be a positive integer") from error
    if page < 1:
        raise ValueError("annotation page must be a positive integer")
    return page, page - 1


def _page_label(
    plan: dict[str, Any],
    source: dict[str, Any],
    page: int,
    page_index: int,
) -> str:
    if source.get("page_label") is not None:
        label = str(source["page_label"])
    elif plan.get("page_label_start") is not None:
        label = str(int(plan["page_label_start"]) + page_index)
    else:
        label = str(page)
    if not label or len(label) > 100:
        raise ValueError("page label must contain 1-100 characters")
    return label


def _color(source: dict[str, Any]) -> str:
    value = source.get("color", "yellow")
    if value not in COLOR_MAP:
        raise ValueError(f"unsupported annotation color: {value}")
    return COLOR_MAP[value]


def _comment(source: dict[str, Any]) -> str:
    value = source.get("annotation_comment") or source.get("claim")
    if not isinstance(value, str) or not value:
        raise ValueError(f"annotation {_stable_id(source)} has no comment")
    if len(value) > 4000:
        raise ValueError("annotation comment exceeds 4000 characters")
    return value


def _finite_quad(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 8:
        raise ValueError("each highlight quad must contain eight numeric values")
    try:
        quad = [float(number) for number in value]
    except (TypeError, ValueError) as error:
        raise ValueError("each highlight quad must contain eight numeric values") from error
    if not all(math.isfinite(number) for number in quad):
        raise ValueError("highlight quad contains a non-finite value")
    return quad


def _quad_rect(quad: list[float]) -> list[float]:
    xs = quad[0::2]
    ys = quad[1::2]
    rect = [min(xs), min(ys), max(xs), max(ys)]
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        raise ValueError("highlight quad has invalid bounds")
    return rect


def _position(source: dict[str, Any], page_index: int) -> tuple[dict[str, Any], float]:
    page_box = source.get("page_box")
    rotation = source.get("page_rotation", 0)
    annotation_type = source.get("annotation_type")
    if annotation_type == "area":
        rect = source.get("rect")
        native_rects = [fitz_rect_to_zotero(rect, page_box, rotation)]
        top = float(rect[1])
    elif annotation_type == "highlight":
        quads = source.get("quads")
        if not isinstance(quads, list) or not quads:
            raise ValueError("resolved highlight quads are required")
        source_rects = [_quad_rect(_finite_quad(quad)) for quad in quads]
        native_rects = [
            fitz_rect_to_zotero(rect, page_box, rotation)
            for rect in source_rects
        ]
        top = min(rect[1] for rect in source_rects)
    else:
        raise ValueError("only area and highlight annotations are supported")
    return {"pageIndex": page_index, "rects": native_rects}, top


def _sort_index(page_index: int, top: float, sequence: int) -> str:
    vertical = max(0, int(round(top * 1000)))
    return f"{page_index:05d}|{vertical:06d}|{sequence:05d}"


def _native_annotation(
    plan: dict[str, Any],
    source: dict[str, Any],
    sequence: int,
) -> dict[str, Any]:
    stable_id = _stable_id(source)
    page, page_index = _page(source)
    position, top = _position(source, page_index)
    annotation_type = source["annotation_type"]
    native: dict[str, Any] = {
        "stable_id": stable_id,
        "type": "image" if annotation_type == "area" else "highlight",
        "page_index": page_index,
        "page_label": _page_label(plan, source, page, page_index),
        "sort_index": _sort_index(page_index, top, sequence),
        "position": position,
        "color": _color(source),
        "comment": _comment(source),
    }
    if annotation_type == "highlight":
        actual_text = source.get("actual_text")
        if not isinstance(actual_text, str) or not actual_text:
            raise ValueError("resolved highlight actual_text is required")
        native["text"] = actual_text
    if source.get("native_key") is not None:
        key = source["native_key"]
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("native_key must be an eight-character Zotero key")
        native["native_key"] = key
    return native


def build_plan(plan: dict[str, Any], attachment_key: str) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("annotation plan must be an object")
    if not isinstance(attachment_key, str) or not KEY_PATTERN.fullmatch(attachment_key):
        raise ValueError("attachment_key must be an eight-character Zotero key")
    operation_id = plan.get("operation_id")
    if not isinstance(operation_id, str) or not STABLE_ID_PATTERN.fullmatch(operation_id):
        raise ValueError("operation_id is required")
    library_id = plan.get("library_id", 1)
    if isinstance(library_id, bool) or not isinstance(library_id, int) or library_id < 1:
        raise ValueError("library_id must be a positive integer")
    allowed = plan.get("allowed_native_keys", [])
    deletions = plan.get("deletions", [])
    if not isinstance(allowed, list) or not isinstance(deletions, list):
        raise ValueError("allowed_native_keys and deletions must be lists")
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "library": {"type": "user", "id": library_id},
        "attachment": {
            "key": attachment_key,
            "content_type": "application/pdf",
        },
        "annotations": [
            _native_annotation(plan, source, sequence)
            for sequence, source in enumerate(_annotations(plan))
        ],
        "allowed_native_keys": list(allowed),
        "deletions": [dict(item) for item in deletions],
    }
