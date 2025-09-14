# src/interpolation.py - Daily allocation logic
import pandas as pd
from typing import List
import warnings

"""
Daily allocation for mixed-frequency series
------------------------------------------
This module converts each source series (TICKER, INDEXNAME, DURATION) into
daily by splitting each period's VALUE uniformly over its window
(prev PERIODEND, curr PERIODEND].

Key points:
- Preserve SOURCEDURATION to keep lineage and avoid cross-duration mixing
- First period uses duration-driven backfill (reviewable calendar defaults)
- CUMULATIVEVALUE is a global running sum over emitted daily VALUEs
"""


def _duration_backfill_start(duration: str, anchor: pd.Timestamp) -> pd.Timestamp:
    """
    Compute the start date for the first backfilled window, based on duration.
    Reviewable, calendar-aware defaults.
    """
    if duration == "Week":
        return anchor - pd.Timedelta(days=7)
    if duration == "Month":
        return anchor - pd.offsets.MonthBegin(1)
    if duration == "Quarter":
        return anchor - pd.offsets.QuarterBegin(startingMonth=1)
    if duration == "Year":
        return anchor - pd.offsets.YearBegin()
    if duration == "Mid-month":
        return anchor - pd.Timedelta(days=15)
    if duration == "Custom Quarter":
        return anchor - pd.Timedelta(days=91)
    return anchor - pd.Timedelta(days=30)


def convert_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Purpose
    -------
    Convert each independent source series (defined by TICKER, INDEXNAME,
    DURATION) into a daily series while preserving lineage via SOURCEDURATION.
    No cross-duration collapsing happens here.

    Rules implemented
    -----------------
    - Windows: allocate each period's VALUE over (prev PERIODEND, curr PERIODEND]
               (exclusive start, inclusive end)
    - Daily amounts: uniform split within the interval so sums equal period VALUE
    - First period backfill: duration-driven bounds
        Week: 7 days
        Month: start of previous calendar month to anchor
        Quarter: start of previous calendar quarter to anchor
        Year: start of previous calendar year to anchor
        Mid-month: 15 days
        Custom Quarter: ~91 days
    - Cumulative: CUMULATIVEVALUE is a global running sum over emitted daily VALUEs
    - Lineage: add SOURCEDURATION so consumers can choose Month/Week/etc. explicitly

    Output
    ------
    Columns: TICKER, DURATION ('Day'), PERIODEND, INDEXNAME, VALUE, CUMULATIVEVALUE, SOURCEDURATION
    """
    if df.empty:
        return pd.DataFrame(columns=["TICKER", "INDEXNAME", "DURATION", "PERIODEND", "VALUE"])

    df_local = df.copy()  # work on a copy to avoid mutating caller's DataFrame
    
    # Normalize PERIODEND to date (midnight) for robust comparisons/joins
    df_local["PERIODEND"] = pd.to_datetime(df_local["PERIODEND"]).dt.normalize()

    daily_frames: List[pd.DataFrame] = []
    # Process each source series independently; do NOT mix durations
    for (ticker, indexname, duration), grp in df_local.groupby(["TICKER", "INDEXNAME", "DURATION"], dropna=False):
        # Inline minimal validation
        if grp.empty:
            warnings.warn(f"Empty group for {ticker}/{indexname}/{duration}")
            continue
        if not {"VALUE", "PERIODEND"}.issubset(grp.columns):
            warnings.warn(f"Missing columns for {ticker}/{indexname}/{duration}")
            continue
        if not grp["VALUE"].notna().any():
            warnings.warn(f"No non-null values for {ticker}/{indexname}/{duration}")
            continue
        # Build clean, ordered anchors and period values (keep last per date)
        grp_sorted = grp.sort_values("PERIODEND").copy()
        grp_sorted["PERIODEND"] = pd.to_datetime(grp_sorted["PERIODEND"]).dt.normalize()
        
        # keep last VALUE per day to avoid duplicate anchors on same date
        last_per_date = grp_sorted.groupby("PERIODEND", as_index=True).tail(1)
        last_per_date = last_per_date.sort_values("PERIODEND")
        anchor_dates = list(last_per_date["PERIODEND"])  # ordered anchor dates
        raw_values = list(last_per_date["VALUE"].astype(float).values)  # period totals aligned to anchors
        if len(anchor_dates) == 0:
            continue

        # Backfill start: duration-driven, reviewable defaults
        a0 = anchor_dates[0]
        first_start = _duration_backfill_start(duration, a0)
        start_date = first_start
        end_date = anchor_dates[-1]
        daily_index = pd.date_range(start=start_date, end=end_date, freq="D")  # full daily grid

        # Allocate per interval (including first backfilled) so sums match period VALUEs exactly
        daily_value = pd.Series(0.0, index=daily_index)  # container for per-day allocations
        # First interval: (first_start, first_anchor]
        # Allocate uniformly so that the sum equals raw_values[0]
        if len(anchor_dates) >= 1 and len(raw_values) >= 1:
            prev_date = first_start
            curr_date = anchor_dates[0]
            num_days = (curr_date - prev_date).days  # number of days in (prev, curr]
            if num_days > 0:
                per_day = float(raw_values[0]) / num_days  # uniform split across days
                window = pd.date_range(prev_date + pd.offsets.Day(1), curr_date, freq="D")  # exclusive start, inclusive end
                daily_value.loc[window] = per_day  # write first interval
        
        # Subsequent intervals: (prev, curr]
        # Always prefer the reported period VALUE; fall back to cumulative delta only if needed
        for i in range(1, len(anchor_dates)):
            prev_date = anchor_dates[i - 1]
            curr_date = anchor_dates[i]
            num_days = (curr_date - prev_date).days  # number of days in (prev, curr]
            if num_days <= 0:
                continue
            period_total = float(raw_values[i]) if i < len(raw_values) else 0.0  # prefer reported VALUE
            per_day = period_total / num_days  # uniform allocation
            window = pd.date_range(prev_date + pd.offsets.Day(1), curr_date, freq="D")  # (prev, curr]
            daily_value.loc[window] = per_day  # write allocation

        # Global running cumulative (not period-to-date)
        cumulative_daily = daily_value.cumsum()  # global running sum over emitted daily values

        # Emit the daily rows for this source series with lineage preserved
        out = pd.DataFrame(
            {
                "TICKER": ticker,
                "DURATION": "Day",
                "PERIODEND": daily_value.index,  # daily date
                "INDEXNAME": indexname,
                "VALUE": daily_value.values,  # per-day allocation
                "CUMULATIVEVALUE": cumulative_daily.values,  # running cumulative
                "SOURCEDURATION": duration,
            }
        )
        out["VALUE"] = out["VALUE"].astype(float)  # preserve sign; no silent clipping

        daily_frames.append(out)

    result = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(columns=["TICKER", "INDEXNAME", "DURATION", "PERIODEND", "VALUE"])
    if result.empty:
        return result

    # Keep sources separate (no cross-duration collapse). Sort for readability.
    result = result.sort_values(["TICKER", "INDEXNAME", "SOURCEDURATION", "PERIODEND"]).reset_index(drop=True)
    # Reorder columns (include SOURCEDURATION for lineage visibility)
    result = result[["TICKER", "DURATION", "PERIODEND", "INDEXNAME", "VALUE", "CUMULATIVEVALUE", "SOURCEDURATION"]]
    return result
