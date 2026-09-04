"""Audit a PPTX's package spine and editable leaf-object signals.

Object counts are recursive leaf counts: ``p:sp``, ``p:cxnSp``, and
``p:graphicFrame`` contribute to ``nativeShapeCount`` and ``p:pic`` contributes
to ``imageCount`` wherever they occur in the slide group tree. ``p:grpSp``
containers never contribute an object count of their own.
"""

from __future__ import annotations

import argparse
import json
import math
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
PRESENTATION_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
SLIDE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
SLIDE_PATTERN = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
REQUIRED_PARTS = (
    "[Content_Types].xml",
    "_rels/.rels",
    "ppt/presentation.xml",
    "ppt/_rels/presentation.xml.rels",
)


def qualified(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def empty_report() -> dict:
    return {
        "ok": False,
        "slideCount": 0,
        "nativeShapeCount": 0,
        "textShapeCount": 0,
        "imageCount": 0,
        "tableCount": 0,
        "chartCount": 0,
        "officeMathCount": 0,
        "oleObjectCount": 0,
        "emptyPlaceholderCount": 0,
        "fullSlideRasterSlides": [],
        "issues": [],
    }


def add_issue(report: dict, code: str, severity: str, message: str, slide: int | None = None) -> None:
    issue = {"code": code, "severity": severity, "message": message}
    if slide is not None:
        issue["slide"] = slide
    report["issues"].append(issue)


def has_nonempty_text(element: ElementTree.Element) -> bool:
    return any(
        text.text is not None and text.text.strip()
        for text in element.iter(qualified(A_NS, "t"))
    )


def presentation_size(root: ElementTree.Element) -> tuple[int, int] | None:
    try:
        size = root.find(qualified(P_NS, "sldSz"))
        if size is None:
            return None
        width = int(size.attrib["cx"])
        height = int(size.attrib["cy"])
        return (width, height) if width > 0 and height > 0 else None
    except (KeyError, ValueError):
        return None


def compose_affine(
    outer: tuple[float, float, float, float, float, float],
    inner: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    """Return ``outer(inner(point))`` for two 2D affine transforms."""
    a1, b1, c1, d1, e1, f1 = outer
    a2, b2, c2, d2, e2, f2 = inner
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def translation(x: float, y: float) -> tuple[float, float, float, float, float, float]:
    return (1.0, 0.0, 0.0, 1.0, x, y)


def scaling(x: float, y: float) -> tuple[float, float, float, float, float, float]:
    return (x, 0.0, 0.0, y, 0.0, 0.0)


def apply_affine(
    transform: tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = transform
    return a * x + c * y + e, b * x + d * y + f


def xml_true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "on"}


def centered_orientation(
    transform: ElementTree.Element,
    center_x: float,
    center_y: float,
) -> tuple[float, float, float, float, float, float]:
    angle = math.radians(float(transform.attrib.get("rot", "0")) / 60000.0)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = (cosine, sine, -sine, cosine, 0.0, 0.0)
    flip = scaling(-1.0 if xml_true(transform.attrib.get("flipH")) else 1.0,
                   -1.0 if xml_true(transform.attrib.get("flipV")) else 1.0)
    oriented = compose_affine(rotation, flip)
    return compose_affine(
        translation(center_x, center_y),
        compose_affine(oriented, translation(-center_x, -center_y)),
    )


def group_transform(
    group: ElementTree.Element,
    parent: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    """Compose a group's scale, translation, rotation, and flips with its parent."""
    transform = group.find(f"./{qualified(P_NS, 'grpSpPr')}/{qualified(A_NS, 'xfrm')}")
    if transform is None:
        return parent
    offset = transform.find(qualified(A_NS, "off"))
    extent = transform.find(qualified(A_NS, "ext"))
    child_offset = transform.find(qualified(A_NS, "chOff"))
    child_extent = transform.find(qualified(A_NS, "chExt"))
    if offset is None or extent is None or child_offset is None or child_extent is None:
        return parent
    try:
        child_width = float(child_extent.attrib["cx"])
        child_height = float(child_extent.attrib["cy"])
        if child_width == 0 or child_height == 0:
            return parent
        local_scale_x = float(extent.attrib["cx"]) / child_width
        local_scale_y = float(extent.attrib["cy"]) / child_height
        local_translate_x = float(offset.attrib["x"]) - float(child_offset.attrib["x"]) * local_scale_x
        local_translate_y = float(offset.attrib["y"]) - float(child_offset.attrib["y"]) * local_scale_y
    except (KeyError, ValueError):
        return parent
    base = (
        local_scale_x,
        0.0,
        0.0,
        local_scale_y,
        local_translate_x,
        local_translate_y,
    )
    center_x = float(offset.attrib["x"]) + float(extent.attrib["cx"]) / 2.0
    center_y = float(offset.attrib["y"]) + float(extent.attrib["cy"]) / 2.0
    return compose_affine(parent, compose_affine(centered_orientation(transform, center_x, center_y), base))


def is_full_slide_raster(
    picture: ElementTree.Element,
    size: tuple[int, int] | None,
    transform_to_slide: tuple[float, float, float, float, float, float],
) -> bool:
    if size is None:
        return False
    transform = picture.find(f".//{qualified(A_NS, 'xfrm')}")
    if transform is None:
        return False
    offset = transform.find(qualified(A_NS, "off"))
    extent = transform.find(qualified(A_NS, "ext"))
    if offset is None or extent is None:
        return False
    try:
        local_x = float(offset.attrib["x"])
        local_y = float(offset.attrib["y"])
        local_width = float(extent.attrib["cx"])
        local_height = float(extent.attrib["cy"])
    except (KeyError, ValueError):
        return False
    center_x = local_x + local_width / 2.0
    center_y = local_y + local_height / 2.0
    picture_to_parent = centered_orientation(transform, center_x, center_y)
    picture_to_slide = compose_affine(transform_to_slide, picture_to_parent)
    corners = [
        apply_affine(picture_to_slide, local_x, local_y),
        apply_affine(picture_to_slide, local_x + local_width, local_y),
        apply_affine(picture_to_slide, local_x, local_y + local_height),
        apply_affine(picture_to_slide, local_x + local_width, local_y + local_height),
    ]
    left = min(point[0] for point in corners)
    top = min(point[1] for point in corners)
    right = max(point[0] for point in corners)
    bottom = max(point[1] for point in corners)
    slide_width, slide_height = size
    return (
        left <= slide_width * 0.02
        and top <= slide_height * 0.02
        and right >= slide_width * 0.98
        and bottom >= slide_height * 0.98
    )


def count_office_math(element: ElementTree.Element, inside_a14_math: bool = False) -> int:
    is_a14_math = element.tag == qualified(A14_NS, "m")
    count = 1 if is_a14_math else 0
    if element.tag == qualified(M_NS, "oMath") and not inside_a14_math:
        count += 1
    for child in element:
        count += count_office_math(child, inside_a14_math or is_a14_math)
    return count


def validate_package_structure(
    package: zipfile.ZipFile,
    report: dict,
) -> tuple[ElementTree.Element, list[tuple[int, str]]] | None:
    """Validate the OPC spine and return the presentation plus referenced slides."""
    bad_entry = package.testzip()
    if bad_entry is not None:
        add_issue(
            report,
            "PACKAGE_CRC_ERROR",
            "error",
            f"CRC validation failed for package part: {bad_entry}.",
        )
        return None

    names = set(package.namelist())
    missing_parts = [part for part in REQUIRED_PARTS if part not in names]
    if missing_parts:
        for part in missing_parts:
            add_issue(
                report,
                "MISSING_REQUIRED_PART",
                "error",
                f"Required package part is missing: {part}.",
            )
        return None

    parsed_parts: dict[str, ElementTree.Element] = {}
    for part in REQUIRED_PARTS:
        try:
            parsed_parts[part] = ElementTree.fromstring(package.read(part))
        except ElementTree.ParseError as error:
            add_issue(
                report,
                "INVALID_REQUIRED_XML",
                "error",
                f"Required package part is malformed: {part}: {error}.",
            )
            return None
    presentation = parsed_parts["ppt/presentation.xml"]
    relationships = parsed_parts["ppt/_rels/presentation.xml.rels"]
    content_types = parsed_parts["[Content_Types].xml"]
    root_relationships = parsed_parts["_rels/.rels"]

    content_type_overrides = {
        override.attrib.get("PartName", ""): override.attrib.get("ContentType", "")
        for override in content_types.findall(qualified(CT_NS, "Override"))
    }
    has_relationship_default = any(
        default.attrib.get("Extension", "").lower() == "rels"
        and default.attrib.get("ContentType") == RELATIONSHIPS_CONTENT_TYPE
        for default in content_types.findall(qualified(CT_NS, "Default"))
    )
    if (
        content_types.tag != qualified(CT_NS, "Types")
        or not has_relationship_default
        or content_type_overrides.get("/ppt/presentation.xml") != PRESENTATION_CONTENT_TYPE
    ):
        add_issue(
            report,
            "CONTENT_TYPES_SEMANTICS_INVALID",
            "error",
            "[Content_Types].xml lacks the PPTX presentation or relationships declarations.",
        )
        return None

    office_document_relationships = [
        relation
        for relation in root_relationships.findall(qualified(PKG_REL_NS, "Relationship"))
        if relation.attrib.get("Type", "").endswith("/officeDocument")
        and relation.attrib.get("TargetMode") != "External"
        and posixpath.normpath(relation.attrib.get("Target", "").replace("\\", "/")).lstrip("/")
        == "ppt/presentation.xml"
    ]
    if root_relationships.tag != qualified(PKG_REL_NS, "Relationships") or len(office_document_relationships) != 1:
        add_issue(
            report,
            "OFFICE_DOCUMENT_RELATIONSHIP_MISSING",
            "error",
            "_rels/.rels must contain exactly one internal officeDocument relationship to ppt/presentation.xml.",
        )
        return None
    if relationships.tag != qualified(PKG_REL_NS, "Relationships"):
        add_issue(
            report,
            "PRESENTATION_RELATIONSHIPS_INVALID",
            "error",
            "ppt/_rels/presentation.xml.rels has the wrong root element.",
        )
        return None

    relation_by_id = {
        relation.attrib.get("Id", ""): relation
        for relation in relationships.findall(qualified(PKG_REL_NS, "Relationship"))
        if relation.attrib.get("Id")
    }
    slide_id_list = presentation.find(qualified(P_NS, "sldIdLst"))
    slide_ids = [] if slide_id_list is None else slide_id_list.findall(qualified(P_NS, "sldId"))
    if not slide_ids:
        add_issue(
            report,
            "NO_PRESENTATION_SLIDES",
            "error",
            "The presentation slide list contains no slides.",
        )
        return None

    entries: list[tuple[int, str]] = []
    for position, slide_id in enumerate(slide_ids, start=1):
        relation_id = slide_id.attrib.get(qualified(R_NS, "id"))
        if not relation_id:
            add_issue(
                report,
                "SLIDE_RELATIONSHIP_ID_MISSING",
                "error",
                f"Presentation slide entry {position} has no r:id.",
            )
            continue
        relation = relation_by_id.get(relation_id)
        if relation is None:
            add_issue(
                report,
                "SLIDE_RELATIONSHIP_NOT_FOUND",
                "error",
                f"Presentation slide entry {position} references missing relationship {relation_id}.",
            )
            continue
        relation_type = relation.attrib.get("Type", "")
        if not relation_type.endswith("/slide"):
            add_issue(
                report,
                "SLIDE_RELATIONSHIP_TYPE_INVALID",
                "error",
                f"Relationship {relation_id} for slide entry {position} is not a slide relationship.",
            )
            continue
        target = relation.attrib.get("Target")
        if relation.attrib.get("TargetMode") == "External" or not target:
            add_issue(
                report,
                "SLIDE_TARGET_INVALID",
                "error",
                f"Relationship {relation_id} for slide entry {position} has no internal slide target.",
            )
            continue
        normalized_target = posixpath.normpath(posixpath.join("ppt", target.replace("\\", "/"))).lstrip("/")
        match = SLIDE_PATTERN.match(normalized_target)
        if match is None:
            add_issue(
                report,
                "SLIDE_TARGET_INVALID",
                "error",
                f"Relationship {relation_id} resolves outside ppt/slides/slide*.xml: {normalized_target}.",
            )
            continue
        if normalized_target not in names:
            add_issue(
                report,
                "SLIDE_PART_MISSING",
                "error",
                f"Relationship {relation_id} targets a missing slide part: {normalized_target}.",
            )
            continue
        if content_type_overrides.get(f"/{normalized_target}") != SLIDE_CONTENT_TYPE:
            add_issue(
                report,
                "SLIDE_CONTENT_TYPE_INVALID",
                "error",
                f"Slide part lacks the required content type declaration: {normalized_target}.",
            )
            continue
        entries.append((int(match.group(1)), normalized_target))

    if any(issue["severity"] == "error" for issue in report["issues"]):
        return None
    return presentation, sorted(entries)


def audit_leaf_objects(
    container: ElementTree.Element,
    report: dict,
    slide_number: int,
    size: tuple[int, int] | None,
    transform_to_slide: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
) -> bool:
    """Count editable leaf objects recursively; group containers are not objects."""
    native_tags = {
        qualified(P_NS, "sp"),
        qualified(P_NS, "cxnSp"),
        qualified(P_NS, "graphicFrame"),
    }
    has_full_slide_raster = False
    for element in list(container):
        if element.tag == qualified(P_NS, "grpSp"):
            nested_transform = group_transform(element, transform_to_slide)
            has_full_slide_raster = (
                audit_leaf_objects(element, report, slide_number, size, nested_transform)
                or has_full_slide_raster
            )
        elif element.tag in native_tags:
            report["nativeShapeCount"] += 1
            if element.tag in {qualified(P_NS, "sp"), qualified(P_NS, "graphicFrame")} and has_nonempty_text(element):
                report["textShapeCount"] += 1
        elif element.tag == qualified(P_NS, "pic"):
            report["imageCount"] += 1
            if is_full_slide_raster(element, size, transform_to_slide):
                has_full_slide_raster = True
    return has_full_slide_raster


def audit_pptx(input_path: Path, require_native_math: bool, forbid_ole: bool) -> tuple[dict, int]:
    report = empty_report()
    try:
        with zipfile.ZipFile(input_path) as package:
            validated = validate_package_structure(package, report)
            if validated is None:
                return report, 2
            presentation, entries = validated

            size = presentation_size(presentation)
            if size is None:
                add_issue(
                    report,
                    "SLIDE_SIZE_UNAVAILABLE",
                    "warning",
                    "The presentation slide size is unavailable; raster geometry was skipped.",
                )

            for slide_number, entry_name in entries:
                try:
                    root = ElementTree.fromstring(package.read(entry_name))
                except (ElementTree.ParseError, zipfile.BadZipFile):
                    invalid = empty_report()
                    add_issue(invalid, "INVALID_PPTX", "error", "The PPTX package cannot be parsed for audit.")
                    return invalid, 2

                report["slideCount"] += 1
                shape_tree = root.find(f".//{qualified(P_NS, 'spTree')}")
                if shape_tree is not None:
                    has_full_slide_raster = audit_leaf_objects(shape_tree, report, slide_number, size)
                    if has_full_slide_raster:
                        report["fullSlideRasterSlides"].append(slide_number)
                        add_issue(
                            report,
                            "FULL_SLIDE_RASTER",
                            "error",
                            "A picture likely covers the full slide raster area.",
                            slide_number,
                        )

                report["tableCount"] += sum(1 for _ in root.iter(qualified(A_NS, "tbl")))
                report["chartCount"] += sum(1 for _ in root.iter(qualified(C_NS, "chart")))
                report["officeMathCount"] += count_office_math(root)
                report["oleObjectCount"] += sum(1 for _ in root.iter(qualified(P_NS, "oleObj")))

                for shape in root.iter(qualified(P_NS, "sp")):
                    if shape.find(f".//{qualified(P_NS, 'ph')}") is not None and not has_nonempty_text(shape):
                        report["emptyPlaceholderCount"] += 1
                        add_issue(
                            report,
                            "EMPTY_PLACEHOLDER",
                            "warning",
                            "A placeholder shape has no non-whitespace text.",
                            slide_number,
                        )
    except (FileNotFoundError, IsADirectoryError, OSError, zipfile.BadZipFile, RuntimeError):
        add_issue(report, "INVALID_PPTX", "error", "The input is missing or is not a readable PPTX ZIP package.")
        return report, 2

    if report["oleObjectCount"]:
        if forbid_ole:
            add_issue(report, "OLE_FORBIDDEN", "error", "OLE objects are forbidden by this audit.")
        else:
            add_issue(report, "OLE_PRESENT", "warning", "OLE objects are present in the PPTX package.")
    if require_native_math and not report["officeMathCount"]:
        add_issue(report, "NATIVE_MATH_REQUIRED", "error", "Native OfficeMath is required but was not found.")

    report["ok"] = not any(issue["severity"] == "error" for issue in report["issues"])
    return report, 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit PPTX package structure and editability signals.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--require-native-math", action="store_true")
    parser.add_argument("--forbid-ole", action="store_true")
    parser.add_argument("--json", dest="json_path", type=Path)
    arguments = parser.parse_args(argv)

    report, exit_code = audit_pptx(arguments.input, arguments.require_native_math, arguments.forbid_ole)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if arguments.json_path is not None:
        arguments.json_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
