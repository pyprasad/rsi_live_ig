# S&P 500 Live Trading Bot

Automated S&P 500 trading bot using RSI(2) reversal strategy with IG Markets integration.

## Features

- ✅ **30-minute candles** built from real-time Lightstreamer tick data
- ✅ **RSI(2) reversal strategy**: Buy when RSI ≤ 90, Sell when RSI ≥ 10
- ✅ **Market open delay**: No trading first 30 minutes after market open
- ✅ **One trade per direction**: Maximum 1 LONG and 1 SHORT position
- ✅ **Dynamic TP**: (last 2 candles difference) × 10
- ✅ **Configurable SL**: Day's low/high + 100 pips (adjustable)
- ✅ **News filter**: Scrapes Forex Factory calendar daily
  - Avoids trading 30 min before/after high-impact USD/EUR news
- ✅ **Database logging**: All signals and trades stored in SQLite + MongoDB
- ✅ **Live trade execution**: Fully integrated with IG Demo/Live accounts

## Files

```
├── configs/
│   └── sp500_live_config.yaml      # Configuration (strategy params, market hours, etc.)
├── src/
│   ├── sp500_live_runner.py        # Main bot runner (based on live_runner.py pattern)
│   └── sp500_strategy_core.py      # RSI(2) strategy logic
├── data/
│   └── sp500_trades.db             # SQLite database (signals, trades, news)
├── run_sp500.py                    # Entry point script
└── README_SP500.md                 # This file
```

## Requirements

### Python Packages

Install dependencies:

```bash
pip install -r requirements.txt
```

Or manually:

```bash
pip install pandas numpy requests PyYAML python-dotenv \
    lightstreamer-client-lib pymongo beautifulsoup4 lxml
```

### Environment Variables

Ensure `.env` file in project root contains:

```ini
IG_API_KEY=your_api_key_here
IG_USERNAME=your_username
IG_PASSWORD=your_password
IG_ACCOUNT_TYPE=DEMO    # or LIVE
```

## Configuration

Edit `configs/sp500_live_config.yaml`:

```yaml
ig:
  epic: "IX.D.SPTRD.DAILY.IP"    # S&P 500 Daily
  size: 1.0                       # Position size (£1 per point)
  guaranteed_stop: false

strategy:
  rsi_period: 2
  rsi_buy_level: 90               # Buy when RSI <= 90
  rsi_sell_level: 10              # Sell when RSI >= 10
  timeframe_sec: 1800             # 30 minutes

  tp_multiplier: 10.0             # TP = candle diff × 10
  sl_pips_from_day_low: 100.0    # SL = day low/high ± 100 pips

  market_open_delay_minutes: 30   # Don't trade first 30 mins
  news_buffer_minutes: 30         # Buffer around news events
  news_currencies: ["USD", "EUR"]

ops:
  dry_run: false                  # Set to true for testing (no real trades)
  db_path: "data/sp500_trades.db"
```

## Usage

### Running the Bot

**Option 1: Using virtual environment (recommended)**

```bash
.venv/bin/python run_sp500.py
```

**Option 2: Using system Python**

```bash
python3 run_sp500.py
```

### What Happens

1. **Startup**
   - Authenticates with IG Markets
   - Scrapes Forex Factory calendar for high-impact news (today + tomorrow)
   - Connects to Lightstreamer for real-time tick data
   - Starts strategy worker thread

2. **Live Trading**
   - Receives ticks from Lightstreamer
   - Builds 30-minute OHLC candles
   - Calculates RSI(2) on each completed candle
   - Checks for BUY/SELL signals
   - Filters out signals during:
     - First 30 mins after market open
     - ± 30 mins around high-impact news
   - Executes trades via IG API (if not dry_run)
   - Logs all signals and trades to database

3. **Logging**
   - Console: Real-time candles, signals, and trade execution
   - SQLite: `data/sp500_trades.db` (signals, trades, news_events tables)
   - MongoDB: All signals and trades (if configured)

### Expected Output

```
ℹ️  IX.D.SPTRD.DAILY.IP min_stop=0.0 step=0.1
[00:32:36] INFO: ✅ Preflight OK
[00:32:37] INFO: 📰 Scraped 3 high-impact events for 2025-11-03
[00:32:37] INFO: 📰 Scraped 3 high-impact events for 2025-11-04
✅ MongoDB connected: rsi_live_trading
[00:32:37] INFO: 🔐 Authenticating for Lightstreamer...
[00:32:37] INFO: ✅ Got credentials - Endpoint: https://demo-apd.marketdatasystems.com
[00:32:37] INFO: 📡 Starting Lightstreamer connection for IX.D.SPTRD.DAILY.IP...
[00:32:38] INFO: ✅ Connected! Mode: LIGHTSTREAMER, Timeframe: 1800s

================================================================================
📡 S&P 500 LIVE TRADER RUNNING
================================================================================
Epic: IX.D.SPTRD.DAILY.IP
Mode: LIGHTSTREAMER
Candles: 30 minutes
Dry Run: False
================================================================================

Waiting for ticks and candles...

🧱 BAR 2025-11-03 00:30:00 O:5920.50 H:5922.00 L:5919.00 C:5921.25

🚨 SIGNAL: BUY
   RSI: 88.45
   Entry: 5921.25
   SL: 5819.25 (dist=102.00)
   TP: 5941.25 (dist=20.00)
   ✅ LIVE order accepted. Ref=ABC123XYZ
```

