# FTSE Strategy Optimization - RESULTS

## ✅ Optimization Complete - 2,304 Combinations Tested

**Data Period**: 4.73 years (2021-2025)
**Total Bars**: Analyzed across all FTSE monthly data
**Session**: 08:00-16:30 Europe/London

---

## 🏆 WINNER: SHORT ONLY Strategy

**Best Configuration**: `RSI4_L10_S90_RR3.0_SL2_short_only`

### Performance Summary

| Metric | Value |
|--------|-------|
| **Total Profit** | +4,294.58 points |
| **Annual Average** | +908.80 pts/year |
| **Win Rate** | 25.8% |
| **Total Trades** | 326 (69/year) |
| **Expectancy** | +13.17 pts/trade |
| **Profit Factor** | 1.13 |
| **Max Drawdown** | 5,248.95 pts |

### Strategy Parameters

```yaml
rsi_period: 4
long_threshold: 10  # Not used (SHORT only)
short_threshold: 90  # SHORT when RSI crosses BELOW 90
rr_ratio: 3.0
sl_lookback: 2
trade_mode: "short_only"
```

### Entry Rules
- **SHORT Signal**: RSI(4) crosses BELOW 90
- **Entry**: Close price
- **Stop Loss**: Highest high of last 2 bars
- **Take Profit**: Entry - (Risk × 3.0)

---

## 📊 All Modes Comparison

| Mode | Total P&L | Annual | Win Rate | Trades | Expect | PF |
|------|-----------|--------|----------|--------|--------|-----|
| **SHORT ONLY** ✅ | **+4,294.58 pts** | **+908.80/yr** | **25.8%** | **326** | **+13.17** | **1.13** |
| LONG ONLY | +1,077.99 pts | +228.12/yr | 19.8% | 742 | +1.45 | 1.01 |
| BOTH | +1,035.19 pts | +219.06/yr | 24.9% | 430 | +2.41 | 1.02 |

**Key Finding**: SHORT-only beats LONG+SHORT combined by 314%!

---

## 🔍 Alternative Configurations

### Top 5 SHORT ONLY Variants (All Profitable)

All these have IDENTICAL performance (+4,294.58 pts):

1. `RSI4_L10_S90_RR3.0_SL2_short_only` ← **Primary**
2. `RSI4_L15_S90_RR3.0_SL2_short_only`
3. `RSI4_L7_S90_RR3.0_SL2_short_only`
4. `RSI4_L5_S90_RR3.0_SL2_short_only`
5. `RSI4_L15_S90_RR3.0_SL3_short_only` (+4,160.14 pts)

**Robustness Note**: LONG threshold doesn't matter for SHORT-only (all L values give same result).

---

## 💡 Key Insights

