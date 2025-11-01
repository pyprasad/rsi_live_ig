# Year-by-Year Strategy Validator

## Purpose

After running the advanced optimizer, you have 14,400 strategy results tested on 2012-2024 data **as one block**. But this doesn't tell you if a strategy is:
- ✅ Consistently profitable across years
- ❌ Only profitable in 1-2 lucky years

This validator solves that by testing top strategies on **each year individually** (2012, 2013, 2014, ..., 2024).

---

## What It Does

```
Input:  dax_advanced_results.csv (14,400 strategies)
        ↓
Step 1: Select top 15 diverse strategies
        (5 long_only + 5 short_only + 5 both)
        ↓
Step 2: Test each strategy on 2012 data only
        Test each strategy on 2013 data only
        ...
        Test each strategy on 2024 data only
        ↓
Output: yearly_breakdown.csv (year-by-year results)
        yearly_summary.txt (consistency report)
```

---

## Quick Start

### 1. Prerequisites

You must have already run the advanced optimizer:
```bash
python scripts/optimize_dax_advanced.py
```

This creates: `results/dax_advanced/dax_advanced_results.csv`

### 2. Run Validator

**Local (foreground):**
```bash
source .venv/bin/activate
python scripts/validate_strategies_yearly.py
```

**Server with screen:**
```bash
screen -S validator
source .venv/bin/activate
python scripts/validate_strategies_yearly.py

# Detach: Ctrl+A then D
# Reattach: screen -r validator
```

**Expected Runtime:** ~3-5 minutes (much faster than full optimizer)

### 3. Check Results

```bash
# Read summary
cat results/yearly_validation/yearly_summary.txt

# View year-by-year breakdown
head -20 results/yearly_validation/yearly_breakdown.csv
```

---

## Output Files

### 1. `yearly_breakdown.csv`

Detailed year-by-year results for each strategy.

**Columns:**
| Column | Description |
|--------|-------------|
| strategy_name | Config name (e.g., RSI4_L5_S90_TP20_SL5_long_only) |
| filter_scenario | "no_filters" or "with_filters" |
| trade_mode | "long_only", "short_only", or "both" |
| year | 2012, 2013, ..., 2024 |
| trades | Number of trades in that year |
| wins | Winning trades |
| losses | Losing trades |
| win_rate_pct | Win rate % for that year |
| pnl_pts | Profit/Loss for that year |
| profit_factor | PF for that year |
| max_drawdown_pts | Max drawdown in that year |
| cumulative_pnl | Running total P&L up to that year |
| is_profitable_year | 1 if year was profitable, 0 otherwise |
| has_min_trades | 1 if >= 5 trades, 0 otherwise |

**Example:**
```csv
strategy_name,year,trades,wins,pnl_pts,profit_factor,cumulative_pnl,is_profitable_year
RSI4_L5_S90_TP20_SL5_long_only,2012,23,14,45.2,1.15,45.2,1
RSI4_L5_S90_TP20_SL5_long_only,2013,18,8,-30.1,0.88,15.1,0
RSI4_L5_S90_TP20_SL5_long_only,2014,21,14,60.5,1.32,75.6,1
...
```

---

### 2. `yearly_summary.txt`

High-level consistency report.

**Example:**
```
================================================================================
YEAR-BY-YEAR VALIDATION SUMMARY
================================================================================

Strategies tested: 15
Years analyzed: 13 (2012-2024)
Minimum trades per year: 5

================================================================================
TOP STRATEGIES BY CONSISTENCY
================================================================================

RSI4_L5_S90_TP20_SL5_long_only (with_filters)
  Mode: long_only
  Total P&L: +172.87 pts
  Profitable Years: 9/13 (69.2%)
  Best Year: +60.5 pts
  Worst Year: -30.1 pts
  Avg per Year: +13.3 pts

RSI3_L10_S85_TP15_SL4_short_only (no_filters)
  Mode: short_only
  Total P&L: +85.4 pts
  Profitable Years: 7/13 (53.8%)
  Best Year: +45.0 pts
  Worst Year: -25.0 pts
  Avg per Year: +6.6 pts
```

---

## Selection Criteria

The validator selects top 15 strategies based on:

1. **Total P&L > 0** (must be profitable overall)
2. **Trades >= 100** (enough data across 13 years)
3. **Profit Factor >= 1.05** (at least 5% edge)
4. **Diversity**: 5 long_only + 5 short_only + 5 both mode

If no strategies meet criteria, it lowers to:
- Trades >= 50
- Any positive P&L

---

## How to Interpret Results

### ✅ Good Signs (Strategy is Robust)

- **Consistency >= 60%** (profitable in 8+ out of 13 years)
- **Recent years profitable** (2022-2024 still making money)
- **Avg per year > 0** (not just 1-2 lucky years)
- **Worst year < -50 pts** (manageable drawdown)

