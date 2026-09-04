from __future__ import annotations

import math
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.compute_timeseries import (
    compute_indicators,
    kdj,
    rolling_mean,
    rsi_wilder,
)


class TimeSeriesTests(unittest.TestCase):
    def test_rolling_mean_has_leading_missing_values(self):
        """Emitting partial-window averages would mislabel incomplete periods."""
        self.assertEqual(
            rolling_mean([1, 2, 3, 4, 5, 6], 5),
            [None, None, None, None, 3.0, 4.0],
        )

    def test_rolling_mean_rejects_invalid_values_and_windows(self):
        """Invalid numbers and non-positive or boolean windows must fail closed."""
        for window in (0, -1, True, 1.5):
            with self.subTest(window=window):
                with self.assertRaises(ValueError):
                    rolling_mean([1.0], window)
        for value in (True, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    rolling_mean([1.0, value], 1)

    def test_increasing_series_rsi_reaches_one_hundred(self):
        """A zero average loss must produce 100 instead of division failure."""
        self.assertEqual(
            rsi_wilder([1, 2, 3, 4, 5, 6, 7, 8], 6),
            [None, None, None, None, None, None, 100.0, 100.0],
        )

    def test_wilder_rsi_uses_seed_then_recursive_smoothing(self):
        """Using rolling simple averages after the seed would change later RSI."""
        result = rsi_wilder([1, 2, 1, 3, 2, 4], 3)
        self.assertEqual(result[:3], [None, None, None])
        self.assertAlmostEqual(result[3], 75.0, places=12)
        self.assertAlmostEqual(result[4], 54.54545454545455, places=12)
        self.assertAlmostEqual(result[5], 75.0, places=12)

    def test_flat_rsi_is_neutral_and_short_series_is_all_missing(self):
        """A zero gain and zero loss seed must be neutral, not 0 or 100."""
        self.assertEqual(
            rsi_wilder([5, 5, 5, 5], 3),
            [None, None, None, 50.0],
        )
        self.assertEqual(rsi_wilder([1, 2, 3], 3), [None, None, None])

    def test_constant_range_kdj_is_neutral(self):
        """A zero price range must use RSV 50 and preserve neutral K, D, and J."""
        highs = [10.0] * 12
        lows = [10.0] * 12
        closes = [10.0] * 12
        k_values, d_values, j_values = kdj(highs, lows, closes, 9)
        self.assertEqual(k_values[:8], [None] * 8)
        self.assertEqual(d_values[:8], [None] * 8)
        self.assertEqual(j_values[:8], [None] * 8)
        for values in (k_values, d_values, j_values):
            self.assertEqual(values[8:], [50.0] * 4)

    def test_kdj_uses_nine_period_rsv_and_recursive_seed(self):
        """Starting K and D from the first RSV instead of 50 changes the series."""
        highs = [float(value) for value in range(1, 11)]
        lows = [0.0] * 10
        closes = highs.copy()
        k_values, d_values, j_values = kdj(highs, lows, closes, 9)
        self.assertEqual(k_values[:8], [None] * 8)
        self.assertAlmostEqual(k_values[8], 200.0 / 3.0, places=12)
        self.assertAlmostEqual(d_values[8], 500.0 / 9.0, places=12)
        self.assertAlmostEqual(j_values[8], 800.0 / 9.0, places=12)
        self.assertAlmostEqual(k_values[9], 700.0 / 9.0, places=12)
        self.assertAlmostEqual(d_values[9], 1700.0 / 27.0, places=12)
        self.assertAlmostEqual(j_values[9], 2900.0 / 27.0, places=12)

    def test_kdj_rejects_misaligned_and_impossible_ohlc(self):
        """Misaligned arrays or closes outside the daily range corrupt RSV."""
        with self.assertRaises(ValueError):
            kdj([2.0], [1.0, 1.0], [1.5], 1)
        for highs, lows, closes in (
            ([1.0], [2.0], [1.5]),
            ([2.0], [1.0], [2.5]),
            ([2.0], [1.0], [0.5]),
            ([2.0], [1.0], [True]),
        ):
            with self.subTest(highs=highs, lows=lows, closes=closes):
                with self.assertRaises(ValueError):
                    kdj(highs, lows, closes, 1)

    def test_compute_preserves_raw_fields_and_does_not_mutate_callers(self):
        """Adding indicators must neither discard raw fields nor alias nested data."""
        rows = [
            {
                "date": f"2026-01-{index + 1:02d}",
                "open": float(index + 1),
                "high": float(index + 2),
                "low": float(index),
                "close": float(index + 1),
                "volume": 100 + index,
                "source": {"name": "exchange"},
            }
            for index in range(12)
        ]
        original = [
            {
                **row,
                "source": dict(row["source"]),
            }
            for row in rows
        ]
        result = compute_indicators(
            rows,
            ma_windows=(5,),
            rsi_periods=(6,),
            kdj_period=9,
            adjustment_mode="raw",
            series_id="600028.XSHG",
        )

        self.assertEqual(rows, original)
        for raw, computed in zip(original, result, strict=True):
            for field, value in raw.items():
                self.assertEqual(computed[field], value)
        result[0]["source"]["name"] = "changed"
        self.assertEqual(rows[0]["source"]["name"], "exchange")
        self.assertEqual(result[0]["MA5"], None)
        self.assertEqual(result[4]["MA5"], 3.0)
        self.assertEqual(result[6]["RSI6"], 100.0)
        self.assertIsNotNone(result[8]["K"])

    def test_compute_attaches_exact_provenance_to_every_row(self):
        """Omitting formula parameters or series provenance permits silent mixing."""
        rows = [
            {
                "date": str(index),
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
            }
            for index in range(12)
        ]
        result = compute_indicators(
            rows,
            ma_windows=(5, 2),
            rsi_periods=(6,),
            kdj_period=9,
            adjustment_mode="forward",
            series_id="600028.XSHG",
        )
        expected = {
            "series_id": "600028.XSHG",
            "adjustment_mode": "forward",
            "price_field": "close",
            "missing_output": None,
            "ma": {
                "MA5": {
                    "formula": "simple rolling arithmetic mean",
                    "window": 5,
                },
                "MA2": {
                    "formula": "simple rolling arithmetic mean",
                    "window": 2,
                },
            },
            "rsi": {
                "RSI6": {
                    "formula": "Wilder RSI",
                    "period": 6,
                    "seed": "mean of first period gains and losses",
                    "smoothing": "(previous * (period - 1) + current) / period",
                },
            },
            "kdj": {
                "fields": ("K", "D", "J"),
                "period": 9,
                "initial_k": 50.0,
                "initial_d": 50.0,
                "zero_range_rsv": 50.0,
                "k_formula": "2/3 * previous K + 1/3 * RSV",
                "d_formula": "2/3 * previous D + 1/3 * K",
                "j_formula": "3 * K - 2 * D",
            },
        }
        for row in result:
            self.assertEqual(row["_indicator_metadata"], expected)
        self.assertEqual(result[-1]["K"], 50.0)
        self.assertEqual(result[-1]["D"], 50.0)
        self.assertEqual(result[-1]["J"], 50.0)

    def test_compute_rejects_duplicate_or_invalid_periods(self):
        """Duplicate, boolean, or non-positive periods make output fields ambiguous."""
        rows = [{"date": "0", "high": 1.0, "low": 1.0, "close": 1.0}]
        invalid_arguments = (
            {"ma_windows": (5, 5)},
            {"ma_windows": (True,)},
            {"ma_windows": (0,)},
            {"rsi_periods": (6, 6)},
            {"rsi_periods": (False,)},
            {"kdj_period": 0},
            {"kdj_period": True},
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    compute_indicators(rows, **arguments)

    def test_compute_rejects_missing_nonfinite_and_colliding_fields(self):
        """Malformed rows must fail closed instead of emitting misleading indicators."""
        invalid_rows = (
            [{"date": "0", "low": 1.0, "close": 1.0}],
            [{"date": "0", "high": math.nan, "low": 1.0, "close": 1.0}],
            [{"date": "0", "high": 2.0, "low": 1.0, "close": True}],
            [{"date": "0", "high": 2.0, "low": 1.0, "close": 3.0}],
            [{"date": "0", "high": 2.0, "low": 1.0, "close": 1.5, "MA5": 1.0}],
            [
                {
                    "date": "0",
                    "high": 2.0,
                    "low": 1.0,
                    "close": 1.5,
                    "_indicator_metadata": {},
                }
            ],
        )
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    compute_indicators(rows, ma_windows=(5,))

    def test_compute_rejects_mixed_adjustments_and_series(self):
        """Rows carrying different adjustment modes or identities cannot be combined."""
        base = {"date": "0", "high": 2.0, "low": 1.0, "close": 1.5}
        with self.assertRaises(ValueError):
            compute_indicators(
                [
                    {**base, "adjustment_mode": "raw"},
                    {**base, "date": "1", "adjustment_mode": "forward"},
                ]
            )
        with self.assertRaises(ValueError):
            compute_indicators(
                [
                    {**base, "series_id": "A"},
                    {**base, "date": "1", "series_id": "B"},
                ]
            )
        with self.assertRaises(ValueError):
            compute_indicators(
                [{**base, "adjustment_mode": "forward"}],
                adjustment_mode="raw",
            )
        with self.assertRaises(ValueError):
            compute_indicators(
                [{**base, "series_id": "A"}],
                series_id="B",
            )

    def test_empty_inputs_have_explicit_empty_outputs(self):
        """Empty inputs must return shape-preserving empty results, not fabricate data."""
        self.assertEqual(rolling_mean([], 3), [])
        self.assertEqual(rsi_wilder([], 3), [])
        self.assertEqual(kdj([], [], [], 9), ([], [], []))
        self.assertEqual(compute_indicators([]), [])

    def test_identical_inputs_produce_equal_detached_outputs(self):
        """Hidden state or shared metadata would make repeated calculations unsafe."""
        rows = [{"date": "0", "high": 2.0, "low": 1.0, "close": 1.5}]
        first = compute_indicators(rows, series_id="A")
        second = compute_indicators(rows, series_id="A")
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(
            first[0]["_indicator_metadata"],
            second[0]["_indicator_metadata"],
        )


if __name__ == "__main__":
    unittest.main()
