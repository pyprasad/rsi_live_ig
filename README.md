# RSI(2) Cross-Up → IG Live Trading (FTSE/S&P)

This repo turns your **exact** strategy into live trading on IG with Lightstreamer:
- **Entry:** RSI(2) crosses **up** through 10 (prev ≤10, current >10)
- **SL:** Lowest of last 2 lows
- **TP (fixed-R):** entry + (entry - SL) × **1.5**
- **One open trade at a time**
- Backtest grid runs fixed R:R in {1.0, 1.5, 2.0, 3.0} and Gap×N in {3,4,5,6}

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill IG creds