**Example:**
```
Profitable Years: 9/13 (69.2%)
Best Year: +60 pts
Worst Year: -30 pts
Avg per Year: +13 pts

→ This is GOOD! Strategy is consistently profitable.
```

---

### ⚠️ Warning Signs (Strategy May Not Be Robust)

- **Consistency < 50%** (profitable in only 5-6 out of 13 years)
- **Recent years negative** (2022-2024 losing money)
- **1-2 huge years** (e.g., +200 in 2015, but -20 every other year)
- **Worst year huge** (e.g., -200 pts in one year)

**Example:**
```
Profitable Years: 4/13 (30.8%)
Best Year: +150 pts (2015)
Worst Year: -180 pts (2020)
Avg per Year: +5 pts

→ This is BAD! Strategy got lucky in 1-2 years, loses most years.
```

---

## Decision Tree

```
Run validator
     ↓
Check consistency
     ↓
┌────────────────────────────────────────┐
│  Best strategy: Consistency >= 60%?    │
└────────────────────────────────────────┘
         ↓                          ↓
       YES                         NO
         ↓                          ↓
   ┌─────────────┐          ┌─────────────┐
   │ Recent      │          │ All         │
   │ years       │          │ strategies  │
   │ profitable? │          │ < 60%?      │
   └─────────────┘          └─────────────┘
         ↓                          ↓
       YES                         YES
         ↓                          ↓
   Test on DEMO          Strategy NOT robust
   for 3 months          Try different approach:
   with small size       - Change parameters
                        - Different strategy type
                        - Different timeframe
```

---

## Analysis Commands

### Filter by Consistency

```bash
# Show only strategies with 60%+ consistency
awk -F',' 'NR==1 || $7 >= 60' results/yearly_validation/yearly_breakdown.csv

# Show strategies with 8+ profitable years
awk -F',' '{
    if (NR==1) print;
    else if ($13==1) count[$1]++;
} END {
    for (s in count) {
        if (count[s] >= 8) print s, count[s]
    }
}' results/yearly_validation/yearly_breakdown.csv
```

### View Specific Strategy

```bash
# See year-by-year for specific strategy
grep "RSI4_L5_S90_TP20_SL5_long_only" results/yearly_validation/yearly_breakdown.csv

# See only recent years (2020-2024)
grep "RSI4_L5_S90_TP20_SL5_long_only" results/yearly_validation/yearly_breakdown.csv | \
awk -F',' '$4 >= 2020'
```

### Compare Modes

```bash
# LONG-only strategies
awk -F',' '$3=="long_only"' results/yearly_validation/yearly_breakdown.csv | \
head -50

# SHORT-only strategies
awk -F',' '$3=="short_only"' results/yearly_validation/yearly_breakdown.csv | \
head -50

# BOTH mode strategies
awk -F',' '$3=="both"' results/yearly_validation/yearly_breakdown.csv | \
head -50
```

### Calculate Statistics

```bash
# Average P&L per year for a strategy
grep "RSI4_L5_S90_TP20_SL5_long_only" results/yearly_validation/yearly_breakdown.csv | \
awk -F',' '{sum+=$9; count++} END {print "Avg per year:", sum/count, "pts"}'

# Count profitable vs losing years
grep "RSI4_L5_S90_TP20_SL5_long_only" results/yearly_validation/yearly_breakdown.csv | \
awk -F',' '$13==1 {profit++} $13==0 {loss++} END {
    print "Profitable years:", profit
    print "Losing years:", loss
    print "Consistency:", (profit/(profit+loss)*100) "%"
}'
```

---

## Expected Output Example

```
================================================================================
YEAR-BY-YEAR STRATEGY VALIDATOR
================================================================================

📂 Loading optimizer results from results/dax_advanced/dax_advanced_results.csv...
✅ Loaded 14,400 strategy results

🔍 Selecting top 15 diverse strategies...
✅ Selected 15 strategies:
   RSI4_L5_S90_TP20_SL5_long_only                 | long_only  | P&L:  +172.87 | Trades: 189 | Filters: with_filters
   RSI4_L5_S85_TP20_SL5_long_only                 | long_only  | P&L:  +172.87 | Trades: 189 | Filters: with_filters
   RSI3_L10_S90_TP15_SL3_short_only               | short_only | P&L:   +85.40 | Trades: 456 | Filters: no_filters
   ...

📂 Loading monthly data from data/dax_monthly...
✅ Loaded 40,234 bars

📅 Testing on years: [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]

🚀 Starting year-by-year validation...

[1/15] Testing: RSI4_L5_S90_TP20_SL5_long_only (with_filters)
   Total: +172.87 pts | Profitable years: 9/13 (69.2%)

[2/15] Testing: RSI4_L5_S85_TP20_SL5_long_only (with_filters)
   Total: +172.87 pts | Profitable years: 9/13 (69.2%)

...

✅ Detailed results saved to: results/yearly_validation/yearly_breakdown.csv
✅ Summary saved to: results/yearly_validation/yearly_summary.txt

================================================================================
TOP 5 MOST CONSISTENT STRATEGIES
================================================================================

1. RSI4_L5_S90_TP20_SL5_long_only (with_filters)
   Mode: long_only
   Total P&L: +172.87 pts
   Profitable Years: 9/13 (69.2%)
   Avg per Year: +13.3 pts

2. RSI4_L5_S85_TP20_SL5_long_only (with_filters)
   Mode: long_only
   Total P&L: +172.87 pts
   Profitable Years: 9/13 (69.2%)
   Avg per Year: +13.3 pts
```

