# src/data_processor.py - Data loading and validation
import pandas as pd
from datetime import datetime
import numpy as np
from typing import List, Dict

def load_and_validate_data(file_path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(file_path, parse_dates=['PERIODEND'])
    except Exception as e:
        raise FileNotFoundError(f"Could not read file {file_path}: {str(e)}")

    # Validate required columns
    required_columns = ['TICKER', 'DURATION', 'PERIODEND', 'INDEXNAME', 'VALUE', 'CUMULATIVEVALUE']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    # Trim string fields to avoid accidental whitespace mismatches
    for col in ['TICKER', 'DURATION', 'INDEXNAME']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Coerce numeric columns
    df['VALUE'] = pd.to_numeric(df['VALUE'], errors='coerce')
    if 'CUMULATIVEVALUE' in df.columns:
        df['CUMULATIVEVALUE'] = pd.to_numeric(df['CUMULATIVEVALUE'], errors='coerce')
    # Parse RELEASEDDATE if present (for revision-aware de-duplication)
    if 'RELEASEDDATE' in df.columns:
        df['RELEASEDDATE'] = pd.to_datetime(df['RELEASEDDATE'], errors='coerce')

    # Drop rows with missing essential fields
    before = len(df)
    df = df.dropna(subset=['TICKER', 'DURATION', 'PERIODEND', 'INDEXNAME', 'VALUE'])
    after = len(df)
    if before != after:
        print(f"Dropped {before - after} rows with missing required fields")

    # Enforce non-negative values
    negatives = (df['VALUE'] < 0).sum()
    if negatives:
        print(f"Warning: {negatives} negative VALUE rows clipped to 0")
        df.loc[df['VALUE'] < 0, 'VALUE'] = 0.0

    # Prefer latest release when multiple versions exist for the same anchor
    if 'RELEASEDDATE' in df.columns:
        # Sort by RELEASEDDATE then keep last per (TICKER, INDEXNAME, DURATION, PERIODEND)
        df = df.sort_values(['TICKER', 'INDEXNAME', 'DURATION', 'PERIODEND', 'RELEASEDDATE'])
        df = df.drop_duplicates(subset=['TICKER', 'INDEXNAME', 'DURATION', 'PERIODEND'], keep='last')
    # Final pass: remove any remaining exact duplicates
    before = len(df)
    df = df.drop_duplicates()
    if len(df) != before:
        print(f"Dropped {before - len(df)} duplicate rows")

    # Sort for processing
    df = df.sort_values(['TICKER', 'INDEXNAME', 'DURATION', 'PERIODEND']).reset_index(drop=True)

    return df