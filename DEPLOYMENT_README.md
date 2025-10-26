# Live Trading Deployment Guide - RSI2_L7_S90_RR5.0_SL5_both

## Quick Start - Deploy to IG DEMO

This guide will help you deploy the **final validated strategy** to your IG DEMO account in ~5 minutes.

---

## Prerequisites

Before starting, ensure you have:

1. **IG DEMO Account** - Create one at https://www.ig.com/uk/demo-trading-account
2. **IG API Key** - Request from IG (takes 1-2 business days)
3. **Python 3.9+** with virtual environment activated
4. **MongoDB** running locally (optional but recommended for audit logs)
5. **Completed backtests** - Verify strategy performance on your data

---

## Strategy Summary

**Configuration**: RSI2_L7_S90_RR5.0_SL5_both

- **LONG Entry**: RSI(2) crosses **above 7**
- **SHORT Entry**: RSI(2) crosses **below 90**
- **Stop Loss**: Lowest/highest of **last 5 bars**
- **Take Profit**: Entry ± (Risk × **5.0**)
- **Timeframe**: 30-minute candles
- **Session**: 08:00-22:00 Europe/Berlin timezone
- **Position Rule**: ONE trade at a time (LONG or SHORT, never both)

**Backtest Performance (5 years: 2015, 2021-2024)**:
- Total PnL: +8,530 points
- Annual Average: +1,706 points/year
- Win Rate: 18.6%
- Profit Factor: 1.16
- Max Drawdown: 2,498 points
- Consistency: **5/5 years profitable (100%)**

---

## Step 1: Environment Setup

### 1.1 Create `.env` File

Create a `.env` file in the project root with your IG credentials:

```bash
# .env
IG_API_KEY=your_api_key_here
IG_USERNAME=your_username_here
IG_PASSWORD=your_password_here
IG_ACCOUNT_TYPE=DEMO
IG_ACCOUNT_KIND=SPREADBET

# MongoDB (optional)
MONGO_URI=mongodb://localhost:27017/
```

**IMPORTANT**:
- Use `IG_ACCOUNT_TYPE=DEMO` for testing
- NEVER commit `.env` to git
- Add `.env` to `.gitignore`

### 1.2 Verify Configuration File

Check that `configs/live_config_final.yaml` exists and contains:

```yaml
ig:
  account_type: "${IG_ACCOUNT_TYPE}"
  epic: "IX.D.DAX.DAILY.IP"
  size: 1.0
  guaranteed_stop: false

strategy:
  rsi_period: 2
  rsi_cross_up_level: 7
  rsi_cross_down_level: 90
  rr: 5.0
  sl_method: "bars_lookback"
  sl_lookback: 5
  trade_mode: "both"
  timeframe_sec: 1800

session:
  use_session_filter: true
  start: "08:00"
  end: "22:00"
  tz: "Europe/Berlin"

ops:
  dry_run: false
  log_level: "INFO"
```

---

## Step 2: Pre-Flight Checks

### 2.1 Test Connection to IG

```bash
# Activate virtual environment
source .venv/bin/activate

# Test connection
python src/print_accounts.py
```

**Expected Output**:
```
✅ Connected to IG DEMO
Account ID: ABC123
Account Type: SPREADBET
Currency: GBP
Balance: £10,000.00
```

### 2.2 Verify Market Details

Check DAX market is available and tradeable:

```python
python -c "
from src.ig_adapter import IGBroker, IGAuth
from dotenv import load_dotenv
import os

load_dotenv()
auth = IGAuth(
    api_key=os.getenv('IG_API_KEY'),
    username=os.getenv('IG_USERNAME'),
    password=os.getenv('IG_PASSWORD'),
    account_type='DEMO'
)
broker = IGBroker(auth)
broker.connect()

md = broker.market_details('IX.D.DAX.DAILY.IP')
print(f\"✅ Epic: {md['instrument']['epic']}\")
print(f\"✅ Name: {md['instrument']['name']}\")
print(f\"✅ Status: {md['snapshot']['marketStatus']}\")
"
```