---

## Troubleshooting

### No strategies meet criteria

If you see:
```
⚠️  No strategies meet the criteria (profitable, 100+ trades, PF > 1.05)
   Lowering criteria to find ANY profitable strategies...
```

**This means**: Very few strategies were profitable in the original optimizer run.

**Action**:
1. Let validator continue with lower criteria
2. Check if ANY strategy has 60%+ consistency
3. If not, consider changing optimizer parameters

---

### Script errors

```bash
# Check Python syntax
source .venv/bin/activate
python3 -m py_compile scripts/validate_strategies_yearly.py

# Test on small dataset
# Edit script: Change TOP_N_STRATEGIES = 3 (line 30)
python scripts/validate_strategies_yearly.py
```

---

### Memory issues

If script crashes due to memory:
```python
# Edit line 30 in validate_strategies_yearly.py:
TOP_N_STRATEGIES = 5  # Reduce from 15 to 5
```

---

## Configuration Options

Edit `scripts/validate_strategies_yearly.py`:

```python
# Line 30: Number of strategies to test
TOP_N_STRATEGIES = 15  # Change to 5, 10, 20, etc.

# Line 31: Minimum trades to consider
MIN_TRADES_OVERALL = 100  # Change to 50, 150, etc.

# Line 32: Minimum profit factor
MIN_PROFIT_FACTOR = 1.05  # Change to 1.0, 1.1, etc.

# Line 33: Minimum trades per year to be valid
MIN_TRADES_PER_YEAR = 5  # Change to 3, 10, etc.
```

---

## Next Steps Based on Results

### Scenario A: Found Consistent Winner (60%+ years profitable)

```bash
# 1. Review winning strategy details
grep "RSI4_L5_S90_TP20_SL5_long_only" results/yearly_validation/yearly_breakdown.csv

# 2. Check recent years (2022-2024)
grep "RSI4_L5_S90_TP20_SL5_long_only" results/yearly_validation/yearly_breakdown.csv | \
awk -F',' '$4 >= 2022'

# 3. If recent years still profitable: Test on DEMO
#    Use configs/live_config_dax_final.yaml
#    Update with winning parameters
```

**Action**: Paper trade on DEMO for 3 months

---

### Scenario B: No Consistent Winners (All < 60%)

**This means**: The strategy approach might not work well on DAX.

**Options**:
1. **Try different optimizer parameters**:
   - Longer TP (30, 40, 50 points)
   - Different RSI thresholds
   - Different timeframe (15min, 1hour)

2. **Try different strategy type**:
   - Trend following instead of mean reversion
   - Breakout strategies
   - Moving average crossovers

3. **Try different market**:
   - You tested FTSE (had better SHORT results)
   - Test S&P 500, Nasdaq, Gold, etc.

---

### Scenario C: LONG-only vs SHORT-only vs BOTH

```bash
# Compare consistency across modes
awk -F',' 'NR>1 {mode[$3]++; if($13==1) profit[$3]++}
END {
    for (m in mode) {
        print m": "profit[m]"/"mode[m]" years profitable ("(profit[m]/mode[m]*100)"%)";
    }
}' results/yearly_validation/yearly_breakdown.csv
```

**If LONG-only is consistently better**: Use long_only mode
**If SHORT-only is better**: Use short_only mode
**If similar**: Use both mode for diversification

---

## Files Created

```
scripts/validate_strategies_yearly.py    # Main validator script
results/yearly_validation/
  ├── yearly_breakdown.csv               # Detailed year-by-year results
  └── yearly_summary.txt                 # High-level consistency report
```

---

## Summary

**Before Validator:**
- "Strategy made +172 pts over 12 years"
- Don't know if consistent or lucky

**After Validator:**
- "Strategy profitable in 9/13 years (69%)"
- "Recent 3 years: +35 pts total"
- "Worst year: -30 pts (manageable)"

→ Now you can make informed decision about DEMO testing!

---

**Last Updated**: 2025-10-29
**Script Version**: 1.0
**Status**: ✅ Ready to run

**Run Command**:
```bash
source .venv/bin/activate
python scripts/validate_strategies_yearly.py
```
