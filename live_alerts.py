"""
Live RSI-14 alerts for Nifty options. You place the orders yourself on Sahi.

Run it in the morning before 9:30 and leave the window open:
    python live_alerts.py

Every 5 minutes, just after a candle closes, it checks Nifty's RSI-14. When your
rule fires it tells you: CALL or PUT, which strike, which expiry, how many lots,
and where to put the stop-loss and target. It also reminds you to exit at 15:15.

Practice run on past data (no waiting, no Telegram):
    python live_alerts.py --replay backtest_data.csv
"""
import argparse
import time as pytime
from datetime import datetime, timedelta

import pandas as pd

import config
import strategy

IST = "Asia/Kolkata"
MARKET_OPEN = pd.Timestamp("09:15").time()
MARKET_CLOSE = pd.Timestamp("15:30").time()


# ---------------- alert delivery ----------------
def send(msg: str, telegram: bool = True):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"\a\n[{stamp}] {msg}\n", flush=True)
    if telegram and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg},
                timeout=10,
            )
        except Exception as e:  # never let an alert failure stop the scanner
            print(f"(Telegram failed: {e})")


# ---------------- data ----------------
def fetch_closed_candles() -> pd.DataFrame:
    """Last few days of 5-min Nifty candles, with the still-forming candle removed."""
    import yfinance as yf

    raw = yf.download("^NSEI", period="5d", interval="5m", progress=False, auto_adjust=False)
    if raw.empty:
        return raw
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    idx = df.index
    df.index = idx.tz_convert(IST).tz_localize(None) if idx.tz is not None else idx
    now = pd.Timestamp.now(tz=IST).tz_localize(None)
    return df[df.index + timedelta(minutes=5) <= now]


# ---------------- scanner ----------------
class Scanner:
    """Remembers what it already alerted so each candle is handled once."""

    def __init__(self, telegram=True):
        self.telegram = telegram
        self.last_seen = None
        self.day = None
        self.trades_today = 0
        self.pos = None          # estimated open position after an alert
        self.squared_off = False
        self.on_alert = None     # optional callback(dict) for every new trade alert

    def _new_day(self, d):
        self.day, self.trades_today, self.pos, self.squared_off = d, 0, None, False

    def process(self, df: pd.DataFrame):
        if df.empty:
            return
        df = strategy.add_signals(df)
        new = df if self.last_seen is None else df[df.index > self.last_seen]
        if self.last_seen is None:
            new = df.tail(1)     # on start-up only look at the latest closed candle
        for ts, bar in new.iterrows():
            self._handle(ts, bar)
        self.last_seen = df.index[-1]

    def _handle(self, ts, bar):
        d = ts.date()
        if d != self.day:
            self._new_day(d)
        close_time = ts + timedelta(minutes=5)

        # 1) track the estimated position so you get a heads-up about SL/target
        if self.pos:
            p = self.pos
            sign = 1 if p["side"] == "CE" else -1
            worst = sign * ((bar.low if p["side"] == "CE" else bar.high) - p["nifty"]) * p["delta"]
            best = sign * ((bar.high if p["side"] == "CE" else bar.low) - p["nifty"]) * p["delta"]
            msg = None
            if worst <= -config.STOP_LOSS_POINTS:
                msg = "likely hit your STOP-LOSS"
            elif best >= config.TARGET_POINTS:
                msg = "likely hit your TARGET"
            if msg:
                send(f"ℹ️ NIFTY {p['strike']} {p['side']} has {msg} (estimated from Nifty's move). "
                     f"Check your Sahi order book.", self.telegram)
                self.pos = None

        # 2) square-off reminder
        if close_time.time() >= strategy.SQUARE_OFF and not self.squared_off:
            self.squared_off = True
            if self.pos:
                send(f"⏰ {config.SQUARE_OFF_TIME} — EXIT NIFTY {self.pos['strike']} {self.pos['side']} now "
                     f"if it is still open.", self.telegram)
                self.pos = None
            return

        # 3) new signal
        side = bar.signal
        if side not in ("CE", "PE") or self.pos:
            return
        if not strategy.in_entry_window(close_time):
            return
        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            return

        spot = bar.close
        strike = strategy.pick_strike(spot, side, d)
        expiry = strategy.expiry_for(d)
        exp_day = strategy.is_expiry_day(d)
        kind = "CALL" if side == "CE" else "PUT"
        qty = config.LOT_SIZE * config.LOTS
        lv = strategy.levels()[("call" if side == "CE" else "put")]
        moneyness = "ATM (expiry day)" if exp_day and config.ATM_ON_EXPIRY_DAY else f"{config.ITM_STRIKES} strike ITM"
        send(
            f"🔔 BUY NIFTY {strike} {side} ({kind})\n"
            f"Expiry: {expiry:%a %d %b %Y}  |  {moneyness}\n"
            f"Qty: {config.LOTS} lots = {qty}\n"
            f"Why: RSI-{config.RSI_PERIOD} crossed {'above' if side == 'CE' else 'below'} {lv} "
            f"(now {bar.rsi:.1f}) on the {ts:%H:%M} candle. Nifty {spot:,.2f}\n"
            f"After you buy: SL = your price − {config.STOP_LOSS_POINTS}, "
            f"Target = your price + {config.TARGET_POINTS}. Exit by {config.SQUARE_OFF_TIME}.",
            self.telegram,
        )
        self.trades_today += 1
        self.pos = {"side": side, "strike": strike, "nifty": spot, "delta": strategy.delta_for(d)}
        if self.on_alert:
            self.on_alert({
                "alert_time": f"{close_time:%Y-%m-%d %H:%M}", "side": side, "strike": strike,
                "expiry": f"{expiry:%Y-%m-%d}", "nifty": round(float(spot), 2), "rsi": round(float(bar.rsi), 1),
                "lots": config.LOTS, "qty": qty, "sl_pts": config.STOP_LOSS_POINTS, "target_pts": config.TARGET_POINTS,
            })


