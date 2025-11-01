import pandas as pd
import numpy as np
from pathlib import Path
import yaml
from strategy_core import rsi, rsi_cross_up, compute_sl_tp_fixed_rr, compute_tp_gapN

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def session_filter(df: pd.DataFrame, start="09:30", end="16:00"):
    df = df[df.index.dayofweek < 5]
    return df.between_time(start, end)

def load_csv_robust(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "Datetime" not in df.columns: raise ValueError("Expected 'Datetime' column")
    dt = pd.to_datetime(df["Datetime"], errors="coerce", utc=True)
    df = df.assign(Datetime=dt).dropna(subset=["Datetime"])
    df["Datetime"] = df["Datetime"].dt.tz_convert("America/New_York")
    df = df.set_index("Datetime")
    df.columns = [str(c).strip().title() for c in df.columns]
    needed = ["Open", "High", "Low", "Close"]
    df[needed] = df[needed].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=needed)
    return df

def backtest(df: pd.DataFrame, mode: str, param: float):
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]
    df["RSI2"] = rsi(close, period=2)
    df["rsi_cross_up_10"] = rsi_cross_up(close, level=10, period=2)

    trades, in_trade = [], False
    entry_price = sl = tp = entry_time = None

    for i in range(2, len(df)):
        ts = df.index[i]
        if not in_trade:
            if bool(df["rsi_cross_up_10"].iat[i]):
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue
                if mode == "fixed":
                    pack = compute_sl_tp_fixed_rr(df, i, float(param))
                elif mode == "gapN":
                    pack = compute_tp_gapN(df, i, float(param))
                else:
                    raise ValueError("Unknown mode")
                if not pack: continue
                entry_price, sl, tp = pack["entry"], pack["sl"], pack["tp"]
                in_trade, entry_time = True, ts
        else:
            bar_low, bar_high = low.iat[i], high.iat[i]
            sl_hit, tp_hit = bar_low <= sl, bar_high >= tp
            if sl_hit or tp_hit:
                exit_reason = "SL" if sl_hit else "TP"
                exit_price = sl if sl_hit else tp
                pnl_pts = exit_price - entry_price
                trades.append({
                    "entry_time": entry_time, "entry": float(entry_price),
                    "exit_time": ts, "exit": float(exit_price),
                    "reason": exit_reason, "pnl_pts": float(pnl_pts),
                    "bars_held": i - df.index.get_loc(entry_time)
                })
                in_trade = False
                entry_price = sl = tp = entry_time = None

    if not trades:
        return ({"variant": mode, "param": param, "trades": 0, "win_rate_pct": 0.0, "pf": 0.0,
                 "total_pnl_pts": 0.0, "avg_bars_held": 0.0},
                pd.DataFrame(columns=["entry_time","entry","exit_time","exit","reason","pnl_pts","bars_held"]),
                pd.DataFrame({"Datetime": [], "equity_pts": []}))
    trades_df = pd.DataFrame(trades)
    wins, losses = trades_df.query("reason=='TP'"), trades_df.query("reason=='SL'")
    total_profit = wins["pnl_pts"].sum() if not wins.empty else 0.0
    total_loss   = -losses["pnl_pts"].sum() if not losses.empty else 0.0
    pf = (total_profit / total_loss) if total_loss > 0 else (np.inf if total_profit > 0 else 0.0)

    summary = {
        "variant": mode, "param": param,
        "trades": len(trades_df),
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 2),
        "pf": round(pf, 2),
        "total_pnl_pts": round(trades_df["pnl_pts"].sum(), 2),
        "avg_bars_held": round(trades_df["bars_held"].mean(), 2)
    }
    eq = trades_df.sort_values("exit_time").copy()
    eq["equity_pts"] = eq["pnl_pts"].cumsum()
    equity_df = eq[["exit_time","equity_pts"]].rename(columns={"exit_time":"Datetime"})
    return summary, trades_df, equity_df

def main():
    cfg = yaml.safe_load(open("configs/backtest_config.yaml"))
    df = load_csv_robust(cfg["data_path"])
    if cfg["session"]["use_us_equity_session"]:
        df = session_filter(df, cfg["session"]["start"], cfg["session"]["end"])
    fixed_summaries, gap_summaries = [], []
    for rr in cfg["fixed_rr_list"]:
        s, tdf, eq = backtest(df, "fixed", rr)
        fixed_summaries.append(s)
        tag = f"fixed_rr_{str(rr).replace('.','_')}"
        tdf.to_csv(f"results/trades_{tag}.csv", index=False)
        eq.to_csv(f"results/equity_{tag}.csv", index=False)
    for N in cfg["gapN_list"]:
        s, tdf, eq = backtest(df, "gapN", N)
        gap_summaries.append(s)
        tag = f"gapN_{N}"
        tdf.to_csv(f"results/trades_{tag}.csv", index=False)
        eq.to_csv(f"results/equity_{tag}.csv", index=False)
    pd.DataFrame(fixed_summaries).to_csv("results/summary_fixed_grid.csv", index=False)
    pd.DataFrame(gap_summaries).to_csv("results/summary_gapN_grid.csv", index=False)

if __name__ == "__main__":
    main()
