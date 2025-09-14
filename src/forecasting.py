# src/forecasting.py - Quarterly estimation logic (avg & seasonal)
import pandas as pd
from typing import List


def _quarter_start(date: pd.Timestamp) -> pd.Timestamp:
    q = (date.month - 1) // 3
    month = q * 3 + 1
    return pd.Timestamp(year=date.year, month=month, day=1)


def _quarter_end(date: pd.Timestamp) -> pd.Timestamp:
    q = (date.month - 1) // 3
    month = (q + 1) * 3
    return (pd.Timestamp(year=date.year, month=month, day=1) + pd.offsets.MonthEnd(0))


def _choose_source_duration(available: List[str]) -> str:
    # Priority (quarter forecasting): Month > Week > Quarter > Custom Quarter > Mid-month > Year
    order = ["Month", "Week", "Quarter", "Custom Quarter", "Mid-month", "Year"]
    for d in order:
        if d in available:
            return d
    return available[0]


def estimate_quarterly(daily_df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """
    Estimate full-quarter totals as of a date by extrapolating the quarter-to-date
    daily average over remaining days in the calendar quarter.

    Inputs:
      - daily_df: output from convert_to_daily with columns including
        TICKER, INDEXNAME, PERIODEND, VALUE, SOURCEDURATION
      - as_of_date: YYYY-MM-DD string

    Output columns:
      TICKER, INDEXNAME, ASOFDATE, QUARTER_START, QUARTER_END,
      DAYS_ELAPSED, DAYS_IN_QUARTER, QTD, FORECAST, SOURCEDURATION, METHOD
    """
    if daily_df.empty:
        return pd.DataFrame(columns=[
            "TICKER", "INDEXNAME", "ASOFDATE", "QUARTER_START", "QUARTER_END",
            "DAYS_ELAPSED", "DAYS_IN_QUARTER", "QTD", "FORECAST", "SOURCEDURATION", "METHOD"
        ])

    df = daily_df.copy()
    df["PERIODEND"] = pd.to_datetime(df["PERIODEND"]).dt.normalize()
    as_of = pd.to_datetime(as_of_date).normalize()
    q_start = _quarter_start(as_of)
    q_end = _quarter_end(as_of)
    # Clamp as_of within the quarter and guard early dates
    if as_of < q_start:
        as_of_clamped = q_start
    elif as_of > q_end:
        as_of_clamped = q_end
    else:
        as_of_clamped = as_of
    days_in_q = (q_end - q_start).days + 1
    days_elapsed = max((as_of_clamped - q_start).days + 1, 0)

    results = []
    # Work per (TICKER, INDEXNAME), choosing one source by priority
    for (ticker, indexname), sub in df.groupby(["TICKER", "INDEXNAME"], dropna=False):
        available = sub["SOURCEDURATION"].dropna().unique().tolist()
        if not available:
            continue
        chosen = _choose_source_duration(available)
        s = sub[sub["SOURCEDURATION"] == chosen]
        mask = (s["PERIODEND"] >= q_start) & (s["PERIODEND"] <= as_of_clamped)
        qtd = float(s.loc[mask, "VALUE"].astype(float).sum()) if days_elapsed > 0 else 0.0
        avg_daily = qtd / max(days_elapsed, 1)
        remaining_days = max((q_end - as_of_clamped).days, 0)
        forecast = qtd + avg_daily * remaining_days
        results.append({
            "TICKER": ticker,
            "INDEXNAME": indexname,
            "ASOFDATE": as_of.date(),
            "QUARTER_START": q_start.date(),
            "QUARTER_END": q_end.date(),
            "DAYS_ELAPSED": days_elapsed,
            "DAYS_IN_QUARTER": days_in_q,
            "QTD": qtd,
            "FORECAST": forecast,
            "SOURCEDURATION": chosen,
            "METHOD": "avg_daily_extrapolation",
        })
    out = pd.DataFrame(results)
    if not out.empty:
        # Round for presentation while keeping internal logic precise
        out["QTD"] = out["QTD"].round(3)
        out["FORECAST"] = out["FORECAST"].round(3)
    return out


def estimate_quarterly_seasonal(daily_df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """
    Seasonality-adjusted estimate using last year's same calendar quarter.

    Idea:
      growth_factor = (current QTD up to as_of) / (last year's QTD up to same day-of-quarter)
      forecast = growth_factor * (last year's full quarter total)
    Fallback to avg-daily extrapolation if last year's data is missing or zero.
    """
    if daily_df.empty:
        return pd.DataFrame(columns=[
            "TICKER", "INDEXNAME", "ASOFDATE", "QUARTER_START", "QUARTER_END",
            "DAYS_ELAPSED", "DAYS_IN_QUARTER", "QTD", "FORECAST", "SOURCEDURATION", "METHOD"
        ])

    df = daily_df.copy()
    df["PERIODEND"] = pd.to_datetime(df["PERIODEND"]).dt.normalize()
    as_of = pd.to_datetime(as_of_date).normalize()
    q_start = _quarter_start(as_of)
    q_end = _quarter_end(as_of)
    if as_of < q_start:
        as_of_clamped = q_start
    elif as_of > q_end:
        as_of_clamped = q_end
    else:
        as_of_clamped = as_of
    days_in_q = (q_end - q_start).days + 1
    days_elapsed = max((as_of_clamped - q_start).days + 1, 0)

    # Last year's same calendar quarter
    ly_as_of = as_of - pd.DateOffset(years=1)
    ly_q_start = _quarter_start(ly_as_of)
    ly_q_end = _quarter_end(ly_as_of)

    results = []
    for (ticker, indexname), sub in df.groupby(["TICKER", "INDEXNAME"], dropna=False):
        available = sub["SOURCEDURATION"].dropna().unique().tolist()
        if not available:
            continue
        chosen = _choose_source_duration(available)
        s = sub[sub["SOURCEDURATION"] == chosen]

        # Current QTD
        curr_mask = (s["PERIODEND"] >= q_start) & (s["PERIODEND"] <= as_of_clamped)
        qtd = float(s.loc[curr_mask, "VALUE"].astype(float).sum()) if days_elapsed > 0 else 0.0

        # Last year QTD up to the same day-of-quarter index
        # Map current days elapsed onto last year's quarter start
        ly_cutoff = ly_q_start + pd.Timedelta(days=max(days_elapsed - 1, 0))
        ly_qtd_mask = (s["PERIODEND"] >= ly_q_start) & (s["PERIODEND"] <= ly_cutoff)
        ly_qtd = float(s.loc[ly_qtd_mask, "VALUE"].astype(float).sum())
        # Last year's full quarter total
        ly_full_mask = (s["PERIODEND"] >= ly_q_start) & (s["PERIODEND"] <= ly_q_end)
        ly_full = float(s.loc[ly_full_mask, "VALUE"].astype(float).sum())

        if ly_qtd > 0 and ly_full > 0:
            growth = qtd / ly_qtd
            forecast = growth * ly_full
        else:
            # Fallback to avg-daily extrapolation
            avg_daily = qtd / max(days_elapsed, 1)
            remaining_days = max((q_end - as_of_clamped).days, 0)
            forecast = qtd + avg_daily * remaining_days

        results.append({
            "TICKER": ticker,
            "INDEXNAME": indexname,
            "ASOFDATE": as_of.date(),
            "QUARTER_START": q_start.date(),
            "QUARTER_END": q_end.date(),
            "DAYS_ELAPSED": days_elapsed,
            "DAYS_IN_QUARTER": days_in_q,
            "QTD": qtd,
            "FORECAST": forecast,
            "SOURCEDURATION": chosen,
            "METHOD": "seasonality_vs_last_year",
        })

    out = pd.DataFrame(results)
    if not out.empty:
        out["QTD"] = out["QTD"].round(3)
        out["FORECAST"] = out["FORECAST"].round(3)
    return out


