# MongoDB Integration Setup

## Overview

The system now stores **signal details** and **trade details** in MongoDB for better analysis and tracking.

## Collections

The system creates two collections in the `rsi_live_trading` database:

### 1. `signals` Collection
Stores every trading signal (including rejected ones):
- `timestamp`: When the signal was generated (UTC)
- `epic`: Instrument EPIC code
- `signal_type`: "BUY", "SKIP", or "REJECTED"
- `bar_datetime`, `bar_open`, `bar_high`, `bar_low`, `bar_close`: OHLC bar data
- `rsi`: Current RSI value
- `entry_price`, `stop_loss`, `take_profit`: Calculated prices
- `reason`: Why signal was generated or rejected

### 2. `trades` Collection
Stores every trade attempt (dry and live):
- `timestamp`: When the trade was placed (UTC)
- `epic`: Instrument EPIC code
- `mode`: "fixed" or "gapN"
- `rr_or_N`: Risk:Reward ratio or N multiplier
- `side`: "BUY" or "SELL"
- `entry_price`, `stop_distance`, `limit_distance`: Order parameters
- `stop_loss_price`, `take_profit_price`: Actual price levels
- `dry_run`: Boolean (true for dry runs)
- `status`: "DRY_OK", "LIVE_OK", or "LIVE_FAIL"
- `broker_ref`: IG Markets deal reference (for live trades)
- `reason`: Error message if failed

## Installation

### Option 1: Local MongoDB (Recommended for Development)

1. **Install MongoDB:**
   ```bash
   # macOS
   brew tap mongodb/brew
   brew install mongodb-community

   # Ubuntu/Debian
   sudo apt-get install mongodb

   # Or use Docker
   docker run -d -p 27017:27017 --name mongodb mongo:latest
   ```

2. **Start MongoDB:**
   ```bash
   # macOS
   brew services start mongodb-community

   # Docker
   docker start mongodb
   ```

3. **Add to .env:**
   ```bash
   MONGO_URI=mongodb://localhost:27017/
   ```

### Option 2: MongoDB Atlas (Cloud - Recommended for Production)

1. **Create free cluster at:** https://www.mongodb.com/cloud/atlas/register

2. **Get connection string** from Atlas dashboard

3. **Add to .env:**
   ```bash
   MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/
   ```

### Option 3: Skip MongoDB (Optional)

If `MONGO_URI` is not set or MongoDB connection fails, the system will:
- Print a warning: `⚠️ MongoDB connection failed`
- Continue running normally
- Only log to CSV files (existing behavior)

## Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs `pymongo==4.6.1` which is now in requirements.txt.

## Usage

Once configured, MongoDB logging is automatic:

```bash
python -m src.live_runner
```

You'll see:
```
✅ MongoDB connected: rsi_live_trading
```

## Querying Your Data

### View Recent Signals:
```python
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client.rsi_live_trading

# Get last 10 signals
signals = db.signals.find().sort("timestamp", -1).limit(10)
for sig in signals:
    print(sig)
```

### View Recent Trades:
```python
# Get all live trades
trades = db.trades.find({"dry_run": False, "status": "LIVE_OK"})
for trade in trades:
    print(f"{trade['timestamp']}: {trade['epic']} @ {trade['entry_price']}")
```

### Count Signals by Type:
```python
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client.rsi_live_trading

pipeline = [
    {"$group": {"_id": "$signal_type", "count": {"$sum": 1}}}
]
results = db.signals.aggregate(pipeline)
for r in results:
    print(f"{r['_id']}: {r['count']}")
```

## Indexes (Optional - for Better Performance)

If you're storing lots of data, create indexes:

```python
from pymongo import MongoClient, ASCENDING, DESCENDING

client = MongoClient("mongodb://localhost:27017/")
db = client.rsi_live_trading

# Create indexes
db.signals.create_index([("timestamp", DESCENDING)])
db.signals.create_index([("epic", ASCENDING)])
db.trades.create_index([("timestamp", DESCENDING)])
db.trades.create_index([("broker_ref", ASCENDING)])
```

## Troubleshooting

### Connection Failed
```
⚠️ MongoDB connection failed: [Errno 61] Connection refused
```
**Solution:** Make sure MongoDB is running:
```bash
brew services start mongodb-community
# or
docker start mongodb
```

### Import Error
```
ModuleNotFoundError: No module named 'pymongo'
```
**Solution:** Install dependencies:
```bash
pip install -r requirements.txt
```

### Wrong Database Name
By default, the database is `rsi_live_trading`. To change it, edit `src/live_runner.py`:
```python
mongo = MongoLogger(database_name="your_custom_name")
```

## Benefits

- **Historical Analysis**: Query past signals and trades
- **Performance Metrics**: Calculate win rates, profit factors
- **Pattern Recognition**: Analyze what RSI levels work best
- **Real-time Dashboard**: Build charts using stored data
- **Backup**: Never lose trade history (CSV + MongoDB redundancy)
