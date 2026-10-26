"""
Live alerts for every enabled strategy (RSI-14, EMA 9/20) and instrument in config.py
(Nifty, Sensex, Bank Nifty, Gold Mini, Silver Mini, Crude Oil, Natural Gas).
You place the orders yourself on Sahi.

On your Mac (double-click "Start Alerts.command", or):   python live_alerts.py
On GitHub every 5 minutes (the "RSI alerts" workflow):   python live_alerts.py --once
Test with your own candles:   python live_alerts.py --once --csv-dir data/   (data/NIFTY.csv, data/GOLDM.csv ...)
"""
import argparse
import json
import time as pytime
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import config
import data
import strategy

ALERT_LOG = "alerts_log.csv"
ALERT_COLS = ["alert_time", "instrument", "name", "strategy", "side", "strike", "expiry", "underlying", "rsi",
              "lots", "qty", "sl_pts", "target_pts"]


# ---------------- alert delivery ----------------
def send(msg: str, telegram: bool = True):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"\a\n[{stamp}] {msg}\n", flush=True)
    if telegram and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            import requests
            requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                          data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
        except Exception as e:  # never let an alert failure stop the scanner
            print(f"(Telegram failed: {e})")


def log_alert(row: dict, path: str = ALERT_LOG):
    """Append one alert to alerts_log.csv. The Paper log page on the website reads this file.
    An alerts_log.csv from the Nifty-only version is upgraded to the new columns first."""
    import csv

    p = Path(path)
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), [])
        if header and header != ALERT_COLS:
            old = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=ALERT_COLS)
                w.writeheader()
                for r in old:
                    r.setdefault("instrument", "NIFTY"); r.setdefault("name", "Nifty 50")
                    r.setdefault("underlying", r.get("nifty", ""))
                    r["strategy"] = r.get("strategy") or "RSI"
                    w.writerow({k: r.get(k, "") for k in ALERT_COLS})
    new_file = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ALERT_COLS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in ALERT_COLS})


def _price(v: float) -> str:
    return f"{v:,.2f}" if v < 1000 else f"{v:,.1f}"


def _pts(v: float) -> str:
    return f"{v:g}"


def now_ist() -> datetime:
    return pd.Timestamp.now(tz=data.IST).tz_localize(None).to_pydatetime()


def fetch_closed(key: str, inst: dict, csv_dir: str = None) -> pd.DataFrame:
    """Recent 5-min candles, without the candle that is still forming."""
    df = data.load(key, inst, csv_dir, period="5d")
    if csv_dir or df.empty:
        return df
    return df[df.index + timedelta(minutes=5) <= pd.Timestamp(now_ist())]


