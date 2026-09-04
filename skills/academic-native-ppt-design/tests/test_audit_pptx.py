from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import audit_pptx


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
PRESENTATION_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
SLIDE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
REPORT_KEYS = {
    "ok",
    "slideCount",
    "nativeShapeCount",
    "textShapeCount",
    "imageCount",
    "tableCount",
    "chartCount",
    "officeMathCount",
    "oleObjectCount",
    "emptyPlaceholderCount",
    "fullSlideRasterSlides",
    "issues",
}


def presentation_xml(slide_numbers: list[int], include_size: bool = True) -> str:
    slide_ids = "".join(
        f'<p:sldId id="{255 + position}" r:id="rId{position}"/>'
        for position, _ in enumerate(slide_numbers, start=1)
    )
    size = '<p:sldSz cx="10000000" cy="7500000"/>' if include_size else ""
    return (
        f'<p:presentation xmlns:p="{P_NS}" xmlns:r="{R_NS}">'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst>{size}</p:presentation>"
    )


def presentation_relationships(
    slide_numbers: list[int],
    *,
    omit_relationship_for: set[int] | None = None,
    target_overrides: dict[int, str] | None = None,
) -> str:
    omitted = omit_relationship_for or set()
    overrides = target_overrides or {}
    relationships = "".join(
        (
            f'<Relationship Id="rId{position}" Type="{SLIDE_REL_TYPE}" '
            f'Target="{overrides.get(number, f"slides/slide{number}.xml")}"/>'
        )
        for position, number in enumerate(slide_numbers, start=1)
        if number not in omitted
    )
    return f'<Relationships xmlns="{PKG_REL_NS}">{relationships}</Relationships>'


def slide_xml(objects: str) -> str:
    return (
        f'<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}" xmlns:c="{C_NS}" '
        f'xmlns:m="{M_NS}" xmlns:a14="{A14_NS}">'
        f'<p:cSld><p:spTree>{objects}</p:spTree></p:cSld></p:sld>'
    )


def text_shape(text: str, placeholder: bool = False) -> str:
    placeholder_xml = "<p:nvPr><p:ph/></p:nvPr>" if placeholder else "<p:nvPr/>"
    return (
        "<p:sp><p:nvSpPr>"
        f"{placeholder_xml}"
        "</p:nvSpPr><p:txBody><a:p><a:r>"
        f"<a:t>{text}</a:t>"
        "</a:r></a:p></p:txBody></p:sp>"
    )


def empty_placeholder() -> str:
    return "<p:sp><p:nvSpPr><p:nvPr><p:ph/></p:nvPr></p:nvSpPr><p:txBody/></p:sp>"


def picture(x: int, y: int, cx: int, cy: int) -> str:
    return (
        "<p:pic><p:spPr><a:xfrm>"
        f'<a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/>'
        "</a:xfrm></p:spPr></p:pic>"
    )


def group(
    objects: str,
    *,
    off: tuple[int, int],
    ext: tuple[int, int],
    child_off: tuple[int, int],
    child_ext: tuple[int, int],
    rotation: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
) -> str:
    transform_attributes = ""
    if rotation:
        transform_attributes += f' rot="{rotation}"'
    if flip_h:
        transform_attributes += ' flipH="1"'
    if flip_v:
        transform_attributes += ' flipV="1"'
    return (
        f"<p:grpSp><p:grpSpPr><a:xfrm{transform_attributes}>"
        f'<a:off x="{off[0]}" y="{off[1]}"/>'
        f'<a:ext cx="{ext[0]}" cy="{ext[1]}"/>'
        f'<a:chOff x="{child_off[0]}" y="{child_off[1]}"/>'
        f'<a:chExt cx="{child_ext[0]}" cy="{child_ext[1]}"/>'
        f"</a:xfrm></p:grpSpPr>{objects}</p:grpSp>"
    )


def graphic_frame(content: str) -> str:
    return f"<p:graphicFrame><a:graphic><a:graphicData>{content}</a:graphicData></a:graphic></p:graphicFrame>"


