import signal, sys
from datetime import datetime
import pytz
from lightstreamer.client import (
    LightstreamerClient, Subscription, SubscriptionListener,
    ClientListener, ConsoleLoggerProvider, ConsoleLogLevel
)
from src.ohlc_aggregator import BarBuilder

# ---- Logger ----
logger_provider = ConsoleLoggerProvider(ConsoleLogLevel.DEBUG)
LightstreamerClient.setLoggerProvider(logger_provider)

# ---- Market timezone explicit ----
MARKET_TZ = pytz.timezone("Europe/London")

def combine_time_today(hhmmss: str):
    today_local = datetime.now(MARKET_TZ).date()
    dt_local = MARKET_TZ.localize(datetime.strptime(f"{today_local} {hhmmss}", "%Y-%m-%d %H:%M:%S"))
    return dt_local

class VerboseClientListener(ClientListener):
    def onStatusChange(self, status):
        print(f"🔌 LS status: {status}")
    def onServerError(self, code, message):
        print(f"❌ LS server error [{code}]: {message}")

class MarketTickListener(SubscriptionListener):
    def __init__(self, builder: BarBuilder, on_bar, name="L1"):
        self.builder = builder
        self.on_bar = on_bar
        self.name = name
        self.update_count = 0  # <-- init the counter

    # lifecycle logs
    def onSubscription(self):
        print(f"✅ [{self.name}] SUBSCRIBED")
    def onSubscriptionError(self, code, message):
        print(f"❌ [{self.name}] SUB ERROR {code}: {message}")
    def onUnsubscription(self):
        print(f"📤 [{self.name}] UNSUBSCRIBED")
    def onClearSnapshot(self, itemName, itemPos):
        print(f"🧹 [{self.name}] SNAPSHOT CLEARED")

    def onItemUpdate(self, update):
        try:
            self.update_count += 1
            # Dump raw fields once or twice so we see the schema
            if self.update_count <= 2:
                print(f"📈 [{self.name}] FIELDS #{self.update_count}: {update.getFields()}")

            bid = update.getValue("BID")
            offer = update.getValue("OFFER")   # For L1 items it's OFFER (not OFR)
            tstr = update.getValue("UPDATE_TIME")  # "HH:MM:SS" (may be None sometimes)

            if not (bid and offer):
                return

            bid_f, offer_f = float(bid), float(offer)
            mid = (bid_f + offer_f) / 2.0

            # Build a timestamp
            if tstr:
                ts = combine_time_today(tstr).timestamp()
            else:
                ts = datetime.now(MARKET_TZ).timestamp()

            finished = self.builder.on_tick(ts, mid)
            if finished and self.on_bar:
                # helpful print for every completed bar
                dt_open = datetime.fromtimestamp(finished.ts_open, MARKET_TZ)
                print(f"🧱 BAR {dt_open} O:{finished.open:.2f} H:{finished.high:.2f} L:{finished.low:.2f} C:{finished.close:.2f}")
                self.on_bar(finished)

        except Exception as e:
            # Never let exceptions kill the LS callback thread
            print(f"⚠️ [{self.name}] Tick handler error: {e}")

class ConnListener(ClientListener):
    def onStatusChange(self, status): print(f"🔌 Lightstreamer status: {status}")
    def onServerError(self, code, message): print(f"❌ LS server error [{code}]: {message}")

def start_streaming(LS_ENDPOINT: str, ACCOUNT_ID: str, CST: str, XST: str,
                    epic: str, timeframe_sec: int, on_bar):
    client = LightstreamerClient(LS_ENDPOINT, "DEFAULT")
    client.connectionDetails.setUser(ACCOUNT_ID)
    client.connectionDetails.setPassword(f"CST-{CST}|XST-{XST}")
    client.addListener(ConnListener())
    client.addListener(VerboseClientListener())

    subscription = Subscription(
        mode="MERGE",
        items=[f"L1:{epic}"],                      # L1 price namespace
        fields=["BID", "OFFER", "UPDATE_TIME"]     # known-good field set
    )
    subscription.setRequestedSnapshot("yes")

    builder = BarBuilder(timeframe_sec=timeframe_sec)
    subscription.addListener(MarketTickListener(builder, on_bar, name=f"L1:{epic}"))

    client.connect()
    client.subscribe(subscription)
    return client, subscription

def stop_streaming(client, sub):
    try:
        client.unsubscribe(sub)
    finally:
        client.disconnect()