### 2.3 Run Smoke Test (Dry Run Mode)

Test the strategy in dry-run mode (no real trades):

```bash
# Edit configs/live_config_final.yaml temporarily:
# Set: dry_run: true

# Run for 5 minutes
python scripts/smoke_trade.py
```

**What to Check**:
- ✅ Connection to Lightstreamer succeeds
- ✅ Ticks are received and aggregated into 30-min bars
- ✅ RSI is calculated correctly
- ✅ Signals are detected (if market conditions trigger them)
- ✅ [DRY] log messages appear (no real trades)
- ✅ MongoDB logs signals and trades (if enabled)

---

## Step 3: Launch Live Trading on DEMO

### 3.1 Enable Live Mode

Edit `configs/live_config_final.yaml`:

```yaml
ops:
  dry_run: false  # ⚠️ Change from true to false
  log_level: "INFO"
```

### 3.2 Start the Live Runner

```bash
# Activate environment
source .venv/bin/activate

# Start live trading
python -m src.live_runner_long_short configs/live_config_final.yaml
```

### 3.3 Monitor Output

You should see:

```
ℹ️ IX.D.DAX.DAILY.IP min_stop=2.0 step=0.1
✅ Preflight OK
📡 Streaming IX.D.DAX.DAILY.IP (tf=1800s) dry_run=False mode=LIGHTSTREAMER trade_mode=BOTH
📊 Strategy: RSI(2) LONG>7 SHORT<90 RR=5.0 SL_lookback=5
🧱 BAR 2025-10-26 08:30:00 O:19850.2 H:19875.5 L:19840.1 C:19860.3
...
```

When a signal triggers:

```
✅ LONG order accepted. Ref=DEAL123456 Entry=19860.30 SL=19820.50 TP=20059.30
```

or

```
✅ SHORT order accepted. Ref=DEAL789012 Entry=19860.30 SL=19900.50 TP=19659.30
```

---

## Step 4: Monitor and Manage

### 4.1 Monitor Logs

Live logs are output to console and stored in MongoDB (if enabled).

**View MongoDB Signals**:
```bash
# Connect to MongoDB
mongosh

# View signals
use rsi_live_trading
db.signals.find().sort({timestamp: -1}).limit(10).pretty()
```

**View MongoDB Trades**:
```bash
db.trades.find().sort({timestamp: -1}).limit(10).pretty()
```

### 4.2 Check Open Positions

```bash
# In another terminal
python -c "
from src.ig_adapter import IGBroker, IGAuth
from dotenv import load_dotenv
import os

load_dotenv()
auth = IGAuth(
    api_key=os.getenv('IG_API_KEY'),
    username=os.getenv('IG_USERNAME'),
    password=os.getenv('IG_PASSWORD'),
    account_type='DEMO'
)
broker = IGBroker(auth)
broker.connect()

positions = broker.open_positions()
for p in positions:
    print(f\"{p['position']['direction']} {p['market']['epic']} Size={p['position']['size']} P&L={p['position']['profit']}\")
"
```

### 4.3 Stop the Strategy

Press `Ctrl+C` in the terminal running the live runner:

```
🛑 Shutting down...
✅ Shutdown complete
```

**IMPORTANT**: Stopping the script does NOT close open positions. You must close them manually via:
1. IG web platform
2. IG mobile app
3. REST API call to `/positions/{dealId}` (DELETE)

---

## Step 5: Review Performance

### 5.1 Check CSV Trade Log

All trades are logged to CSV:

```bash
cat logs/trades.csv
```

**Columns**:
- timestamp
- epic
- side (BUY/SELL)
- entry_px
- stop_distance
- limit_distance
- status (LIVE_OK, LIVE_FAIL, DRY_OK)
- broker_ref (IG deal reference)

### 5.2 MongoDB Analytics

Run queries to analyze performance:

