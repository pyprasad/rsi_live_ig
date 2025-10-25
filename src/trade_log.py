from pathlib import Path
import csv
from datetime import datetime, timezone

LOG_PATH = Path("results/live_trades.csv")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

HEADERS = [
    "ts_utc", "epic", "mode", "rr_or_N", "side",
    "entry_px", "stop_distance", "limit_distance",
    "dry_run", "status", "reason", "broker_ref"
]

def log_trade_csv(*, epic, mode, rr_or_N, side, entry_px,
                  stop_distance, limit_distance,
                  dry_run, status, reason="", broker_ref=""):
    new_file = not LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADERS)
        w.writerow([
            datetime.now(timezone.utc).isoformat(),
            epic, mode, rr_or_N, side,
            f"{entry_px:.5f}", f"{stop_distance:.5f}", f"{limit_distance:.5f}",
            str(dry_run), status, reason, broker_ref
        ])
