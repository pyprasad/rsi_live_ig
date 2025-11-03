"""
S&P 500 Live Trading Runner
Based on live_runner.py pattern with S&P 500 specific strategy
"""
import os, time, yaml, pandas as pd, threading, sqlite3
from queue import Queue, Empty
from dotenv import load_dotenv
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

from .sp500_strategy_core import sp500_signal, price_to_dist
from .ig_adapter import IGBroker, IGAuth
from .data.collector import start_streaming, stop_streaming
from .logging_setup import setup_logging
from .preflight import preflight_can_trade
from .position_gate import PositionGate
from .trade_log import log_trade_csv
from .mongo_logger import MongoLogger

logging = setup_logging()


def authenticate_for_stream(auth: IGAuth):
    """Authenticate and get Lightstreamer credentials"""
    import requests
    base = "https://demo-api.ig.com/gateway/deal" if auth.account_type.upper()=="DEMO" else "https://api.ig.com/gateway/deal"
    h = {"X-IG-API-KEY": auth.api_key, "Content-Type":"application/json", "Accept":"application/json"}
    r = requests.post(f"{base}/session", json={"identifier": auth.username, "password": auth.password}, headers=h); r.raise_for_status()
    CST, XST = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
    s = requests.get(f"{base}/session?fetchSessionTokens=true", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}); s.raise_for_status()
    data = s.json()
    ls_endpoint = data.get("lightstreamerEndpoint") or ("https://demo-apd.marketdatasystems.com" if auth.account_type.upper()=="DEMO" else "https://apd.marketdatasystems.com")
    a = requests.get(f"{base}/accounts", headers={**h, "CST": CST, "X-SECURITY-TOKEN": XST}); a.raise_for_status()
    accounts = a.json().get("accounts", [])
    account_id = next((x["accountId"] for x in accounts if x.get("preferred")), (accounts[0]["accountId"] if accounts else None))
    return CST, XST, ls_endpoint, account_id


