# pipeline.py
import argparse
import os
import pandas as pd
from src.data_processor import load_and_validate_data
from src.daily_allocation import convert_to_daily
from src.forecasting import estimate_quarterly, estimate_quarterly_seasonal

def main():
    parser = argparse.ArgumentParser(description='Hatched Analytics Data Pipeline')
    parser.add_argument('--input', required=True, help='Input CSV file path')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--forecast-method', choices=['avg', 'seasonal', 'both'], default=None, help='If provided, runs quarterly forecast (avg/seasonal/both). If omitted, outputs daily.')

    args = parser.parse_args()

    # Load and validate input data
    df = load_and_validate_data(args.input)

    # Decide mode by presence of --forecast-method
    if args.forecast_method is None:
        print("\nTask 1: Converting to daily data")
        daily_df = convert_to_daily(df)
        
        # Ensure stable sort before writing
        daily_df = daily_df.sort_values(["TICKER", "INDEXNAME", "SOURCEDURATION", "PERIODEND"]).reset_index(drop=True)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        daily_df.to_csv(args.output, index=False)
        
        print(f"Daily data saved to: {args.output}")
        print(f"Generated {len(daily_df)} daily records")
    else:
        print("\nTask 2: Estimating quarterly values")
        
        daily_df_for_forecast = convert_to_daily(df)
        if daily_df_for_forecast.empty:
            raise ValueError("No daily data available for forecasting")
        as_of_str = pd.to_datetime(daily_df_for_forecast['PERIODEND']).max().normalize().strftime('%Y-%m-%d')
        
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        
        if args.forecast_method in ('avg', 'both'):
            forecast_df = estimate_quarterly(daily_df_for_forecast, as_of_str)
            forecast_df.to_csv(args.output, index=False)
            print(f"Quarterly forecasts saved to: {args.output}")

        if args.forecast_method in ('seasonal', 'both'):
            seasonal_df = estimate_quarterly_seasonal(daily_df_for_forecast, as_of_str)
            seasonal_path = args.output.replace('.csv', '_seasonal.csv')
            
            os.makedirs(os.path.dirname(seasonal_path), exist_ok=True)
            seasonal_df.to_csv(seasonal_path, index=False)
            print(f"Seasonal quarterly forecasts saved to: {seasonal_path}")
        
if __name__ == "__main__":
    main()