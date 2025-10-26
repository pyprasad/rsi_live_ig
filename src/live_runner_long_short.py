"""
Live Trading Runner - LONG + SHORT Strategy

Final Validated Strategy: RSI2_L7_S90_RR5.0_SL5_both
- LONG signals: RSI(2) crosses above 7
- SHORT signals: RSI(2) crosses below 90
- Stop Loss: Lowest/highest of last 5 bars
- Take Profit: Entry ± (Risk × 5.0)
- Trade Mode: BOTH (one position at a time)
- Session: 08:00-22:00 Europe/Berlin

This script:
1. Connects to IG Markets via Lightstreamer for real-time tick data
2. Aggregates ticks into 30-minute OHLC candles
3. Calculates RSI(2) and detects cross-up/cross-down signals
4. Places LONG or SHORT trades via IG REST API
5. Logs all signals and trades to MongoDB
"""

import os
import time
import yaml
import pandas as pd
import threading
import pytz
from queue import Queue, Empty
from datetime import datetime, time as dt_time
from dotenv import load_dotenv

from .strategy_core import rsi
from .ig_adapter import IGBroker, IGAuth
from .data.collector import start_streaming, stop_streaming
from .logging_setup import setup_logging
from .preflight import preflight_can_trade
from .position_gate import PositionGate
from .trade_log import log_trade_csv
from .mongo_logger import MongoLogger

logging = setup_logging()


def price_to_dist(entry, sl, tp):
    """Convert price levels to distance values for IG API."""
    return max(abs(entry - sl), 0.1), max(abs(tp - entry), 0.1)


def authenticate_for_stream(auth: IGAuth):
    """Authenticate and get Lightstreamer credentials."""
    import requests
    base = (
        "https://demo-api.ig.com/gateway/deal"
        if auth.account_type.upper() == "DEMO"
        else "https://api.ig.com/gateway/deal"
    )
    h = {
        "X-IG-API-KEY": auth.api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    r = requests.post(
        f"{base}/session",
        json={"identifier": auth.username, "password": auth.password},
        headers=h,
    )
    r.raise_for_status()
    CST, XST = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
    s = requests.get(
        f"{base}/session?fetchSessionTokens=true",
        headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST},
    )
    s.raise_for_status()
    data = s.json()
    ls_endpoint = data.get("lightstreamerEndpoint") or (
        "https://demo-apd.marketdatasystems.com"
        if auth.account_type.upper() == "DEMO"
        else "https://apd.marketdatasystems.com"
    )
    # Get account id
    a = requests.get(
        f"{base}/accounts", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}
    )
    a.raise_for_status()
    accounts = a.json().get("accounts", [])
    account_id = next(
        (x["accountId"] for x in accounts if x.get("preferred")),
        (accounts[0]["accountId"] if accounts else None),
    )
    return CST, XST, ls_endpoint, account_id


def compute_sl_long_lookback(df: pd.DataFrame, idx: int, lookback: int):
    """
    Calculate stop loss for LONG position (lowest low of last N bars).
    Returns: sl_price or None if invalid
    """
    if idx < lookback:
        return None
    lows = [df["Low"].iloc[idx - i] for i in range(1, lookback + 1)]
    sl = min(lows)
    entry = df["Close"].iloc[idx]
    if entry <= sl:
        return None
    return float(sl)


def compute_sl_short_lookback(df: pd.DataFrame, idx: int, lookback: int):
    """
    Calculate stop loss for SHORT position (highest high of last N bars).
    Returns: sl_price or None if invalid
    """
    if idx < lookback:
        return None
    highs = [df["High"].iloc[idx - i] for i in range(1, lookback + 1)]
    sl = max(highs)
    entry = df["Close"].iloc[idx]
    if entry >= sl:
        return None
    return float(sl)


