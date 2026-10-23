"""
Backtest the RSI-14 option-buying strategy on every enabled instrument in config.py.

Usage:
    python backtest.py                          # all instruments, last ~60 days of 5-min data (Yahoo Finance)
    python backtest.py --only NIFTY,GOLDM       # just some instruments
    python backtest.py --mode momentum          # try the other RSI reading
    python backtest.py --html report.html       # also build the dashboard web page
    python backtest.py --csv-dir data/          # use your own candles: data/NIFTY.csv, data/GOLDM.csv ...

IMPORTANT: option premiums are ESTIMATED from the underlying's moves using delta.
Real premiums also lose value to time decay, so real results are usually WORSE.
Commodity signals use international prices (COMEX/NYMEX) converted to rupees.
"""
import argparse
from datetime import timedelta

import pandas as pd

import config
import data
import strategy


def run(df: pd.DataFrame, key: str, inst: dict, fx: pd.Series) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = strategy.add_signals(df)
    df = df[[strategy.in_session(ts, inst) for ts in df.index]]
    rows = list(df.itertuples())
    units = inst["units_per_lot"] * inst["lots"]
    sq_off_bar_start = (pd.Timestamp(inst["square_off"]) - timedelta(minutes=5)).time()

    trades, i = [], 0
    day_count, day_pnl, cur_day = 0, 0.0, None
    while i < len(rows) - 1:
        bar, nxt = rows[i], rows[i + 1]
        d = bar.Index.date()
        if d != cur_day:
            cur_day, day_count, day_pnl = d, 0, 0.0
        if not (bar.signal in ("CE", "PE") and nxt.Index.date() == d and strategy.in_entry_window(nxt.Index, inst)
                and day_count < config.MAX_TRADES_PER_DAY and day_pnl > -config.DAILY_MAX_LOSS_RS):
            i += 1
            continue

        side, sign = bar.signal, (1 if bar.signal == "CE" else -1)
        delta = strategy.delta_for(d, inst)
        qf = strategy.quote_factor(inst, data.usdinr_on(fx, d))
        sl, tg = strategy.sl_target(inst, bar.atr, delta, qf)
        if sl <= 0:
            i += 1
            continue
        entry = nxt.open

        exit_pts, reason, exit_time, j = None, None, None, i + 1
        while j < len(rows) and rows[j].Index.date() == d:
            b = rows[j]
            worst = sign * ((b.low if side == "CE" else b.high) - entry) * delta * qf
            best = sign * ((b.high if side == "CE" else b.low) - entry) * delta * qf
            if worst <= -sl:                    # both touched in one candle -> assume stop-loss first
                exit_pts, reason = -sl, "stop-loss"
            elif best >= tg:
                exit_pts, reason = tg, "target"
            elif b.Index.time() >= sq_off_bar_start or j == len(rows) - 1 or rows[j + 1].Index.date() != d:
                exit_pts, reason = sign * (b.close - entry) * delta * qf, "time exit"
            if reason:
                exit_time = b.Index + timedelta(minutes=5)
                break
            j += 1

        pnl = exit_pts * units - inst["cost_rs"]
        exp = strategy.expiry_for(d, inst)
        trades.append({
            "instrument": key, "date": d, "signal_candle": bar.Index, "entry_time": nxt.Index, "side": side,
            "strike": strategy.pick_strike(entry, side, d, inst), "expiry": exp,
            "expiry_day": exp == d, "rsi_at_signal": round(bar.rsi, 1), "underlying_entry": round(entry, 2),
            "sl_points": sl, "target_points": tg, "exit_time": exit_time, "exit_reason": reason,
            "premium_points": round(exit_pts, 2), "lots": inst["lots"], "units": units, "pnl_rs": round(pnl, 0),
        })
        day_count += 1
        day_pnl += pnl
        i = j
    return pd.DataFrame(trades)


def summary_line(key: str, inst: dict, t: pd.DataFrame, df: pd.DataFrame) -> str:
    if df.empty:
        return f"{inst['name']:<13} no data downloaded"
    if t.empty:
        return f"{inst['name']:<13} {0:>4} trades"
    eq = t.pnl_rs.cumsum()
    return (f"{inst['name']:<13} {len(t):>4} trades  win {(t.pnl_rs > 0).mean():>4.0%}  "
            f"P&L Rs {t.pnl_rs.sum():>10,.0f}  max DD Rs {(eq - eq.cummax()).min():>10,.0f}")


def run_all(only=None, csv_dir=None):
    fx = data.usdinr_series(csv_dir)
    results = {}
    for key, inst in config.enabled_instruments().items():
        if only and key not in only:
            continue
        try:
            df = data.load(key, inst, csv_dir)
        except Exception as e:
            print(f"{inst['name']}: data download failed ({e})")
            df = pd.DataFrame(columns=["open", "high", "low", "close"])
        results[key] = {"inst": inst, "data": df, "trades": run(df, key, inst, fx)}
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="comma-separated instrument keys, e.g. NIFTY,SENSEX,GOLDM")
    p.add_argument("--mode", choices=["reversal", "momentum"], help="override STRATEGY_MODE")
    p.add_argument("--html", help="also write the dashboard web page to this path, e.g. report.html")
    p.add_argument("--csv-dir", help="folder with <KEY>.csv candle files instead of downloading")
    a = p.parse_args()
    if a.mode:
        config.STRATEGY_MODE = a.mode
    only = [s.strip().upper() for s in a.only.split(",")] if a.only else None
    res = run_all(only, a.csv_dir)

    print("\n" + "=" * 78)
    print(f"RSI-{config.RSI_PERIOD} option buying | {config.STRATEGY_MODE} mode | 5-min candles")
    print("=" * 78)
    for key, r in res.items():
        print(summary_line(key, r["inst"], r["trades"], r["data"]))
    allt = [r["trades"] for r in res.values() if not r["trades"].empty]
    if allt:
        allt = pd.concat(allt, ignore_index=True)
        print("-" * 78)
        print(f"{'All':<13} {len(allt):>4} trades  win {(allt.pnl_rs > 0).mean():>4.0%}  P&L Rs {allt.pnl_rs.sum():>10,.0f}")
        allt.to_csv("backtest_trades.csv", index=False)
        print("Saved trade list: backtest_trades.csv")
    print("\nPremiums are estimated with delta and ignore time decay, so treat this as optimistic.")
    if not any(not r["data"].empty for r in res.values()):
        if a.html:
            raise SystemExit("No market data could be downloaded for any instrument.")
    if a.html:
        import report
        report.write(res, a.html)
        print(f"Saved dashboard: {a.html}")
