import time
import json
import threading
from sseclient import SSEClient
import requests

class IGStreamClient:
    def __init__(self, api_key, username, password, account_type="DEMO"):
        self.api_key = api_key
        self.username = username
        self.password = password
        self.account_type = account_type.upper()
        self.rest_base = "https://demo-api.ig.com/gateway/deal" if self.account_type == "DEMO" \
                         else "https://api.ig.com/gateway/deal"
        self.stream_url = "https://demo-apd.marketdatasystems.com" if self.account_type == "DEMO" \
                          else "https://apd.marketdatasystems.com"
        self.headers = {"X-IG-API-KEY": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json"}
        self.cst = None
        self.xst = None
        self.account_id = None
        self.streaming_api_key = None

    def connect(self):
        # --- Step 1: Login (REST) ---
        r = requests.post(f"{self.rest_base}/session",
                          json={"identifier": self.username, "password": self.password},
                          headers=self.headers)
        r.raise_for_status()
        self.cst = r.headers["CST"]
        self.xst = r.headers["X-SECURITY-TOKEN"]
        self.headers.update({"CST": self.cst, "X-SECURITY-TOKEN": self.xst})
        # --- Step 2: Get accounts ---
        accs = requests.get(f"{self.rest_base}/accounts", headers=self.headers).json()
        for a in accs.get("accounts", []):
            if a.get("preferred"):
                self.account_id = a["accountId"]
                break
        # --- Step 3: Obtain streaming creds ---
        resp = requests.get(f"{self.rest_base}/session?fetchSessionTokens=true",
                            headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        self.streaming_api_key = data["accountInfo"]["lightstreamerEndpoint"]

    def listen_ticks(self, epic, callback):
        """
        Subscribes to L1 price stream for the given EPIC.
        callback signature: callback(timestamp, midprice)
        """
        url = f"{self.stream_url}/lightstreamer/streaming/Price/{epic}"
        headers = {
            "X-IG-API-KEY": self.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.xst,
            "Accept": "text/event-stream"
        }
        messages = SSEClient(url, headers=headers)
        for msg in messages:
            if not msg.data or msg.data.startswith("PROBE"):  # heartbeat
                continue
            try:
                data = json.loads(msg.data)
                bid = float(data["values"].get("BID", 0))
                ask = float(data["values"].get("OFR", 0))
                mid = (bid + ask) / 2
                ts = time.time()
                callback(ts, mid)
            except Exception as e:
                print("⚠️ Stream parse error:", e)
                continue

    def start_background(self, epic, callback):
        t = threading.Thread(target=self.listen_ticks, args=(epic, callback), daemon=True)
        t.start()
        return t
