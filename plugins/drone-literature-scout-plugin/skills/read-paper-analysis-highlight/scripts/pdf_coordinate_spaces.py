from __future__ import annotations

import math
from collections.abc import Sequence


class CoordinateSpaceError(ValueError):
    """Raised when a rectangle cannot be safely transformed."""


def _finite_rectangle(values: Sequence[float], label: str) -> list[float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CoordinateSpaceError(f"{label} must be a four-value sequence")
    if len(values) != 4:
        raise CoordinateSpaceError(f"{label} must contain four values")
    try:
        rectangle = [float(value) for value in values]
    except (TypeError, ValueError) as error:
        raise CoordinateSpaceError(f"{label} contains a non-numeric value") from error
    if not all(math.isfinite(value) for value in rectangle):
        raise CoordinateSpaceError(f"{label} contains a non-finite value")
    x0, y0, x1, y1 = rectangle
    if x1 <= x0 or y1 <= y0:
        raise CoordinateSpaceError(f"{label} has invalid coordinate order")
    return rectangle


def _validated_inputs(
    rect: Sequence[float],
    page_box: Sequence[float],
    page_rotation: int,
) -> tuple[list[float], list[float]]:
    if isinstance(page_rotation, bool):
        raise CoordinateSpaceError("page rotation must be an integer")
    try:
        rotation = int(page_rotation)
    except (TypeError, ValueError) as error:
        raise CoordinateSpaceError("page rotation must be an integer") from error
    if rotation != 0:
        raise CoordinateSpaceError(
            "non-zero page rotation requires a separately verified transform"
        )

    rectangle = _finite_rectangle(rect, "rect")
    box = _finite_rectangle(page_box, "page_box")
    x0, y0, x1, y1 = rectangle
    px0, py0, px1, py1 = box
    if not (px0 <= x0 < x1 <= px1 and py0 <= y0 < y1 <= py1):
        raise CoordinateSpaceError("rect is outside page_box")
    return rectangle, box


def fitz_rect_to_zotero(
    rect: Sequence[float],
    page_box: Sequence[float],
    page_rotation: int,
) -> list[float]:
    """Convert PyMuPDF top-left page coordinates to Zotero PDF coordinates."""

    rectangle, box = _validated_inputs(rect, page_box, page_rotation)
    x0, y0, x1, y1 = rectangle
    _, py0, _, py1 = box
    return [
        round(x0, 6),
        round(py0 + py1 - y1, 6),
        round(x1, 6),
        round(py0 + py1 - y0, 6),
    ]


def zotero_rect_to_fitz(
    rect: Sequence[float],
    page_box: Sequence[float],
    page_rotation: int,
) -> list[float]:
    """Convert Zotero PDF coordinates back to PyMuPDF page coordinates."""

    # A vertical reflection about the page-box midline is its own inverse.
    return fitz_rect_to_zotero(rect, page_box, page_rotation)


def rectangle_area(rect: Sequence[float]) -> float:
    x0, y0, x1, y1 = _finite_rectangle(rect, "rect")
    return (x1 - x0) * (y1 - y0)


def round_trip_error(
    source: Sequence[float],
    restored: Sequence[float],
) -> float:
    left = _finite_rectangle(source, "source rect")
    right = _finite_rectangle(restored, "restored rect")
    return max(abs(a - b) for a, b in zip(left, right, strict=True))