# ---------------- scanner (one per instrument) ----------------
class Scanner:
    """Watches one instrument for one strategy. Each has its own open position and daily limit."""

    def __init__(self, key: str, inst: dict, strat: str = "RSI", telegram: bool = True, fx: pd.Series = None):
        self.key, self.inst, self.strat, self.telegram, self.fx = key, inst, strat, telegram, fx
        self.tag = f"[{config.STRATEGY_NAMES.get(strat, strat)}]"
        self.last_seen = None
        self.day = None
        self.trades_today = 0
        self.pos = None
        self.squared_off = False
        self.on_alert = None

    def _new_day(self, d):
        self.day, self.trades_today, self.pos, self.squared_off = d, 0, None, False

    def process(self, df: pd.DataFrame):
        if df.empty:
            return
        df = strategy.add_signals(df, self.strat)
        new = df.tail(1) if self.last_seen is None else df[df.index > self.last_seen]
        for ts, bar in new.iterrows():
            if strategy.in_session(ts, self.inst):
                self._handle(ts, bar)
        self.last_seen = df.index[-1]

    def _handle(self, ts, bar):
        inst, name = self.inst, self.inst["name"]
        d = ts.date()
        if d != self.day:
            self._new_day(d)
        close_time = ts + timedelta(minutes=5)

        # 1) heads-up when the last alerted trade has probably hit its stop-loss or target
        if self.pos:
            p = self.pos
            sign = 1 if p["side"] == "CE" else -1
            worst = sign * ((bar.low if p["side"] == "CE" else bar.high) - p["spot"]) * p["k"]
            best = sign * ((bar.high if p["side"] == "CE" else bar.low) - p["spot"]) * p["k"]
            msg = "likely hit your STOP-LOSS" if worst <= -p["sl"] else "likely hit your TARGET" if best >= p["tg"] else None
            if msg:
                send(f"ℹ️ {self.tag} {name} {p['label']} has {msg} (estimated). Check your Sahi order book.", self.telegram)
                self.pos = None

        # 2) square-off reminder
        if close_time.time() >= strategy.t(inst["square_off"]) and not self.squared_off:
            self.squared_off = True
            if self.pos:
                send(f"⏰ {self.tag} {inst['square_off']} — EXIT {name} {self.pos['label']} now if it is still open.", self.telegram)
                self.pos = None
            return

        # 3) new signal
        side = bar.signal
        if side not in ("CE", "PE") or self.pos or not strategy.in_entry_window(close_time, inst):
            return
        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            return

        spot = float(bar.close)
        delta = strategy.delta_for(d, inst)
        qf = strategy.quote_factor(inst, data.usdinr_on(self.fx, d))
        sl, tg = strategy.sl_target(inst, bar.atr, delta, qf)
        if sl <= 0:
            return
        kind = "CALL" if side == "CE" else "PUT"
        if self.strat == "EMA":
            why = (f"Why: {config.EMA_FAST} EMA crossed {'above' if side == 'CE' else 'below'} the {config.EMA_SLOW} EMA "
                   f"on the {ts:%H:%M} candle ({_price(bar.ema_fast)} vs {_price(bar.ema_slow)}).")
        else:
            lv = strategy.levels()["call" if side == "CE" else "put"]
            why = (f"Why: RSI-{config.RSI_PERIOD} crossed {'above' if side == 'CE' else 'below'} {lv} "
                   f"(now {bar.rsi:.1f}) on the {ts:%H:%M} candle.")
        lots = inst["lots"]
        strike = strategy.pick_strike(spot, side, d, inst)
        expiry = strategy.expiry_for(d, inst)

        if inst["segment"] == "index":
            on_exp = expiry == d and config.ATM_ON_EXPIRY_DAY
            label = f"{strike} {side}"
            text = (f"🔔 {self.tag} BUY {self.key} {strike} {side} ({kind}) — {name}, {inst['exchange']}\n"
                    f"Expiry: {expiry:%a %d %b %Y}  |  {'ATM (expiry day)' if on_exp else f'{config.ITM_STRIKES} strike ITM'}\n"
                    f"Qty: {lots} lot{'s' if lots > 1 else ''} × {inst['units_per_lot']} = {lots * inst['units_per_lot']}\n"
                    f"{why} {name} at {_price(spot)}\n")
        else:
            label = f"{side} option"
            text = (f"🔔 {self.tag} BUY {name.upper()} {side} ({kind}) — MCX\n"
                    f"Strike: {config.ITM_STRIKES} strike in-the-money in Sahi's {self.key} option chain, nearest expiry\n"
                    f"Qty: {lots} lot{'s' if lots > 1 else ''}\n"
                    f"{why} International price {_price(spot)} ({inst['ticker']})\n")
        text += (f"After you buy: SL = your price − {_pts(sl)}, Target = your price + {_pts(tg)}"
                 f"{' (approx.)' if inst['segment'] == 'commodity' else ''}. Exit by {inst['square_off']}.")
        send(text, self.telegram)

        self.trades_today += 1
        self.pos = {"side": side, "spot": spot, "k": delta * qf, "sl": sl, "tg": tg, "label": label}
        if self.on_alert:
            self.on_alert({"alert_time": f"{close_time:%Y-%m-%d %H:%M}", "instrument": self.key, "name": name,
                           "strategy": self.strat,
                           "side": side, "strike": strike if strike is not None else "",
                           "expiry": f"{expiry:%Y-%m-%d}" if expiry else "nearest",
                           "underlying": round(spot, 2), "rsi": round(float(bar.rsi), 1), "lots": lots,
                           "qty": lots * inst["units_per_lot"], "sl_pts": sl, "target_pts": tg})


