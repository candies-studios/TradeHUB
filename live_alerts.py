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
              "lots", "qty", "sl_pts", "target_pts", "est_premium"]


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
        self.now = None          # set by once(): used to flag alerts that arrive late
        self.vix = config.INDIA_VIX_FALLBACK   # India VIX, for the estimated option price

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
        if not strategy.under_daily_limit(self.trades_today):
            return

        spot = float(bar.close)
        delta = strategy.delta_for(d, inst)
        qf = strategy.quote_factor(inst, data.usdinr_on(self.fx, d))
        sl, tg = strategy.sl_target(inst, bar.atr, delta, qf)
        if sl <= 0:
            return
        kind = "CALL" if side == "CE" else "PUT"
        lots = inst["lots"]
        strike = strategy.pick_strike(spot, side, d, inst)
        expiry = strategy.expiry_for(d, inst)

        late = int((self.now - close_time).total_seconds() // 60) if self.now else 0
        when = f"{close_time:%d %b %Y, %H:%M}" + (f"  (⏱️ {late} min late)" if late > 10 else "")
        approx = " (approx.)" if inst["segment"] == "commodity" else ""
        est = None
        if inst["segment"] == "index" and config.ESTIMATE_PREMIUM:
            vol = self.vix / 100 * config.VIX_MULTIPLIER.get(self.key, 1.0)
            years = strategy.years_to_expiry(close_time.to_pydatetime() if hasattr(close_time, "to_pydatetime") else close_time,
                                             expiry, inst["session"][1])
            est = strategy.tick(strategy.bs_premium(spot, strike, years, vol, side))
            if est < 0.5:
                est = None
        if inst["segment"] == "index":
            on_exp = expiry == d and config.ATM_ON_EXPIRY_DAY
            label = f"{strike} {side}"
            which = f"{self.key} {expiry:%d %b} expiry, {lots} lot{'s' if lots > 1 else ''} ({config.STRATEGY_NAMES[self.strat]})"
            strike_txt = f"{strike}" + (" (ATM, expiry day)" if on_exp else "")
        else:
            label = f"{side} option"
            which = f"{self.key} nearest expiry, {lots} lot{'s' if lots > 1 else ''} ({config.STRATEGY_NAMES[self.strat]})"
            strike_txt = f"{config.ITM_STRIKES} strike in-the-money in Sahi's option chain"
        if est:
            prices = (f"Buy price (approx.) - ₹{est:,.2f}  (estimate, confirm in Sahi)\n"
                      f"Stop loss price - ₹{max(est - sl, 0.05):,.2f}  (your buy price − {_pts(sl)})\n"
                      f"Target price - ₹{est + tg:,.2f}  (your buy price + {_pts(tg)})\n")
        else:
            prices = (f"Stop loss price - your buy price − {_pts(sl)}{approx}\n"
                      f"Target price - your buy price + {_pts(tg)}{approx}\n")
        text = (f"Instrument name - {name} ({inst['exchange']})\n"
                f"Which option - {which}\n"
                f"CE/PE - {side} ({kind})\n"
                f"Strike price to buy - {strike_txt}\n"
                + prices +
                f"Time of the signal - {when}")
        send(text, self.telegram)

        self.trades_today += 1
        self.pos = {"side": side, "spot": spot, "k": delta * qf, "sl": sl, "tg": tg, "label": label}
        if self.on_alert:
            self.on_alert({"alert_time": f"{close_time:%Y-%m-%d %H:%M}", "instrument": self.key, "name": name,
                           "strategy": self.strat,
                           "side": side, "strike": strike if strike is not None else "",
                           "expiry": f"{expiry:%Y-%m-%d}" if expiry else "nearest",
                           "underlying": round(spot, 2), "rsi": round(float(bar.rsi), 1), "lots": lots,
                           "qty": lots * inst["units_per_lot"], "sl_pts": sl, "target_pts": tg,
                           "est_premium": est if est else ""})


def _open_now(inst, now: datetime) -> bool:
    a, b = inst["session"]
    end = (datetime.combine(now.date(), strategy.t(b)) + timedelta(minutes=6)).time()
    return now.weekday() < 5 and strategy.t(a) <= now.time() <= end


# ---------------- one check (GitHub, every 5 minutes) ----------------
CATCH_UP_MINUTES = 120   # if GitHub runs late, still check every candle from the last 2 hours


def once(csv_dir: str = None, state_file: str = ".alert_state.json", now: datetime = None):
    """Check every instrument once, then exit. A small state file prevents duplicate alerts.
    GitHub's scheduler often starts late, so this catches up on every candle since the last check
    (up to CATCH_UP_MINUTES) and marks alerts older than 10 minutes as late."""
    st_path = Path(state_file)
    try:
        state = json.loads(st_path.read_text())
    except Exception:
        state = {}
    if "last" in state:                       # state file from the Nifty-only version
        state = {"NIFTY": state}
    fx = data.usdinr_series(csv_dir)
    vix = data.india_vix(csv_dir)
    check_lateness = now is not None or not csv_dir   # test runs on old CSVs skip the lateness check
    now = now or now_ist()
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
            floor = last - timedelta(minutes=CATCH_UP_MINUTES)
            sc.last_seen = seen if seen is not None and seen > floor else floor
            sc.on_alert = log_alert
            sc.now = now if check_lateness else None
            sc.vix = vix
            try:
                sc.process(df)
            except Exception as e:           # one instrument's problem must never stop the others
                import traceback
                traceback.print_exc()
                print(f"{inst['name']} {sc.tag}: ERROR, skipped this check ({e})")
                continue
            state[sk] = {"last": str(last), "day": str(last.date()), "count": sc.trades_today}
            state.pop(key, None)
            print(f"{inst['name']} {sc.tag}: checked up to the {last:%d %b %H:%M} candle. Alerts today: {sc.trades_today}.")
    st_path.write_text(json.dumps(state))


# ---------------- watch mode (GitHub: one long run instead of many short ones) ----------------
def _save_log_to_github():
    """Commit and push alerts_log.csv if new alerts were added (only inside GitHub Actions)."""
    import os
    import subprocess

    if not os.environ.get("GITHUB_ACTIONS") or not Path(ALERT_LOG).exists():
        return
    run = lambda *c: subprocess.run(list(c), capture_output=True, text=True)
    run("git", "add", ALERT_LOG)
    if run("git", "diff", "--cached", "--quiet").returncode == 0:
        return
    run("git", "commit", "-m", "Log new trading alert")
    for _ in range(3):
        run("git", "pull", "--rebase")
        if run("git", "push").returncode == 0:
            return
        pytime.sleep(5)
    print("Could not save alerts_log.csv to GitHub this time; will retry after the next check.")


def _any_market_open(now: datetime) -> bool:
    return any(_open_now(inst, now) for inst in config.enabled_instruments().values())


def watch(minutes: int = 345):
    """Stay on for `minutes`, checking every 5 minutes (20 s after each candle closes) while any market is open.
    The GitHub workflow starts the next run when this one ends, so the bot keeps itself running
    around the clock and never depends on GitHub's unreliable scheduler. Outside market hours it just waits."""
    end = now_ist() + timedelta(minutes=minutes)
    print(f"Watching until {end:%d %b %H:%M} IST, then the next run takes over.")
    last_note = None
    while True:
        now = now_ist()
        if _any_market_open(now):
            try:
                once()
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Check failed, will retry next candle ({e})")
            _save_log_to_github()
        elif last_note is None or (now - last_note) >= timedelta(hours=1):
            print(f"[{now:%d %b %H:%M} IST] Markets closed, waiting.")
            last_note = now
        wait = seconds_to_next_check(datetime.now())     # 20 s after the next 5-minute candle closes
        if now_ist() + timedelta(seconds=wait) > end:
            break
        pytime.sleep(wait)
    print("Watch period finished; the next run takes over now.")


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
        vix = data.india_vix()
        for (key, _), sc in scanners.items():
            sc.vix = vix
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
    p.add_argument("--watch", type=int, metavar="MINUTES", help="check every 5 minutes for this many minutes (GitHub)")
    p.add_argument("--csv-dir", help="with --once: read <KEY>.csv candle files from this folder (for testing)")
    p.add_argument("--now", help="with --once: pretend the time is 'YYYY-MM-DD HH:MM' (for testing)")
    a = p.parse_args()
    if a.watch:
        watch(a.watch)
    elif a.once:
        once(a.csv_dir, now=pd.Timestamp(a.now).to_pydatetime() if a.now else None)
    else:
        live()
