#!/usr/bin/env python3
"""
Simple IG Data Fetcher
Fetches candle data from IG and saves to CSV.
"""

import sys
import os
from pathlib import Path
import pandas as pd
import yaml
import requests
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ig_adapter import IGBroker, IGAuth

# Load environment
load_dotenv()

# Timeframe mapping for IG API
TIMEFRAMES = {
    '1Min': 'MINUTE',
    '5Min': 'MINUTE_5',
    '15Min': 'MINUTE_15',
    '30Min': 'MINUTE_30',
    '1Hour': 'HOUR',
    '4Hour': 'HOUR_4',
    'Day': 'DAY',
}


def load_config():
    """Load configuration from YAML file."""
    config_path = PROJECT_ROOT / "configs" / "rsi_test_config.yaml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def fetch_data(broker, epic, timeframe, max_candles):
    """
    Fetch historical candles from IG.

    Note: IG API limits:
    - Maximum 10,000 data points per request
    - No pagination support for historical prices
    - Single request only
    """

    if timeframe not in TIMEFRAMES:
        print(f"❌ Invalid timeframe: {timeframe}")
        print(f"   Valid options: {', '.join(TIMEFRAMES.keys())}")
        return None

    resolution = TIMEFRAMES[timeframe]

    # IG API maximum is 10,000 candles per request
    if max_candles > 10000:
        print(f"⚠️  IG API limit is 10,000 candles. Reducing from {max_candles} to 10,000")
        max_candles = 10000

    print(f"📊 Fetching {max_candles} candles...")
    print(f"   Epic: {epic}")
    print(f"   Timeframe: {timeframe} ({resolution})")

    try:
        headers = broker._headers(version=3)

        # Build URL - single request
        url = f"{broker.base}/prices/{epic}"
        params = {
            'resolution': resolution,
            'max': max_candles,
        }

        # Make request
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()

        if 'prices' not in data or not data['prices']:
            print("❌ No data returned from IG")
            return None

        # Convert to DataFrame
        candles = []
        for price in data['prices']:
            candles.append({
                'Datetime': price['snapshotTime'],
                'Open': float(price['openPrice']['bid']),
                'High': float(price['highPrice']['bid']),
                'Low': float(price['lowPrice']['bid']),
                'Close': float(price['closePrice']['bid']),
            })

        df = pd.DataFrame(candles)

        # Reverse to oldest first
        df = df.iloc[::-1].reset_index(drop=True)

        # Parse datetime
        df['Datetime'] = pd.to_datetime(df['Datetime'])

        # Sort by datetime
        df = df.sort_values('Datetime').reset_index(drop=True)

        print(f"✅ Fetched {len(df)} candles")
        print(f"   From: {df['Datetime'].min()}")
        print(f"   To:   {df['Datetime'].max()}")

        # Calculate date range coverage
        if len(df) > 0:
            days = (df['Datetime'].max() - df['Datetime'].min()).days
            print(f"   Coverage: {days} days")

        return df

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def save_data(df, epic, timeframe, output_folder):
    """Save data to CSV with epic_timeframe.csv naming."""

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    # Clean epic name for filename
    epic_clean = epic.replace('.', '_')
    filename = f"{epic_clean}_{timeframe}.csv"
    filepath = output_path / filename

    df.to_csv(filepath, index=False)

    print(f"💾 Saved: {filepath}")
    print(f"   Rows: {len(df)}")

    return filepath


def main():
    print("=" * 60)
    print("IG DATA FETCHER")
    print("=" * 60)
    print()

    # Load config
    config = load_config()

    epic = config['data']['epic']
    timeframe = config['data']['timeframe']
    max_candles = config['data']['max_candles']
    output_folder = config['data']['output_folder']

    # Create auth from environment
    auth = IGAuth(
        api_key=os.getenv('IG_API_KEY'),
        username=os.getenv('IG_USERNAME'),
        password=os.getenv('IG_PASSWORD'),
        account_type=os.getenv('IG_ACCOUNT_TYPE', 'DEMO')
    )

    # Connect to IG
    print("🔐 Connecting to IG...")
    broker = IGBroker(auth)

    try:
        broker.connect()
        print("✅ Connected\n")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        sys.exit(1)

    # Fetch data
    df = fetch_data(broker, epic, timeframe, max_candles)

    if df is None or len(df) == 0:
        print("❌ No data fetched")
        sys.exit(1)

    print()

    # Save data
    filepath = save_data(df, epic, timeframe, output_folder)

    print()
    print("=" * 60)
    print("✅ COMPLETE")
    print("=" * 60)
    print(f"\nData file: {filepath}")
    print(f"Total candles: {len(df)}\n")


if __name__ == "__main__":
    main()
