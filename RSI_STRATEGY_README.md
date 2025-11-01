# RSI Strategy Testing

Simple system to fetch IG data and test RSI strategies with different Take Profit levels.

## Quick Start

### 1. Configure Settings

Edit `configs/rsi_test_config.yaml`:

```yaml
data:
  epic: "IX.D.DAX.DAILY.IP"      # Change to your epic
  timeframe: "5Min"               # 1Min, 5Min, 15Min, 30Min, 1Hour, 4Hour, Day
  max_candles: 10000              # Max candles to fetch

strategy:
  rsi_period: 14                  # RSI period
  buy_level: 30                   # Buy when RSI crosses above 30
  sell_level: 70                  # Sell when RSI crosses below 70

  take_profit_levels:             # TP levels to test
    - 5
    - 10
    - 15

  stop_loss: 20                   # Stop loss in points (or null to disable)
```

### 2. Fetch Data from IG

```bash
source .venv/bin/activate
python scripts/fetch_data_simple.py
```

This will:
- Connect to IG API
- Fetch historical candles
- Save to `data/fetched/EPIC_TIMEFRAME.csv`

Example output file: `data/fetched/IX_D_DAX_DAILY_IP_5Min.csv`

### 3. Test RSI Strategy

```bash
python scripts/test_rsi_strategy.py
```

This will:
- Load the fetched data
- Test RSI strategy with multiple TP levels (5, 10, 15 points)
- Show results comparison
- Save trades and summary to `results/rsi_tests/`

## Strategy Logic

**Entry Rules:**
- **LONG**: When RSI crosses **above 30** (was below, now above)
- **SHORT**: When RSI crosses **below 70** (was above, now below)

**Exit Rules:**
- **Take Profit**: Exit when price reaches TP level (5, 10, or 15 points)
- **Stop Loss**: Exit when price hits SL level (20 points, configurable)

**Position Management:**
- One trade at a time
- Exit previous trade before entering new one

## Output Files

After running the tests, you'll find:

```
results/rsi_tests/
├── trades_TP5.csv          # All trades for TP=5
├── trades_TP10.csv         # All trades for TP=10
├── trades_TP15.csv         # All trades for TP=15
└── summary.csv             # Comparison summary
```

### Summary Example

```
TP  Trades  Wins  Losses  Win_Rate  Total_PnL  Profit_Factor
 5     150    80      70     53.3%    +125.50           1.45
10     120    65      55     54.2%    +245.00           1.62
15      95    52      43     54.7%    +320.50           1.78
```

## Results Interpretation

**Key Metrics:**
- **Total Trades**: Number of trades executed
- **Win Rate**: Percentage of winning trades
- **Total P&L**: Total profit/loss in points
- **Profit Factor**: Gross profit / Gross loss (>1 = profitable)

**What to Look For:**
- ✅ Profit Factor > 1.5 = Good strategy
- ✅ Win Rate > 50% with positive P&L = Consistent
- ✅ Higher Total P&L = More profitable
- ❌ Profit Factor < 1.0 = Losing strategy

## Customization

### Test Different Epics

Edit `configs/rsi_test_config.yaml`:

```yaml
data:
  epic: "CS.D.GBPUSD.CFD.IP"     # GBP/USD
  timeframe: "15Min"
```

Then re-run both scripts.

### Test Different TP Levels

```yaml
strategy:
  take_profit_levels:
    - 10
    - 20
    - 30
    - 50
```

### Adjust RSI Parameters

```yaml
strategy:
  rsi_period: 14        # Standard RSI
  buy_level: 30         # Oversold level
  sell_level: 70        # Overbought level
```

Common variations:
- **Aggressive**: RSI(9), Buy=25, Sell=75
- **Conservative**: RSI(21), Buy=35, Sell=65

### Disable Stop Loss

```yaml
strategy:
  stop_loss: null       # No stop loss
```

## Troubleshooting

### "Data file not found"

Run the data fetcher first:
```bash
python scripts/fetch_data_simple.py
```

### "Failed to connect to IG"

Check your `.env` file has:
```
IG_USERNAME=your_username
IG_PASSWORD=your_password
IG_API_KEY=your_api_key
IG_ACCOUNT_TYPE=DEMO  # or LIVE
```

### "No trades generated"

- Check if your epic has price data in the timeframe
- Try different RSI levels (30/70 might not trigger on all instruments)
- Verify data file has enough candles (need > RSI period)

## Next Steps

1. **Backtest on historical data** - Fetch max candles and test
2. **Optimize parameters** - Try different RSI periods and levels
3. **Forward test on DEMO** - Test winning strategy live
4. **Add more filters** - Time filters, trend filters, etc.

## Files Created

```
configs/
└── rsi_test_config.yaml           # Configuration file

scripts/
├── fetch_data_simple.py           # Data fetcher
└── test_rsi_strategy.py           # Strategy tester

data/fetched/
└── EPIC_TIMEFRAME.csv             # Downloaded data

results/rsi_tests/
├── trades_TP5.csv                 # Trade logs
├── trades_TP10.csv
├── trades_TP15.csv
└── summary.csv                    # Results summary
```

## Tips

1. **Start with DEMO account** - Test with demo data first
2. **Use longer timeframes** - 5Min+ for cleaner signals
3. **Test multiple epics** - Different instruments behave differently
4. **Check data quality** - Ensure you have enough historical data
5. **Compare TP levels** - Higher TP = fewer trades but bigger wins

---

**Happy Testing! 🚀**
