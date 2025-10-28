# DAX Advanced Optimizer - Fixed TP + Session Filters

## What's New

This advanced optimizer tests **FIXED TAKE PROFIT** levels instead of Risk:Reward ratios, plus adds optional **session filters** to avoid volatile market open periods.

### Key Differences from Previous Optimizer

| Feature | Previous Optimizer | Advanced Optimizer |
|---------|-------------------|-------------------|
| **Take Profit** | R:R ratios (2.0, 3.0, 5.0) | **BOTH: Fixed points (5, 10, 15, 20, 25) + R:R (2.0, 3.0, 5.0)** |
| **Session Filters** | None | **Skip DAX open (08:00-08:30)** |
|  |  | **Skip US open (15:30-16:00 CET with DST)** |
| **Filter Testing** | N/A | **Tests WITH and WITHOUT filters** |
| **Saving Mode** | Batch at end | **Progressive (append each combo)** |
| **Multiprocessing** | Sequential (1 core) | **Parallel (uses all CPU cores - 1)** |
| **Total Combos** | 3,600 | **14,400 (7,200 × 2 scenarios)** |
| **Runtime** | N/A | **15-25 minutes** (vs 2 hours sequential) |

---

## Quick Start

### 1. Verify Data Exists

```bash
ls data/dax_monthly/
# Should show: dax_2015-*.csv files
```

If no data, convert first:
```bash
source .venv/bin/activate
python scripts/convert_dax_to_csv.py
```

### 2. Run Smoke Test (Optional)

```bash
source .venv/bin/activate
python scripts/smoke_test_advanced.py
```

Should show:
```
✅ ALL SMOKE TESTS PASSED
The advanced optimizer functions are working correctly!
```

### 3. Verify Multiprocessing (Optional)

Check how many CPU cores you have:

```bash
python3 -c "from multiprocessing import cpu_count; print(f'✅ Multiprocessing works! CPU cores: {cpu_count()}')"
```

### 4. Run Full Optimization

**Local (foreground):**
```bash
source .venv/bin/activate
python scripts/optimize_dax_advanced.py
```

**Server with Screen (recommended):**
```bash
# Start screen session
screen -S optimizer

# Inside screen: run optimizer
cd /path/to/rsi-live-ig
source .venv/bin/activate
python scripts/optimize_dax_advanced.py

# Detach from screen (keeps running)
# Press: Ctrl+A then D

# Later: Reattach to check progress
screen -r optimizer

# When done: exit screen
exit
```

**Server with nohup (alternative):**
```bash
source .venv/bin/activate
nohup python scripts/optimize_dax_advanced.py > optimizer.log 2>&1 &

# Monitor progress
tail -f optimizer.log

# Check if still running
ps aux | grep optimize_dax_advanced

# Kill if needed
pkill -f optimize_dax_advanced
```

**Expected Runtime**:
- **8 cores**: ~15-20 minutes
- **6 cores**: ~20-25 minutes
- **4 cores**: ~30-40 minutes
- **Sequential (1 core)**: ~2 hours

**Output:**
```
🔧 Using 7 worker processes (out of 8 CPU cores)
🚀 Processing 14,400 combinations in parallel...

[100/14,400] RSI2_L5_S70_TP5_SL2_long_only (no_filters)
            P&L: +123.45 pts | Trades: 234 | WR: 18.5% | PF: 1.15
            Progress: 0.7% | ETA: 18.2 mins
```

### 5. Results Saved To

```
results/dax_advanced/dax_advanced_results.csv
```

Results are appended **immediately after each combo** - so if the script crashes, you keep what's been processed!

---

## Multiprocessing Details

### How It Works

```
Main Process:
  ├─ Loads data once (30-40k bars)
  ├─ Creates 14,400 combo tasks
  ├─ Spawns N-1 worker processes (e.g., 7 workers on 8-core CPU)
  └─ Collects results and writes to CSV

Worker 1: Tests combos 1, 11, 21, 31... → returns results
Worker 2: Tests combos 2, 12, 22, 32... → returns results
Worker 3: Tests combos 3, 13, 23, 33... → returns results
...
Worker N: Tests combos N, N+10, N+20... → returns results

Main process writes all results → NO CONFLICTS!
```

### Safety Features

✅ **No race conditions** - Only main process writes to CSV
✅ **No data loss** - Results saved as they complete
✅ **No overwrites** - Each worker processes different combinations
✅ **Memory efficient** - Data loaded once, shared across workers
✅ **Clean exit** - Pool properly closed after completion

### Performance

| CPU Cores | Workers | Expected Runtime | Speedup |
|-----------|---------|------------------|---------|
| 12 cores  | 11      | ~12 minutes      | 10x     |
| 8 cores   | 7       | ~18 minutes      | 7x      |
| 6 cores   | 5       | ~24 minutes      | 5x      |
| 4 cores   | 3       | ~40 minutes      | 3x      |
| 1 core    | 0       | ~2 hours         | 1x      |

