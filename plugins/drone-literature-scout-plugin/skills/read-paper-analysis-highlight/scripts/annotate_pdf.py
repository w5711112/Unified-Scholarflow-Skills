from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import fitz

import annotate_pdf_legacy as _legacy
from pdf_coordinate_spaces import (
    CoordinateSpaceError,
    fitz_rect_to_zotero,
    rectangle_area,
    round_trip_error,
    zotero_rect_to_fitz,
)


READING_COORDINATE_SPACE = "pymupdf-page-top-left"
ZOTERO_COORDINATE_SPACE = "pdf-page-bottom-left"
COORDINATE_TOLERANCE_PT = 0.01


def _page_box(page: fitz.Page) -> list[float]:
    return [
        float(page.rect.x0),
        float(page.rect.y0),
        float(page.rect.x1),
        float(page.rect.y1),
    ]


def _float_sequence(value: Any, label: str) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 4
    ):
        raise ValueError(f"{label} must contain four numeric values")
    try:
        return [float(number) for number in value]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must contain four numeric values") from error


def _maximum_difference(left: Sequence[float], right: Sequence[float]) -> float:
    return max(abs(float(a) - float(b)) for a, b in zip(left, right, strict=True))


def _resolve_area_v3(page: fitz.Page, item: dict[str, Any]) -> dict[str, Any]:
    resolved = _legacy_area_resolver(page, item)
    schema_version = int(item.get("annotation_schema_version", 1))
    actual_page_box = _page_box(page)
    actual_rotation = int(page.rotation)

    if schema_version >= 3:
        if item.get("coordinate_space") != READING_COORDINATE_SPACE:
            raise ValueError(
                "V3 area annotation coordinate_space must be "
                f"'{READING_COORDINATE_SPACE}'"
            )
        if "page_box" not in item:
            raise ValueError("V3 area annotation requires page_box")
        if "page_rotation" not in item:
            raise ValueError("V3 area annotation requires page_rotation")
        supplied_page_box = _float_sequence(item["page_box"], "page_box")
        supplied_rotation = int(item["page_rotation"])
    else:
        supplied_page_box = actual_page_box
        supplied_rotation = actual_rotation

    if _maximum_difference(supplied_page_box, actual_page_box) > COORDINATE_TOLERANCE_PT:
        raise ValueError(
            "annotation page_box does not match the resolved PDF page box"
        )
    if supplied_rotation != actual_rotation:
        raise ValueError(
            "annotation page_rotation does not match the resolved PDF page rotation"
        )

    try:
        zotero_rect = fitz_rect_to_zotero(
            resolved["rect"],
            supplied_page_box,
            supplied_rotation,
        )
        restored = zotero_rect_to_fitz(
            zotero_rect,
            supplied_page_box,
            supplied_rotation,
        )
        error = round_trip_error(resolved["rect"], restored)
        source_area = rectangle_area(resolved["rect"])
        native_area = rectangle_area(zotero_rect)
    except CoordinateSpaceError as coordinate_error:
        raise ValueError(str(coordinate_error)) from coordinate_error

    if error > COORDINATE_TOLERANCE_PT:
        raise ValueError(
            "area coordinate round trip exceeds "
            f"{COORDINATE_TOLERANCE_PT} pt: {error}"
        )
    if abs(source_area - native_area) > COORDINATE_TOLERANCE_PT:
        raise ValueError("area coordinate transform changed rectangle area")

    return {
        **resolved,
        "annotation_schema_version": schema_version,
        "coordinate_space": READING_COORDINATE_SPACE,
        "page_box": supplied_page_box,
        "page_rotation": supplied_rotation,
        "zotero_rect": zotero_rect,
        "zotero_coordinate_space": ZOTERO_COORDINATE_SPACE,
        "coordinate_round_trip_error": error,
    }


_legacy_area_resolver = _legacy._resolve_area
_legacy._resolve_area = _resolve_area_v3

annotate_pdf = _legacy.annotate_pdf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    raw = json.loads(Path(args.annotations).read_text(encoding="utf-8"))
    annotations = raw["annotations"] if isinstance(raw, dict) else raw
    result = annotate_pdf(
        args.input,
        args.output,
        args.backup,
        args.manifest,
        annotations,
        overwrite=args.overwrite,
        expected_sha256=args.expected_sha256,
    )
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