def write_pptx(
    path: Path,
    slides: dict[int, str],
    *,
    include_presentation: bool = True,
    include_size: bool = True,
    omit_required_parts: set[str] | None = None,
    omit_relationship_for: set[int] | None = None,
    target_overrides: dict[int, str] | None = None,
    presentation_override: str | None = None,
    required_part_overrides: dict[str, str] | None = None,
) -> None:
    slide_numbers = sorted(slides)
    omitted_parts = omit_required_parts or set()
    with zipfile.ZipFile(path, "w") as package:
        slide_content_types = "".join(
            f'<Override PartName="/ppt/slides/slide{number}.xml" ContentType="{SLIDE_CONTENT_TYPE}"/>'
            for number in slide_numbers
        )
        required_content = {
            "[Content_Types].xml": (
                f'<Types xmlns="{CT_NS}">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                f'<Override PartName="/ppt/presentation.xml" ContentType="{PRESENTATION_CONTENT_TYPE}"/>'
                f'{slide_content_types}'
                '</Types>'
            ),
            "_rels/.rels": (
                f'<Relationships xmlns="{PKG_REL_NS}"><Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="ppt/presentation.xml"/></Relationships>'
            ),
            "ppt/_rels/presentation.xml.rels": presentation_relationships(
                slide_numbers,
                omit_relationship_for=omit_relationship_for,
                target_overrides=target_overrides,
            ),
        }
        overrides = required_part_overrides or {}
        for part, content in required_content.items():
            if part not in omitted_parts:
                package.writestr(part, overrides.get(part, content))
        if include_presentation and "ppt/presentation.xml" not in omitted_parts:
            package.writestr(
                "ppt/presentation.xml",
                presentation_override if presentation_override is not None else presentation_xml(slide_numbers, include_size),
            )
        for number, content in slides.items():
            package.writestr(f"ppt/slides/slide{number}.xml", slide_xml(content))


def corrupt_stored_member(path: Path, marker: bytes) -> None:
    content = bytearray(path.read_bytes())
    location = content.find(marker)
    if location < 0:
        raise AssertionError(f"Marker not found in fixture: {marker!r}")
    content[location] ^= 0x01
    path.write_bytes(content)


def run_cli(*args: str) -> tuple[int, dict[str, object]]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = audit_pptx.main(list(args))
    return exit_code, json.loads(stdout.getvalue())


