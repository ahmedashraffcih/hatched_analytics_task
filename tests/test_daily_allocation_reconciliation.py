"""
Synthetic-input unit tests for src.daily_allocation.convert_to_daily.

These tests run in-process against constructed DataFrames — no dependency on
having previously executed the pipeline. They establish the test scaffold for
CI and verify the project's central invariant: the sum of daily VALUE over
each source interval equals the source period VALUE to floating-point
tolerance.

For the integration-style validation (which reads outputs/daily_index.csv
produced by an actual pipeline run), see tests/test_daily_validation.py.
"""

from pathlib import Path
import sys

import pandas as pd
import pytest

# Make `src/` importable when pytest is invoked from the repo root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.daily_allocation import convert_to_daily  # noqa: E402


TOL = 1e-9


def _monthly_two_anchors():
    """Two consecutive month-end anchors, simple monotonic VALUEs."""
    return pd.DataFrame(
        {
            "TICKER": ["ADBE", "ADBE"],
            "INDEXNAME": ["users", "users"],
            "DURATION": ["Month", "Month"],
            "PERIODEND": [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")],
            "VALUE": [310.0, 290.0],
        }
    )


def test_reconciliation_second_interval_sums_to_source():
    """Sum of daily VALUE over (prev anchor, curr anchor] equals the source VALUE."""
    raw = _monthly_two_anchors()
    daily = convert_to_daily(raw)

    feb_window = daily[
        (daily["PERIODEND"] > pd.Timestamp("2024-01-31"))
        & (daily["PERIODEND"] <= pd.Timestamp("2024-02-29"))
    ]

    # Feb has 29 days (2024 is a leap year), source VALUE for Feb is 290
    assert len(feb_window) == 29, f"Expected 29 daily rows in Feb window, got {len(feb_window)}"
    assert abs(feb_window["VALUE"].sum() - 290.0) < TOL, (
        f"Reconciliation broke: Feb daily sum = {feb_window['VALUE'].sum()}, expected 290.0"
    )


def test_uniform_split_within_interval():
    """Each day in a window has the same per-day value (uniform allocation)."""
    raw = _monthly_two_anchors()
    daily = convert_to_daily(raw)

    feb_window = daily[
        (daily["PERIODEND"] > pd.Timestamp("2024-01-31"))
        & (daily["PERIODEND"] <= pd.Timestamp("2024-02-29"))
    ]

    expected_per_day = 290.0 / 29
    diffs = (feb_window["VALUE"] - expected_per_day).abs()
    assert diffs.max() < TOL, (
        f"Allocation not uniform: max deviation from {expected_per_day} is {diffs.max()}"
    )


def test_first_interval_backfill_window_for_month():
    """Month duration backfills the first interval to the start of the prior calendar month.

    For an anchor at 2024-01-31, the first interval is (2024-01-01, 2024-01-31].
    The backfill-start day (2024-01-01) appears in the emitted daily series
    with VALUE=0 (exclusive-start `(prev, curr]` semantics); the 30 days from
    2024-01-02 through 2024-01-31 carry the uniform per-day allocation that
    reconciles to the source VALUE.
    """
    raw = _monthly_two_anchors()
    daily = convert_to_daily(raw).sort_values("PERIODEND").reset_index(drop=True)

    # Earliest emitted row is the backfill-start boundary at VALUE=0
    earliest = daily.iloc[0]
    assert earliest["PERIODEND"] == pd.Timestamp("2024-01-01"), (
        f"Expected backfill-start at 2024-01-01, got {earliest['PERIODEND']}"
    )
    assert earliest["VALUE"] == 0.0, (
        f"Backfill-start day should have VALUE=0 (exclusive-start semantics), got {earliest['VALUE']}"
    )

    # Strict (prev, curr] window holds 30 allocated days and reconciles to source
    jan_window = daily[
        (daily["PERIODEND"] > pd.Timestamp("2024-01-01"))
        & (daily["PERIODEND"] <= pd.Timestamp("2024-01-31"))
    ]
    assert len(jan_window) == 30, f"Expected 30 days in strict Jan window, got {len(jan_window)}"
    assert abs(jan_window["VALUE"].sum() - 310.0) < TOL, (
        f"First-interval reconciliation broke: Jan window sum = {jan_window['VALUE'].sum()}, expected 310.0"
    )


def test_lineage_source_duration_preserved():
    """Output rows carry the original DURATION as SOURCEDURATION."""
    raw = _monthly_two_anchors()
    daily = convert_to_daily(raw)
    assert (daily["SOURCEDURATION"] == "Month").all()
    assert (daily["DURATION"] == "Day").all()


def test_cumulative_value_is_global_running_sum():
    """CUMULATIVEVALUE is monotonic non-decreasing over the sorted daily series."""
    raw = _monthly_two_anchors()
    daily = convert_to_daily(raw).sort_values("PERIODEND").reset_index(drop=True)

    diffs = daily["CUMULATIVEVALUE"].diff().dropna()
    # Each diff should equal the corresponding day's VALUE (within tolerance)
    daily_values = daily["VALUE"].iloc[1:].reset_index(drop=True)
    diffs_aligned = diffs.reset_index(drop=True)
    assert (diffs_aligned - daily_values).abs().max() < TOL


def test_empty_input_returns_empty_with_expected_columns():
    """Empty input doesn't crash; returns an empty frame with the documented columns."""
    raw = pd.DataFrame(columns=["TICKER", "INDEXNAME", "DURATION", "PERIODEND", "VALUE"])
    daily = convert_to_daily(raw)
    assert daily.empty
    for col in ("TICKER", "INDEXNAME", "DURATION", "PERIODEND", "VALUE"):
        assert col in daily.columns
