# data/collector.py
import os, time, threading, requests
from typing import Tuple, Any

from src.ohlc_aggregator import BarBuilder

# ... import your Bar/BarBuilder/OnBar types here ...
# from .bars import BarBuilder, Bar, OnBar  # example

def _ig_headers(api_key: str, cst: str, xst: str, account_id: str, version: str = "3"):
    return {
        "X-IG-API-KEY": api_key,
        "CST": cst,
        "X-SECURITY-TOKEN": xst,
        "IG-ACCOUNT-ID": account_id,
        "VERSION": version,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


RATE_LIMIT_SLEEP = 60.0 
BASE_POLL_PERIOD = 5.0  # seconds between polls when not near bar edge

class _RestPoller:
    def __init__(self, base_url: str, epic: str, timeframe_sec: int, broker, on_bar: "OnBar",
                 cst: str, xst: str, account_id: str, api_key: str, reauth_fn):
        self.base_url = base_url.rstrip("/")
        self.epic = epic
        self.tf = timeframe_sec
        self.on_bar = on_bar
        self.broker = broker
        self.cst = cst
        self.xst = xst
        self.account_id = account_id
        self.api_key = api_key
        self.reauth_fn = reauth_fn
        self.sess = requests.Session()
        self.bb = BarBuilder(timeframe_sec)
        self._stop = False
        self._thread = None

    def _headers(self):
        return _ig_headers(self.api_key, self.cst, self.xst, self.account_id, version="3")

    def _reauth(self):
        try:
            cst, xst, _, account_id = self.reauth_fn()
            self.cst, self.xst, self.account_id = cst, xst, account_id
            print("🔁 Re-authenticated IG session for REST poller.")
        except Exception as e:
            print(f"❌ Re-auth failed: {e}")

    def _poll_once(self):
        # Using /markets is cheap; you could switch to /prices if you want OHLC directly
        url = f"{self.base_url}/markets/{self.epic}"
        r = self.sess.get(url, headers=self._headers(), timeout=10)
        if r.status_code == 403:
            print("REST poll 403 on /markets — attempting single re-auth...")
            self._reauth()
            r = self.sess.get(url, headers=self._headers(), timeout=10)
        r.raise_for_status()
        j = r.json()

        # pull mid from snapshot (BID/OFFER) → tick → bar
        snap = j.get("snapshot") or {}
        bid = snap.get("bid")
        offer = snap.get("offer")
        if bid is None or offer is None:
            return
        try:
            bid = float(bid); offer = float(offer)
        except Exception:
            return
        mid = (bid + offer) / 2.0
        now = time.time()
        finished = self.bb.on_tick(now, mid)
        if finished:
            self.on_bar(finished)

    def _run(self):
        # cheap heartbeat cadence: poll twice per second and let BarBuilder roll on timeframe
        # You can tune this to 1s if rate limits are tight.
        while not self._stop:
            try:
                self._poll_once()
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", None)
                body = getattr(e.response, "text", "")[:400]
                print(f"REST poll error: {e} (status={code})")
                if body:
                    print(f"Body: {body}")
                time.sleep(1.0)
            except Exception as e:
                print(f"REST poll exception: {e}")
                time.sleep(1.0)
            time.sleep(0.5)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return {"mode": "REST_POLL"}, {"mode": "REST_POLL"}  # simple handles

    def stop(self):
        self._stop = True

    def _should_reauth(self, resp: requests.Response) -> bool:
        try:
            data = resp.json()
            code = (data.get("errorCode") or "").lower()
        except Exception:
            code = ""
        # Only re-auth on token/auth errors, NOT on rate limit
        token_errors = {
            "error.security.access-token-invalid",
            "error.security.client-token-missing",
            "error.security.account-token-invalid",
        }
        return code in token_errors

    def _handle_rate_limit(self, resp: requests.Response):
        # Friendly cooldown
        print("⏳ Hit IG API allowance — cooling down for 60s.")
        time.sleep(RATE_LIMIT_SLEEP)

    def _poll_once(self):
        url = f"{self.base_url}/markets/{self.epic}"
        r = self.sess.get(url, headers=self._headers(), timeout=10)
        if r.status_code == 403:
            # Parse error code to decide
            try:
                data = r.json()
                code = (data.get("errorCode") or "").lower()
            except Exception:
                code = ""
            if "exceeded-api-key-allowance" in code:
                self._handle_rate_limit(r)
                return
            if self._should_reauth(r):
                print("🔁 Token issue on /markets — re-auth once...")
                self._reauth()
                r = self.sess.get(url, headers=self._headers(), timeout=10)
        r.raise_for_status()

        j = r.json()
        snap = j.get("snapshot") or {}
        bid = snap.get("bid"); offer = snap.get("offer")
        if bid is None or offer is None:
            return
        bid = float(bid); offer = float(offer)
        mid = (bid + offer) / 2.0
        finished = self.bb.on_tick(time.time(), mid)
        if finished:
            self.on_bar(finished)

    def _run(self):
        # Align polling cadence with bar timeframe to avoid spam
        tf = max(1, self.tf)
        while not self._stop:
            try:
                now = time.time()
                # Poll slowly most of the time, faster near the bar edge
                secs_into = int(now) % tf
                secs_left = tf - secs_into
                self._poll_once()
                if secs_left <= 3:
                    # near boundary: check a bit more often
                    time.sleep(1.0)
                else:
                    time.sleep(BASE_POLL_PERIOD)
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", None)
                body = getattr(e.response, "text", "")[:300]
                print(f"REST poll error: {e} (status={code})")
                if body: print(f"Body: {body}")
                # Gentle backoff on any HTTP error
                time.sleep(5.0)
            except Exception as e:
                print(f"REST poll exception: {e}")
                time.sleep(2.0)


def _start_rest_poll(epic: str, timeframe_sec: int, broker, on_bar: "OnBar"):
    # infer base URL from broker auth
    is_demo = broker.auth.account_type.upper() == "DEMO"
    base = "https://demo-api.ig.com/gateway/deal" if is_demo else "https://api.ig.com/gateway/deal"
    api_key = broker.auth.api_key

    # reuse current tokens (must be the same that live_runner fetched)
    # broker should expose CST/XST/account_id, or give a reauth_fn that returns them.
    def reauth_fn():
        # delegate to your existing authenticate_for_stream(auth) function
        return broker.reauthenticate_stream_tokens()  # <-- implement this to call authenticate_for_stream

    # you need initial CST/XST/accountId accessible; add getters on your broker:
    cst = broker.session_tokens["CST"]
    xst = broker.session_tokens["XST"]
    account_id = broker.session_tokens["ACCOUNT_ID"]

    poller = _RestPoller(base, epic, timeframe_sec, broker, on_bar, cst, xst, account_id, api_key, reauth_fn)
    client, sub = poller.start()
    # store poller instance somewhere so stop_streaming can call poller.stop()
    client["_poller"] = poller
    return client, sub

def stop_streaming(client, subscription):
    # Lightstreamer or REST_POLL
    if isinstance(client, dict) and client.get("mode") == "REST_POLL":
        poller = client.get("_poller")
        if poller:
            poller.stop()
        return
    try:
        client.unsubscribe(subscription)
    except Exception:
        pass
    try:
        client.disconnect()
    except Exception:
        pass

def start_streaming(ls_endpoint: str, account_id: str, CST: str, XST: str,
                    epic: str, timeframe_sec: int, on_bar: "OnBar",
                    broker=None) -> Tuple[Any, Any]:
    """
    Try Lightstreamer if lib present, else REST polling.
    Returns (client, subscription) handles for stop_streaming().
    """
    use_poll = os.getenv("USE_REST_POLLING", "false").lower() == "true"
    if use_poll:
        return _start_rest_poll(epic, timeframe_sec, broker, on_bar)

    try:
        from lightstreamer.client import LSClient, Subscription
    except Exception:
        # library not installed → fallback
        return _start_rest_poll(epic, timeframe_sec, broker, on_bar)

    # ✅ Correct LS auth: adapter set "DEFAULT", then set user/password
    ls_client = LSClient(ls_endpoint, "DEFAULT")
    # Some SDKs expose connection options; others set at client level:
    try:
        # Python SDK v1 style:
        ls_client.connectionOptions.setUser(account_id)
        ls_client.connectionOptions.setPassword(f"CST-{CST}|XST-{XST}")
    except Exception:
        # Older style fallback (if attributes differ)
        ls_client.set_user(account_id)
        ls_client.set_password(f"CST-{CST}|XST-{XST}")

    ls_client.connect()

    bb = BarBuilder(timeframe_sec)

    def on_item_update(item_update):
        try:
            values = item_update.getFields()
            bid = values.get("BID")
            ofr = values.get("OFR") or values.get("OFFER") or values.get("ASK")
            if bid is None or ofr is None:
                return
            bid = float(bid); ofr = float(ofr)
            mid = (bid + ofr) / 2.0
            finished = bb.on_tick(time.time(), mid)
            if finished:
                on_bar(finished)
        except Exception as e:
            print("LS parse error:", e)

    sub = Subscription(
        mode="MERGE",
        items=[f"MARKET:{epic}"],
        fields=["BID", "OFR"]  # "OFR" is IG's name for offer/ask on LS
    )
    sub.addListener({"onItemUpdate": on_item_update})
    ls_client.subscribe(sub)

    return ls_client, sub