### What Works on FTSE:
✅ **SHORT trades are superior** (4x more profitable than LONG)
✅ **RSI(4)** works better than RSI(2) or RSI(3)
✅ **RR=3.0** is optimal (not 5.0 like DAX!)
✅ **SL=2 bars** is best (tighter than DAX's 5 bars)
✅ **SHORT threshold 90** (same as DAX!)

### FTSE vs DAX Comparison:

| Parameter | DAX Winner | FTSE Winner | Same? |
|-----------|------------|-------------|-------|
| Trade Mode | **BOTH** (LONG+SHORT) | **SHORT ONLY** | ❌ Different |
| RSI Period | **2** | **4** | ❌ Different |
| SHORT Threshold | **90** | **90** | ✅ Same! |
| R:R Ratio | **5.0** | **3.0** | ❌ Different |
| SL Lookback | **5 bars** | **2 bars** | ❌ Different |

**Conclusion**: Each market has its own character. RSI mean-reversion works on both, but optimal parameters differ significantly.

---

## ⚠️ Important Findings

### 1. LONG Trades Underperform on FTSE
- LONG only: +1,078 pts
- SHORT only: +4,295 pts
- **SHORT is 4x more profitable**

### 2. Adding LONG Hurts Performance
- SHORT only: +4,295 pts
- BOTH (LONG+SHORT): +1,035 pts
- **Adding LONG trades reduces profit by 76%!**

### 3. Lower R:R Ratio
- DAX best at RR=5.0
- FTSE best at RR=3.0
- Suggests FTSE needs tighter targets

### 4. Tighter Stop Loss
- DAX best at SL=5 bars
- FTSE best at SL=2 bars
- FTSE is less volatile, needs tighter risk management

---

## 📈 Expected Performance (Based on Backtest)

**With £1/point**:
- Annual Profit: ~£909/year
- Per Trade: ~£13.17
- Max Risk: ~£5,249 drawdown
- Recommended Capital: ~£15,000+

**With £5/point**:
- Annual Profit: ~£4,544/year
- Per Trade: ~£65.85
- Max Risk: ~£26,245 drawdown
- Recommended Capital: ~£75,000+

---

## 🎯 Next Steps

### Before Live Trading:

1. ✅ **Validate year-by-year** (check each year is profitable)
2. ✅ **Test on out-of-sample data** (if you get 2016-2020)
3. ✅ **Create live config** for FTSE
4. ✅ **Run on DEMO** for 1-2 months minimum

### Potential Strategy:

**Option A: Run SHORT-only on FTSE**
- Most profitable single strategy
- 326 trades over 4.73 years = ~69/year
- +4,295 pts

**Option B: Run DAX (BOTH) + FTSE (SHORT)**
- DAX: LONG+SHORT (RSI2_L7_S90_RR5.0_SL5_both)
- FTSE: SHORT-only (RSI4_L10_S90_RR3.0_SL2_short_only)
- Portfolio diversification
- Different market characteristics

---

## 📁 Files & Results

**Results File**: `results/ftse_long_short/ftse_long_short_results.csv`
**Optimizer Script**: `scripts/optimize_ftse_long_short.py`
**Data Location**: `data/ftse_monthly/*.csv`

---

## Quick Start

### Step 1: Convert FTSE Database Files to CSV

```bash
python scripts/convert_ftse_to_csv.py
```

**What it does**:
- Reads: `ftse_2021.db`, `ftse_2022.db`, `ftse_2023.db`, `ftse_2024.db`, `ftse_2025.db`
- Converts to 30-minute OHLC bars
- Saves to: `data/ftse_monthly/*.csv`

**Expected output**:
```
📊 Converting FTSE tick data to monthly CSV files...
📥 Loading tick data from ftse_2021.db...
   ✓ Loaded XXX,XXX ticks from ftse_2021.db
...
✅ Total ticks loaded: XXX,XXX
🔄 Converting to 30T OHLC bars...
✅ Created XXX,XXX OHLC bars
   Sample price: 7,XXX.XX (should be ~7,000-8,500 for FTSE)
📁 Splitting into XX monthly files...
✅ Done! Files saved to data/ftse_monthly/
```

---

### Step 2: Run FTSE Optimization

```bash
python scripts/optimize_ftse_long_short.py
```

**What it tests**:
- RSI periods: 2, 3, 4
- LONG thresholds: 5, 7, 10, 15
- SHORT thresholds: 70, 80, 90, 95
- R:R ratios: 2.0, 3.0, 4.0, 5.0
- SL lookback: 2, 3, 4, 5 bars
- Trade modes: long_only, short_only, both

**Total combinations**: 2,304

**Session hours**: 08:00-16:30 Europe/London (FTSE closes earlier than DAX!)

**Results saved to**: `results/ftse_long_short/ftse_long_short_results.csv`

---

### Step 3: Analyze Results

```bash
# View top 10 performers
head -1 results/ftse_long_short/ftse_long_short_results.csv
grep "both" results/ftse_long_short/ftse_long_short_results.csv | sort -t',' -k7 -rn | head -10
```

**Look for**:
- ✅ High total P&L
- ✅ Profit factor > 1.0
- ✅ Win rate ~15-20% (acceptable with high R:R)
- ✅ Reasonable max drawdown

---

## Key Differences: FTSE vs DAX

| Aspect | DAX | FTSE |
|--------|-----|------|
| **Session** | 08:00-22:00 CET | 08:00-16:30 GMT/BST |
| **Timezone** | Europe/Berlin | Europe/London |
| **Price Level** | ~19,000 | ~8,000 |
| **Volatility** | Higher | Moderate |
| **IG Epic** | IX.D.DAX.DAILY.IP | IX.D.FTSE.DAILY.IP |

---

## What to Expect

### Scenario A: FTSE Works Well ✅
- Find a profitable configuration
- Validates RSI(2) approach
- Can run both DAX + FTSE strategies simultaneously
- Portfolio diversification

### Scenario B: FTSE Doesn't Work ⚠️
- No consistently profitable config
- Suggests DAX might be curve-fitted
- Or: FTSE market structure is different
- Useful information either way!

---

## Next Steps After Optimization

1. **Validate the winner**:
   - Check year-by-year consistency
   - Must be profitable in 80%+ of years

2. **Compare to DAX**:
   - Are parameters similar? (Good sign!)
   - Or completely different? (Each market has character)

3. **Test out-of-sample**:
   - If you get 2016-2020 FTSE data
   - Test winner config on that data

4. **Create FTSE live config**:
   - Copy `configs/live_config_final.yaml` → `configs/live_config_ftse.yaml`
   - Update parameters with FTSE winner
   - Set epic to `IX.D.FTSE.DAILY.IP`
   - Set session to 08:00-16:30 Europe/London

---

## Files Created

- `scripts/convert_ftse_to_csv.py` - Database to CSV converter
- `scripts/optimize_ftse_long_short.py` - FTSE optimizer (2,304 combinations)
- `data/ftse_monthly/` - Monthly CSV files (created after Step 1)
- `results/ftse_long_short/` - Optimization results (created after Step 2)

---

## Important Notes

- ✅ **Completely separate** from DAX setup
- ✅ **No impact** on existing DAX strategy
- ✅ **Same methodology** as DAX optimization
- ⚠️ **FTSE closes at 4:30pm** (vs DAX at 10pm)
- ⚠️ **Check price scaling** - FTSE might not need divisor adjustment

---

## 📋 Quick Summary Card

**Copy this for future reference:**

```
FTSE WINNER: SHORT ONLY
========================
Config: RSI4_L10_S90_RR3.0_SL2_short_only
Profit: +4,295 pts (4.73 years)
Annual: +909 pts/year
Trades: 69/year
Win Rate: 25.8%
Max DD: 5,249 pts

Entry: RSI(4) crosses BELOW 90
Exit: TP = Entry - (Risk × 3.0)
      SL = Highest of last 2 bars
Session: 08:00-16:30 GMT/BST
```

---

**Last Updated**: 2025-10-26
**Data Period**: 2021-2025 (4.73 years)
**Status**: ✅ Optimization Complete - Ready for validation testing