class AuditPptxTests(unittest.TestCase):
    def test_invalid_zip_returns_stable_report_and_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.pptx"
            source.write_text("not a zip package", encoding="utf-8")

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(report["slideCount"], 0)
        self.assertEqual(report["issues"][0]["code"], "INVALID_PPTX")
        self.assertEqual(report["issues"][0]["severity"], "error")

    def test_package_without_slide_xml_returns_no_slides_and_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "no-slides.pptx"
            write_pptx(source, {})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["slideCount"], 0)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("NO_PRESENTATION_SLIDES", "error")],
        )

    def test_slide_numbers_are_processed_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "numeric-order.pptx"
            write_pptx(source, {10: empty_placeholder(), 2: empty_placeholder()})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["slideCount"], 2)
        self.assertEqual(report["emptyPlaceholderCount"], 2)
        self.assertEqual(
            [issue["slide"] for issue in report["issues"] if issue["code"] == "EMPTY_PLACEHOLDER"],
            [2, 10],
        )

    def test_nested_a14_math_counts_as_one_formula_not_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nested-math.pptx"
            write_pptx(
                source,
                {
                    1: (
                        "<a14:m><m:oMathPara><m:oMath><m:r><m:t>x</m:t></m:r>"
                        "</m:oMath></m:oMathPara></a14:m>"
                        + text_shape("z² = 4")
                    )
                },
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["officeMathCount"], 1)
        self.assertEqual(report["textShapeCount"], 1)

    def test_top_level_omath_counts_as_one_formula(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "top-level-math.pptx"
            write_pptx(source, {1: "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["officeMathCount"], 1)

    def test_missing_slide_size_is_a_warning_and_other_counts_continue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing-size.pptx"
            write_pptx(source, {1: text_shape("Auditable text")}, include_size=False)

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["slideCount"], 1)
        self.assertEqual(report["textShapeCount"], 1)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("SLIDE_SIZE_UNAVAILABLE", "warning")],
        )

    def test_ole_and_empty_placeholder_are_counted_with_warning_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ole-warning.pptx"
            write_pptx(source, {1: "<p:oleObj/>" + empty_placeholder()})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["oleObjectCount"], 1)
        self.assertEqual(report["emptyPlaceholderCount"], 1)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("EMPTY_PLACEHOLDER", "warning"), ("OLE_PRESENT", "warning")],
        )

    def test_full_slide_raster_requires_both_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raster.pptx"
            write_pptx(
                source,
                {
                    1: picture(100000, 100000, 9500000, 7125000) + picture(0, 0, 10000000, 7500000),
                    2: picture(0, 0, 10000000, 3750000),
                },
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["imageCount"], 3)
        self.assertEqual(report["fullSlideRasterSlides"], [1])
        self.assertEqual(
            [(issue["code"], issue["severity"], issue["slide"]) for issue in report["issues"]],
            [("FULL_SLIDE_RASTER", "error", 1)],
        )

    def test_grouped_leaf_shapes_and_pictures_are_counted_and_nested_transform_detects_raster(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "grouped-objects.pptx"
            grouped_objects = group(
                group(
                    text_shape("Grouped text") + picture(20, 30, 100, 75),
                    off=(100, 50),
                    ext=(1000, 750),
                    child_off=(20, 30),
                    child_ext=(100, 75),
                ),
                off=(0, 0),
                ext=(10000000, 7500000),
                child_off=(100, 50),
                child_ext=(1000, 750),
            )
            write_pptx(source, {1: grouped_objects})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["nativeShapeCount"], 1)
        self.assertEqual(report["textShapeCount"], 1)
        self.assertEqual(report["imageCount"], 1)
        self.assertEqual(report["fullSlideRasterSlides"], [1])
        self.assertEqual(
            [(issue["code"], issue["severity"], issue["slide"]) for issue in report["issues"]],
            [("FULL_SLIDE_RASTER", "error", 1)],
        )

    def test_group_rotation_and_flip_cannot_hide_full_slide_rasters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "group-orientation.pptx"
            rotated = group(
                picture(0, 0, 7500000, 10000000),
                off=(1250000, -1250000),
                ext=(7500000, 10000000),
                child_off=(0, 0),
                child_ext=(7500000, 10000000),
                rotation=5400000,
            )
            flipped = group(
                picture(10000000, 0, 10000000, 7500000),
                off=(0, 0),
                ext=(20000000, 7500000),
                child_off=(0, 0),
                child_ext=(20000000, 7500000),
                flip_h=True,
            )
            write_pptx(source, {1: rotated, 2: flipped})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["imageCount"], 2)
        self.assertEqual(report["fullSlideRasterSlides"], [1, 2])

    def test_well_formed_empty_content_types_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty-content-types.pptx"
            write_pptx(
                source,
                {1: text_shape("Native")},
                required_part_overrides={"[Content_Types].xml": f'<Types xmlns="{CT_NS}"/>'},
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["issues"][0]["code"], "CONTENT_TYPES_SEMANTICS_INVALID")

    def test_well_formed_empty_root_relationships_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty-root-rels.pptx"
            write_pptx(
                source,
                {1: text_shape("Native")},
                required_part_overrides={"_rels/.rels": f'<Relationships xmlns="{PKG_REL_NS}"/>'},
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["issues"][0]["code"], "OFFICE_DOCUMENT_RELATIONSHIP_MISSING")

    def test_missing_presentation_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing-presentation.pptx"
            write_pptx(source, {1: text_shape("orphan")}, include_presentation=False)

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertFalse(report["ok"])
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("MISSING_REQUIRED_PART", "error")],
        )
        self.assertIn("ppt/presentation.xml", report["issues"][0]["message"])

    def test_crc_failure_is_structurally_invalid_and_names_bad_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad-crc.pptx"
            write_pptx(source, {1: text_shape("CRC_MARKER")})
            corrupt_stored_member(source, b"CRC_MARKER")

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertFalse(report["ok"])
        self.assertEqual(report["issues"][0]["code"], "PACKAGE_CRC_ERROR")
        self.assertEqual(report["issues"][0]["severity"], "error")
        self.assertIn("ppt/slides/slide1.xml", report["issues"][0]["message"])

    def test_missing_required_parts_are_reported_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing-required.pptx"
            write_pptx(
                source,
                {1: text_shape("Native")},
                omit_required_parts={"[Content_Types].xml", "_rels/.rels"},
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            [(issue["code"], issue["message"]) for issue in report["issues"]],
            [
                ("MISSING_REQUIRED_PART", "Required package part is missing: [Content_Types].xml."),
                ("MISSING_REQUIRED_PART", "Required package part is missing: _rels/.rels."),
            ],
        )

    def test_malformed_presentation_xml_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad-presentation-xml.pptx"
            write_pptx(source, {1: text_shape("Native")}, presentation_override="<p:presentation")

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["issues"][0]["code"], "INVALID_REQUIRED_XML")
        self.assertEqual(report["issues"][0]["severity"], "error")
        self.assertIn("ppt/presentation.xml", report["issues"][0]["message"])

    def test_malformed_content_types_xml_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad-content-types.pptx"
            write_pptx(
                source,
                {1: text_shape("Native")},
                required_part_overrides={"[Content_Types].xml": "<Types"},
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["issues"][0]["code"], "INVALID_REQUIRED_XML")
        self.assertIn("[Content_Types].xml", report["issues"][0]["message"])

    def test_missing_slide_relationship_is_structurally_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing-slide-rel.pptx"
            write_pptx(source, {1: text_shape("Native")}, omit_relationship_for={1})

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("SLIDE_RELATIONSHIP_NOT_FOUND", "error")],
        )
        self.assertIn("rId1", report["issues"][0]["message"])

    def test_slide_relationship_target_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing-slide-target.pptx"
            write_pptx(
                source,
                {1: text_shape("Native")},
                target_overrides={1: "slides/slide99.xml"},
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("SLIDE_PART_MISSING", "error")],
        )
        self.assertIn("ppt/slides/slide99.xml", report["issues"][0]["message"])

    def test_require_native_math_reports_error_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "no-math.pptx"
            write_pptx(source, {1: text_shape("ordinary notation")})

            exit_code, report = run_cli(str(source), "--require-native-math")

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["officeMathCount"], 0)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("NATIVE_MATH_REQUIRED", "error")],
        )

    def test_forbid_ole_reports_error_when_ole_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ole-forbidden.pptx"
            write_pptx(source, {1: "<p:oleObj/>"})

            exit_code, report = run_cli(str(source), "--forbid-ole")

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["oleObjectCount"], 1)
        self.assertEqual(
            [(issue["code"], issue["severity"]) for issue in report["issues"]],
            [("OLE_FORBIDDEN", "error")],
        )

    def test_valid_native_content_returns_zero_with_exact_report_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "native-content.pptx"
            write_pptx(
                source,
                {
                    1: (
                        text_shape("Native title")
                        + picture(1000000, 1000000, 2000000, 1000000)
                        + graphic_frame("<a:tbl><a:tr/></a:tbl><a:t>Table label</a:t>")
                        + graphic_frame("<c:chart r:id=\"rId1\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"/><a:t>Chart label</a:t>")
                        + "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"
                    )
                },
            )

            exit_code, report = run_cli(str(source))

        self.assertEqual(exit_code, 0)
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(report["nativeShapeCount"], 3)
        self.assertEqual(report["textShapeCount"], 3)
        self.assertEqual(report["imageCount"], 1)
        self.assertEqual(report["tableCount"], 1)
        self.assertEqual(report["chartCount"], 1)
        self.assertEqual(report["officeMathCount"], 1)
        self.assertEqual(report["issues"], [])

    def test_json_file_matches_stdout_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "json-output.pptx"
            destination = Path(directory) / "report.json"
            write_pptx(source, {1: text_shape("JSON output")})

            exit_code, stdout_report = run_cli(str(source), "--json", str(destination))

            file_report = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(file_report, stdout_report)


if __name__ == "__main__":
    unittest.main()
