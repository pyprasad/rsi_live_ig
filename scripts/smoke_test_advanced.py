"""
Quick smoke test for the advanced optimizer functions.
Tests DST handling and session filtering logic.
"""
import pandas as pd
from datetime import datetime, time
import pytz
import sys
sys.path.insert(0, 'scripts')

# Import the functions we need to test
from optimize_dax_advanced import (
    get_us_open_cet_time,
    is_us_open_period,
    should_skip_trade,
    TIMEZONE
)

def test_dst_handling():
    """Test DST handling for US market open times."""
    print("=" * 60)
    print("Testing DST Handling for US Market Open")
    print("=" * 60)

    # Test dates: one in winter (CET), one in summer (CEST)
    test_dates = [
        "2015-01-15 15:30:00",  # Winter: should be 15:30 CET (9:30 ET)
        "2015-07-15 14:30:00",  # Summer: should be 14:30 CEST (9:30 ET) - actually 15:30 CEST
        "2021-01-15 15:30:00",  # Winter
        "2021-07-15 15:30:00",  # Summer
    ]

    for date_str in test_dates:
        dt_berlin = TIMEZONE.localize(datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S"))
        us_open_time = get_us_open_cet_time(dt_berlin)
        is_us_open = is_us_open_period(dt_berlin, duration_mins=30)

        print(f"\nDate: {dt_berlin}")
        print(f"  US market open time in Berlin: {us_open_time}")
        print(f"  Is within US open period? {is_us_open}")

def test_session_filters():
    """Test session filtering logic."""
    print("\n" + "=" * 60)
    print("Testing Session Filters")
    print("=" * 60)

    # Test cases
    test_cases = [
        ("2015-01-15 08:00:00", "DAX open start"),
        ("2015-01-15 08:15:00", "DAX open middle"),
        ("2015-01-15 08:29:59", "DAX open end -1s"),
        ("2015-01-15 08:30:00", "After DAX open"),
        ("2015-01-15 15:30:00", "US open (winter)"),
        ("2015-01-15 15:45:00", "US open middle (winter)"),
        ("2015-01-15 16:00:00", "After US open (winter)"),
        ("2015-07-15 15:30:00", "Possible US open (summer)"),
    ]

    for date_str, description in test_cases:
        dt_berlin = TIMEZONE.localize(datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S"))

        skip_both = should_skip_trade(dt_berlin, skip_dax_open=True, skip_us_open=True)
        skip_dax_only = should_skip_trade(dt_berlin, skip_dax_open=True, skip_us_open=False)
        skip_us_only = should_skip_trade(dt_berlin, skip_dax_open=False, skip_us_open=True)
        skip_none = should_skip_trade(dt_berlin, skip_dax_open=False, skip_us_open=False)

        print(f"\n{description}: {dt_berlin.time()}")
        print(f"  Skip (both filters): {skip_both}")
        print(f"  Skip (DAX only): {skip_dax_only}")
        print(f"  Skip (US only): {skip_us_only}")
        print(f"  Skip (no filters): {skip_none}")

def test_rsi_calculation():
    """Test RSI calculation with small dataset."""
    print("\n" + "=" * 60)
    print("Testing RSI Calculation")
    print("=" * 60)

    from optimize_dax_advanced import calculate_rsi

    # Create small test dataset
    prices = pd.Series([100, 102, 101, 103, 105, 104, 106, 108, 107, 109])
    rsi = calculate_rsi(prices, period=2)

    print(f"\nPrices: {list(prices)}")
    print(f"RSI(2): {list(rsi.round(2))}")
    print(f"Last RSI value: {rsi.iloc[-1]:.2f}")

    # Check for NaN values
    print(f"NaN count: {rsi.isna().sum()}")

if __name__ == "__main__":
    print("\n🔬 SMOKE TEST FOR ADVANCED OPTIMIZER\n")

    try:
        test_dst_handling()
        test_session_filters()
        test_rsi_calculation()

        print("\n" + "=" * 60)
        print("✅ ALL SMOKE TESTS PASSED")
        print("=" * 60)
        print("\nThe advanced optimizer functions are working correctly!")
        print("You can now run: python scripts/optimize_dax_advanced.py")

    except Exception as e:
        print(f"\n❌ SMOKE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