def _open_now(inst, now: datetime) -> bool:
    a, b = inst["session"]
    end = (datetime.combine(now.date(), strategy.t(b)) + timedelta(minutes=6)).time()
    return now.weekday() < 5 and strategy.t(a) <= now.time() <= end


# ---------------- one check (GitHub, every 5 minutes) ----------------
def once(csv_dir: str = None, state_file: str = ".alert_state.json"):
    """Check every instrument once, then exit. A small state file prevents duplicate alerts."""
    st_path = Path(state_file)
    try:
        state = json.loads(st_path.read_text())
    except Exception:
        state = {}
    if "last" in state:                       # state file from the Nifty-only version
        state = {"NIFTY": state}
    fx = data.usdinr_series(csv_dir)
    now = now_ist()
    for key, inst in config.enabled_instruments().items():
        if not csv_dir and not _open_now(inst, now):
            continue
        try:
            df = fetch_closed(key, inst, csv_dir)
        except Exception as e:
            print(f"{inst['name']}: data error, will retry next run ({e})")
            continue
        if df.empty:
            print(f"{inst['name']}: no candles yet.")
            continue
        last = df.index[-1]
        for strat in config.enabled_strategies():
            sk = f"{key}:{strat}"
            st = state.get(sk) or (state.get(key, {}) if strat == "RSI" else {})   # older state used plain keys
            sc = Scanner(key, inst, strat, fx=fx)
            if st.get("day") == str(last.date()):
                sc.day, sc.trades_today = last.date(), int(st.get("count", 0))
            seen = pd.Timestamp(st["last"]) if st.get("last") else None
            floor = last - timedelta(minutes=20)
            sc.last_seen = seen if seen is not None and seen > floor else floor
            sc.on_alert = log_alert
            sc.process(df)
            state[sk] = {"last": str(last), "day": str(last.date()), "count": sc.trades_today}
            state.pop(key, None)
            print(f"{inst['name']} {sc.tag}: checked up to the {last:%d %b %H:%M} candle. Alerts today: {sc.trades_today}.")
    st_path.write_text(json.dumps(state))


# ---------------- continuous mode (your Mac) ----------------
def seconds_to_next_check(now: datetime) -> float:
    nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=5 - now.minute % 5)
    return (nxt - now).total_seconds() + 20


def live():
    fx = data.usdinr_series()
    scanners = {(k, s_): Scanner(k, v, s_, fx=fx) for k, v in config.enabled_instruments().items()
                for s_ in config.enabled_strategies()}
    for sc in scanners.values():
        sc.on_alert = log_alert
    names = ", ".join(v["name"] for v in config.enabled_instruments().values())
    strats = " and ".join(config.STRATEGY_NAMES[s_] for s_ in config.enabled_strategies())
    send(f"Alerts started ({strats}) for: {names}.")
    while True:
        now = now_ist()
        cache = {}
        for (key, _), sc in scanners.items():
            if _open_now(sc.inst, now):
                try:
                    if key not in cache:                      # download once, share between strategies
                        cache[key] = fetch_closed(key, sc.inst)
                    sc.process(cache[key])
                except Exception as e:
                    print(f"[{now:%H:%M}] {sc.inst['name']}: data error, will retry ({e})")
        pytime.sleep(seconds_to_next_check(datetime.now()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="check once and exit (for scheduled runs)")
    p.add_argument("--csv-dir", help="with --once: read <KEY>.csv candle files from this folder (for testing)")
    a = p.parse_args()
    once(a.csv_dir) if a.once else live()
