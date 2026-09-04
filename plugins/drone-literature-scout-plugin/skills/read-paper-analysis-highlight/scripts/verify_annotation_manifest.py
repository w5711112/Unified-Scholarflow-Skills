from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import fitz

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric_rectangle(value: object, label: str) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 4
    ):
        raise ValueError(f"{label} must contain four values")
    try:
        return [float(number) for number in value]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must contain numeric values") from error


def _maximum_difference(left: Sequence[float], right: Sequence[float]) -> float:
    return max(abs(float(a) - float(b)) for a, b in zip(left, right, strict=True))


def _verify_area_coordinates(page: fitz.Page, item: dict) -> None:
    required = {
        "rect",
        "coordinate_space",
        "page_box",
        "page_rotation",
        "zotero_rect",
        "zotero_coordinate_space",
        "coordinate_round_trip_error",
    }
    missing = sorted(required.difference(item))
    if missing:
        raise ValueError(f"area annotation missing coordinate fields: {missing}")
    if item["coordinate_space"] != READING_COORDINATE_SPACE:
        raise ValueError("area annotation has invalid coordinate_space")
    if item["zotero_coordinate_space"] != ZOTERO_COORDINATE_SPACE:
        raise ValueError("area annotation has invalid zotero_coordinate_space")

    rect = _numeric_rectangle(item["rect"], "rect")
    zotero_rect = _numeric_rectangle(item["zotero_rect"], "zotero_rect")
    page_box = _numeric_rectangle(item["page_box"], "page_box")
    actual_page_box = [
        float(page.rect.x0),
        float(page.rect.y0),
        float(page.rect.x1),
        float(page.rect.y1),
    ]
    if _maximum_difference(page_box, actual_page_box) > COORDINATE_TOLERANCE_PT:
        raise ValueError("area annotation page_box does not match PDF page")
    rotation = int(item["page_rotation"])
    if rotation != int(page.rotation):
        raise ValueError("area annotation page_rotation does not match PDF page")

    try:
        expected_zotero_rect = fitz_rect_to_zotero(rect, page_box, rotation)
        restored = zotero_rect_to_fitz(zotero_rect, page_box, rotation)
        measured_error = round_trip_error(rect, restored)
        area_difference = abs(rectangle_area(rect) - rectangle_area(zotero_rect))
    except CoordinateSpaceError as error:
        raise ValueError(str(error)) from error

    if _maximum_difference(zotero_rect, expected_zotero_rect) > COORDINATE_TOLERANCE_PT:
        raise ValueError(
            "zotero_rect does not match the transformed PyMuPDF rectangle"
        )
    if measured_error > COORDINATE_TOLERANCE_PT:
        raise ValueError("zotero_rect round trip exceeds coordinate tolerance")
    recorded_error = float(item["coordinate_round_trip_error"])
    if abs(recorded_error - measured_error) > COORDINATE_TOLERANCE_PT:
        raise ValueError("recorded coordinate_round_trip_error is inconsistent")
    if area_difference > COORDINATE_TOLERANCE_PT:
        raise ValueError("zotero_rect does not preserve rectangle area")

