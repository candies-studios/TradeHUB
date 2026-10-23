"""
Backtest the Nifty RSI-14 option-buying strategy on 5-minute Nifty data.

Usage:
    python backtest.py                 # downloads the last ~60 days of 5-min Nifty data (Yahoo Finance)
    python backtest.py --csv my.csv    # use your own data: columns datetime,open,high,low,close
    python backtest.py --mode momentum # try the other RSI reading without editing config.py

Outputs: a summary on screen, backtest_trades.csv, backtest_equity.png (if matplotlib is installed)
and, with --html report.html, a dashboard page you can open in any browser.

IMPORTANT: option premiums are ESTIMATED from Nifty moves using delta (see config.py).
Real premiums also lose value to time decay and change with volatility, so real
results will usually be somewhat WORSE than this estimate, especially on expiry day.
"""
import argparse
from datetime import timedelta

import pandas as pd

import config
import strategy


def load_yahoo() -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download("^NSEI", period="60d", interval="5m", progress=False, auto_adjust=False)
    if raw.empty:
        raise SystemExit("No data came back from Yahoo Finance. Try again later or use --csv.")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close"]]
    idx = df.index
    df.index = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
    return df


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = "datetime" if "datetime" in df.columns else df.columns[0]
    df[tcol] = pd.to_datetime(df[tcol])
    if df[tcol].dt.tz is not None:
        df[tcol] = df[tcol].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return df.set_index(tcol)[["open", "high", "low", "close"]].sort_index()


def run(df: pd.DataFrame) -> pd.DataFrame:
    df = strategy.add_signals(df)
    df = df[(df.index.time >= pd.Timestamp("09:15").time()) & (df.index.time < pd.Timestamp("15:30").time())]
    rows = list(df.itertuples())
    qty = config.LOT_SIZE * config.LOTS
    sq_off_bar_start = (pd.Timestamp(config.SQUARE_OFF_TIME) - timedelta(minutes=5)).time()

    trades = []
    i = 0
    day_count, day_pnl, cur_day = 0, 0.0, None
    while i < len(rows) - 1:
        bar, nxt = rows[i], rows[i + 1]
        d = bar.Index.date()
        if d != cur_day:
            cur_day, day_count, day_pnl = d, 0, 0.0

        can_trade = (
            bar.signal in ("CE", "PE")
            and nxt.Index.date() == d                      # enter on the next candle, same day
            and strategy.in_entry_window(nxt.Index)
            and day_count < config.MAX_TRADES_PER_DAY
            and day_pnl > -config.DAILY_MAX_LOSS_RS
        )
        if not can_trade:
            i += 1
            continue

        side = bar.signal
        sign = 1 if side == "CE" else -1
        delta = strategy.delta_for(d)
        entry_idx = nxt.open
        strike = strategy.pick_strike(entry_idx, side, d)

        exit_pts, reason, exit_time = None, None, None
        j = i + 1
        while j < len(rows) and rows[j].Index.date() == d:
            b = rows[j]
            worst = (b.low if side == "CE" else b.high) - entry_idx
            best = (b.high if side == "CE" else b.low) - entry_idx
            worst_prem = sign * worst * delta
            best_prem = sign * best * delta
            # If SL and target are both touched inside one candle we assume SL first (conservative).
            if worst_prem <= -config.STOP_LOSS_POINTS:
                exit_pts, reason = -config.STOP_LOSS_POINTS, "stop-loss"
            elif best_prem >= config.TARGET_POINTS:
                exit_pts, reason = config.TARGET_POINTS, "target"
            elif b.Index.time() >= sq_off_bar_start or j == len(rows) - 1 or rows[j + 1].Index.date() != d:
                exit_pts, reason = sign * (b.close - entry_idx) * delta, "time exit"
            if reason:
                exit_time = b.Index + timedelta(minutes=5)
                break
            j += 1

        pnl = exit_pts * qty - config.COST_PER_TRADE_RS
        trades.append({
            "date": d, "signal_candle": bar.Index, "entry_time": nxt.Index, "side": side,
            "strike": strike, "expiry": strategy.expiry_for(d), "expiry_day": strategy.is_expiry_day(d),
            "rsi_at_signal": round(bar.rsi, 1), "nifty_entry": round(entry_idx, 2),
            "exit_time": exit_time, "exit_reason": reason, "premium_points": round(exit_pts, 1),
            "lots": config.LOTS, "qty": qty, "pnl_rs": round(pnl, 0),
        })
        day_count += 1
        day_pnl += pnl
        i = j  # one position at a time; the exit candle's own signal can start the next trade
    return pd.DataFrame(trades)


