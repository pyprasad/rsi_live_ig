# scripts/smoke_trade.py
import os, sys, json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
from src.ig_adapter import IGAuth, IGBroker
from src.preflight import preflight_can_trade

EPIC = os.getenv("SMOKE_EPIC", "IX.D.SPTRD.DAILY.IP")
SIZE = float(os.getenv("SMOKE_SIZE", "1.0"))

def round_up_to_step(x, s):
    if s <= 0: return x
    k = int((x + 1e-9) / s)
    return (k if abs(k*s - x) <= 1e-9 else k+1) * s

def main():
    load_dotenv()
    print("Using account type:", os.getenv("IG_ACCOUNT_TYPE"))
    print("Username:", os.getenv("IG_USERNAME"))
    print("API key present:", bool(os.getenv("IG_API_KEY")))

    broker = IGBroker(IGAuth(
        api_key=os.getenv("IG_API_KEY",""),
        username=os.getenv("IG_USERNAME",""),
        password=os.getenv("IG_PASSWORD",""),
        account_type=os.getenv("IG_ACCOUNT_TYPE","DEMO")
    ))
    broker.connect()
    print("Selected IG account:", getattr(broker, "account_id", "?"),
          getattr(broker, "selected_account_type", "?"),
          getattr(broker, "account_currency", "?"))
    print("EPIC:", EPIC)

    # preflight (market open / size / basic dealing rules)
    pf = preflight_can_trade(broker, EPIC, SIZE)
    if not pf.ok:
        print("❌ Preflight failed:", pf.reason); return

    # read dealing rules & build sensible distances
    md = broker.market_details(EPIC)
    rules = md.get("dealingRules", {})
    min_norm = (rules.get("minNormalStopOrLimitDistance", {}) or {}).get("value", 0)
    min_stop = float(min_norm or (rules.get("minStopOrLimitDistance", {}) or {}).get("value", 0) or 0.0)
    step     = float((rules.get("minStepDistance", {}) or {}).get("value", 0) or
                     (rules.get("stopDistance", {}) or {}).get("step", 0) or 0.0)

    FALLBACK_MIN_STOP, FALLBACK_STEP = 20.0, 0.1
    eff_min_stop = min_stop if min_stop > 0 else FALLBACK_MIN_STOP
    eff_step     = step if step > 0 else FALLBACK_STEP
    stop_d  = round_up_to_step(eff_min_stop, eff_step)
    limit_d = round_up_to_step(max(eff_min_stop*2, 2*eff_step), eff_step)
    print(f"Using min_stop={min_stop}, step={step} → effective stop_d={stop_d}, limit_d={limit_d}")

    res = broker.place_otc_market(EPIC, SIZE, "BUY", stop_d, limit_d, guaranteed_stop=False)
    print("Place order response:")
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