## Database Schema

### SQLite Tables

**signals**
```sql
CREATE TABLE signals (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    signal_type TEXT,  -- 'BUY' or 'SELL'
    rsi_value REAL,
    entry_price REAL,
    tp_price REAL,
    sl_price REAL,
    executed BOOLEAN DEFAULT 0
);
```

**trades**
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    direction TEXT,  -- 'BUY' or 'SELL'
    entry_price REAL,
    tp_price REAL,
    sl_price REAL,
    size REAL,
    status TEXT,     -- 'OPEN', 'CLOSED', 'FILLED'
    broker_ref TEXT,
    exit_price REAL,
    pnl REAL
);
```

**news_events**
```sql
CREATE TABLE news_events (
    event_time TEXT,
    currency TEXT,
    title TEXT,
    impact TEXT,     -- 'HIGH', 'MEDIUM', 'LOW'
    scraped_at TEXT,
    PRIMARY KEY (event_time, currency, title)
);
```

## Strategy Details

### RSI(2) Reversal Logic

```python
# BUY Signal Conditions:
- RSI(2) <= 90 (oversold reversal)
- Past market open delay (30 mins)
- No high-impact news within 30 mins
- No existing open position

# SELL Signal Conditions:
- RSI(2) >= 10 (overbought reversal)
- Past market open delay (30 mins)
- No high-impact news within 30 mins
- No existing open position
```

### Take Profit Calculation

```python
TP = abs(close[n-1] - close[n-2]) * 10

Example:
- Candle -2 close: 5920.00
- Candle -1 close: 5922.00
- Difference: 2.00
- TP Distance: 2.00 * 10 = 20.00 points
```

### Stop Loss Calculation

```python
# For BUY orders:
SL = day's_low - (sl_pips / 10000)

# For SELL orders:
SL = day's_high + (sl_pips / 10000)

# Default sl_pips = 100
```

## Deployment (UK Server)

### Using systemd

1. Create service file `/etc/systemd/system/sp500-trader.service`:

```ini
[Unit]
Description=S&P 500 Live Trading Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/rsi-live-ig
ExecStart=/path/to/rsi-live-ig/.venv/bin/python run_sp500.py
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

2. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sp500-trader
sudo systemctl start sp500-trader
sudo systemctl status sp500-trader
```

3. View logs:

```bash
sudo journalctl -u sp500-trader -f
```

### Using screen (alternative)

```bash
screen -S sp500
cd /path/to/rsi-live-ig
.venv/bin/python run_sp500.py

# Detach: Ctrl+A, then D
# Reattach: screen -r sp500
```

## Monitoring

### Check if bot is running

```bash
ps aux | grep run_sp500.py
```

### View recent trades

```bash
sqlite3 data/sp500_trades.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"
```

### View recent signals

```bash
sqlite3 data/sp500_trades.db "SELECT * FROM signals ORDER BY timestamp DESC LIMIT 10;"
```

### View scraped news

```bash
sqlite3 data/sp500_trades.db "SELECT * FROM news_events WHERE impact='HIGH' ORDER BY event_time;"
```

## Troubleshooting

### Bot not receiving ticks

Check Lightstreamer connection mode:
- Look for `Mode: LIGHTSTREAMER` or `Mode: REST_POLL` in startup output
- REST_POLL is fallback when Lightstreamer library not available
- Ensure `lightstreamer-client-lib` is installed

### News scraper returning 0 events

Forex Factory may block scraping:
- Add delays between requests
- Use proxy/VPN if necessary
- Check URL format: `https://www.forexfactory.com/calendar?day=20251103`

### Trades not executing

1. Check `dry_run` setting in config (should be `false` for live trading)
2. Verify IG account has sufficient funds
3. Check preflight status on startup
4. Review `position_gate` logs (may be blocking due to existing positions)

## Safety Features

- ✅ **Position gate**: Prevents multiple trades in same direction
- ✅ **Preflight checks**: Validates trading conditions before bot starts
- ✅ **News filter**: Avoids trading during volatile news periods
- ✅ **Market hours**: Respects trading session hours
- ✅ **Stop losses**: All trades have SL protection
- ✅ **Dry run mode**: Test strategy without risking capital

## Support

For issues or questions:
- Check logs in `data/sp500_trades.db`
- Review MongoDB logs (if configured)
- Verify `.env` credentials are correct
- Ensure IG account type matches config (DEMO/LIVE)

---

**⚠️ Risk Warning**: Trading involves substantial risk of loss. This bot is provided as-is with no guarantees. Always test thoroughly in demo mode before live trading.
