# src/ig_adapter.py
import os
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
        self.base = (
            "https://demo-api.ig.com/gateway/deal"
            if auth.account_type.upper() == "DEMO"
            else "https://api.ig.com/gateway/deal"
        )
        # base headers (VERSION set per endpoint)
        self.base_headers = {
            "X-IG-API-KEY": auth.api_key,
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json; charset=UTF-8",
        }
        self.account_id: str | None = None
        self.account_currency: str | None = None
        self.selected_account_type: str | None = None  # "SPREADBET" | "CFD"

        # ✅ keep current streaming/trading tokens handy
        self.session_tokens: dict = {
            "CST": None,
            "XST": None,
            "ACCOUNT_ID": None,
            "LS_ENDPOINT": None,
        }
    
    # ---- helpers ----
    def _headers(self, version: int, extra: dict | None = None) -> dict:
        h = dict(self.base_headers)
        h["VERSION"] = str(version)
        if extra:
            h.update(extra)
        return h

    def _update_tokens_from_resp(self, r: requests.Response):
        cst, xst = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
        if cst and xst:
            self.base_headers.update({"CST": cst, "X-SECURITY-TOKEN": xst})
            # mirror into session_tokens
            self.session_tokens["CST"] = cst
            self.session_tokens["XST"] = xst

    # ---- session/account selection ----
    def connect(self):
        """Login, fetch accounts, select SPREADBET/CFD by IG_ACCOUNT_KIND, set IG-ACCOUNT-ID."""
        # 1) login (v2)
        r = requests.post(
            f"{self.base}/session",
            json={"identifier": self.auth.username, "password": self.auth.password},
            headers=self._headers(2),
        )
        r.raise_for_status()
        self._update_tokens_from_resp(r)

        # 2) accounts (v1)
        a = requests.get(f"{self.base}/accounts", headers=self._headers(1))
        a.raise_for_status()
        accounts = a.json().get("accounts", [])
        if not accounts:
            raise RuntimeError("No IG accounts returned")

        want_kind = (os.getenv("IG_ACCOUNT_KIND", "SPREADBET") or "SPREADBET").upper()
        chosen = next((acc for acc in accounts if (acc.get("accountType") or "").upper() == want_kind), None)
        if chosen is None:
            chosen = next((acc for acc in accounts if acc.get("preferred")), None) or accounts[0]

        self.account_id = chosen["accountId"]
        self.selected_account_type = chosen.get("accountType") or want_kind
        self.account_currency = chosen.get("currency") or chosen.get("accountCurrency") or "GBP"

        # trading endpoints require IG-ACCOUNT-ID
        self.base_headers.update({"IG-ACCOUNT-ID": self.account_id})
        self.session_tokens["ACCOUNT_ID"] = self.account_id

        # (optional) prime LS endpoint now so it’s available immediately
        try:
            self._prime_stream_tokens_once()
        except Exception:
            # non-fatal; LS can still be fetched lazily later
            pass

    def _prime_stream_tokens_once(self):
        """
        Fetch Lightstreamer endpoint via GET /session?fetchSessionTokens=true (v1).
        Keeps current CST/XST; some regions need a fresh GET after login.
        """
        h = self._headers(1)
        r = requests.get(f"{self.base}/session?fetchSessionTokens=true", headers=h)
        r.raise_for_status()
        data = r.json()
        ls_endpoint = data.get("lightstreamerEndpoint")
        if not ls_endpoint:
            # fallback by account type
            ls_endpoint = (
                "https://demo-apd.marketdatasystems.com"
                if self.auth.account_type.upper() == "DEMO"
                else "https://apd.marketdatasystems.com"
            )
        self.session_tokens["LS_ENDPOINT"] = ls_endpoint

    # ---- streaming token helpers (for LS and REST poll reauth) ----
    def authenticate_stream_tokens(self):
        """
        Re-login (POST /session) to refresh CST/XST, then GET /session?fetchSessionTokens=true for LS endpoint.
        Also ensures we still have a valid account id selected.
        Returns: (CST, XST, ls_endpoint, account_id)
        """
        # login again to refresh tokens
        r = requests.post(
            f"{self.base}/session",
            json={"identifier": self.auth.username, "password": self.auth.password},
            headers=self._headers(2),
        )
        r.raise_for_status()
        self._update_tokens_from_resp(r)

        # fetch LS endpoint
        self._prime_stream_tokens_once()

        # ensure account id remains present in headers (some regions require it)
        if not self.account_id:
            a = requests.get(f"{self.base}/accounts", headers=self._headers(1))
            a.raise_for_status()
            accounts = a.json().get("accounts", [])
            self.account_id = (next((acc for acc in accounts if acc.get("preferred")), None) or accounts[0])["accountId"]
            self.base_headers.update({"IG-ACCOUNT-ID": self.account_id})
            self.session_tokens["ACCOUNT_ID"] = self.account_id

        return (
            self.session_tokens["CST"],
            self.session_tokens["XST"],
            self.session_tokens["LS_ENDPOINT"],
            self.session_tokens["ACCOUNT_ID"],
        )

    def reauthenticate_stream_tokens(self):
        """
        Wrapper used by the REST poller on 403. Updates internal headers.
        Returns: (CST, XST, ls_endpoint, account_id)
        """
        CST, XST, LS, ACC = self.authenticate_stream_tokens()
        # base_headers already updated by _update_tokens_from_resp/connect path
        return CST, XST, LS, ACC

    def get_stream_context(self):
        """Convenience for start_streaming(...)."""
        return (
            self.session_tokens["CST"],
            self.session_tokens["XST"],
            self.session_tokens["LS_ENDPOINT"],
            self.session_tokens["ACCOUNT_ID"],
        )

    # ---- markets ----
    def market_details(self, epic: str):
        """Return market detail JSON. Try v4 -> v3 -> v2."""
        r = requests.get(f"{self.base}/markets/{epic}", headers=self._headers(4))
        if r.status_code in (400, 404):
            r = requests.get(f"{self.base}/markets/{epic}", headers=self._headers(3))
        if r.status_code in (400, 404):
            r = requests.get(f"{self.base}/markets/{epic}", headers=self._headers(2))
        r.raise_for_status()
        return r.json()

    def market_details_by_epic(self, epic: str, full: bool = True):
        """Bulk markets endpoint; v2 supports filter=ALL for richer instrument info."""
        params = {"epics": epic}
        if full:
            params["filter"] = "ALL"
        r = requests.get(f"{self.base}/markets", params=params, headers=self._headers(2))
        if r.status_code in (400, 404):
            r = requests.get(f"{self.base}/markets", params={"epics": epic}, headers=self._headers(1))
        r.raise_for_status()
        arr = r.json().get("marketDetails") or r.json().get("markets") or []
        return arr[0] if arr else {}

    def prices_snapshot(self, epic: str) -> float:
        """Mid price from /markets snapshot."""
        md = self.market_details(epic)
        snap = md.get("snapshot", {})
        bid = float(snap.get("bid", 0.0) or 0.0)
        ask = float(snap.get("offer", 0.0) or 0.0)
        return (bid + ask) / 2 if bid and ask else float(snap.get("midOpen", 0.0) or 0.0)

    # ---- dealing ----
    def _resolve_expiry_for_account(self) -> str:
        """Spread-bet daily-funded = 'DFB'; CFD cash = '-'."""
        return "DFB" if (self.selected_account_type or "").upper() == "SPREADBET" else "-"

    def open_positions(self):
        r = requests.get(f"{self.base}/positions", headers=self._headers(2))
        r.raise_for_status()
        return r.json().get("positions", [])

    def place_otc_market(
        self,
        epic: str,
        size: float,
        direction: str,
        stop_distance: float,
        limit_distance: float,
        guaranteed_stop: bool = False,
        currency_code: str | None = None,
    ):
        payload = {
            "epic": epic,
            "expiry": self._resolve_expiry_for_account(),  # key for SB vs CFD
            "direction": direction.upper(),
            "size": size,
            "orderType": "MARKET",
            "forceOpen": True,
            "guaranteedStop": bool(guaranteed_stop),
            "stopDistance": float(stop_distance),
            "limitDistance": float(limit_distance),
            "currencyCode": currency_code or self.account_currency or "GBP",
        }
        r = requests.post(f"{self.base}/positions/otc", json=payload, headers=self._headers(2))
        if r.status_code >= 400:
            return {"ok": False, "error": r.text}

        deal_ref = r.json().get("dealReference")
        c = requests.get(f"{self.base}/confirms/{deal_ref}", headers=self._headers(1))
        return {"ok": c.status_code < 400, "confirm": c.json() if c.ok else r.text}
