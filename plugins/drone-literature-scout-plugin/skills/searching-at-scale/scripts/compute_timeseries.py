"""Deterministic, in-memory time-series indicator calculations.

Insufficient windows are represented by ``None``.  The module performs no
network or file I/O and never mutates input rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
from numbers import Real
from typing import Any


MissingFloat = float | None
_ADJUSTMENT_MODES = frozenset({"raw", "forward", "backward"})
_METADATA_FIELD = "_indicator_metadata"


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _periods(values: Sequence[int], name: str) -> tuple[int, ...]:
    try:
        periods = tuple(values)
    except TypeError as error:
        raise ValueError(f"{name} must be a sequence of positive integers") from error
    validated = tuple(
        _positive_integer(value, f"{name} item") for value in periods
    )
    if len(validated) != len(set(validated)):
        raise ValueError(f"{name} must contain unique periods")
    return validated


def _finite_values(values: Sequence[Real], name: str) -> list[float]:
    try:
        raw_values = list(values)
    except TypeError as error:
        raise ValueError(f"{name} must be a sequence of finite numbers") from error

    result: list[float] = []
    for index, value in enumerate(raw_values):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name}[{index}] must be a finite number")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name}[{index}] must be a finite number")
        result.append(number)
    return result


def rolling_mean(values: Sequence[Real], window: int) -> list[MissingFloat]:
    """Return a simple rolling arithmetic mean with leading ``None`` values."""
    size = _positive_integer(window, "window")
    numbers = _finite_values(values, "values")
    result: list[MissingFloat] = []
    running = 0.0
    for index, value in enumerate(numbers):
        running += value
        if index >= size:
            running -= numbers[index - size]
        result.append(running / size if index + 1 >= size else None)
    return result


def rsi_wilder(values: Sequence[Real], period: int) -> list[MissingFloat]:
    """Return Wilder RSI seeded from the first ``period`` price changes.

    The first ``period`` outputs are ``None``.  A flat gain/loss state is
    neutral (50), a gain-only state is 100, and a loss-only state is 0.
    """
    size = _positive_integer(period, "period")
    prices = _finite_values(values, "values")
    result: list[MissingFloat] = [None] * len(prices)
    if len(prices) <= size:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, size + 1):
        change = prices[index] - prices[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains) / size
    average_loss = sum(losses) / size

    def rsi_value() -> float:
        if average_gain == 0.0 and average_loss == 0.0:
            return 50.0
        if average_loss == 0.0:
            return 100.0
        if average_gain == 0.0:
            return 0.0
        relative_strength = average_gain / average_loss
        return 100.0 - 100.0 / (1.0 + relative_strength)

    result[size] = rsi_value()
    for index in range(size + 1, len(prices)):
        change = prices[index] - prices[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = (average_gain * (size - 1) + gain) / size
        average_loss = (average_loss * (size - 1) + loss) / size
        result[index] = rsi_value()
    return result


def kdj(
    highs: Sequence[Real],
    lows: Sequence[Real],
    closes: Sequence[Real],
    period: int = 9,
) -> tuple[list[MissingFloat], list[MissingFloat], list[MissingFloat]]:
    """Return K, D, and J using a rolling RSV and neutral 50/50 seed."""
    size = _positive_integer(period, "period")
    high_values = _finite_values(highs, "highs")
    low_values = _finite_values(lows, "lows")
    close_values = _finite_values(closes, "closes")
    if not (len(high_values) == len(low_values) == len(close_values)):
        raise ValueError("highs, lows, and closes must have equal lengths")

    for index, (high, low, close) in enumerate(
        zip(high_values, low_values, close_values, strict=True)
    ):
        if high < low:
            raise ValueError(f"highs[{index}] must be greater than or equal to lows[{index}]")
        if not low <= close <= high:
            raise ValueError(f"closes[{index}] must lie between low and high")

    k_values: list[MissingFloat] = [None] * len(close_values)
    d_values: list[MissingFloat] = [None] * len(close_values)
    j_values: list[MissingFloat] = [None] * len(close_values)
    previous_k = 50.0
    previous_d = 50.0

    for index in range(size - 1, len(close_values)):
        lowest = min(low_values[index - size + 1 : index + 1])
        highest = max(high_values[index - size + 1 : index + 1])
        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (close_values[index] - lowest) / (highest - lowest) * 100.0
        current_k = (2.0 * previous_k + rsv) / 3.0
        current_d = (2.0 * previous_d + current_k) / 3.0
        current_j = 3.0 * current_k - 2.0 * current_d
        k_values[index] = current_k
        d_values[index] = current_d
        j_values[index] = current_j
        previous_k = current_k
        previous_d = current_d

    return k_values, d_values, j_values


def _row_identity(row: Mapping[str, Any]) -> str | None:
    if "series_id" not in row:
        return None
    value = row["series_id"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("row series_id must be a non-empty string")
    return value


def _row_adjustment(row: Mapping[str, Any]) -> str | None:
    if "adjustment_mode" not in row:
        return None
    value = row["adjustment_mode"]
    if value not in _ADJUSTMENT_MODES:
        raise ValueError(
            "row adjustment_mode must be raw, forward, or backward"
        )
    return value


def _resolve_series_id(
    rows: Sequence[Mapping[str, Any]],
    requested: str | None,
) -> str:
    if requested is not None and (
        not isinstance(requested, str) or not requested.strip()
    ):
        raise ValueError("series_id must be a non-empty string or None")
    row_values = {value for row in rows if (value := _row_identity(row)) is not None}
    if len(row_values) > 1:
        raise ValueError("rows must not mix series identities")
    if requested is not None and row_values and requested not in row_values:
        raise ValueError("series_id conflicts with row series identity")
    if requested is not None:
        return requested
    if row_values:
        return next(iter(row_values))
    return "unspecified"


def _validate_adjustment_mode(
    rows: Sequence[Mapping[str, Any]],
    requested: str,
) -> str:
    if requested not in _ADJUSTMENT_MODES:
        raise ValueError("adjustment_mode must be raw, forward, or backward")
    row_values = {
        value for row in rows if (value := _row_adjustment(row)) is not None
    }
    if len(row_values) > 1:
        raise ValueError("rows must not mix adjustment modes")
    if row_values and requested not in row_values:
        raise ValueError("adjustment_mode conflicts with row adjustment mode")
    return requested


def _metadata(
    ma_windows: tuple[int, ...],
    rsi_periods: tuple[int, ...],
    kdj_period: int,
    adjustment_mode: str,
    series_id: str,
) -> dict[str, Any]:
    return {
        "series_id": series_id,
        "adjustment_mode": adjustment_mode,
        "price_field": "close",
        "missing_output": None,
        "ma": {
            f"MA{window}": {
                "formula": "simple rolling arithmetic mean",
                "window": window,
            }
            for window in ma_windows
        },
        "rsi": {
            f"RSI{period}": {
                "formula": "Wilder RSI",
                "period": period,
                "seed": "mean of first period gains and losses",
                "smoothing": "(previous * (period - 1) + current) / period",
            }
            for period in rsi_periods
        },
        "kdj": {
            "fields": ("K", "D", "J"),
            "period": kdj_period,
            "initial_k": 50.0,
            "initial_d": 50.0,
            "zero_range_rsv": 50.0,
            "k_formula": "2/3 * previous K + 1/3 * RSV",
            "d_formula": "2/3 * previous D + 1/3 * K",
            "j_formula": "3 * K - 2 * D",
        },
    }


def compute_indicators(
    rows: Sequence[Mapping[str, Any]],
    *,
    ma_windows: Sequence[int] = (5, 20),
    rsi_periods: Sequence[int] = (6,),
    kdj_period: int = 9,
    adjustment_mode: str = "raw",
    series_id: str | None = None,
) -> list[dict[str, Any]]:
    """Copy rows and attach requested MA, Wilder RSI, KDJ, and provenance.

    Rows must contain finite ``high``, ``low``, and ``close`` values.  ``open``
    is validated when present.  Existing derived-field names are rejected so
    no raw input field can be overwritten silently.
    """
    windows = _periods(ma_windows, "ma_windows")
    periods = _periods(rsi_periods, "rsi_periods")
    kdj_size = _positive_integer(kdj_period, "kdj_period")
    try:
        raw_rows = list(rows)
    except TypeError as error:
        raise ValueError("rows must be a sequence of mappings") from error
    for index, row in enumerate(raw_rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"rows[{index}] must be a mapping")

    resolved_adjustment = _validate_adjustment_mode(raw_rows, adjustment_mode)
    resolved_series_id = _resolve_series_id(raw_rows, series_id)
    if not raw_rows:
        return []

    derived_fields = {
        *(f"MA{window}" for window in windows),
        *(f"RSI{period}" for period in periods),
        "K",
        "D",
        "J",
        _METADATA_FIELD,
    }
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    copied_rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        collisions = derived_fields.intersection(row)
        if collisions:
            names = ", ".join(sorted(collisions))
            raise ValueError(f"rows[{index}] contains derived output field(s): {names}")
        missing = {"high", "low", "close"}.difference(row)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"rows[{index}] is missing required field(s): {names}")

        high, low, close = (
            _finite_values([row[field]], f"rows[{index}].{field}")[0]
            for field in ("high", "low", "close")
        )
        if high < low:
            raise ValueError(f"rows[{index}].high must be greater than or equal to low")
        if not low <= close <= high:
            raise ValueError(f"rows[{index}].close must lie between low and high")
        if "open" in row:
            open_value = _finite_values(
                [row["open"]], f"rows[{index}].open"
            )[0]
            if not low <= open_value <= high:
                raise ValueError(f"rows[{index}].open must lie between low and high")

        highs.append(high)
        lows.append(low)
        closes.append(close)
        copied_rows.append(deepcopy(dict(row)))

    ma_series = {
        f"MA{window}": rolling_mean(closes, window) for window in windows
    }
    rsi_series = {
        f"RSI{period}": rsi_wilder(closes, period) for period in periods
    }
    k_values, d_values, j_values = kdj(highs, lows, closes, kdj_size)
    metadata = _metadata(
        windows,
        periods,
        kdj_size,
        resolved_adjustment,
        resolved_series_id,
    )

    for index, row in enumerate(copied_rows):
        for field, values in ma_series.items():
            row[field] = values[index]
        for field, values in rsi_series.items():
            row[field] = values[index]
        row["K"] = k_values[index]
        row["D"] = d_values[index]
        row["J"] = j_values[index]
        row[_METADATA_FIELD] = deepcopy(metadata)
    return copied_rows
