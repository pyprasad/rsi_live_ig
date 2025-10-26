# Quick Start Guide - Final DAX Strategy

## TL;DR

**Best Strategy:** `RSI2_L7_S90_RR5.0_SL5_both`

**Performance:** +8,530 points over 5 years (+853 pts/year)

**Profitable:** 5 out of 5 years (100% consistency)

---

## Run Backtest in 30 Seconds

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Run backtest
python scripts/backtest_final_strategy.py

# Done! Results will show on screen.
```

---

## Test on Different Data

### Step 1: Prepare Data
Put your CSV files in a folder with this format:

```csv
Datetime,Open,High,Low,Close
2025-01-01 00:00:00,13850.5,13900.2,13840.1,13875.3
2025-01-01 00:30:00,13875.3,13920.5,13870.2,13910.1
...
```

**Requirements:**
- Datetime column (UTC timezone)
- OHLC columns
- 30-minute candles recommended

### Step 2: Edit Script
Open `scripts/backtest_final_strategy.py` and change line 27:

```python
DATA_DIR = Path("data/your_folder_name")  # Change this!
```

### Step 3: Run
```bash
python scripts/backtest_final_strategy.py
```

---

## The Strategy

### LONG Trades
```
WHEN: RSI(2) crosses above 7
ENTRY: Current close price
STOP: Lowest of last 5 bars
TARGET: Entry + (Risk × 5)
```

### SHORT Trades
```
WHEN: RSI(2) crosses below 90
ENTRY: Current close price
STOP: Highest of last 5 bars
TARGET: Entry - (Risk × 5)
```

### Rules
- ✅ Trade BOTH long and short
- ✅ ONE position at a time
- ✅ Only during 08:00-22:00 CET
- ✅ 30-minute timeframe

---

## Expected Results

With **£1 per point:**
- Profit: ~£853/year (~£71/month)
- Risk: £60-80 per trade
- Need: £8,000 account minimum

With **£10 per point:**
- Profit: ~£8,530/year (~£711/month)
- Risk: £600-800 per trade
- Need: £80,000 account minimum

---

## Files You Need

| File | Purpose |
|------|---------|
| `backtest_final_strategy.py` | Run backtests |
| `FINAL_STRATEGY_README.md` | Full documentation |
| `configs/live_config_dax_final.yaml` | Live trading config |

---

## Before Going Live

1. ✅ **Test on out-of-sample data** (2025, 2016-2020, etc.)
2. ✅ **Run on IG DEMO for 1-2 months**
3. ✅ **Verify execution quality** (slippage, fills)
4. ✅ **Start with £0.50-£1 per point**
5. ✅ **Never risk more than 2% per trade**

---

## Need Help?

- Full docs: `FINAL_STRATEGY_README.md`
- All results: `results/dax_long_short/dax_long_short_results.csv`
- Validate config: `python scripts/validate_single_config.py`

---

**Good luck! 🚀**
