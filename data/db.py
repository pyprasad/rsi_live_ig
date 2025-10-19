from pathlib import Path
import csv

LOG_PATH = Path("logs/ticks.csv")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log_tick(market: str, bid: float, ofr: float, ts):
    exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["market", "timestamp_iso", "bid", "ofr"])
        w.writerow([market, ts.isoformat(), bid, ofr])