**Note**: Script automatically detects CPU cores and uses N-1 workers (leaves 1 core free for system)

### Troubleshooting

**If multiprocessing fails:**
```bash
# Check Python version (needs 3.7+)
python3 --version

# Test multiprocessing
python3 -c "from multiprocessing import Pool; print('✅ Works!')"
```

**If you want to disable multiprocessing:**
Edit line 623 in `scripts/optimize_dax_advanced.py`:
```python
# Change this:
n_workers = max(1, cpu_count() - 1)

# To this:
n_workers = 1  # Run sequentially
```

---

## Parameter Grid

### Fixed Parameters
```python
RSI_PERIODS = [2, 3, 4]
LONG_THRESHOLDS = [5, 7, 10, 12, 15]
SHORT_THRESHOLDS = [70, 80, 85, 90, 95]

# Take Profit - Tests BOTH approaches!
FIXED_TP_POINTS = [5, 10, 15, 20, 25]  # Fixed TP in points
RR_RATIOS = [2.0, 3.0, 5.0]             # Risk:Reward ratios

SL_LOOKBACK_PERIODS = [2, 3, 4, 5]
TRADE_MODES = ["long_only", "short_only", "both"]
```

### Session Filter Scenarios

**Scenario 1: `no_filters`**
- All trades allowed (08:00-22:00 CET as before)

**Scenario 2: `with_filters`**
- Skip DAX open: 08:00-08:30 (first 30 mins)
- Skip US open: 15:30-16:00 CET (with DST handling)

### Total Combinations

```
Base: 3 × 5 × 5 × (5 + 3) × 4 × 3 = 7,200
      RSI  L   S   TP+RR    SL  Mode

With filters: 7,200 × 2 scenarios = 14,400 tests
```

---

## Session Filters Explained

### Filter 1: Skip DAX Market Open
- **When**: 08:00-08:30 CET/CEST
- **Why**: First 30 minutes often volatile, wide spreads
- **How**: Simple time check against Europe/Berlin timezone

### Filter 2: Skip US Market Open
- **When**: 15:30-16:00 CET (winter) OR 14:30-15:00 CEST (summer)
- **Why**: US market open at 9:30 ET causes volatility spikes
- **How**: Converts 9:30 ET to Berlin time, handles DST automatically

**DST Handling**: Both US and Europe switch DST on different dates. The script:
1. Converts Berlin time → UTC → US Eastern
2. Checks if 9:30 ET falls within the bar
3. Converts back to Berlin time
4. Result: Works correctly across ALL date ranges in backtest data

---

## Results Analysis

### 1. View Top Performers

```bash
# View CSV header
head -1 results/dax_advanced/dax_advanced_results.csv

# Top 20 by total P&L
sort -t',' -k10 -rn results/dax_advanced/dax_advanced_results.csv | head -20
```

### 2. Filter by Criteria

```bash
# Profitable configs with PF > 1.1
awk -F',' '$24==1 && $25==1' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k10 -rn

# High win rate (> 20%)
awk -F',' '$28==1' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k10 -rn
```

### 3. Compare Filter Scenarios

```bash
# Best configs WITH filters
grep 'with_filters' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k14 -rn | head -10

# Best configs WITHOUT filters
grep 'no_filters' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k14 -rn | head -10
```

### 4. Compare Fixed TP vs R:R Ratios

```bash
# Best Fixed TP configs
grep 'TP[0-9]' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k14 -rn | head -10

# Best R:R ratio configs
grep 'RR[0-9]' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k14 -rn | head -10

# Your current live strategy (R:R=5.0)
grep 'RSI2_L7_S95_RR5.0_SL2_both' results/dax_advanced/dax_advanced_results.csv
```

### 5. Filter by Date Range

```bash
# Results from 2015 only
awk -F',' '$33==2015 && $34==2015' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k14 -rn | head -10

# Results spanning multiple years
awk -F',' '$33 != $34' results/dax_advanced/dax_advanced_results.csv

# Results from specific year
awk -F',' '$33==2021' results/dax_advanced/dax_advanced_results.csv | sort -t',' -k14 -rn
```

### 6. CSV Columns

