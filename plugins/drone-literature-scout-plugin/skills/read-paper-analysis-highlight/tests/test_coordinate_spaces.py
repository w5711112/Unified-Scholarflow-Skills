from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from pdf_coordinate_spaces import (  # noqa: E402
    CoordinateSpaceError,
    fitz_rect_to_zotero,
    rectangle_area,
    round_trip_error,
    zotero_rect_to_fitz,
)


class PdfCoordinateSpaceTests(unittest.TestCase):
    def test_page_four_figure_one_and_equation_eight_are_not_vertically_mirrored(self):
        page_box = [0.0, 0.0, 594.0, 792.0]
        figure_one = [53.16, 66.08, 545.17, 223.53]
        equation_eight = [337.0, 659.0, 557.0, 694.0]

        self.assertEqual(
            fitz_rect_to_zotero(figure_one, page_box, 0),
            [53.16, 568.47, 545.17, 725.92],
        )
        self.assertEqual(
            fitz_rect_to_zotero(equation_eight, page_box, 0),
            [337.0, 98.0, 557.0, 133.0],
        )

    def test_coordinate_round_trip_is_lossless_within_point_tolerance(self):
        source = [53.16, 66.08, 545.17, 223.53]
        page_box = [0.0, 0.0, 594.0, 792.0]
        native = fitz_rect_to_zotero(source, page_box, 0)
        restored = zotero_rect_to_fitz(native, page_box, 0)

        self.assertLessEqual(round_trip_error(source, restored), 0.01)
        self.assertAlmostEqual(rectangle_area(source), rectangle_area(native))

    def test_coordinate_conversion_supports_nonzero_page_box_origin(self):
        page_box = [10.0, 20.0, 310.0, 420.0]
        source = [20.0, 40.0, 100.0, 120.0]

        self.assertEqual(
            fitz_rect_to_zotero(source, page_box, 0),
            [20.0, 320.0, 100.0, 400.0],
        )

    def test_coordinate_conversion_fails_closed_for_unverified_rotation(self):
        with self.assertRaisesRegex(CoordinateSpaceError, "rotation"):
            fitz_rect_to_zotero(
                [20.0, 40.0, 100.0, 120.0],
                [0.0, 0.0, 300.0, 300.0],
                90,
            )

    def test_coordinate_conversion_rejects_invalid_or_nonfinite_rectangles(self):
        invalid_rectangles = (
            [20.0, 20.0, 20.0, 40.0],
            [20.0, 40.0, 10.0, 60.0],
            [-1.0, 20.0, 50.0, 60.0],
            [20.0, 20.0, 301.0, 60.0],
            [20.0, math.nan, 50.0, 60.0],
        )
        for rectangle in invalid_rectangles:
            with self.subTest(rectangle=rectangle):
                with self.assertRaises(CoordinateSpaceError):
                    fitz_rect_to_zotero(
                        rectangle,
                        [0.0, 0.0, 300.0, 300.0],
                        0,
                    )


if __name__ == "__main__":
    unittest.main()