def summarize(t: pd.DataFrame, df: pd.DataFrame):
    print("\n" + "=" * 60)
    print(f"Nifty RSI-{config.RSI_PERIOD} option buying | mode: {config.STRATEGY_MODE} | "
          f"{config.LOTS} lots x {config.LOT_SIZE}")
    print(f"Data: {df.index[0]:%d %b %Y} to {df.index[-1]:%d %b %Y}  ({df.index.normalize().nunique()} trading days)")
    print(f"SL {config.STOP_LOSS_POINTS} pts | Target {config.TARGET_POINTS} pts (option premium)")
    print("=" * 60)
    if t.empty:
        print("No trades were triggered in this period.")
        return
    wins, losses = t[t.pnl_rs > 0], t[t.pnl_rs <= 0]
    equity = t.pnl_rs.cumsum()
    max_dd = (equity - equity.cummax()).min()
    print(f"Trades:            {len(t)}  (calls {sum(t.side == 'CE')}, puts {sum(t.side == 'PE')})")
    print(f"Win rate:          {len(wins) / len(t):.0%}")
    print(f"Total P&L:         Rs {t.pnl_rs.sum():,.0f}  (after est. costs of Rs {config.COST_PER_TRADE_RS}/trade)")
    print(f"Average win:       Rs {wins.pnl_rs.mean():,.0f}" if len(wins) else "Average win:       -")
    print(f"Average loss:      Rs {losses.pnl_rs.mean():,.0f}" if len(losses) else "Average loss:      -")
    print(f"Max drawdown:      Rs {max_dd:,.0f}")
    print(f"Best / worst day:  Rs {t.groupby('date').pnl_rs.sum().max():,.0f} / "
          f"Rs {t.groupby('date').pnl_rs.sum().min():,.0f}")
    print("\nExit reasons:", t.exit_reason.value_counts().to_dict())
    exp = t[t.expiry_day]
    if len(exp):
        print(f"Expiry-day trades: {len(exp)}, P&L Rs {exp.pnl_rs.sum():,.0f}")
    print("\nReminder: premiums are estimated with delta and ignore time decay/IV,")
    print("so treat this as an optimistic first look, not a promise.")


def plot(t: pd.DataFrame):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(pd.to_datetime(t.exit_time), t.pnl_rs.cumsum(), color="#2563eb", lw=2)
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_title(f"Nifty RSI-{config.RSI_PERIOD} options — cumulative P&L (estimated)")
    ax.set_ylabel("Rs")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig("backtest_equity.png", dpi=120)
    print("Saved chart: backtest_equity.png")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="CSV of 5-minute Nifty candles: datetime,open,high,low,close")
    p.add_argument("--mode", choices=["reversal", "momentum"], help="override STRATEGY_MODE")
    p.add_argument("--html", help="also write a dashboard web page to this path, e.g. report.html")
    a = p.parse_args()
    if a.mode:
        config.STRATEGY_MODE = a.mode
    data = load_csv(a.csv) if a.csv else load_yahoo()
    trades = run(data)
    summarize(trades, data)
    if not trades.empty:
        trades.to_csv("backtest_trades.csv", index=False)
        print("Saved trade list: backtest_trades.csv")
        plot(trades)
    if a.html:
        import report
        report.write(trades, data, a.html)
        print(f"Saved dashboard: {a.html}")
