#!/usr/bin/env python3
"""
Convert tick data in SQLite -> monthly CSVs with OHLC bars.
- Robust time parsing (ISO8601 'Z' -> UTC)
- Safe on empty results (no .iloc[0] crashes)
- Symbol / timeframe / date-range / table customizable
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="SQLite DB path (e.g., us500_2024.db)")
    ap.add_argument("--table", default="ticks", help="Table name (default: ticks)")
    ap.add_argument("--symbol", required=True, help="Symbol to export (e.g., USA500IDXUSD or DEUIDXEUR)")
    ap.add_argument("--timeframe", default="30min",
                    help="Resample interval (e.g., 1min, 5min, 15min, 30min, 1H). Default: 30min")
    ap.add_argument("--outdir", default="data/out_monthly", help="Output directory")
    ap.add_argument("--start", default=None,
                    help="Optional start date (YYYY-MM-DD) to filter in SQL (UTC day prefix match)")
    ap.add_argument("--end", default=None,
                    help="Optional end date (YYYY-MM-DD, exclusive) for SQL filter")
    ap.add_argument("--where-extra", default=None,
                    help="Optional extra SQL WHERE clause without 'WHERE' (e.g., substr(ts,1,10)='2024-03-14')")
    ap.add_argument("--price-divisor", type=float, default=None,
                    help="Optional extra scaling (generally NOT needed; mid is already scaled).")
    return ap.parse_args()


def build_query(table: str, symbol: str, start: str | None, end: str | None, where_extra: str | None) -> str:
    clauses = [f"symbol = '{symbol}'"]
    # Use substr(ts,1,10) for day prefix filtering (fast with proper index)
    if start:
        clauses.append(f"substr(ts,1,10) >= '{start}'")
    if end:
        clauses.append(f"substr(ts,1,10) < '{end}'")
    if where_extra:
        clauses.append(f"({where_extra})")
    where_sql = " AND ".join(clauses)
    return f"""
        SELECT ts, mid AS price
        FROM {table}
        WHERE {where_sql}
        ORDER BY ts
    """

def parse_iso8601_utc(series):
    """
    Handle ISO8601 strings like:
      2024-03-14T13:16:51Z
      2024-03-14T13:16:51.123000Z
    Always returns tz-aware UTC datetimes.
    """
    try:
        # Pandas 2.x: fast path for mixed ISO8601
        return pd.to_datetime(series, utc=True, format="mixed", errors="raise")
    except (TypeError, ValueError):
        # Fallback for older Pandas: normalize the 'Z' and infer
        s = series.astype(str).str.replace("Z", "+00:00", regex=False)
        return pd.to_datetime(s, utc=True, errors="raise")
    
def main():
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"📥 Loading ticks from {args.db}  table={args.table}  symbol={args.symbol} ...")
    conn = sqlite3.connect(args.db)
    query = build_query(args.table, args.symbol, args.start, args.end, args.where_extra)
    df = pd.read_sql_query(query, conn)
    conn.close()

    n = len(df)
    print(f"✅ Loaded {n:,} ticks")
    if n == 0:
        print("ℹ️ No data found for the given filters. Nothing to write.")
        return

    # Parse timestamps: they look like '2024-03-14T19:59:58.123000Z'
    # Let pandas infer; ensure tz-aware UTC
    df["ts"] = parse_iso8601_utc(df["ts"])

    # Set index for resampling
    df = df.set_index("ts")

    # Optional extra scaling (usually unnecessary)
    if args.price_divisor and args.price_divisor != 1.0:
        df["price"] = df["price"] / float(args.price_divisor)

    # Resample to OHLC
    tf = args.timeframe  # e.g., '30min'
    print(f"🔄 Resampling to {tf} OHLC ...")
    ohlc = df["price"].resample(tf).ohlc().dropna()
    if ohlc.empty:
        print("ℹ️ Resampled frame is empty. Nothing to write.")
        return

    ohlc = ohlc.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"}).reset_index()
    ohlc = ohlc.rename(columns={"ts": "Datetime"})

    # Preview first row safely
    first_close = float(ohlc["Close"].iloc[0])
    print(f"✅ Created {len(ohlc):,} bars  | sample Close={first_close:.2f}")

    # Split by year-month (UTC)
    ohlc["YearMonth"] = ohlc["Datetime"].dt.to_period("M")
    months = ohlc["YearMonth"].unique()
    print(f"📁 Writing {len(months)} monthly files to {outdir}/")

    base = args.symbol.lower()
    for ym in months:
        month_df = ohlc[ohlc["YearMonth"] == ym].drop(columns=["YearMonth"]).copy()
        fname = f"{base}_{ym}.csv"  # e.g., usa500idxusd_2024-03.csv
        month_df.to_csv(outdir / fname, index=False)
        print(f"  ✓ {fname}: {len(month_df)} bars")

    print("🎉 Done.")


if __name__ == "__main__":
    main()

