import sys
from pathlib import Path
import pandas as pd


def compare(avg_path: Path, seasonal_path: Path, out_path: Path) -> int:
    avg = pd.read_csv(avg_path)
    seas = pd.read_csv(seasonal_path)

    # Normalize key columns
    for df in (avg, seas):
        if 'ASOFDATE' in df.columns:
            df['ASOFDATE'] = pd.to_datetime(df['ASOFDATE']).dt.date

    # Select comparable columns and rename forecasts
    a = avg[['TICKER','INDEXNAME','ASOFDATE','SOURCEDURATION','FORECAST']].copy()
    a = a.rename(columns={'FORECAST':'FORECAST_AVG'})
    s = seas[['TICKER','INDEXNAME','ASOFDATE','SOURCEDURATION','FORECAST']].copy()
    s = s.rename(columns={'FORECAST':'FORECAST_SEASONAL', 'SOURCEDURATION':'SOURCEDURATION_SEASONAL'})

    merged = pd.merge(a, s, on=['TICKER','INDEXNAME','ASOFDATE'], how='outer', suffixes=('_AVG','_SEASONAL'))
    merged['DIFF'] = merged['FORECAST_SEASONAL'] - merged['FORECAST_AVG']
    merged.to_csv(out_path, index=False)
    print(f"Wrote comparison to {out_path} rows={len(merged)}")
    return 0


if __name__ == '__main__':
    project = Path(__file__).resolve().parents[1]
    avg_path = project / 'outputs' / 'quarterly_forecasts.csv'
    seasonal_path = project / 'outputs' / 'quarterly_forecasts_seasonal.csv'
    out_path = project / 'outputs' / 'quarterly_forecasts_comparison.csv'
    if len(sys.argv) > 1:
        avg_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        seasonal_path = Path(sys.argv[2])
    if len(sys.argv) > 3:
        out_path = Path(sys.argv[3])
    sys.exit(compare(avg_path, seasonal_path, out_path))