def is_in_session(timestamp, session_cfg):
    """Check if timestamp is within trading session."""
    if not session_cfg.get("use_session_filter", False):
        return True

    tz = pytz.timezone(session_cfg.get("tz", "Europe/Berlin"))
    start_time = dt_time.fromisoformat(session_cfg.get("start", "08:00"))
    end_time = dt_time.fromisoformat(session_cfg.get("end", "22:00"))

    if timestamp.tzinfo is None:
        local_time = tz.localize(timestamp)
    else:
        local_time = timestamp.astimezone(tz)

    current_time = local_time.time()
    return start_time <= current_time <= end_time


def main(cfg_path="configs/live_config_final.yaml"):
    load_dotenv()
    cfg = yaml.safe_load(open(cfg_path))

    auth = IGAuth(
        api_key=os.getenv("IG_API_KEY", ""),
        username=os.getenv("IG_USERNAME", ""),
        password=os.getenv("IG_PASSWORD", ""),
        account_type=os.getenv("IG_ACCOUNT_TYPE", cfg["ig"]["account_type"]),
    )
    broker = IGBroker(auth)
    broker.connect()

    # Strategy config
    epic = cfg["ig"]["epic"]
    size = float(cfg["ig"]["size"])
    guaranteed = bool(cfg["ig"]["guaranteed_stop"])

    rsi_period = int(cfg["strategy"]["rsi_period"])
    long_threshold = int(cfg["strategy"]["rsi_cross_up_level"])
    short_threshold = int(cfg["strategy"]["rsi_cross_down_level"])
    rr = float(cfg["strategy"]["rr"])
    sl_lookback = int(cfg["strategy"]["sl_lookback"])
    trade_mode = cfg["strategy"]["trade_mode"]
    tf = int(cfg["strategy"]["timeframe_sec"])
    dry = bool(cfg["ops"]["dry_run"])

    session_cfg = cfg.get("session", {})

    # Dealing rules
    md = broker.market_details(epic)
    rules = md.get("dealingRules", {})
    min_stop = float(rules.get("minStopOrLimitDistance", {}).get("value", 0.0))
    step_stop = (
        float(rules.get("stopDistance", {}).get("step", 0.1))
        if rules.get("stopDistance")
        else 0.1
    )
    logging.info(f"ℹ️ {epic} min_stop={min_stop} step={step_stop}")

    def clamp_distance(d):
        if d < min_stop:
            d = min_stop
        if step_stop and step_stop > 0:
            k = int((d + 1e-9) / step_stop)
            if abs(k * step_stop - d) > 1e-9:
                d = (k + 1) * step_stop
        return d

    # Preflight check
    pf = preflight_can_trade(broker, epic, size)
    if not pf.ok:
        logging.error(f"❌ Preflight failed: {pf.reason}")
        return
    logging.info("✅ Preflight OK")

    # MongoDB logger
    mongo = MongoLogger()

    # Position gate (one trade at a time)
    # Uses Lightstreamer updates + 5-minute fallback polling
    gate = PositionGate(broker, fallback_poll_sec=300.0)

    # Check startup state (one-time API call)
    has_open = gate.check_startup_state()
    if has_open:
        logging.warning("⚠️ STARTUP: Existing position detected on IG. Will not trade until closed.")
    else:
        logging.info("✅ STARTUP: No open positions. Ready to trade.")

    # Start fallback polling thread (safety net)
    gate.start_fallback_polling()

    # Bar queue
    bar_q: Queue = Queue(maxsize=200)
    bars = []

    def on_bar(bar):
        try:
            bar_q.put_nowait(bar)
        except:
            try:
                _ = bar_q.get_nowait()
            except:
                pass
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
                row = {
                    "Datetime": pd.to_datetime(bar.ts_open, unit="s"),
                    "Open": bar.open,
                    "High": bar.high,
                    "Low": bar.low,
                    "Close": bar.close,
                }
                bars.append(row)
                logging.info(
                    f"🧱 BAR {row['Datetime']} O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f}"
                )

                # Need enough bars for RSI + SL lookback
                min_bars = max(rsi_period, sl_lookback) + 1
                if len(bars) < min_bars:
                    continue

                df = pd.DataFrame(bars).set_index("Datetime")

                # Calculate RSI
                rsi_series = rsi(df["Close"], period=rsi_period)
                current_rsi = float(rsi_series.iloc[-1])
                prev_rsi = float(rsi_series.iloc[-2]) if len(rsi_series) > 1 else 0.0

                # Detect signals
                long_signal = (prev_rsi <= long_threshold) and (
                    current_rsi > long_threshold
                )
                short_signal = (prev_rsi >= short_threshold) and (
                    current_rsi < short_threshold
                )

                # No signal - continue
                if not long_signal and not short_signal:
                    continue

                # Check if we're in trading session
                if not is_in_session(row["Datetime"], session_cfg):
                    logging.info(
                        f"⏰ Skip: Signal detected outside session hours (RSI={current_rsi:.1f})"
                    )
                    mongo.log_signal(
                        epic=epic,
                        signal_type="LONG" if long_signal else "SHORT",
                        bar_data={
                            "datetime": row["Datetime"],
                            "open": row["Open"],
                            "high": row["High"],
                            "low": row["Low"],
                            "close": row["Close"],
                        },
                        rsi_value=current_rsi,
                        entry_price=row["Close"],
                        sl=0.0,
                        tp=0.0,
                        reason="Outside session hours",
                    )
                    continue

                # Check for existing position
                if gate.has_open():
                    logging.info(
                        f"⛔ Skip: Existing open position (RSI={current_rsi:.1f})"
                    )
                    continue

                idx = len(df) - 1

                # Process LONG signal (checked first, so it wins if both signal)
                if trade_mode in ["long_only", "both"] and long_signal:
                    sl_price = compute_sl_long_lookback(df, idx, sl_lookback)
                    if sl_price is None:
                        logging.warning(
                            f"⚠️ Skip LONG: Invalid SL (idx={idx}, lookback={sl_lookback})"
                        )
                        mongo.log_signal(
                            epic=epic,
                            signal_type="REJECTED_LONG",
                            bar_data={
                                "datetime": row["Datetime"],
                                "open": row["Open"],
                                "high": row["High"],
                                "low": row["Low"],
                                "close": row["Close"],
                            },
                            rsi_value=current_rsi,
                            entry_price=row["Close"],
                            sl=0.0,
                            tp=0.0,
                            reason="Invalid SL calculation",
                        )
                        continue

                    entry_price = float(df["Close"].iloc[idx])
                    sl = sl_price
                    risk = entry_price - sl

                    if risk <= 0:
                        logging.warning(f"⚠️ Skip LONG: Non-positive risk ({risk:.2f})")
                        mongo.log_signal(
                            epic=epic,
                            signal_type="REJECTED_LONG",
                            bar_data={
                                "datetime": row["Datetime"],
                                "open": row["Open"],
                                "high": row["High"],
                                "low": row["Low"],
                                "close": row["Close"],
                            },
                            rsi_value=current_rsi,
                            entry_price=entry_price,
                            sl=sl,
                            tp=0.0,
                            reason="Non-positive risk",
                        )
                        continue

                    tp = entry_price + (risk * rr)

                    stop_dist, limit_dist = price_to_dist(entry_price, sl, tp)
                    stop_dist, limit_dist = clamp_distance(stop_dist), clamp_distance(
                        limit_dist
                    )

                    # Log signal to MongoDB
                    mongo.log_signal(
                        epic=epic,
                        signal_type="LONG",
                        bar_data={
                            "datetime": row["Datetime"],
                            "open": row["Open"],
                            "high": row["High"],
                            "low": row["Low"],
                            "close": row["Close"],
                        },
                        rsi_value=current_rsi,
                        entry_price=entry_price,
                        sl=sl,
                        tp=tp,
                        reason=f"RSI({rsi_period}) crossed above {long_threshold}",
                    )

                    if dry:
                        logging.info(
                            f"[DRY] LONG {epic} @{entry_price:.2f} SL={sl:.2f} TP={tp:.2f} (Risk={risk:.2f}, R:R={rr})"
                        )
                        log_trade_csv(
                            epic=epic,
                            mode="fixed",
                            rr_or_N=str(rr),
                            side="BUY",
                            entry_px=entry_price,
                            stop_distance=stop_dist,
                            limit_distance=limit_dist,
                            dry_run=True,
                            status="DRY_OK",
                            reason="signal",
                        )
                        mongo.log_trade(
                            epic=epic,
                            mode="fixed",
                            rr_or_N=str(rr),
                            side="BUY",
                            entry_px=entry_price,
                            stop_distance=stop_dist,
                            limit_distance=limit_dist,
                            dry_run=True,
                            status="DRY_OK",
                            reason="signal",
                        )
                    else:
                        res = broker.place_otc_market(
                            epic, size, "BUY", stop_dist, limit_dist, guaranteed
                        )
                        ok = bool(res.get("ok"))
                        if ok:
                            gate.mark_open()
                            broker_ref = (
                                res.get("confirm", {}).get("dealId", "")
                                or res.get("confirm", {}).get("dealReference", "")
                            )
                            logging.info(
                                f"✅ LONG order accepted. Ref={broker_ref} Entry={entry_price:.2f} SL={sl:.2f} TP={tp:.2f}"
                            )
                            log_trade_csv(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="BUY",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_OK",
                                broker_ref=broker_ref,
                            )
                            mongo.log_trade(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="BUY",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_OK",
                                broker_ref=broker_ref,
                            )
                        else:
                            err = res.get("error", "UNKNOWN_ERROR")
                            logging.error(f"❌ LONG order failed: {err}")
                            log_trade_csv(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="BUY",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_FAIL",
                                reason=err,
                            )
                            mongo.log_trade(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="BUY",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_FAIL",
                                reason=err,
                            )

                # Process SHORT signal (only if LONG didn't trigger)
                elif trade_mode in ["short_only", "both"] and short_signal:
                    sl_price = compute_sl_short_lookback(df, idx, sl_lookback)
                    if sl_price is None:
                        logging.warning(
                            f"⚠️ Skip SHORT: Invalid SL (idx={idx}, lookback={sl_lookback})"
                        )
                        mongo.log_signal(
                            epic=epic,
                            signal_type="REJECTED_SHORT",
                            bar_data={
                                "datetime": row["Datetime"],
                                "open": row["Open"],
                                "high": row["High"],
                                "low": row["Low"],
                                "close": row["Close"],
                            },
                            rsi_value=current_rsi,
                            entry_price=row["Close"],
                            sl=0.0,
                            tp=0.0,
                            reason="Invalid SL calculation",
                        )
                        continue

                    entry_price = float(df["Close"].iloc[idx])
                    sl = sl_price
                    risk = sl - entry_price

                    if risk <= 0:
                        logging.warning(
                            f"⚠️ Skip SHORT: Non-positive risk ({risk:.2f})"
                        )
                        mongo.log_signal(
                            epic=epic,
                            signal_type="REJECTED_SHORT",
                            bar_data={
                                "datetime": row["Datetime"],
                                "open": row["Open"],
                                "high": row["High"],
                                "low": row["Low"],
                                "close": row["Close"],
                            },
                            rsi_value=current_rsi,
                            entry_price=entry_price,
                            sl=sl,
                            tp=0.0,
                            reason="Non-positive risk",
                        )
                        continue

                    tp = entry_price - (risk * rr)

                    stop_dist, limit_dist = price_to_dist(entry_price, sl, tp)
                    stop_dist, limit_dist = clamp_distance(stop_dist), clamp_distance(
                        limit_dist
                    )

                    # Log signal to MongoDB
                    mongo.log_signal(
                        epic=epic,
                        signal_type="SHORT",
                        bar_data={
                            "datetime": row["Datetime"],
                            "open": row["Open"],
                            "high": row["High"],
                            "low": row["Low"],
                            "close": row["Close"],
                        },
                        rsi_value=current_rsi,
                        entry_price=entry_price,
                        sl=sl,
                        tp=tp,
                        reason=f"RSI({rsi_period}) crossed below {short_threshold}",
                    )

                    if dry:
                        logging.info(
                            f"[DRY] SHORT {epic} @{entry_price:.2f} SL={sl:.2f} TP={tp:.2f} (Risk={risk:.2f}, R:R={rr})"
                        )
                        log_trade_csv(
                            epic=epic,
                            mode="fixed",
                            rr_or_N=str(rr),
                            side="SELL",
                            entry_px=entry_price,
                            stop_distance=stop_dist,
                            limit_distance=limit_dist,
                            dry_run=True,
                            status="DRY_OK",
                            reason="signal",
                        )
                        mongo.log_trade(
                            epic=epic,
                            mode="fixed",
                            rr_or_N=str(rr),
                            side="SELL",
                            entry_px=entry_price,
                            stop_distance=stop_dist,
                            limit_distance=limit_dist,
                            dry_run=True,
                            status="DRY_OK",
                            reason="signal",
                        )
                    else:
                        res = broker.place_otc_market(
                            epic, size, "SELL", stop_dist, limit_dist, guaranteed
                        )
                        ok = bool(res.get("ok"))
                        if ok:
                            gate.mark_open()
                            broker_ref = (
                                res.get("confirm", {}).get("dealId", "")
                                or res.get("confirm", {}).get("dealReference", "")
                            )
                            logging.info(
                                f"✅ SHORT order accepted. Ref={broker_ref} Entry={entry_price:.2f} SL={sl:.2f} TP={tp:.2f}"
                            )
                            log_trade_csv(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="SELL",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_OK",
                                broker_ref=broker_ref,
                            )
                            mongo.log_trade(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="SELL",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_OK",
                                broker_ref=broker_ref,
                            )
                        else:
                            err = res.get("error", "UNKNOWN_ERROR")
                            logging.error(f"❌ SHORT order failed: {err}")
                            log_trade_csv(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="SELL",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_FAIL",
                                reason=err,
                            )
                            mongo.log_trade(
                                epic=epic,
                                mode="fixed",
                                rr_or_N=str(rr),
                                side="SELL",
                                entry_px=entry_price,
                                stop_distance=stop_dist,
                                limit_distance=limit_dist,
                                dry_run=False,
                                status="LIVE_FAIL",
                                reason=err,
                            )

            except Exception as e:
                logging.error(f"⚠️ Worker error: {e}", exc_info=True)

    # Start strategy worker thread
    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # Start streaming (Lightstreamer or REST polling)
    CST, XST, LS_ENDPOINT, ACCOUNT_ID = authenticate_for_stream(auth)
    client, sub = start_streaming(
        LS_ENDPOINT,
        ACCOUNT_ID,
        CST,
        XST,
        epic=epic,
        timeframe_sec=tf,
        on_bar=on_bar,
        broker=broker,
        position_gate=gate,  # Enable real-time position tracking
    )

    mode_str = "REST_POLL" if isinstance(client, dict) else "LIGHTSTREAMER"
    logging.info(
        f"📡 Streaming {epic} (tf={tf}s) dry_run={dry} mode={mode_str} trade_mode={trade_mode.upper()}"
    )
    logging.info(
        f"📊 Strategy: RSI({rsi_period}) LONG>{long_threshold} SHORT<{short_threshold} RR={rr} SL_lookback={sl_lookback}"
    )

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logging.info("🛑 Shutting down...")
    finally:
        stop_streaming(client, sub)
        gate.stop_fallback_polling()
        mongo.close()
        logging.info("✅ Shutdown complete")


if __name__ == "__main__":
    main()