```javascript
// Total trades by side
db.trades.aggregate([
  { $match: { status: "LIVE_OK" } },
  { $group: { _id: "$side", count: { $sum: 1 } } }
])

// Signals vs trades ratio
db.signals.countDocuments({ signal_type: { $in: ["LONG", "SHORT"] } })
db.trades.countDocuments({ status: "LIVE_OK" })

// Rejected signals breakdown
db.signals.aggregate([
  { $match: { signal_type: { $regex: "REJECTED" } } },
  { $group: { _id: "$reason", count: { $sum: 1 } } }
])
```

---

## Position Tracking (Crash Recovery)

The strategy includes **robust position tracking** to handle crashes and restarts:

### How It Works

**Three-Layer Safety System**:

1. **Lightstreamer Real-Time Updates** (Primary)
   - Subscribes to `ACCOUNT:{accountId}` stream
   - Receives instant notifications when positions open/close
   - Zero API calls - pure websocket updates
   - Fastest response time

2. **Fallback API Polling** (Safety Net)
   - Polls `/positions` endpoint every **5 minutes**
   - Detects if Lightstreamer missed any updates
   - Low API usage (12 calls/hour)
   - Automatically syncs state

3. **Staleness Detection** (Watchdog)
   - If no updates for 10 minutes, forces API check
   - Prevents being stuck in wrong state
   - Handles Lightstreamer silent failures

### Crash Recovery Scenario

**What happens if strategy crashes:**

1. Strategy crashes while position is open
2. Meanwhile, IG closes position (hits TP or SL)
3. You restart strategy
4. **Startup check** calls API → detects NO open positions
5. Strategy logs: `✅ STARTUP: No open positions. Ready to trade.`
6. Strategy correctly resumes trading

**What you'll see in logs:**
```
ℹ️ IX.D.DAX.DAILY.IP min_stop=2.0 step=0.1
✅ Preflight OK
🔄 PositionGate [startup]: State changed to CLOSED (0 positions)
✅ STARTUP: No open positions. Ready to trade.
✅ Lightstreamer position tracking enabled
📡 Streaming IX.D.DAX.DAILY.IP (tf=1800s) dry_run=False mode=LIGHTSTREAMER trade_mode=BOTH
```

### Position Events You'll See

**When position opens:**
```
📡 PositionGate [lightstreamer]: OPENED → OPEN (deal=DEAL123456)
```

**When position closes (TP/SL hit):**
```
📡 PositionGate [lightstreamer]: CLOSED → CLOSED (deal=DEAL123456)
```

**Fallback polling verification:**
```
🔄 PositionGate [fallback_poll]: State changed to CLOSED (0 positions)
```

**Staleness detection (if LS quiet for 10 min):**
```
⏰ PositionGate: No updates for 605s (stale threshold: 600s) - refreshing from API
🔄 PositionGate [staleness_check]: State changed to CLOSED (0 positions)
```

### Rate Limit Protection

**API Call Frequency**:
- Startup: 1 call
- Fallback polling: 12 calls/hour (every 5 minutes)
- Staleness check: Only if no LS updates for 10+ minutes

**Total**: ~13-15 calls/hour (well within IG limits)

---

## Troubleshooting

### Issue: "Preflight failed: Market closed"
**Solution**: DAX trades 08:00-22:00 CET. Check current time in Europe/Berlin timezone.

### Issue: "Connection refused to Lightstreamer"
**Solution**:
1. Check your IG credentials in `.env`
2. Verify API key is active
3. Ensure DEMO account is accessible
4. Try REST polling fallback (automatic if LS fails)

### Issue: "Stop distance too small"
**Solution**: IG has minimum stop distance (usually 2-5 points for DAX). Script automatically clamps to minimum.

### Issue: "Insufficient funds"
**Solution**: Reduce position size in `configs/live_config_final.yaml`:
```yaml
ig:
  size: 0.5  # Reduce from 1.0 to 0.5
```

### Issue: No signals generated
**Solution**:
1. Check market is open (08:00-22:00 CET)
2. RSI(2) crossing 7 or 90 is rare - wait for market conditions
3. Verify bars are being generated (check console output)
4. Confirm session filter is correct for your timezone

