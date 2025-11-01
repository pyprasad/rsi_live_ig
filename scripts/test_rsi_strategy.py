#!/usr/bin/env python3
"""
RSI Strategy Tester
Tests RSI strategy with multiple Take Profit levels.

Strategy:
- RSI(14): Buy when crosses above 30, Sell when crosses below 70
- Test TP levels: 5, 10, 15 points
"""

from pathlib import Path
import pandas as pd
import yaml


def load_config():
    """Load configuration."""
    config_path = Path(__file__).parent.parent / "configs" / "rsi_test_config.yaml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def calculate_rsi(prices, period=14):
    """Calculate RSI indicator."""
    deltas = prices.diff()
    gain = deltas.where(deltas > 0, 0.0)
    loss = -deltas.where(deltas < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def backtest_strategy(df, rsi_period, buy_level, sell_level, tp_points, sl_points=None):
    """
    Backtest RSI strategy with given parameters.

    Args:
        df: DataFrame with OHLC data
        rsi_period: RSI period (e.g., 14)
        buy_level: RSI level to buy (e.g., 30)
        sell_level: RSI level to sell (e.g., 70)
        tp_points: Take profit in points
        sl_points: Stop loss in points (optional)

    Returns:
        dict with results
    """
    df = df.copy()

    # Calculate RSI
    df['RSI'] = calculate_rsi(df['Close'], period=rsi_period)
    df['RSI_prev'] = df['RSI'].shift(1)

    # Generate signals
    df['buy_signal'] = (df['RSI_prev'] <= buy_level) & (df['RSI'] > buy_level)
    df['sell_signal'] = (df['RSI_prev'] >= sell_level) & (df['RSI'] < sell_level)

    # Track trades
    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_idx = None
    take_profit = None
    stop_loss = None

    for i in range(rsi_period, len(df)):
        row = df.iloc[i]

        # Check exit conditions if in position
        if in_position:
            exit_price = None
            exit_reason = None

            if position_type == "LONG":
                # Check TP and SL
                if row['High'] >= take_profit:
                    exit_price = take_profit
                    exit_reason = "TP"
                elif sl_points and row['Low'] <= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "SL"

            elif position_type == "SHORT":
                # Check TP and SL
                if row['Low'] <= take_profit:
                    exit_price = take_profit
                    exit_reason = "TP"
                elif sl_points and row['High'] >= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "SL"

            # Record trade if exited
            if exit_price:
                if position_type == "LONG":
                    pnl = exit_price - entry_price
                else:
                    pnl = entry_price - exit_price

                trades.append({
                    'entry_time': df.iloc[entry_idx]['Datetime'],
                    'exit_time': row['Datetime'],
                    'type': position_type,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'exit_reason': exit_reason
                })

                in_position = False
                position_type = None

        # Check entry signals if not in position
        if not in_position:
            if row['buy_signal']:
                # LONG entry
                entry_price = row['Close']
                entry_idx = i
                position_type = "LONG"
                take_profit = entry_price + tp_points
                stop_loss = entry_price - sl_points if sl_points else None
                in_position = True

            elif row['sell_signal']:
                # SHORT entry
                entry_price = row['Close']
                entry_idx = i
                position_type = "SHORT"
                take_profit = entry_price - tp_points
                stop_loss = entry_price + sl_points if sl_points else None
                in_position = True

    # Calculate statistics
    if not trades:
        return None

    trades_df = pd.DataFrame(trades)
    total_pnl = trades_df['pnl'].sum()
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]

    win_rate = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0
    avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
    avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0

    profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 0

    return {
        'total_trades': len(trades_df),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'trades': trades_df
    }


