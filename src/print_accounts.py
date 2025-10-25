# scripts/print_accounts.py
import os, sys, json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
import requests

def main():
    load_dotenv()
    base = "https://demo-api.ig.com/gateway/deal" if (os.getenv("IG_ACCOUNT_TYPE","DEMO").upper()=="DEMO") \
           else "https://api.ig.com/gateway/deal"
    h = {
        "X-IG-API-KEY": os.getenv("IG_API_KEY",""),
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json; charset=UTF-8",
        "VERSION": "2",
    }
    # login
    r = requests.post(f"{base}/session",
                      json={"identifier": os.getenv("IG_USERNAME",""), "password": os.getenv("IG_PASSWORD","")},
                      headers=h)
    r.raise_for_status()
    h.update({"CST": r.headers["CST"], "X-SECURITY-TOKEN": r.headers["X-SECURITY-TOKEN"]})
    # accounts (VERSION 1)
    h_acc = dict(h); h_acc["VERSION"] = "1"
    a = requests.get(f"{base}/accounts", headers=h_acc); a.raise_for_status()
    accs = a.json().get("accounts", [])
    print("All accounts:")
    print(json.dumps(accs, indent=2))
    pref = next((x for x in accs if x.get("preferred")), accs[0] if accs else None)
    print("\nPreferred account IG thinks:", pref and {"accountId": pref["accountId"], "accountType": pref.get("accountType"), "currency": pref.get("currency")})

if __name__ == "__main__":
    main()
