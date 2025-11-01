# RSI(2) Cross-Up → IG Live Trading (FTSE/S&P)

This repo turns your **exact** strategy into live trading on IG with Lightstreamer:
- **Entry:** RSI(2) crosses **up** through 10 (prev ≤10, current >10)
- **SL:** Lowest of last 2 lows
- **TP (fixed-R):** entry + (entry - SL) × **1.5**
- **One open trade at a time**
- **MongoDB Integration:** Stores all signals and trades for analysis
- Backtest grid runs fixed R:R in {1.0, 1.5, 2.0, 3.0} and Gap×N in {3,4,5,6}

## Setup

### 1. Install Python Dependencies
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
```bash
cp .env.example .env  # Edit .env with your credentials
```

Your `.env` file should contain:
```bash
# IG Markets Credentials
IG_API_KEY="your_ig_api_key"
IG_USERNAME="your_username"
IG_PASSWORD="your_password"
IG_ACCOUNT_TYPE="DEMO"   # DEMO or LIVE

# MongoDB Configuration (optional)
MONGO_URI="mongodb://127.0.0.1:27017/"
```

### 3. Setup MongoDB (Optional but Recommended)

MongoDB stores all trading signals and execution details for analysis.

**Option A: Local MongoDB**
```bash
# macOS
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community

# Ubuntu/Debian
sudo apt-get install mongodb
sudo systemctl start mongodb

# Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

**Option B: MongoDB Atlas (Cloud)**
- Sign up at https://www.mongodb.com/cloud/atlas/register
- Create a free cluster
- Get connection string and add to `.env`:
  ```bash
  MONGO_URI="mongodb+srv://username:password@cluster.mongodb.net/"
  ```

**Option C: Skip MongoDB**
- Leave `MONGO_URI` unset in `.env`
- System will continue normally with CSV logging only

See [MONGODB_SETUP.md](MONGODB_SETUP.md) for detailed MongoDB setup and usage guide.

## Usage

### Live Trading
```bash
python -m src.live_runner
```

When MongoDB is configured, you'll see:
```
✅ MongoDB connected: rsi_live_trading
📡 Feeding IX.D.SPTRD.DAILY.IP (tf=300s)  dry_run=false
```

### Configuration
Edit `configs/live_config.yaml`:
```yaml
ig:
  epic: "IX.D.SPTRD.DAILY.IP"  # Change instrument
  size: 1.0                     # Contract size

strategy:
  mode: "fixed"                 # "fixed" or "gapN"
  rr: 1.5                       # Risk:Reward ratio
  timeframe_sec: 300            # 5 minutes

ops:
  dry_run: false                # Set true for testing without real trades
```

### Backtesting
```bash
python -m src.backtest_runner
```

Results saved to `results/` directory.

## MongoDB Data

### Collections Created
- `signals` - All trading signals (BUY, REJECTED)
- `trades` - All trade executions (DRY_OK, LIVE_OK, LIVE_FAIL)

### Query Examples
```python
from pymongo import MongoClient

client = MongoClient("mongodb://127.0.0.1:27017/")
db = client.rsi_live_trading

# View recent signals
for sig in db.signals.find().sort("timestamp", -1).limit(10):
    print(f"{sig['timestamp']}: {sig['epic']} RSI={sig['rsi']:.2f} -> {sig['signal_type']}")

# View successful live trades
for trade in db.trades.find({"dry_run": False, "status": "LIVE_OK"}):
    print(f"{trade['timestamp']}: {trade['epic']} @ {trade['entry_price']} [Ref: {trade['broker_ref']}]")

# Count signals by type
pipeline = [{"$group": {"_id": "$signal_type", "count": {"$sum": 1}}}]
for result in db.signals.aggregate(pipeline):
    print(f"{result['_id']}: {result['count']}")
```

## Project Structure
```
rsi-live-ig/
├── configs/
│   ├── live_config.yaml      # Live trading parameters
│   └── backtest_config.yaml  # Backtesting parameters
├── src/
│   ├── live_runner.py        # Main live trading orchestrator
│   ├── strategy_core.py      # RSI calculation & SL/TP logic
│   ├── ig_adapter.py         # IG Markets API wrapper
│   ├── mongo_logger.py       # MongoDB integration
│   ├── position_gate.py      # One-trade-at-a-time enforcer
│   └── data/
│       └── collector.py      # Lightstreamer/REST streaming
├── results/                  # Backtest outputs & trade logs
├── MONGODB_SETUP.md          # Detailed MongoDB guide
└── README.md                 # This file


Super Optimizezr for DAX  (RSI 2 , 95, 5)

python scripts/optimize_dax_super.py