def main():
    print("=" * 70)
    print("RSI STRATEGY TESTER")
    print("=" * 70)
    print()

    # Load config
    config = load_config()

    epic = config['data']['epic']
    timeframe = config['data']['timeframe']
    output_folder = config['data']['output_folder']

    rsi_period = config['strategy']['rsi_period']
    buy_level = config['strategy']['buy_level']
    sell_level = config['strategy']['sell_level']
    tp_levels = config['strategy']['take_profit_levels']
    sl_points = config['strategy'].get('stop_loss')

    results_folder = Path(config['results']['output_folder'])
    results_folder.mkdir(parents=True, exist_ok=True)

    print("Strategy Configuration:")
    print(f"  RSI Period: {rsi_period}")
    print(f"  Buy Level: RSI crosses above {buy_level}")
    print(f"  Sell Level: RSI crosses below {sell_level}")
    print(f"  Stop Loss: {sl_points} points" if sl_points else "  Stop Loss: None")
    print(f"  TP Levels to Test: {tp_levels}")
    print()

    # Find data file
    epic_clean = epic.replace('.', '_')
    data_file = Path(output_folder) / f"{epic_clean}_{timeframe}.csv"

    if not data_file.exists():
        print(f"❌ Data file not found: {data_file}")
        print(f"\nPlease run: python scripts/fetch_data_simple.py")
        return

    print(f"📂 Loading data: {data_file}")
    df = pd.read_csv(data_file)
    df['Datetime'] = pd.to_datetime(df['Datetime'])

    print(f"✅ Loaded {len(df)} candles")
    print(f"   From: {df['Datetime'].min()}")
    print(f"   To:   {df['Datetime'].max()}")
    print()

    # Test each TP level
    print("=" * 70)
    print("TESTING TAKE PROFIT LEVELS")
    print("=" * 70)
    print()

    all_results = []

    for tp in tp_levels:
        print(f"Testing TP = {tp} points...")

        result = backtest_strategy(
            df,
            rsi_period=rsi_period,
            buy_level=buy_level,
            sell_level=sell_level,
            tp_points=tp,
            sl_points=sl_points
        )

        if result is None:
            print(f"  ❌ No trades generated\n")
            continue

        print(f"  ✅ Trades: {result['total_trades']}")
        print(f"     Win Rate: {result['win_rate']:.1f}%")
        print(f"     Total P&L: {result['total_pnl']:+.2f} points")
        print(f"     Profit Factor: {result['profit_factor']:.2f}")
        print()

        all_results.append({
            'TP': tp,
            'Trades': result['total_trades'],
            'Wins': result['wins'],
            'Losses': result['losses'],
            'Win_Rate': f"{result['win_rate']:.1f}%",
            'Total_PnL': f"{result['total_pnl']:+.2f}",
            'Avg_Win': f"{result['avg_win']:+.2f}",
            'Avg_Loss': f"{result['avg_loss']:+.2f}",
            'Profit_Factor': f"{result['profit_factor']:.2f}"
        })

        # Save trades
        trades_file = results_folder / f"trades_TP{tp}.csv"
        result['trades'].to_csv(trades_file, index=False)
        print(f"  💾 Trades saved: {trades_file}\n")

    # Summary comparison
    if all_results:
        print("=" * 70)
        print("SUMMARY COMPARISON")
        print("=" * 70)
        print()

        summary_df = pd.DataFrame(all_results)
        print(summary_df.to_string(index=False))
        print()

        # Save summary
        summary_file = results_folder / "summary.csv"
        summary_df.to_csv(summary_file, index=False)
        print(f"💾 Summary saved: {summary_file}")

        # Find best strategy
        summary_df['PnL_numeric'] = summary_df['Total_PnL'].astype(float)
        best_idx = summary_df['PnL_numeric'].idxmax()
        best_tp = summary_df.loc[best_idx, 'TP']
        best_pnl = summary_df.loc[best_idx, 'Total_PnL']

        print()
        print("🏆 Best Strategy:")
        print(f"   TP = {best_tp} points")
        print(f"   Total P&L = {best_pnl} points")

    print()
    print("=" * 70)
    print("✅ COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
