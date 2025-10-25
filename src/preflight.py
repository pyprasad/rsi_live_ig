# src/preflight.py
from dataclasses import dataclass

@dataclass
class PreflightResult:
    ok: bool
    reason: str = ""

def preflight_can_trade(broker, epic: str, size: float) -> PreflightResult:
    try:
        md = broker.market_details(epic)
        snap = md.get("snapshot", {})
        rules = md.get("dealingRules", {})

        status = snap.get("marketStatus", "UNKNOWN")
        if status not in ("TRADEABLE", "OPEN"):
            return PreflightResult(False, f"Market status={status}")

        min_size = rules.get("minDealSize", {}).get("value")
        if min_size is not None and float(size) < float(min_size):
            return PreflightResult(False, f"Size {size} < minDealSize {min_size}")

        # Accept 0 or missing; only reject if negative
        raw_min_stop = rules.get("minStopOrLimitDistance", {}).get("value", 0)
        raw_step     = (rules.get("stopDistance", {}) or {}).get("step", 0)

        try:
            min_stop = float(raw_min_stop or 0.0)
        except Exception:
            min_stop = 0.0
        try:
            step_stop = float(raw_step or 0.0)
        except Exception:
            step_stop = 0.0

        if min_stop < 0 or step_stop < 0:
            return PreflightResult(False, f"Invalid dealing rules (min_stop={min_stop}, step={step_stop})")

        # Auth sanity
        _ = broker.open_positions()
        return PreflightResult(True, "")
    except Exception as e:
        return PreflightResult(False, f"Preflight error: {e}")
