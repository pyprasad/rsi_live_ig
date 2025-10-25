"""
MongoDB logger for signals and trades.
Simple and clean implementation.
"""
import os
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError


class MongoLogger:
    """Logs signals and trades to MongoDB."""

    def __init__(self, connection_string=None, database_name="rsi_live_trading"):
        """
        Initialize MongoDB connection.

        Args:
            connection_string: MongoDB URI (default: from MONGO_URI env var)
            database_name: Database name (default: rsi_live_trading)
        """
        self.connection_string = connection_string or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        self.database_name = database_name
        self.client = None
        self.db = None
        self.enabled = False

        self._connect()

    def _connect(self):
        """Establish MongoDB connection."""
        try:
            self.client = MongoClient(
                self.connection_string,
                serverSelectionTimeoutMS=5000,  # 5 second timeout
                connectTimeoutMS=5000
            )
            # Test connection
            self.client.admin.command('ping')
            self.db = self.client[self.database_name]
            self.enabled = True
            print(f"✅ MongoDB connected: {self.database_name}")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"⚠️ MongoDB connection failed: {e}")
            print("   Continuing without MongoDB logging...")
            self.enabled = False
        except Exception as e:
            print(f"⚠️ MongoDB error: {e}")
            self.enabled = False

    def log_signal(self, epic, signal_type, bar_data, rsi_value, entry_price, sl, tp, reason=""):
        """
        Log a trading signal.

        Args:
            epic: Instrument EPIC
            signal_type: "BUY" or "SKIP" or "REJECTED"
            bar_data: Dict with bar info (datetime, open, high, low, close)
            rsi_value: Current RSI value
            entry_price: Calculated entry price
            sl: Stop loss price
            tp: Take profit price
            reason: Why signal was generated or skipped
        """
        if not self.enabled:
            return

        try:
            signal_doc = {
                "timestamp": datetime.utcnow(),
                "epic": epic,
                "signal_type": signal_type,
                "bar_datetime": bar_data.get("datetime"),
                "bar_open": bar_data.get("open"),
                "bar_high": bar_data.get("high"),
                "bar_low": bar_data.get("low"),
                "bar_close": bar_data.get("close"),
                "rsi": rsi_value,
                "entry_price": entry_price,
                "stop_loss": sl,
                "take_profit": tp,
                "reason": reason
            }
            self.db.signals.insert_one(signal_doc)
        except Exception as e:
            print(f"⚠️ MongoDB signal logging error: {e}")

    def log_trade(self, epic, mode, rr_or_N, side, entry_px, stop_distance, limit_distance,
                  dry_run, status, reason="", broker_ref=""):
        """
        Log a trade execution.

        Args:
            epic: Instrument EPIC
            mode: "fixed" or "gapN"
            rr_or_N: Risk:Reward ratio or N multiplier
            side: "BUY" or "SELL"
            entry_px: Entry price
            stop_distance: Stop distance in points
            limit_distance: Limit distance in points
            dry_run: True if dry run, False if live
            status: "DRY_OK", "LIVE_OK", "LIVE_FAIL"
            reason: Additional reason/error message
            broker_ref: Broker deal reference ID
        """
        if not self.enabled:
            return

        try:
            trade_doc = {
                "timestamp": datetime.utcnow(),
                "epic": epic,
                "mode": mode,
                "rr_or_N": rr_or_N,
                "side": side,
                "entry_price": entry_px,
                "stop_distance": stop_distance,
                "limit_distance": limit_distance,
                "stop_loss_price": entry_px - stop_distance if side == "BUY" else entry_px + stop_distance,
                "take_profit_price": entry_px + limit_distance if side == "BUY" else entry_px - limit_distance,
                "dry_run": dry_run,
                "status": status,
                "reason": reason,
                "broker_ref": broker_ref
            }
            self.db.trades.insert_one(trade_doc)
        except Exception as e:
            print(f"⚠️ MongoDB trade logging error: {e}")

    def close(self):
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            print("MongoDB connection closed")