# News scraper
class NewsFilter:
    def __init__(self, db_path, currencies=['USD', 'EUR'], buffer_minutes=30):
        self.db_path = db_path
        self.currencies = currencies
        self.buffer_minutes = buffer_minutes
        self.events = []
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for news events"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS news_events
                     (event_time TEXT, currency TEXT, title TEXT, impact TEXT,
                      scraped_at TEXT, PRIMARY KEY (event_time, currency, title))''')
        conn.commit()
        conn.close()

    def scrape_forex_factory(self, date=None):
        """Scrape Forex Factory calendar for high-impact events"""
        if date is None:
            date = datetime.now()

        url = f"https://www.forexfactory.com/calendar?day={date.strftime('%Y%m%d')}"

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')
            events = []

            # Parse events (simplified - adjust based on actual HTML structure)
            for row in soup.find_all('tr', class_='calendar__row'):
                try:
                    impact = row.find('td', class_='calendar__impact')
                    if impact and 'icon--ff-impact-red' in str(impact):  # High impact
                        time_elem = row.find('td', class_='calendar__time')
                        currency_elem = row.find('td', class_='calendar__currency')
                        title_elem = row.find('td', class_='calendar__event')

                        if time_elem and currency_elem and title_elem:
                            event_time_str = time_elem.text.strip()
                            currency = currency_elem.text.strip()
                            title = title_elem.text.strip()

                            if currency in self.currencies:
                                # Parse time
                                try:
                                    event_time = datetime.strptime(f"{date.strftime('%Y-%m-%d')} {event_time_str}", '%Y-%m-%d %I:%M%p')
                                except:
                                    continue

                                events.append({
                                    'time': event_time,
                                    'currency': currency,
                                    'title': title,
                                    'impact': 'HIGH'
                                })
                except:
                    continue

            # Store in DB
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for event in events:
                try:
                    c.execute('INSERT OR REPLACE INTO news_events VALUES (?,?,?,?,?)',
                             (event['time'].isoformat(), event['currency'], event['title'],
                              event['impact'], datetime.now().isoformat()))
                except:
                    pass
            conn.commit()
            conn.close()

            self.events = events
            logging.info(f"📰 Scraped {len(events)} high-impact events for {date.date()}")
            return events

        except Exception as e:
            logging.error(f"❌ Failed to scrape Forex Factory: {e}")
            return []

    def is_near_news(self, check_time):
        """Check if current time is within buffer of any high-impact news"""
        for event in self.events:
            diff = abs((event['time'] - check_time).total_seconds() / 60)
            if diff <= self.buffer_minutes:
                logging.info(f"⛔ Near news event: {event['title']} at {event['time']}")
                return True
        return False


def main(cfg_path="configs/sp500_live_config.yaml"):
    load_dotenv()
    cfg = yaml.safe_load(open(cfg_path))

    auth = IGAuth(
        api_key=os.getenv("IG_API_KEY",""),
        username=os.getenv("IG_USERNAME",""),
        password=os.getenv("IG_PASSWORD",""),
        account_type=os.getenv("IG_ACCOUNT_TYPE", cfg["ig"]["account_type"])
    )
    broker = IGBroker(auth); broker.connect()

    epic = cfg["ig"]["epic"]
    size = float(cfg["ig"]["size"])
    tf = int(cfg["strategy"]["timeframe_sec"])
    dry = bool(cfg["ops"]["dry_run"])
    guaranteed = bool(cfg["ig"]["guaranteed_stop"])
    db_path = cfg["ops"]["db_path"]

    # Dealing rules
    md = broker.market_details(epic)
    rules = md.get("dealingRules", {})
    min_stop = float(rules.get("minStopOrLimitDistance", {}).get("value", 0.0))
    step_stop = float(rules.get("stopDistance", {}).get("step", 0.1)) if rules.get("stopDistance") else 0.1
    print(f"ℹ️  {epic} min_stop={min_stop} step={step_stop}")

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

    # News filter
    news_filter = NewsFilter(
        db_path=db_path,
        currencies=cfg["strategy"].get("news_currencies", ["USD", "EUR"]),
        buffer_minutes=cfg["strategy"].get("news_buffer_minutes", 30)
    )

    # Scrape today's and tomorrow's news
    news_filter.scrape_forex_factory(datetime.now())
    news_filter.scrape_forex_factory(datetime.now() + timedelta(days=1))

    # MongoDB logger
    mongo = MongoLogger()

    # Position gate (one trade per direction)
    gate = PositionGate(broker, fallback_poll_sec=300.0)

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

                # Check signal
                signal = sp500_signal(df, cfg["strategy"])

                if not signal:
                    continue

                # Check news filter
                if news_filter.is_near_news(signal['timestamp']):
                    print("⛔ Skip: near high-impact news")
                    continue

                gate.refresh_if_due()
                if gate.has_open():
                    print("⛔ Skip: existing open position (gated)")
                    continue

                # Calculate distances
                stop_dist, limit_dist = price_to_dist(signal['entry'], signal['sl'], signal['tp'])
                stop_dist, limit_dist = clamp_distance(stop_dist), clamp_distance(limit_dist)

                print(f"\n🚨 SIGNAL: {signal['type']}")
                print(f"   RSI: {signal['rsi']:.2f}")
                print(f"   Entry: {signal['entry']:.2f}")
                print(f"   SL: {signal['sl']:.2f} (dist={stop_dist:.2f})")
                print(f"   TP: {signal['tp']:.2f} (dist={limit_dist:.2f})")

                # Log signal to MongoDB
                mongo.log_signal(
                    epic=epic,
                    signal_type=signal['type'],
                    bar_data={"datetime": row['Datetime'], "open": row['Open'], "high": row['High'],
                              "low": row['Low'], "close": row['Close']},
                    rsi_value=signal['rsi'],
                    entry_price=signal['entry'],
                    sl=signal['sl'],
                    tp=signal['tp'],
                    reason="S&P500 RSI(2) reversal"
                )

                if dry:
                    print(f"   [DRY RUN] Would place {signal['type']} order")
                    log_trade_csv(epic=epic, mode="sp500", rr_or_N="reversal",
                                  side=signal['type'], entry_px=signal['entry'],
                                  stop_distance=stop_dist, limit_distance=limit_dist,
                                  dry_run=True, status="DRY_OK", reason="signal")
                    mongo.log_trade(epic=epic, mode="sp500", rr_or_N="reversal",
                                   side=signal['type'], entry_px=signal['entry'],
                                   stop_distance=stop_dist, limit_distance=limit_dist,
                                   dry_run=True, status="DRY_OK", reason="signal")
                else:
                    res = broker.place_otc_market(epic, size, signal['type'], stop_dist, limit_dist, guaranteed)
                    ok = bool(res.get("ok"))
                    if ok:
                        gate.mark_open()
                        broker_ref = res.get("confirm", {}).get("dealId", "") or res.get("confirm", {}).get("dealReference", "")
                        print(f"✅ LIVE order accepted. Ref={broker_ref}")
                        log_trade_csv(epic=epic, mode="sp500", rr_or_N="reversal",
                                      side=signal['type'], entry_px=signal['entry'],
                                      stop_distance=stop_dist, limit_distance=limit_dist,
                                      dry_run=False, status="LIVE_OK", broker_ref=broker_ref)
                        mongo.log_trade(epic=epic, mode="sp500", rr_or_N="reversal",
                                       side=signal['type'], entry_px=signal['entry'],
                                       stop_distance=stop_dist, limit_distance=limit_dist,
                                       dry_run=False, status="LIVE_OK", broker_ref=broker_ref)
                    else:
                        err = res.get("error", "UNKNOWN_ERROR")
                        print(f"❌ LIVE order failed: {err}")
                        log_trade_csv(epic=epic, mode="sp500", rr_or_N="reversal",
                                      side=signal['type'], entry_px=signal['entry'],
                                      stop_distance=stop_dist, limit_distance=limit_dist,
                                      dry_run=False, status="LIVE_FAIL", reason=err)
                        mongo.log_trade(epic=epic, mode="sp500", rr_or_N="reversal",
                                       side=signal['type'], entry_px=signal['entry'],
                                       stop_distance=stop_dist, limit_distance=limit_dist,
                                       dry_run=False, status="LIVE_FAIL", reason=err)
            except Exception as e:
                print(f"⚠️  Worker error: {e}")
                import traceback
                traceback.print_exc()

    t = threading.Thread(target=worker, daemon=True); t.start()

    # Streaming (using existing collector.py)
    logging.info("🔐 Authenticating for Lightstreamer...")
    CST, XST, LS_ENDPOINT, ACCOUNT_ID = authenticate_for_stream(auth)
    logging.info(f"✅ Got credentials - Endpoint: {LS_ENDPOINT}, Account: {ACCOUNT_ID}")

    logging.info(f"📡 Starting Lightstreamer connection for {epic}...")
    client, sub = start_streaming(LS_ENDPOINT, ACCOUNT_ID, CST, XST, epic=epic, timeframe_sec=tf, on_bar=on_bar, broker=broker)

    mode = 'REST_POLL' if isinstance(client, dict) else 'LIGHTSTREAMER'
    logging.info(f"✅ Connected! Mode: {mode}, Timeframe: {tf}s, Dry Run: {dry}")
    print(f"\n{'='*80}")
    print(f"📡 S&P 500 LIVE TRADER RUNNING")
    print(f"{'='*80}")
    print(f"Epic: {epic}")
    print(f"Mode: {mode}")
    print(f"Candles: {tf//60} minutes")
    print(f"Dry Run: {dry}")
    print(f"{'='*80}\n")
    print("Waiting for ticks and candles...\n")

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