| Column # | Field | Description |
|----------|-------|-------------|
| 1 | config_name | e.g., RSI2_L7_S90_TP15_SL5_both |
| 2 | rsi_period | 2, 3, or 4 |
| 3 | long_threshold | 5, 7, 10, 12, 15 |
| 4 | short_threshold | 70, 80, 85, 90, 95 |
| 5 | fixed_tp_points | 5, 10, 15, 20, 25 |
| 6 | sl_lookback | 2, 3, 4, 5 |
| 7 | trade_mode | long_only, short_only, both |
| 8 | skip_dax_open | True/False |
| 9 | skip_us_open | True/False |
| 10 | trades | Total trade count |
| 11 | wins | Winning trades |
| 12 | losses | Losing trades |
| 13 | win_rate_pct | Win rate % |
| 14 | **total_pnl_pts** | **Total P&L in points** |
| 15 | avg_win_pts | Average winning trade |
| 16 | avg_loss_pts | Average losing trade |
| 17 | expectancy_pts | Expected pts/trade |
| 18 | profit_factor | Total wins / Total losses |
| 19 | max_drawdown_pts | Maximum drawdown |
| 20 | long_trades | Number of LONG trades |
| 21 | short_trades | Number of SHORT trades |
| 22 | long_win_rate_pct | LONG win rate |
| 23 | short_win_rate_pct | SHORT win rate |
| 24 | avg_bars_held | Average bars per trade |
| 25 | total_win_pts | Total winning points |
| 26 | total_loss_pts | Total losing points |
| 27 | is_profitable | 1 if P&L > 0 |
| 28 | pf_above_1.1 | 1 if PF > 1.1 |
| 29 | pf_above_1.2 | 1 if PF > 1.2 |
| 30 | wr_above_15 | 1 if WR > 15% |
| 31 | wr_above_20 | 1 if WR > 20% |
| 32 | filter_scenario | "no_filters" or "with_filters" |
| 33 | year_start | Year of first trade (e.g., 2015) |
| 34 | year_end | Year of last trade (e.g., 2015) |
| 35 | month_start | Month of first trade (1-12) |
| 36 | month_end | Month of last trade (1-12) |

**Date columns for validation:**
- Use `year_start` and `year_end` to filter results by year
- Use `month_start` and `month_end` to see date range coverage
- Example: Filter results from 2015 only: `awk -F',' '$33==2015 && $34==2015'`

---

## What You're Looking For

### Good Signs ✅
- **Fixed TP = 15-20 points**: Sweet spot (not too tight, not too wide)
- **Profit Factor > 1.2**: Strong edge
- **Win Rate 15-20%**: Reasonable for this strategy type
- **Filters HELP**: `with_filters` > `no_filters` P&L
- **Consistent across modes**: Both LONG and SHORT profitable

### Red Flags ⚠️
- **Fixed TP = 5 points**: Likely too tight (spread kills edge)
- **Fixed TP = 25 points**: Might miss TP too often
- **Filters HURT**: `with_filters` < `no_filters` P&L
- **Very low trade count**: < 50 trades (not enough data)
- **One-sided**: Only LONG works, SHORT fails (or vice versa)

---

## Expected Outcomes

### Scenario A: Fixed TP Improves Results ✅
- Find TP=15 or TP=20 beats R:R=5.0
- Suggests market moves in fixed increments
- More predictable profit targets

### Scenario B: Filters Improve Results ✅
- `with_filters` outperforms `no_filters`
- Validates avoiding market open volatility
- Reduces whipsaw losses

### Scenario C: No Improvement ⚠️
- R:R approach was already optimal
- Market open periods not the problem
- Stick with original strategy

**Either way, you'll know!**

---

## Files Created

```
configs/optimizer_advanced.yaml          # Configuration file
scripts/optimize_dax_advanced.py         # Main optimizer script
scripts/smoke_test_advanced.py           # Test DST/filter logic
results/dax_advanced/                    # Output directory
  └── dax_advanced_results.csv          # Results (created on run)
```

---

## Comparison to Original Strategy

Your current live strategy:
```yaml
# configs/live_config_dax_final.yaml
RSI: 2
LONG threshold: 7
SHORT threshold: 95
R:R ratio: 5.0
SL lookback: 2
Mode: both
Session: 08:00-22:00 (no filters)
```

**To test this EXACT config with fixed TP**, look for:
```
RSI2_L7_S95_TP??_SL2_both (no_filters)
```

Then compare:
- `TP5` = very tight (5 points)
- `TP10` = tight (10 points)
- `TP15` = moderate (15 points)
- `TP20` = loose (20 points)
- `TP25` = very loose (25 points)

**Your R:R=5.0 with SL=2 bars** typically gives TP ~50-100 points (depends on volatility)

So if you want comparable TP distance, you'd look at **higher fixed TP values**.

---

## Running in Background

If you want to run overnight:

```bash
source .venv/bin/activate
nohup python scripts/optimize_dax_advanced.py > optimizer_advanced.log 2>&1 &
```

Monitor progress:
```bash
tail -f optimizer_advanced.log
```

Check how many combos done:
```bash
wc -l results/dax_advanced/dax_advanced_results.csv
# Should grow from 0 → 9,001 lines (9,000 + header)
```

---

## Next Steps After Completion