def _resolve_manifest_file(value: object, manifest_path: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("manifest path field must be a non-empty string")
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [Path.cwd() / path, manifest_path.parent / path]
    candidates.extend(parent / path for parent in manifest_path.parent.parents)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (manifest_path.parent / path).resolve()


def _hash_matches(path: Path, expected: object) -> bool:
    return isinstance(expected, str) and sha256(path).lower() == expected.lower()


def _verify_zotero_native_manifest(manifest: dict, manifest_path: Path) -> bool:
    required = {
        "source_pdf",
        "annotated_pdf",
        "backup_pdf",
        "original_sha256",
        "current_pdf_sha256",
        "page_count",
        "annotation_count",
        "native_annotation_keys",
        "annotation_plan",
        "locked_annotation_count",
        "external_annotation_count",
        "embedded_pdf_annotation_count",
        "editable_verified",
        "deletable_verified",
    }
    missing = required.difference(manifest)
    if missing:
        raise ValueError(f"zotero-native manifest missing fields: {sorted(missing)}")

    source = _resolve_manifest_file(manifest["source_pdf"], manifest_path)
    annotated = _resolve_manifest_file(manifest["annotated_pdf"], manifest_path)
    backup = _resolve_manifest_file(manifest["backup_pdf"], manifest_path)
    plan_path = _resolve_manifest_file(manifest["annotation_plan"], manifest_path)
    for label, path in (
        ("source PDF", source),
        ("annotated PDF", annotated),
        ("backup PDF", backup),
        ("annotation plan", plan_path),
    ):
        if not path.is_file():
            raise ValueError(f"{label} is missing: {path}")

    if not _hash_matches(backup, manifest["original_sha256"]):
        raise ValueError("backup hash does not match original_sha256")
    if not _hash_matches(annotated, manifest["current_pdf_sha256"]):
        raise ValueError("annotated hash does not match current_pdf_sha256")

    annotation_count = int(manifest["annotation_count"])
    native_keys = manifest["native_annotation_keys"]
    if not isinstance(native_keys, list):
        raise ValueError("native_annotation_keys must be a list")
    if len(native_keys) != annotation_count or len(set(native_keys)) != annotation_count:
        raise ValueError("native annotation key count or uniqueness mismatch")

    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    annotations = (
        plan_payload.get("annotations")
        if isinstance(plan_payload, dict)
        else plan_payload
    )
    if not isinstance(annotations, list) or len(annotations) != annotation_count:
        raise ValueError("annotation plan count mismatch")

    for field in (
        "locked_annotation_count",
        "external_annotation_count",
        "embedded_pdf_annotation_count",
    ):
        if int(manifest[field]) != 0:
            raise ValueError(f"{field} must be zero for finalized native annotations")
    if manifest["editable_verified"] is not True:
        raise ValueError("native annotations were not verified editable")
    if manifest["deletable_verified"] is not True:
        raise ValueError("native annotations were not verified deletable")

    with fitz.open(annotated) as doc:
        if doc.page_count != int(manifest["page_count"]):
            raise ValueError("page count changed")
        identifiers: set[str] = set()
        for item in annotations:
            if not isinstance(item, dict):
                raise ValueError("annotation plan item must be an object")
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("annotation plan item has no id")
            if identifier in identifiers:
                raise ValueError(f"duplicate annotation plan id: {identifier}")
            identifiers.add(identifier)
            page_number = int(item["page"])
            if not 1 <= page_number <= doc.page_count:
                raise ValueError(f"annotation page out of bounds: {page_number}")
            annotation_type = item.get("annotation_type")
            if annotation_type == "area":
                page = doc[page_number - 1]
                coordinate_fields = {
                    "rect",
                    "coordinate_space",
                    "page_box",
                    "page_rotation",
                    "zotero_rect",
                    "zotero_coordinate_space",
                    "coordinate_round_trip_error",
                }
                if coordinate_fields.issubset(item):
                    _verify_area_coordinates(page, item)
                else:
                    staging = manifest.get("staging_verification")
                    if (
                        not isinstance(staging, dict)
                        or staging.get("coordinate_manifest_valid") is not True
                    ):
                        raise ValueError(
                            "native area coordinates need verified staging evidence"
                        )
                    rect = fitz.Rect(_numeric_rectangle(item.get("rect"), "rect"))
                    if not page.rect.contains(rect):
                        raise ValueError(
                            f"annotation rect out of bounds: {item['rect']}"
                        )
                    if not item.get("visual_object"):
                        raise ValueError("area annotation has no visual_object")
            elif annotation_type != "highlight":
                raise ValueError(f"unknown annotation_type: {annotation_type}")
        embedded_count = sum(1 for page in doc for _ in (page.annots() or []))
        if embedded_count != int(manifest["embedded_pdf_annotation_count"]):
            raise ValueError("embedded PDF annotation count does not match manifest")

    database = manifest.get("database_verification")
    if isinstance(database, dict):
        if int(database.get("annotation_count", -1)) != annotation_count:
            raise ValueError("database annotation count mismatch")
        if int(database.get("unique_key_count", -1)) != annotation_count:
            raise ValueError("database native key count mismatch")
        if database.get("manifest_keys_exact_match") is not True:
            raise ValueError("database native keys do not match manifest")
    staging = manifest.get("staging_verification")
    if isinstance(staging, dict) and staging.get("coordinate_manifest_valid") is not True:
        raise ValueError("staging coordinate manifest was not verified")
    return True


def verify_manifest(manifest_path: str | Path) -> bool:
    manifest_file = Path(manifest_path).resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("storage_mode") == "zotero-native":
        return _verify_zotero_native_manifest(manifest, manifest_file)
    required = {
        "source_pdf",
        "annotated_pdf",
        "backup_pdf",
        "original_sha256",
        "annotated_sha256",
        "page_count",
        "annotation_count",
        "storage_mode",
        "annotations",
    }
    missing = required.difference(manifest)
    if missing:
        raise ValueError(f"manifest missing fields: {sorted(missing)}")
    annotated = Path(manifest["annotated_pdf"])
    backup = Path(manifest["backup_pdf"])
    if not annotated.is_file() or not backup.is_file():
        raise ValueError("annotated PDF or backup PDF is missing")
    if sha256(backup) != manifest["original_sha256"]:
        raise ValueError("backup hash does not match original_sha256")
    if sha256(annotated) != manifest["annotated_sha256"]:
        raise ValueError("annotated hash does not match manifest")
    with fitz.open(annotated) as doc:
        if doc.page_count != int(manifest["page_count"]):
            raise ValueError("page count changed")
        for item in manifest["annotations"]:
            page_number = int(item["page"])
            if not 1 <= page_number <= doc.page_count:
                raise ValueError(f"annotation page out of bounds: {page_number}")
            page = doc[page_number - 1]
            if item.get("annotation_type") == "highlight":
                quads = item.get("quads")
                if not quads:
                    raise ValueError("highlight annotation has no quads")
                for values in quads:
                    if len(values) != 8:
                        raise ValueError(f"invalid quad: {values}")
                    points = [
                        fitz.Point(values[index], values[index + 1])
                        for index in range(0, 8, 2)
                    ]
                    if not all(point in page.rect for point in points):
                        raise ValueError(f"annotation quad out of bounds: {values}")
                if not item.get("actual_text"):
                    raise ValueError("highlight annotation has no actual_text")
            elif item.get("annotation_type") == "area":
                rect = fitz.Rect(item["rect"])
                if not page.rect.contains(rect):
                    raise ValueError(
                        f"annotation rect out of bounds: {item['rect']}"
                    )
                if not item.get("visual_object"):
                    raise ValueError("area annotation has no visual_object")
                _verify_area_coordinates(page, item)
            else:
                raise ValueError(
                    f"unknown annotation_type: {item.get('annotation_type')}"
                )
        actual_count = sum(
            1 for page in doc for _ in (page.annots() or [])
        )
        if actual_count != int(manifest["annotation_count"]):
            raise ValueError("PDF annotation count does not match manifest")
    if len(manifest["annotations"]) != int(manifest["annotation_count"]):
        raise ValueError("annotation count mismatch")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    args = parser.parse_args()
    print("valid" if verify_manifest(args.manifest) else "invalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
