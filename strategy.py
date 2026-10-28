"""
Shared strategy logic: RSI, signals, expiries, strikes and stop-loss/target sizing.
Used by backtest.py and live_alerts.py so they always agree.
Every function takes the instrument's settings dict from config.INSTRUMENTS.
"""
import calendar
from datetime import date, time, timedelta

import pandas as pd

import config


def wilder_rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> pd.Series:
    """RSI using Wilder's smoothing (same method TradingView and most broker charts use)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rsi = 100 - 100 / (1 + avg_gain / avg_loss)
    rsi[avg_loss == 0] = 100
    return rsi


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def levels():
    return config.REVERSAL_LEVELS if config.STRATEGY_MODE == "reversal" else config.MOMENTUM_LEVELS


def add_signals(df: pd.DataFrame, strat: str = "RSI") -> pd.DataFrame:
    """Adds rsi, atr, ema_fast, ema_slow and 'signal' ('CE', 'PE' or None, decided at candle CLOSE)
    for one strategy: "RSI" (RSI-14 crosses your levels) or "EMA" (9 EMA crosses the 20 EMA)."""
    df = df.copy()
    df["rsi"] = wilder_rsi(df["close"])
    df["atr"] = atr(df)
    df["ema_fast"] = df["close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=config.EMA_SLOW, adjust=False).mean()
    df["signal"] = None
    if strat == "EMA":
        gap = df["ema_fast"] - df["ema_slow"]
        prev = gap.shift(1)
        df.loc[(prev <= 0) & (gap > 0), "signal"] = "CE"
        df.loc[(prev >= 0) & (gap < 0), "signal"] = "PE"
        df.iloc[: config.EMA_SLOW * 3, df.columns.get_loc("signal")] = None   # let the EMAs settle first
    else:
        prev = df["rsi"].shift(1)
        lv = levels()
        df.loc[(prev <= lv["call"]) & (df["rsi"] > lv["call"]), "signal"] = "CE"
        df.loc[(prev >= lv["put"]) & (df["rsi"] < lv["put"]), "signal"] = "PE"
    return df


def under_daily_limit(count: int) -> bool:
    """True if another signal is allowed today (MAX_TRADES_PER_DAY = None means unlimited)."""
    limit = config.MAX_TRADES_PER_DAY
    return limit is None or count < limit


def t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def in_session(ts, inst) -> bool:
    a, b = inst["session"]
    return t(a) <= ts.time() < t(b)


def in_entry_window(ts, inst) -> bool:
    a, b = inst["entry"]
    return t(a) <= ts.time() <= t(b)


# ---------------- expiries ----------------
def _holidays():
    return {date.fromisoformat(d) for d in config.NSE_HOLIDAYS}


def _roll_back(d: date) -> date:
    hol = _holidays()
    while d in hol or d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _last_weekday_of_month(y: int, m: int, wd: int) -> date:
    last = date(y, m, calendar.monthrange(y, m)[1])
    return last - timedelta(days=(last.weekday() - wd) % 7)


def expiry_for(d: date, inst):
    """Nearest expiry on or after d. None for MCX (pick it from Sahi's option chain)."""
    kind = inst.get("expiry")
    wd = inst.get("expiry_weekday", 1)
    if kind == "weekly":
        exp = _roll_back(d + timedelta(days=(wd - d.weekday()) % 7))
        return exp if exp >= d else expiry_for(d + timedelta(days=7 - d.weekday()), inst)
    if kind == "monthly":
        y, m = d.year, d.month
        for _ in range(3):
            exp = _roll_back(_last_weekday_of_month(y, m, wd))
            if exp >= d:
                return exp
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def is_expiry_day(d: date, inst) -> bool:
    return expiry_for(d, inst) == d


def delta_for(d: date, inst) -> float:
    return config.DELTA_ATM_EXPIRY if (config.ATM_ON_EXPIRY_DAY and is_expiry_day(d, inst)) else config.DELTA_ITM


def pick_strike(spot: float, side: str, d: date, inst):
    """ITM strike on normal days, ATM on expiry day. None for MCX (strike chosen in Sahi)."""
    step = inst.get("strike_step")
    if not step:
        return None
    atm = int(round(spot / step) * step)
    if config.ATM_ON_EXPIRY_DAY and is_expiry_day(d, inst):
        return atm
    shift = step * config.ITM_STRIKES
    return atm - shift if side == "CE" else atm + shift


# ---------------- estimated option premium (indices) ----------------
def _ncdf(x: float) -> float:
    import math
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_premium(spot: float, strike: float, years: float, vol: float, side: str, rate: float = None) -> float:
    """Black-Scholes price of a European index option (NSE/BSE index options are European)."""
    import math
    rate = config.RISK_FREE_RATE if rate is None else rate
    years = max(years, 1 / (365 * 24))          # at least one hour left
    vol = max(vol, 0.01)
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * years) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    disc = math.exp(-rate * years)
    if side == "CE":
        return spot * _ncdf(d1) - strike * disc * _ncdf(d2)
    return strike * disc * _ncdf(-d2) - spot * _ncdf(-d1)


def years_to_expiry(now, expiry_date, close_hhmm: str = "15:30") -> float:
    from datetime import datetime
    end = datetime.combine(expiry_date, t(close_hhmm))
    return max((end - now).total_seconds(), 3600) / (365 * 24 * 3600)


def tick(x: float) -> float:
    """Round to the 0.05 tick that NSE/BSE option prices trade in."""
    return round(round(x / 0.05) * 0.05, 2)


# ---------------- price conversion (commodities) ----------------
def quote_factor(inst, usdinr: float) -> float:
    """Multiply an underlying price move by this to get MCX rupee quote points."""
    conv = inst.get("convert")
    if conv == "usd_oz_to_inr_10g":
        return usdinr * 10 / 31.1035
    if conv == "usd_oz_to_inr_kg":
        return usdinr * 1000 / 31.1035
    if conv == "usd_to_inr":
        return usdinr
    return 1.0


def _nice(x: float) -> float:
    """Round a stop-loss/target to a tidy number a trader would actually type."""
    if x <= 0 or x != x:
        return 0.0
    if x >= 100:
        return float(round(x / 5) * 5)
    if x >= 10:
        return float(round(x))
    if x >= 1:
        return round(x * 2) / 2
    return round(x, 2)


def sl_target(inst, atr_value: float, delta: float, qf: float):
    """Stop-loss and target in PREMIUM points (instrument's own quote units)."""
    sl, tg = inst.get("sl_points", "auto"), inst.get("target_points", "auto")
    if sl == "auto" or tg == "auto":
        base = _nice(delta * config.AUTO_SL_ATR * float(atr_value) * qf) if atr_value == atr_value else 0.0
        if sl == "auto":
            sl = base
        if tg == "auto":
            tg = _nice(float(sl) * config.AUTO_TARGET_MULT)
    return float(sl), float(tg)