1. **Analyze results** (see commands above)
2. **Find best config** with fixed TP
3. **Compare to R:R approach**:
   - Does fixed TP beat R:R=5.0?
   - Do session filters help?
4. **Validate winner** on individual years (2015, 2021, 2022, etc.)
5. **Update live config** if new approach is superior
6. **Test on DEMO** for 1-2 months before going live

---

## Screen Command Reference

### Why Use Screen?

| Feature | nohup | screen |
|---------|-------|--------|
| **See live progress** | ❌ Need `tail -f log` | ✅ Just reattach |
| **Easy to stop** | ❌ Need PID + kill | ✅ Ctrl+C works |
| **Detach/Reattach** | ❌ One-way only | ✅ Anytime |
| **Lost SSH connection** | ✅ Keeps running | ✅ Keeps running |

### Basic Commands

```bash
# Create named session
screen -S optimizer

# Detach (leave running in background)
Ctrl+A then D

# List all sessions
screen -ls

# Reattach to session
screen -r optimizer

# Kill session (from outside)
screen -X -S optimizer quit

# Kill session (from inside)
exit
```

### Complete Server Workflow

```bash
# 1. SSH into server
ssh root@your-server

# 2. Start screen session
screen -S optimizer

# 3. Navigate and run
cd /path/to/rsi-live-ig
source .venv/bin/activate
python scripts/optimize_dax_advanced.py

# 4. See output starting...
🔧 Using 5 worker processes (out of 6 CPU cores)
🚀 Processing 14,400 combinations in parallel...

# 5. Detach (Ctrl+A then D)
[detached from 12345.optimizer]

# 6. Close SSH - optimizer keeps running!
exit

# 7. Later: SSH back and check progress
ssh root@your-server
screen -r optimizer

# 8. See current progress
[2,400/14,400] RSI3_L10_S85_TP20_SL4_both
            P&L: +234.56 pts | Trades: 456 | WR: 16.7% | PF: 1.23
            Progress: 16.7% | ETA: 18.5 mins

# 9. Detach again or wait for completion
Ctrl+A then D

# 10. When done, exit screen
exit
```

### Advanced Screen Commands

```bash
# Create new window inside screen
Ctrl+A then C

# Switch between windows
Ctrl+A then N  # Next window
Ctrl+A then P  # Previous window
Ctrl+A then 0  # Go to window 0
Ctrl+A then 1  # Go to window 1

# List windows
Ctrl+A then "

# Split screen horizontally
Ctrl+A then S

# Switch between splits
Ctrl+A then TAB

# Close current split
Ctrl+A then X

# Scroll back (view history)
Ctrl+A then [
# Use arrow keys to scroll
# Press ESC to exit scroll mode

# Rename session
Ctrl+A then :sessionname newname
```

### Troubleshooting Screen

```bash
# Screen session exists but can't attach?
screen -d -r optimizer  # Force detach and reattach

# Multiple screens with same name?
screen -ls  # Get full session ID
screen -r 12345.optimizer  # Use full ID

# Check if screen is installed
screen --version

# Install screen (if needed)
# Ubuntu/Debian:
sudo apt-get install screen

# CentOS/RHEL:
sudo yum install screen
```

---

## Troubleshooting

### Script Crashes
- Don't worry! Results saved progressively
- Check `results/dax_advanced/dax_advanced_results.csv`
- Count lines: `wc -l results/dax_advanced/dax_advanced_results.csv`
- Resume not needed - just rerun (will overwrite)

### Out of Memory
- Script loads all data at once (~40k bars)
- If crashes, close other programs
- Or test on subset: edit `DATA_DIR` to single month

### Wrong Results
- Run smoke test: `python scripts/smoke_test_advanced.py`
- Should show DST handling works correctly
- Should show session filters work correctly

---

## Technical Notes

### Why Fixed TP?
- R:R approach: TP = Entry ± (SL distance × ratio)
- Variable TP based on volatility (SL changes with market)
- Fixed TP: TP = Entry ± fixed points
- Consistent targets, easier to analyze
- May capture market microstructure better

### Why Skip Market Opens?
- DAX 08:00 open: Low liquidity, wide spreads, gap moves
- US 09:30 ET open: Macro news, volatility spikes, correlation changes
- Mean reversion works best in "normal" trading hours
- Avoiding opens might reduce false signals

### DST Complexity
- Europe switches DST: Last Sunday March/October
- US switches DST: 2nd Sunday March, 1st Sunday November
- Different dates! So 15:30 CET ≠ always 9:30 ET
- Script uses `pytz` to handle conversions properly
- Tested on 2015-2025 date range

---

**Last Updated**: 2025-10-27
**Script Version**: 1.0
**Status**: ✅ Ready to run

**Run Command**:
```bash
source .venv/bin/activate
python scripts/optimize_dax_advanced.py
```

Good luck! 🚀
