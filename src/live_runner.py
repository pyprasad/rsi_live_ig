import os, time, yaml, pandas as pd, threading
from queue import Queue, Empty
from dotenv import load_dotenv

from .strategy_core import rsi_cross_up, compute_sl_tp_fixed_rr, compute_tp_gapN, rsi
from .ig_adapter import IGBroker, IGAuth
from .data.collector import start_streaming, stop_streaming
from .logging_setup import setup_logging
from .preflight import preflight_can_trade
from .position_gate import PositionGate
from .trade_log import log_trade_csv
from .mongo_logger import MongoLogger

logging = setup_logging()

def price_to_dist(entry, sl, tp):
    return max(entry - sl, 0.1), max(tp - entry, 0.1)

def authenticate_for_stream(auth: IGAuth):
    import requests
    base = "https://demo-api.ig.com/gateway/deal" if auth.account_type.upper()=="DEMO" else "https://api.ig.com/gateway/deal"
    h = {"X-IG-API-KEY": auth.api_key, "Content-Type":"application/json", "Accept":"application/json"}
    r = requests.post(f"{base}/session", json={"identifier": auth.username, "password": auth.password}, headers=h); r.raise_for_status()
    CST, XST = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
    s = requests.get(f"{base}/session?fetchSessionTokens=true", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}); s.raise_for_status()
    data = s.json()
    ls_endpoint = data.get("lightstreamerEndpoint") or ("https://demo-apd.marketdatasystems.com" if auth.account_type.upper()=="DEMO" else "https://apd.marketdatasystems.com")
    # account id (preferred)
    a = requests.get(f"{base}/accounts", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}); a.raise_for_status()
    accounts = a.json().get("accounts", [])
    account_id = next((x["accountId"] for x in accounts if x.get("preferred")), (accounts[0]["accountId"] if accounts else None))
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

    # Dealing rules
    md = broker.market_details(epic)
    rules = md.get("dealingRules", {})
    min_stop = float(rules.get("minStopOrLimitDistance", {}).get("value", 0.0))
    step_stop = float(rules.get("stopDistance", {}).get("step", 0.1)) if rules.get("stopDistance") else 0.1
    print(f"ℹ️ {epic} min_stop={min_stop} step={step_stop}")

    def clamp_distance(d):
        if d < min_stop:
            d = min_stop
        if step_stop and step_stop > 0:
            k = int((d + 1e-9) / step_stop)
            if abs(k * step_stop - d) > 1e-9:
                d = (k + 1) * step_stop
        return d

    # Preflight
    pf = preflight_can_trade(broker, epic, size)
    if not pf.ok:
        logging.error(f"❌ Preflight failed: {pf.reason}")
        return
    logging.info("✅ Preflight OK")

    # MongoDB logger
    mongo = MongoLogger()

    gate = PositionGate(broker, refresh_sec=5.0)

    # Bar queue
    bar_q: Queue = Queue(maxsize=200)
    bars = []

    def on_bar(bar):
        try:
            bar_q.put_nowait(bar)
        except:
            try: _ = bar_q.get_nowait()
            except: pass
            bar_q.put_nowait(bar)

    # Strategy worker
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
                print(f"🧱 BAR {row['Datetime']} O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f}")

                if len(bars) < 3:
                    continue

                df = pd.DataFrame(bars).set_index("Datetime")

                # signal
                cross = rsi_cross_up(df["Close"], level=lvl, period=2)
                rsi_series = rsi(df["Close"], period=2)
                current_rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 0.0

                if not cross.iloc[-1]:
                    continue

                gate.refresh_if_due()
                if gate.has_open():
                    print("⛔ Skip: existing open position (gated)")
                    continue

                idx = len(df) - 1
                pack = compute_sl_tp_fixed_rr(df, idx, rr) if mode == "fixed" else compute_tp_gapN(df, idx, float(cfg["strategy"].get("N", 3.0)))
                if not pack:
                    print("⚠️ Skip: non-positive risk / pack None")
                    # Log rejected signal
                    mongo.log_signal(
                        epic=epic,
                        signal_type="REJECTED",
                        bar_data={"datetime": row['Datetime'], "open": row['Open'], "high": row['High'],
                                  "low": row['Low'], "close": row['Close']},
                        rsi_value=current_rsi,
                        entry_price=row['Close'],
                        sl=0.0,
                        tp=0.0,
                        reason="Non-positive risk or pack None"
                    )
                    continue

                stop_dist, limit_dist = price_to_dist(pack["entry"], pack["sl"], pack["tp"])
                stop_dist, limit_dist = clamp_distance(stop_dist), clamp_distance(limit_dist)

                # Log signal to MongoDB
                mongo.log_signal(
                    epic=epic,
                    signal_type="BUY",
                    bar_data={"datetime": row['Datetime'], "open": row['Open'], "high": row['High'],
                              "low": row['Low'], "close": row['Close']},
                    rsi_value=current_rsi,
                    entry_price=pack['entry'],
                    sl=pack['sl'],
                    tp=pack['tp'],
                    reason="RSI cross-up signal"
                )

                if dry:
                    print(f"[DRY] LONG {epic} @{pack['entry']:.2f} SLd={stop_dist:.2f} LId={limit_dist:.2f}")
                    log_trade_csv(epic=epic, mode=mode, rr_or_N=str(rr if mode=='fixed' else cfg['strategy'].get('N')),
                                  side="BUY", entry_px=pack['entry'], stop_distance=stop_dist, limit_distance=limit_dist,
                                  dry_run=True, status="DRY_OK", reason="signal")
                    # Log to MongoDB
                    mongo.log_trade(epic=epic, mode=mode, rr_or_N=str(rr if mode=='fixed' else cfg['strategy'].get('N')),
                                    side="BUY", entry_px=pack['entry'], stop_distance=stop_dist, limit_distance=limit_dist,
                                    dry_run=True, status="DRY_OK", reason="signal")
                else:
                    res = broker.place_otc_market(epic, size, "BUY", stop_dist, limit_dist, guaranteed)
                    ok = bool(res.get("ok"))
                    if ok:
                        gate.mark_open()
                        broker_ref = res.get("confirm", {}).get("dealId", "") or res.get("confirm", {}).get("dealReference", "")
                        print(f"✅ LIVE order accepted. Ref={broker_ref}")
                        log_trade_csv(epic=epic, mode=mode, rr_or_N=str(rr if mode=='fixed' else cfg['strategy'].get('N')),
                                      side="BUY", entry_px=pack['entry'], stop_distance=stop_dist, limit_distance=limit_dist,
                                      dry_run=False, status="LIVE_OK", broker_ref=broker_ref)
                        # Log to MongoDB
                        mongo.log_trade(epic=epic, mode=mode, rr_or_N=str(rr if mode=='fixed' else cfg['strategy'].get('N')),
                                        side="BUY", entry_px=pack['entry'], stop_distance=stop_dist, limit_distance=limit_dist,
                                        dry_run=False, status="LIVE_OK", broker_ref=broker_ref)
                    else:
                        err = res.get("error", "UNKNOWN_ERROR")
                        print(f"❌ LIVE order failed: {err}")
                        log_trade_csv(epic=epic, mode=mode, rr_or_N=str(rr if mode=='fixed' else cfg['strategy'].get('N')),
                                      side="BUY", entry_px=pack['entry'], stop_distance=stop_dist, limit_distance=limit_dist,
                                      dry_run=False, status="LIVE_FAIL", reason=err)
                        # Log to MongoDB
                        mongo.log_trade(epic=epic, mode=mode, rr_or_N=str(rr if mode=='fixed' else cfg['strategy'].get('N')),
                                        side="BUY", entry_px=pack['entry'], stop_distance=stop_dist, limit_distance=limit_dist,
                                        dry_run=False, status="LIVE_FAIL", reason=err)
            except Exception as e:
                print(f"⚠️ Worker error: {e}")

    t = threading.Thread(target=worker, daemon=True); t.start()

    # Streaming (LS or REST polling)
    CST, XST, LS_ENDPOINT, ACCOUNT_ID = authenticate_for_stream(auth)
    client, sub = start_streaming(LS_ENDPOINT, ACCOUNT_ID, CST, XST, epic=epic, timeframe_sec=tf, on_bar=on_bar, broker=broker)
    print(f"📡 Feeding {epic} (tf={tf}s)  dry_run={dry}  mode={'REST_POLL' if isinstance(client, dict) else 'LIGHTSTREAMER'}")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_streaming(client, sub)
        mongo.close()

if __name__ == "__main__":
    main()