# ---------------- main loops ----------------
def seconds_to_next_check(now: datetime) -> float:
    """Wake 20 seconds after each 5-minute candle closes (gives the data feed time to update)."""
    nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=5 - now.minute % 5)
    return (nxt - now).total_seconds() + 20


def live():
    sc = Scanner()
    send(f"Nifty RSI-{config.RSI_PERIOD} alerts started ({config.STRATEGY_MODE} mode, "
         f"{config.LOTS} lots, SL {config.STOP_LOSS_POINTS} / target {config.TARGET_POINTS}).", sc.telegram)
    while True:
        now = pd.Timestamp.now(tz=IST).tz_localize(None).to_pydatetime()
        market_open = now.weekday() < 5 and MARKET_OPEN <= now.time() <= (
            datetime.combine(now.date(), MARKET_CLOSE) + timedelta(minutes=2)).time()
        if market_open:
            try:
                sc.process(fetch_closed_candles())
            except Exception as e:
                print(f"[{now:%H:%M}] data error, will retry next candle: {e}")
        elif now.time() > MARKET_CLOSE and now.weekday() < 5 and sc.day == now.date():
            print("Market closed for today. Leave this running or stop it with Ctrl+C.")
        pytime.sleep(seconds_to_next_check(datetime.now()))


def replay(path: str):
    from backtest import load_csv

    df = load_csv(path)
    sc = Scanner(telegram=False)
    sc.last_seen = df.index[0]
    for k in range(50, len(df) + 1):     # feed candles one at a time, like the live feed
        sc.process(df.iloc[:k])


ALERT_LOG = "alerts_log.csv"
ALERT_COLS = ["alert_time", "side", "strike", "expiry", "nifty", "rsi", "lots", "qty", "sl_pts", "target_pts"]


def log_alert(row: dict, path: str = ALERT_LOG):
    """Append one alert to alerts_log.csv. The Paper log page on the website reads this file."""
    import csv
    from pathlib import Path

    new_file = not Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ALERT_COLS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in ALERT_COLS})


def once(csv: str = None, state_file: str = ".alert_state.json"):
    """One check, then exit. Used by the scheduled GitHub run every 5 minutes.
    A small state file remembers what was already alerted so nothing is sent twice."""
    import json
    from pathlib import Path

    st_path = Path(state_file)
    try:
        state = json.loads(st_path.read_text())
    except Exception:
        state = {}
    if csv:
        from backtest import load_csv
        df = load_csv(csv)
    else:
        df = fetch_closed_candles()
    if df.empty:
        print("No candle data yet (market closed or data delayed).")
        return
    last = df.index[-1]
    sc = Scanner()
    if state.get("day") == str(last.date()):
        sc.day, sc.trades_today = last.date(), int(state.get("count", 0))
    # only look at candles that closed since the previous check (max 20 minutes back)
    seen = pd.Timestamp(state["last"]) if state.get("last") else None
    floor = last - timedelta(minutes=20)
    sc.last_seen = max(seen, floor) if seen is not None and seen > floor else floor
    sc.on_alert = log_alert
    sc.process(df)
    st_path.write_text(json.dumps({"last": str(last), "day": str(last.date()), "count": sc.trades_today}))
    print(f"Checked up to the {last:%d %b %H:%M} candle. Alerts today: {sc.trades_today}.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--replay", help="CSV of past 5-min candles to practise on")
    p.add_argument("--once", action="store_true", help="check once and exit (for scheduled runs)")
    p.add_argument("--csv", help="with --once: use this CSV instead of live data (for testing)")
    a = p.parse_args()
    if a.replay:
        replay(a.replay)
    elif a.once:
        once(a.csv)
    else:
        live()
