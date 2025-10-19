# src/live_runner.py
import os, time, yaml, pandas as pd, threading
from queue import Queue, Empty
from dotenv import load_dotenv
from src.strategy_core import rsi_cross_up, compute_sl_tp_fixed_rr, compute_tp_gapN
from src.ig_adapter import IGBroker, IGAuth
from data.collector import start_streaming, stop_streaming

def price_to_dist(entry, sl, tp):
    return max(entry - sl, 0.1), max(tp - entry, 0.1)

def authenticate_for_stream(auth: IGAuth):
    import requests
    base = "https://demo-api.ig.com/gateway/deal" if auth.account_type.upper()=="DEMO" else "https://api.ig.com/gateway/deal"
    h = {"X-IG-API-KEY": auth.api_key, "Content-Type":"application/json", "Accept":"application/json"}
    r = requests.post(f"{base}/session", json={"identifier": auth.username, "password": auth.password}, headers=h); r.raise_for_status()
    CST, XST = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
    a = requests.get(f"{base}/accounts", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}); a.raise_for_status()
    accounts = a.json().get("accounts", [])
    account_id = next((x["accountId"] for x in accounts if x.get("preferred")), (accounts[0]["accountId"] if accounts else None))
    s = requests.get(f"{base}/session?fetchSessionTokens=true", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}); s.raise_for_status()
    ls_endpoint = s.json().get("lightstreamerEndpoint") or ("https://demo-apd.marketdatasystems.com" if auth.account_type.upper()=="DEMO" else "https://apd.marketdatasystems.com")
    return CST, XST, ls_endpoint, account_id

def main(cfg_path="configs/live_config.yaml"):
    load_dotenv()
    cfg = yaml.safe_load(open(cfg_path))

    auth = IGAuth(
        api_key=os.getenv("IG_API_KEY",""),
        username=os.getenv("IG_USERNAME",""),
        password=os.getenv("IG_PASSWORD",""),
        account_type=os.getenv("IG_ACCOUNT_TYPE", cfg["ig"]["account_type"])
    )
    broker = IGBroker(auth); broker.connect()

    epic = cfg["ig"]["epic"]; size = float(cfg["ig"]["size"])
    rr   = float(cfg["strategy"]["rr"])
    mode = cfg["strategy"]["mode"]
    lvl  = int(cfg["strategy"]["rsi_cross_up_level"])
    tf   = int(cfg["strategy"]["timeframe_sec"])
    dry  = bool(cfg["ops"]["dry_run"])
    guaranteed = bool(cfg["ig"]["guaranteed_stop"])

    # --- Dealing rules (min stop distance & step) ---
    md = broker.market_details(epic)
    rules = md.get("dealingRules", {})
    min_stop = float(rules.get("minStopOrLimitDistance", {}).get("value", 0.0))
    step_stop = float(rules.get("stopDistance", {}).get("step", 0.1)) if rules.get("stopDistance") else 0.1
    print(f"ℹ️ {epic} min_stop={min_stop} step={step_stop}")

    def clamp_distance(d):
        # obey min stop and step increment
        if d < min_stop: d = min_stop
        # round up to the next step increment
        if step_stop > 0:
            k = int((d + 1e-9) / step_stop)
            if abs(k * step_stop - d) > 1e-9:
                d = (k + 1) * step_stop
        return d

    # --- Bar queue so LS thread never blocks on network I/O ---
    bar_q: Queue = Queue(maxsize=200)
    bars = []

    def on_bar(bar):
        try:
            bar_q.put_nowait(bar)
        except:
            # drop oldest to keep up
            _ = bar_q.get_nowait()
            bar_q.put_nowait(bar)

    # --- Strategy worker thread ---
    def worker():
        nonlocal bars
        while True:
            try:
                bar = bar_q.get(timeout=1.0)
            except Empty:
                continue
            try:
                row = {"Datetime": pd.to_datetime(bar.ts_open, unit="s"),
                       "Open": bar.open, "High": bar.high, "Low": bar.low, "Close": bar.close}
                bars.append(row)

                # tiny console breadcrumb for each completed bar
                if len(bars) % 1 == 0:  # change to 5/10 if too chatty
                    print(f"🧱 BAR {row['Datetime']} O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f}")

                if len(bars) < 3:
                    continue  # need at least 3 bars for SL-from-last-2

                df = pd.DataFrame(bars).set_index("Datetime")

                # === EXACT ENTRY RULE ===
                cross = rsi_cross_up(df["Close"], level=lvl, period=2)
                if not bool(cross.iloc[-1]):
                    continue

                # one-open-trade gate (read once per bar)
                has_open = bool(broker.open_positions())
                if has_open:
                    print("⛔ Skip: existing open position")
                    continue

                idx = len(df) - 1
                pack = compute_sl_tp_fixed_rr(df, idx, rr) if mode == "fixed" else compute_tp_gapN(df, idx, float(cfg["strategy"].get("N", 3)))
                if not pack:
                    print("⚠️ Skip: non-positive risk / pack None")
                    continue

                stop_dist, limit_dist = price_to_dist(pack["entry"], pack["sl"], pack["tp"])
                stop_dist, limit_dist = clamp_distance(stop_dist), clamp_distance(limit_dist)

                if dry:
                    print(f"[DRY] LONG {epic} @{pack['entry']:.2f} SLd={stop_dist:.2f} LId={limit_dist:.2f}")
                else:
                    res = broker.place_otc_market(epic, size, "BUY", stop_dist, limit_dist, guaranteed)
                    print(res)
            except Exception as e:
                print(f"⚠️ Worker error: {e}")

    t = threading.Thread(target=worker, daemon=True); t.start()

    # --- Lightstreamer auth + streaming ---
    CST, XST, LS_ENDPOINT, ACCOUNT_ID = authenticate_for_stream(auth)
    client, sub = start_streaming(LS_ENDPOINT, ACCOUNT_ID, CST, XST, epic=epic, timeframe_sec=tf, on_bar=on_bar)
    print(f"📡 Streaming {epic} on {auth.account_type}… (timeframe={tf}s)  dry_run={dry}")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_streaming(client, sub)

if __name__ == "__main__":
    main()