### Issue: Trades not appearing in MongoDB
**Solution**:
1. Verify MongoDB is running: `mongosh`
2. Check `MONGO_URI` in `.env`
3. Set `mongodb.enabled: true` in config
4. Check logs for MongoDB connection errors

### Issue: Strategy won't trade after restart (stuck thinking position is open)
**Solution**:
1. Check logs for startup state: Look for `🔄 PositionGate [startup]` message
2. Verify no positions on IG web platform
3. Wait 5 minutes for fallback poll to sync
4. If still stuck, restart strategy (startup check will refresh)
5. Check Lightstreamer connection: Look for `✅ Lightstreamer position tracking enabled`

### Issue: Position tracking shows wrong state
**Solution**:
1. Check for error messages: `⚠️ PositionGate API refresh failed`
2. Verify IG API credentials in `.env`
3. Check IG account status (not locked/suspended)
4. Fallback polling will auto-correct within 5 minutes
5. Restart strategy to force immediate API check

---

## Important Warnings

### ⚠️ Risk Warnings

1. **Past performance does not guarantee future results**
2. **Backtest includes NO slippage or commissions** - real trading will be slightly worse
3. **Win rate is LOW** (~18.6%) - expect long losing streaks
4. **Gap risk exists** - DAX can gap on opens (especially SHORT positions)
5. **Always test on DEMO first** - minimum 1-2 months before considering live
6. **Never risk more than 2% of capital per trade**

### 🚨 CRITICAL: Before Going LIVE

1. ✅ Run on DEMO for **1-2 months minimum**
2. ✅ Verify execution quality (slippage, fills)
3. ✅ Test during different market conditions
4. ✅ Start with **£0.50-£1.00 per point** only
5. ✅ Have **£8,000+ account** for £1/point (£80,000+ for £10/point)
6. ✅ Monitor daily and be prepared to stop if results diverge from backtest

### 📋 Going LIVE Checklist

Before changing `IG_ACCOUNT_TYPE=LIVE`:

- [ ] Tested on DEMO for 1-2 months
- [ ] Verified strategy follows signals correctly
- [ ] Confirmed slippage and commissions are acceptable
- [ ] Tested during volatile market conditions
- [ ] Have sufficient capital (min £8,000 for £1/point)
- [ ] Comfortable with 18.6% win rate and losing streaks
- [ ] Understand gap risk and max drawdown
- [ ] Have stop-loss plan if strategy underperforms
- [ ] Starting with £0.50-£1.00 per point maximum
- [ ] Willing to monitor daily for first month

---

## Files Reference

### Core Files
- **`src/live_runner_long_short.py`** - Live trading script (LONG+SHORT)
- **`configs/live_config_final.yaml`** - Final strategy configuration
- **`scripts/backtest_final_strategy.py`** - Backtest script for validation
- **`.env`** - Your IG credentials (DO NOT commit to git)

### Documentation
- **`FINAL_STRATEGY_README.md`** - Complete strategy documentation
- **`QUICK_START.md`** - Quick backtest guide
- **`DEPLOYMENT_README.md`** - This file

### Results
- **`results/final_strategy/`** - Final strategy backtest results
- **`results/dax_long_short/dax_long_short_results.csv`** - Full optimization results (2,304 configs)
- **`logs/trades.csv`** - Live trade log (CSV)

---

## Support

If you encounter issues:

1. Check logs in console output
2. Review MongoDB logs: `db.signals.find().sort({timestamp: -1}).limit(10)`
3. Verify configuration: `cat configs/live_config_final.yaml`
4. Test connection: `python src/print_accounts.py`
5. Run smoke test in dry-run mode
6. Review backtest results to confirm strategy validity

---

## Contact

For questions about this strategy or deployment:
- Review `FINAL_STRATEGY_README.md` for strategy details
- Check `QUICK_START.md` for backtest instructions
- Verify configuration matches final validated settings

---

**Last Updated**: 2025-10-26
**Strategy Version**: 1.0
**Validated Data**: 2015, 2021-2024 (5 years, 100% profitable)
**Configuration**: RSI2_L7_S90_RR5.0_SL5_both

---

**Good luck and trade safely! 🚀**
