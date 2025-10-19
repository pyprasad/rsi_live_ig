import requests
from dataclasses import dataclass

@dataclass
class IGAuth:
    api_key: str
    username: str
    password: str
    account_type: str  # "DEMO" | "LIVE"

class IGBroker:
    def __init__(self, auth: IGAuth):
        self.auth = auth
        self.base = "https://demo-api.ig.com/gateway/deal" if auth.account_type.upper()=="DEMO" \
                    else "https://api.ig.com/gateway/deal"
        self.h = {"X-IG-API-KEY": auth.api_key, "Content-Type":"application/json", "Accept":"application/json"}

    def _update_tokens(self, r):
        cst, xst = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
        if cst and xst:
            self.h.update({"CST": cst, "X-SECURITY-TOKEN": xst})

    def connect(self):
        r = requests.post(f"{self.base}/session",
                          json={"identifier": self.auth.username, "password": self.auth.password},
                          headers=self.h)
        r.raise_for_status()
        self._update_tokens(r)

    def open_positions(self):
        r = requests.get(f"{self.base}/positions", headers=self.h)
        r.raise_for_status()
        return r.json().get("positions", [])

    def market_details(self, epic: str):
        r = requests.get(f"{self.base}/markets/{epic}", headers=self.h)
        r.raise_for_status()
        return r.json()

    def place_otc_market(self, epic: str, size: float, direction: str,
                         stop_distance: float, limit_distance: float,
                         guaranteed_stop: bool=False):
        payload = {
            "epic": epic, "expiry": "-", "direction": direction.upper(),
            "size": size, "orderType": "MARKET", "forceOpen": True,
            "guaranteedStop": bool(guaranteed_stop),
            "stopDistance": float(stop_distance),
            "limitDistance": float(limit_distance)
        }
        r = requests.post(f"{self.base}/positions/otc", json=payload, headers=self.h)
        if r.status_code >= 400:
            return {"ok": False, "error": r.text}
        deal_ref = r.json().get("dealReference")
        c = requests.get(f"{self.base}/confirms/{deal_ref}", headers=self.h)
        return {"ok": c.status_code < 400, "confirm": c.json() if c.ok else r.text}
